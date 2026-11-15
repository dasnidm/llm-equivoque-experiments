"""Separate, bounded technical throughput stage; never a scientific sample.

This module does not start work on import. Each CLI invocation runs one new
stage and preserves every failed/pending state. An existing stage is never
overwritten or replayed. The original scientific board must remain STOP.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from exp7_persistent.audit import audit_trial
from exp7_persistent.transport import _Conversation, isolation_preflight
from exp7_pre.runner import CallBudget, atomic_json
from scripts.exp7_native_retry_audit import audit_native_retries
from .coordination import GitCoordinator
from .fast_pacing import StageResult, next_stage
from .fast_profile import FastGatedTransport
from .fast_transport import FastPersistentTransport
from .protocol import CardProtocol
from .runner import run_trial
from .schedule import EFFORTS, MODELS, build
from .supervise import BOARD, REMOTE
from .tool_surface_probe import probe as probe_tool_surface


def technical_trials(stage, n):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', stage) or type(n) is not int or not 7 <= n <= 70:
        raise ValueError('Invalid fresh technical stage or concurrency')
    _, rows = build()
    selected = []
    for i in range(n):
        # The first seven sessions include all effort levels, including the
        # previous 5.6 Sol/high isolation failure; later blocks rotate levels.
        model, effort = MODELS[i % len(MODELS)], EFFORTS[(i // len(MODELS) + i) % 3]
        game = 'obj' if i % 2 == 0 else 'seq'
        candidates = sorted((t for t in rows if t['model'] == model and t['effort'] == effort
                             and t['game'] == game and t['split'] == 'development'),
                            key=lambda t: t['case_id'])
        trial = dict(candidates[(i // len(MODELS)) % len(candidates)])
        trial.update(trial_id=f'tech-{stage}-{i+1:03}', run_id='technical-speed-'+stage,
                     cohort='technical_calibration', split='calibration', fold=None,
                     case_id=f'tech-{stage}-{i+1:03}')
        selected.append(trial)
    return selected


class TechnicalGate:
    def __init__(self, coordinator):
        self.board, self.coordinator = coordinator, self
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.last = 0.0
        self.reason = None
        self.completions = []

    def check(self):
        if self.stopped.is_set():
            raise RuntimeError('Technical stage stopped; do not replay')
        with self.lock:
            if time.monotonic()-self.last < 10:
                return
            b = self.board.status()
            if not b.get('global_stop') or b.get('run_id') != 'equivoque-exp7-cards-200-20261115':
                self.reason = 'Original scientific board is not stopped'
                self.stopped.set()
                raise RuntimeError(self.reason)
            self.last = time.monotonic()

    def set_stop(self, stopped, reason):
        if stopped:
            self.reason = self.reason or reason
            self.stopped.set()

    def observe(self, result):
        diagnostics = str(result.get('stderr', ''))
        for e in result.get('events', []):
            if e.get('type') in ('error', 'turn.failed', 'thread.failed'):
                diagnostics += ' ' + str(e.get('message', ''))
        if result.get('usage') is not None and result.get('ok'):
            with self.lock:
                self.completions.append(time.monotonic())
        if re.search(r'\b429\b|rate[ _-]?limit|too many requests', diagnostics, re.I):
            self.set_stop(True, 'rate limit or native retry diagnostic')


class Meter:
    def __init__(self, pacer):
        self.pacer, self.sends = pacer, []

    def send(self, permission, write_request):
        def write():
            stamp = time.monotonic()
            result = write_request()
            self.sends.append(stamp)
            return result
        return self.pacer.send(permission, write)


def sqlite_wrapper(root, binary):
    """Use separate native logs while inheriting the existing CLI auth home."""
    root = Path(root)
    db = root/'native-sqlite'
    db.mkdir(mode=0o700)
    wrapper = root/'codex-technical'
    code = """#!/usr/bin/env python3
import os, sys
env = os.environ.copy()
if 'app-server' in sys.argv[1:]:
    env['CODEX_SQLITE_HOME'] = %r
    env['RUST_LOG'] = 'codex_core::responses_retry=warn,error'
