"""Bounded fresh technical comparison; never resume the stopped main study."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import shutil
import statistics
import subprocess
import time

from exp7_header_probe import BUNDLE, UPSTREAM, header_transport, now
from exp7_cli_upgrade_probe import isolated_sqlite_launcher, initialize_sqlite_without_inference
from exp7_retry_transport import retry_relay, audit_retry_trial
from exp7_native_retry_audit import audit_native_retries
from exp7_main_v2.coordination import GitCoordinator
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.runner import run_trial
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.worker import verify_freeze
from exp7_pre.runner import CallBudget, atomic_json

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {'p6-r100': (6, 100), 'p8-r110': (8, 110), 'p10-r160': (10, 160), 'p10-r100': (10, 100),
            'p10-unpaced': (10, None), 'p20-unpaced': (20, None), 'p40-unpaced': (40, None)}


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


def summarize(root, client, relay, admission, trials, freeze, url):
    states = [json.loads(path.read_text()) for path in sorted((root / 'states').glob('*.json'))]
    turns = [turn for state in states for turn in state.get('turns', [])]
    good = [turn for turn in turns if turn.get('ok')]
    records = sorted(client.records, key=lambda row: row['ticket'])
    audits = [audit_retry_trial(trial, MainProtocol(), root / 'states' / (trial['trial_id'] + '.json'), freeze, url)
              for trial in trials if (root / 'states' / (trial['trial_id'] + '.json')).exists()]
    atomic_json(root / 'audits.json', audits)
    groups = {}
    for row in records:
        groups.setdefault(row['logical_id'], []).append(row)
    invariant_errors = []
    for logical_id, group in groups.items():
        group.sort(key=lambda row: row['attempt'])
        if len({row['request_body_sha256'] for row in group}) != 1:
            invariant_errors.append(f'Logical {logical_id}: request bytes changed')
        if [row['attempt'] for row in group] != list(range(len(group))):
            invariant_errors.append(f'Logical {logical_id}: attempt sequence gap')
        if any(not row.get('explicit_capacity_429') or not row.get('retry_scheduled') for row in group[:-1]):
            invariant_errors.append(f'Logical {logical_id}: replay without explicit capacity rejection')
    admits = [row for row in admission.events if row['kind'] == 'admit']
    enqueues = [row for row in admission.events if row['kind'] == 'enqueue']
    admitted_tickets = [row['queue_ticket'] for row in admits]
    admitted_set = set(admitted_tickets)
    expected_tickets = [row['queue_ticket'] for row in enqueues if row['queue_ticket'] in admitted_set]
    fifo_ok = admitted_tickets == expected_tickets
    if not fifo_ok:
        invariant_errors.append('Physical admission overtook an older queued request')
    for cooldown in [row for row in admission.events if row['kind'] == 'cooldown']:
        if any(cooldown['monotonic'] < row['monotonic'] < cooldown['until_monotonic'] for row in admits):
            invariant_errors.append('New admission occurred during shared cooldown')
    times = [(row['started_monotonic'], 1) for row in records] + [(row['ended_monotonic'], -1) for row in records]
    active = peak = 0
    for _, delta in sorted(times):
        active += delta
        peak = max(peak, active)
    elapsed = (max(timestamp(t['received_at']) for t in turns) - min(timestamp(t['requested_at']) for t in turns)) if turns else 0
    latencies = [turn['duration_seconds'] for turn in good]
    rolling_peak = max((sum(row['started_monotonic'] - 60 < other['started_monotonic'] <= row['started_monotonic']
                            for other in records) for row in records), default=0)
    native = audit_native_retries(root)
    atomic_json(root / 'native-retry-audit.json', native)
    statuses = {str(status): sum(row.get('status') == status for row in records)
                for status in sorted({row['status'] for row in records if 'status' in row})}
    clean_audit = (len(audits) == len(trials) and len(states) == len(trials)
                   and all(state['status'] == 'complete' for state in states)
                   and all(row['integrity_ok'] for row in audits)
                   and not invariant_errors and native['available']
                   and not native['native_429_retry_log_records'] and not native['other_native_retry_log_records'])
    scan = json.loads((root / 'credential-scan.json').read_text())
    summary = {'ended_at': now(), 'sessions_planned': len(trials),
               'sessions_complete': sum(state['status'] == 'complete' for state in states),
               'successful_turns': len(good), 'logical_turns_recorded': len(turns),
               'duration_seconds_including_retries': elapsed,
               'successful_turns_per_minute': len(good) / elapsed * 60 if elapsed else None,
               'p95_turn_seconds': statistics.quantiles(latencies, n=100, method='inclusive')[94] if len(latencies) > 1 else None,
               'physical_attempts': len(records), 'status_counts': statuses,
               'explicit_capacity_429': sum(row.get('explicit_capacity_429', False) for row in records),
               'retried_attempts': sum(row.get('retry_scheduled', False) for row in records),
               'recovered_logical_requests': sum(len(group) > 1 and group[-1].get('status') == 200 for group in groups.values()),
               'actual_peak_inflight_http': peak, 'rolling_60s_start_peak': rolling_peak,
               'admission_queue_policy': 'FIFO', 'FIFO_order_ok': fifo_ok,
               'admission_wait_p95_seconds': statistics.quantiles([row['queue_wait_seconds'] for row in admits], n=100, method='inclusive')[94] if len(admits) > 1 else None,
               'physical_attempts_per_successful_turn': len(records) / len(good) if good else None,
               'complete_session_audits_ok': clean_audit,
               'retry_invariant_errors': invariant_errors,
               'credential_scan_clean': not scan['matched_files'] and not scan['skipped_files'],
               'actual_tool_events': sum(turn.get('tool_events', 0) for turn in turns),
               'stop_reason': relay.gate.reason, 'samples_in_main': 0,
               'main_freeze_sha256': freeze,
               'http_response_diagnostics_only': True}
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--study-id', required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--profile', choices=sorted(PROFILES), required=True)
    p.add_argument('--sessions', type=int, default=12)
    p.add_argument('--physical-budget', type=int, default=600)
    p.add_argument('--max-retries', type=int, default=4)
    p.add_argument('--max-wait-seconds', type=float, default=240)
    p.add_argument('--stage-seconds', type=float, default=900)
    p.add_argument('--retry-wait-scope', choices=['shared', 'request'], default='shared')
    args = p.parse_args()
    if args.sessions < 10 or args.sessions % 2:
        p.error('At least ten sessions and an even model balance are required')
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    logging.getLogger('httpx').setLevel(logging.ERROR)
    coordinator = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                                 'exp7/persistent-v1-coordination', root / 'main-status.git')
    board = coordinator.status()
    if not board['global_stop'] or not Path('/workspace/work/exp7-cli-upgrade-20261108/HALT').exists():
        raise RuntimeError('Prior STOPs must remain active')
    _, freeze = verify_freeze(BUNDLE / 'freeze.json')
    assignments = load_bundle(BUNDLE)['trials']
    models = ['gpt-6-astra', 'gpt-5.6-sol']
    templates = [next(t for t in assignments if t['model'] == model and t['effort'] == 'medium'
                      and t['arm'] == 'en_schema' and t['frame'] == 'cards' and t['game'] == 'seq') for model in models]
    pool, rpm = PROFILES[args.profile]
    if args.sessions < pool:
        raise ValueError('Sessions must fill the declared pool')
    run = args.study_id + '-' + root.name
    trials = [{**templates[i % 2], 'trial_id': f'retry-{i+1:02d}', 'run_id': run, 'cohort': 'technical_retry_efficiency'}
              for i in range(args.sessions)]
    atomic_json(root / 'assignments.json', trials)
    launcher, database = isolated_sqlite_launcher(root, 'native', args.binary.resolve())
    interval = 0 if rpm is None else 60 / rpm
    relay, client, admission = retry_relay(root, interval, args.sessions * 34,
                                         physical_limit=args.physical_budget,
                                         max_retries=args.max_retries,
                                         max_wait_seconds=args.max_wait_seconds,
                                         max_seconds=args.stage_seconds,
                                         shared_cooldown=args.retry_wait_scope == 'shared')
    profile = {'run_id': run, 'created_at': now(), 'profile': args.profile, 'pool': pool,
               'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'sessions': args.sessions, 'models': models, 'effort': 'medium',
               'physical_start_ceiling_per_minute': rpm, 'physical_start_interval_seconds': interval,
               'transport_local_start_interval_seconds': 0, 'CLI_gate_interval_seconds': 0,
               'logical_turn_timeout_seconds': max(360, args.max_wait_seconds + 120),
               'cli_version': '0.167.0',
               'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
               'source_sha256': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                                 for name in ['exp7_retry_efficiency_study.py', 'exp7_retry_transport.py', 'exp7_header_probe.py']},
               'scientific_freeze_sha256': freeze,
               'assignment_science_sha256': hashlib.sha256(json.dumps(templates, sort_keys=True).encode()).hexdigest(),
               'transport': 'persistent CLI HTTP/SSE; distinct from retired WS main profile',
               'upstream': UPSTREAM, 'loopback_base_url': relay.base_url,
               'native_request_retries': 0, 'native_stream_retries': 0,
               'retry_policy': {'only': 'complete pre-stream HTTP 429 rate_limit_error/turn_rate_limit_exceeded',
                                'admission_queue': 'FIFO across new requests and capacity retries',
                                'max_retries_per_logical_request': args.max_retries,
                                'max_wait_seconds_per_request': args.max_wait_seconds,
                                'server_Retry_After_honored': True,
                                'shared_cooldown_all_models': args.retry_wait_scope == 'shared',
                                'physical_budget': args.physical_budget,
                                'new_admission_deadline_seconds': args.stage_seconds,
                                'byte_identical_request_retry': True, 'new_turn_start_on_retry': False},
               'main_sample_inclusion': False, 'old_STOPs_preserved': True}
    atomic_json(root / 'profile.json', profile)
    transport = header_transport(launcher, relay.base_url)
    transport.timeout = max(360, args.max_wait_seconds + 120)
    checked = [0.]
    check_lock = __import__('threading').Lock()
    def before_send():
        if relay.gate.stop.is_set() or (root / 'HALT').exists() or (root.parent / 'HALT').exists():
            raise RuntimeError('Retry study STOP active; no turn replay')
        with check_lock:
            if time.monotonic() - checked[0] > 30:
                if not coordinator.status()['global_stop']:
                    relay.gate.halt('Scientific STOP changed; avoid overlap')
                    raise RuntimeError('Scientific STOP changed')
                checked[0] = time.monotonic()
    transport.before_send = before_send
    failure = None
    try:
        with relay, closing(transport):
            initialize_sqlite_without_inference(root, 'serial-db')
            budget = CallBudget(root / 'budget.json', run, args.sessions * 34)
            with ThreadPoolExecutor(max_workers=pool) as executor:
                futures = [executor.submit(run_trial, trial, MainProtocol(), transport,
                                           root / 'states' / (trial['trial_id'] + '.json'), root / 'native', budget, freeze)
                           for trial in trials]
                for future in futures:
                    future.result()
    except Exception as exc:
        failure = type(exc).__name__
        relay.gate.halt('Technical driver exception; no replacement')
    finally:
        if database.exists():
            shutil.copytree(database, root / 'native-sqlite')
        matches, skipped = [], []
        for path in root.rglob('*'):
            if path.is_file() and path.stat().st_size < 200_000_000:
                if any(secret and secret in path.read_bytes() for secret in relay._credential_values):
                    matches.append(path.relative_to(root).as_posix())
            elif path.is_file():
                skipped.append(path.relative_to(root).as_posix())
        atomic_json(root / 'credential-scan.json', {'matched_files': matches, 'skipped_files': skipped,
                                                  'credential_values_kept_in_memory_only': True})
    summary = summarize(root, client, relay, admission, trials, freeze, relay.base_url)
    summary.update(driver_exception_type=failure, pool=pool, physical_start_ceiling_per_minute=rpm,
                   main_STOP_preserved=coordinator.status()['global_stop'])
    atomic_json(root / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    if (summary['sessions_complete'] != args.sessions or not summary['complete_session_audits_ok']
            or not summary['credential_scan_clean'] or failure or summary['stop_reason']):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
