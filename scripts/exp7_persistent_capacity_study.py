"""Independent, bounded load measurement; never resumes a scientific trial.

The main run must remain stopped. All probe sessions are new, use the frozen
34-turn stimulus, and stay outside the scientific sample. No request is replayed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time

import exp7_persistent.transport as native
from exp7_main_v2.coordination import GitCoordinator
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.runner import run_trial
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.worker import verify_freeze
from exp7_pre.runner import CallBudget, atomic_json
from exp7_persistent.audit import audit_trial

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'manifests/equivoque-2026-11-08-exp7-persistent-v1'
MODELS = ('gpt-6-astra', 'gpt-5.6-sol')
RATE = re.compile(r'\b429\b|too many requests', re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


class Guard:
    def __init__(self, coordinator, root):
        self.coordinator, self.root = coordinator, root
        self.stop = threading.Event()
        self.reason = None
        self.lock = threading.Lock()
        self.checked = 0.0

    def halt(self, reason):
        with self.lock:
            if self.reason is None:
                self.reason = reason
        self.stop.set()

    def check(self):
        if self.stop.is_set() or (self.root / 'HALT').exists():
            raise RuntimeError('Capacity probe stopped; no replay')
        with self.lock:
            if time.monotonic() - self.checked < 10:
                return
            board = self.coordinator.status()
            if board['run_id'] != 'equivoque-2026-11-08-exp7-persistent-v1' or not board['global_stop']:
                self.reason = 'Main run no longer stopped; capacity measurement must not overlap collection'
                self.stop.set()
                raise RuntimeError(self.reason)
            self.checked = time.monotonic()


class Meter:
    def __init__(self, root, guard, interval):
        self.root, self.guard, self.interval = root, guard, interval
        self.lock, self.pace_lock = threading.Lock(), threading.Lock()
        self.next_start = 0.0

    def record(self, kind, **fields):
        with self.lock, (self.root / 'meter.jsonl').open('a') as log:
            log.write(json.dumps({'kind': kind, 'utc': now(), 'monotonic': time.monotonic(), **fields}) + '\n')
            log.flush()

    def admit(self, **fields):
        with self.pace_lock:
            remaining = self.next_start - time.monotonic()
            if remaining > 0 and self.guard.stop.wait(remaining):
                raise RuntimeError('Stopped during account admission; no send')
            self.guard.check()
            self.next_start = time.monotonic() + self.interval
            self.record('send', **fields)


def instrument(meter, guard):
    original = native._Conversation

    class MeteredConversation(original):
        def send(self, message, sent):
            if message.get('method') == 'turn/start':
                meter.admit(pid=self.process.pid, thread_id=message['params']['threadId'])
            return super().send(message, sent)

        def receive(self, deadline, received, messages):
            message = super().receive(deadline, received, messages)
            method, params = message.get('method'), message.get('params') or {}
            if method in ('turn/started', 'turn/completed'):
                turn = params.get('turn') or {}
                meter.record(method, pid=self.process.pid, thread_id=params.get('threadId'),
                             turn_id=turn.get('id'), status=turn.get('status'), emitted_at_ms=message.get('emittedAtMs'))
            if method == 'error' or message.get('error'):
                error = params.get('error') if method == 'error' else message.get('error')
                limited = bool(RATE.search(json.dumps(error)))
                meter.record('rpc_error', pid=self.process.pid, is_429=limited, will_retry=params.get('willRetry'))
                if limited:
                    guard.halt('Response 429 observed; do not retry or continue the stage')
            return message

    native._Conversation = MeteredConversation


class ProbeTransport:
    def __init__(self, transport, guard):
        self.transport, self.guard, self.name = transport, guard, transport.name
        transport.before_send = guard.check

    def request(self, *args, **kwargs):
        self.guard.check()
        result = self.transport.request(*args, **kwargs)
        if RATE.search(result.get('stderr', '')):
            self.guard.halt('Rate-limit diagnostic in process log; no further sends')
        if not result.get('ok'):
            self.guard.halt('Non-successful transport result; inspect immutable evidence')
        return result

    def close_trial(self, trial_id):
        return self.transport.close_trial(trial_id)


class ModelWorkerTransports:
    """Two independently paced worker transports, with one account send meter."""
    name = native.PersistentTransport.name

    def __init__(self, **kwargs):
        self.workers = {model: native.PersistentTransport(**kwargs) for model in MODELS}

    @property
    def before_send(self):
        return next(iter(self.workers.values())).before_send

    @before_send.setter
    def before_send(self, value):
        for worker in self.workers.values():
            worker.before_send = value

    def request(self, trial, *args, **kwargs):
        return self.workers[trial['model']].request(trial, *args, **kwargs)

    def close_trial(self, trial_id):
        return [entry for worker in self.workers.values() for entry in worker.close_trial(trial_id)]

    def close(self):
        for worker in self.workers.values():
            worker.close()


def summarize(root, guard):
    states = [json.loads(p.read_text()) for p in sorted((root / 'states').glob('*.json'))]
    records = [json.loads(line) for line in (root / 'meter.jsonl').read_text().splitlines()] if (root / 'meter.jsonl').exists() else []
    sends = [r for r in records if r['kind'] == 'send']
    completions = [r for r in records if r['kind'] == 'turn/completed' and r.get('status') == 'completed']
    started = next((r['monotonic'] for r in records), None)
    ended = records[-1]['monotonic'] if records else None
    duration = ended - started if started is not None else 0
    allturns = [t for s in states for t in s.get('turns', [])]
    latencies = sorted(t['duration_seconds'] for t in allturns if t.get('ok'))
    overlaps, active = [], {}
    for r in records:
        if r['kind'] == 'turn/started':
            active[(r.get('thread_id'), r.get('turn_id'))] = r['monotonic']
        elif r['kind'] == 'turn/completed':
            key = (r.get('thread_id'), r.get('turn_id'))
            if key in active:
                overlaps.extend(((active.pop(key), 1), (r['monotonic'], -1)))
    current = peak = 0
    for _, delta in sorted(overlaps):
        current += delta
        peak = max(peak, current)
    counts = {'catalog_429_lines': 0, 'response_429_records': sum(r['kind'] == 'rpc_error' and r.get('is_429', False) for r in records),
              'unclassified_429_lines': 0}
    for path in (root / 'native').rglob('process.stderr.log'):
        for line in path.read_text(errors='replace').splitlines():
            if RATE.search(line):
                key = 'catalog_429_lines' if re.search(r'models_manager|/models|model catalog', line, re.I) else 'unclassified_429_lines'
                counts[key] += 1
    loaded = [r for r in completions if started is not None and r['monotonic'] >= started + 20]
    loaded_duration = max(0, duration - 20)
    audit_results = []
    for s in states:
        if s['status'] == 'complete':
            p = root / 'states' / (s['trial']['trial_id'] + '.json')
            audit_results.append(audit_trial(s['trial'], MainProtocol(), p, s['freeze_sha256'])['integrity_ok'])
    return {'ended_at': now(), 'sessions_observed': len(states), 'sessions_complete': sum(s['status'] == 'complete' for s in states),
            'successful_turns': sum(t.get('ok') is True for t in allturns), 'logical_sends': len(sends),
            'duration_seconds': duration, 'successful_turns_per_minute': len(completions) / duration * 60 if duration else None,
            'after20_seconds_successful_turns_per_minute': len(loaded) / loaded_duration * 60 if loaded_duration else None,
            'p95_response_seconds': latencies[math.ceil(.95*len(latencies))-1] if latencies else None,
            'visible_rpc_turn_overlap_peak': peak, 'diagnostics': counts, 'stop_reason': guard.reason,
            'complete_session_audits_ok': all(audit_results) and bool(audit_results),
            'uncertain_pending_states': sum(s.get('pending_turn') is not None for s in states),
            'note': 'No HTTP retry count or provider-internal execution count is inferred. Finite successful load does not establish an immutable service limit.'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--stage', required=True)
    p.add_argument('--pool', required=True, type=int)
    p.add_argument('--sessions', required=True, type=int)
    p.add_argument('--account-interval', required=True, type=float)
    p.add_argument('--per-model-workers', action='store_true')
    args = p.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', args.stage) or not 1 <= args.pool <= 10 or args.sessions < args.pool or args.account_interval < 0:
        p.error('Invalid bounded stage')
    root = args.root.resolve() / args.stage
    root.mkdir(parents=True, exist_ok=False)
    frozen, freeze_hash = verify_freeze(BUNDLE / 'freeze.json')
    coordinator = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                                 'exp7/persistent-v1-coordination', args.root / 'main-status.git')
    guard = Guard(coordinator, args.root)
    guard.check()
    plan = load_bundle(BUNDLE)
    templates = [next(t for t in plan['trials'] if t['model'] == m and t['effort'] == 'medium'
                      and t['arm'] == 'en_schema' and t['frame'] == 'cards' and t['game'] == 'seq') for m in MODELS]
    trials = []
    for i in range(args.sessions):
        trial = dict(templates[i % len(templates)])
        trial.update(evaluation_source_trial_id=trial['trial_id'], trial_id=f'capacity-{args.stage}-{i+1:03d}',
                     run_id='equivoque-2026-11-08-exp7-capacity-v1-' + args.stage,
                     cohort='technical_capacity', split='calibration', fold=None)
        trials.append(trial)
    atomic_json(root / 'profile.json', {'stage': args.stage, 'created_at': now(), 'pool': args.pool, 'sessions': args.sessions,
        'account_interval_seconds': args.account_interval, 'per_transport_interval_seconds': 1,
        'models': list(MODELS), 'effort': 'medium', 'per_model_workers': args.per_model_workers,
        'frozen_scientific_sha256': freeze_hash,
        'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'sample_inclusion': False,
        'trials': trials, 'source_commit': frozen['source_commit']})
    meter = Meter(root, guard, args.account_interval)
    instrument(meter, guard)
    factory = ModelWorkerTransports if args.per_model_workers else native.PersistentTransport
    transport = factory(timeout=180, min_start_interval=1, catalog_path=BUNDLE / 'model-catalog.json')
    wrapped = ProbeTransport(transport, guard)
    budget = CallBudget(root / 'budget.json', 'capacity-' + args.stage, args.sessions * 34)
    iterator = iter(trials)
    try:
        with closing(transport), ThreadPoolExecutor(max_workers=args.pool) as pool:
            pending = {}
            def submit():
                if guard.stop.is_set(): return
                trial = next(iterator, None)
                if trial:
                    f = pool.submit(run_trial, trial, MainProtocol(), wrapped, root / 'states' / (trial['trial_id']+'.json'),
                                    root / 'native', budget, freeze_hash)
                    pending[f] = trial
            for _ in range(args.pool): submit()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for f in done:
                    pending.pop(f)
                    try:
                        state = f.result()
                        if state['status'] != 'complete': guard.halt('Incomplete technical session; no replacement')
                    except Exception:
                        guard.halt('Technical runner exception; preserve and inspect')
                for _ in done: submit()
    finally:
        summary = summarize(root, guard)
        summary.update(stage=args.stage, pool=args.pool, sessions_planned=args.sessions,
                       account_interval_seconds=args.account_interval, per_model_workers=args.per_model_workers)
        atomic_json(root / 'summary.json', summary)
        print(json.dumps(summary), flush=True)
    if guard.stop.is_set() or summary['sessions_complete'] != args.sessions or any(summary['diagnostics'].values()) or not summary['complete_session_audits_ok']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