os.execve(%r, [%r] + sys.argv[1:], env)
""" % (str(db), str(binary), str(binary))
    with wrapper.open('x') as f:
        f.write(code)
    wrapper.chmod(0o700)
    return wrapper, db


def initialize_sqlite(root, transport):
    """Initialize isolated SQLite serially; no model thread or turn is sent."""
    warm = Path(root)/'sqlite-warmup'
    warm.mkdir()
    subject = warm/'subject'
    subject.mkdir()
    isolation_preflight(subject)
    system = warm/'subject-system.txt'
    system.write_text('Technical initialization only.')
    command = transport._command({'effort': 'low'}, system)
    c = _Conversation(command, subject, warm, ())
    try:
        with (warm/'sent.jsonl').open('xb') as sent, (warm/'received.jsonl').open('xb') as received:
            c.rpc('initialize', {'clientInfo': {'name': 'codex_exec', 'version': '0.159.0-alpha.3'},
                                 'capabilities': {'experimentalApi': True}}, time.monotonic()+30,
                  sent, received, [])
            c.send({'method': 'initialized'}, sent)
    finally:
        c.close()
    if c.process.returncode not in (0, -15):
        raise RuntimeError('Isolated SQLite initialization failed')


def run_stage(parent, stage, rpm, concurrency, catalog, *, binary='/opt/codex/bin/codex'):
    """Execute new technical sessions only; never change the scientific board."""
    catalogue = Path(catalog).resolve()
    info = json.loads(catalogue.read_text())
    if not set(MODELS) <= {m.get('slug') for m in info.get('models', [])}:
        raise ValueError('Catalogue does not contain all seven requested models')
    tool_check = probe_tool_surface(binary, catalogue)
    if not tool_check['no_tool_isolation_passed']:
        raise RuntimeError('Tool-free CLI wire check failed; no live calls')
    trials = technical_trials(stage, concurrency)
    root = Path(parent).resolve()/stage
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    board = GitCoordinator(REMOTE, BOARD, root/'guard.git')
    gate = TechnicalGate(board)
    gate.check()
    wrapper, db = sqlite_wrapper(root, binary)
    raw = FastPersistentTransport(pace_path=root/'pace', target_rpm=rpm, timeout=180,
                                  codex_binary=str(wrapper), catalog_path=catalogue)
    initialize_sqlite(root, raw)
    meter = Meter(raw.pacer)
    raw.pacer = meter
    wrapped = FastGatedTransport(raw, gate)
    metadata = {'stage': stage, 'scope': 'independent technical stage, excluded from scientific sample',
                'target_rpm': rpm, 'concurrency': concurrency,
                'catalog_sha256': hashlib.sha256(catalogue.read_bytes()).hexdigest(),
                'source_sha256': {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                  for name in ('technical_sweep.py','fast_transport.py','fast_pacing.py',
                                               'fast_profile.py','tool_surface_probe.py','catalog_isolation.py')},
                'trials': trials}
    profile = (json.dumps(metadata, sort_keys=True, separators=(',', ':'))+'\n').encode()
    freeze = hashlib.sha256(profile).hexdigest()
    (root/'profile.json').write_bytes(profile)
    budget = CallBudget(root/'budget.json', 'technical-speed-'+stage, concurrency*34)
    states = []
    try:
        with wrapped, ThreadPoolExecutor(max_workers=concurrency) as pool:
            tasks = {pool.submit(run_trial, t, CardProtocol(), wrapped, root/'states'/(t['trial_id']+'.json'),
                                 root/'native', budget, freeze): t for t in trials}
            for f in as_completed(tasks):
                try:
                    state = f.result()
                    states.append(state)
                    if state.get('status') != 'complete':
                        gate.set_stop(True, 'technical session incomplete')
                except Exception as exc:
                    gate.set_stop(True, 'technical worker exception: '+type(exc).__name__)
    finally:
        wrapped.close()
    audits = [audit_trial(s['trial'], CardProtocol(), root/'states'/(s['trial']['trial_id']+'.json'), freeze)
              for s in states if s.get('status') == 'complete']
    # The isolated SQLite directory contains only technical CLI DBs; the
    # retry audit copies its own logs to a temporary read-only snapshot.
    native = audit_native_retries(root)
    turns = [t for s in states for t in s.get('turns', [])]
    successes = sum(bool(t.get('ok')) for t in turns)
    elapsed = max(gate.completions)-min(meter.sends) if gate.completions and meter.sends else 0.0
    uncertain = sum(s.get('status') != 'complete' or bool(s.get('pending_turn')) for s in states)
    uncertain += concurrency-len(states)
    uncertain += sum(not x.get('integrity_ok') for x in audits)
    tools = sum(int(t.get('tool_events', 0) or 0) for t in turns)
    compactions = sum(int(t.get('compaction_events', 0) or 0) for t in turns)
    result = StageResult(target_rpm=rpm, successful_calls=successes, duration_seconds=elapsed,
                         concurrency=concurrency, native_429=native.get('native_429_retry_log_records') or 0,
                         uncertain_requests=uncertain+compactions, forbidden_tool_events=tools,
                         telemetry_complete=bool(native.get('available')) and native.get('other_native_retry_log_records') == 0)
    summary = {'stage': stage, 'technical_only': True, 'planned_sessions': concurrency,
               'session_statuses': dict(Counter(s.get('status') for s in states)),
               'successful_calls': successes, 'actual_turn_starts': len(meter.sends),
               'elapsed_seconds': elapsed, 'observed_successes_per_minute': result.completed_rpm,
               'target_rpm': rpm, 'concurrency': concurrency, 'forbidden_tool_events': tools,
               'compaction_events': compactions, 'uncertain_sessions': uncertain,
               'native_429_retry_log_records': native.get('native_429_retry_log_records'),
               'native_telemetry_available': native.get('available'),
               'audits_passed': sum(a.get('integrity_ok', False) for a in audits),
               'gate_reason': gate.reason, 'stage_result': asdict(result), 'decision': next_stage(result)}
    atomic_json(root/'summary.json', summary)
    return summary


def combine_measurements(measurements):
    """Accumulate repeated independent stages at the same configuration."""
    if not measurements:
        raise ValueError('At least one measurement is required')
    first = measurements[0]
    if any((x.target_rpm, x.concurrency) != (first.target_rpm, first.concurrency) for x in measurements):
        raise ValueError('Cannot combine different configurations')
    return StageResult(target_rpm=first.target_rpm, concurrency=first.concurrency,
                       successful_calls=sum(x.successful_calls for x in measurements),
                       duration_seconds=sum(x.duration_seconds for x in measurements),
                       response_429=sum(x.response_429 for x in measurements),
                       native_429=sum(x.native_429 for x in measurements),
                       uncertain_requests=sum(x.uncertain_requests for x in measurements),
                       forbidden_tool_events=sum(x.forbidden_tool_events for x in measurements),
                       telemetry_complete=all(x.telemetry_complete for x in measurements))


def run_sweep(parent, label, catalog, *, rpm=100, concurrency=7, max_stages=100,
              binary='/opt/codex/bin/codex'):
    """Run fresh technical stages until a fault, plateau, or explicit bound.

    The enclosing directory must not already exist, so an interrupted sweep
    cannot silently resume or reissue previously uncertain work.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', label):
        raise ValueError('Invalid sweep label')
    if type(max_stages) is not int or not 1 <= max_stages <= 100:
        raise ValueError('max_stages must be between 1 and 100')
    # Validate parameters before creating the directory or running any stage.
    StageResult(target_rpm=rpm, successful_calls=0, duration_seconds=0, concurrency=concurrency)
    technical_trials('validation', concurrency)
    root = Path(parent).resolve()/label
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    previous, same_config, records = None, [], []
    result = {'technical_only': True, 'stages': records, 'status': 'running'}
    atomic_json(root/'sweep-summary.json', result)
    for index in range(1, max_stages + 1):
        summary = run_stage(root, f'stage-{index:02}', rpm, concurrency, catalog, binary=binary)
        current = StageResult(**summary['stage_result'])
        same_config.append(current)
        combined = combine_measurements(same_config)
        decision = next_stage(combined, previous)
        records.append({'stage': summary['stage'], 'measurement': asdict(current), 'decision': decision})
        result['status'] = decision['action']
        atomic_json(root/'sweep-summary.json', result)
        if decision['action'] in ('stop', 'plateau'):
            return result
        if decision['action'] == 'measure_more':
            continue
        previous, same_config = combined, []
        rpm, concurrency = decision['target_rpm'], decision['concurrency']
    result['status'] = 'stage_bound_reached'
    atomic_json(root/'sweep-summary.json', result)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--rpm', required=True, type=float)
    p.add_argument('--concurrency', required=True, type=int)
    p.add_argument('--catalog', required=True)
    p.add_argument('--sweep', action='store_true', help='run fresh technical stages until stop/plateau')
    args = p.parse_args()
    run = run_sweep if args.sweep else run_stage
    print(json.dumps(run(args.root, args.stage, args.catalog, rpm=args.rpm, concurrency=args.concurrency)
                     if args.sweep else run(args.root, args.stage, args.rpm, args.concurrency, args.catalog), indent=2))
