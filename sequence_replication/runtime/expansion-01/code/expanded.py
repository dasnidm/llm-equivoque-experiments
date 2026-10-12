"""Operational expansion; original study stimuli, IDs and result shards stay fixed."""
import argparse
import collections
import concurrent.futures
import datetime
import fcntl
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equivoque.core import read_json, write_json, digest
from sequence_replication.protocol import CONFIG, FREEZE, SequenceProtocol, frozen_hashes
from sequence_replication.runner import run_trial
from sequence_replication.preflight import execute_check
from equivoque.transport import CodexTransport

config = read_json(CONFIG)
RUN = config['run_id']
OP = ROOT / 'sequence_replication/runtime/expansion-01'
CONTROLS = ROOT / 'work/expanded-controls' / RUN
EXECUTORS = [f'x{i:02d}' for i in range(1, 41)]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def transact(path, action):
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = read_json(path)
            result = action(data)
            write_json(path, data)
            return result
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class PauseBeforeRequest(Exception):
    pass


class Admission:
    def __init__(self, directory, executor):
        self.directory, self.executor = Path(directory), executor
        self.pid = os.getpid()
        self.held = False
        self.admitted = None

    def acquire(self, trial, turn):
        path = self.directory / 'requests.json'
        queued_at = now()
        def enqueue(data):
            if any(x['pid'] == self.pid for x in data['queue'] + data['active']):
                raise ValueError('Executor already owns or queues a request slot')
            data['queue'].append({'pid': self.pid, 'executor': self.executor,
                'trial_id': trial['trial_id'], 'turn': turn, 'queued_at': queued_at})
        transact(path, enqueue)
        while True:
            def grant(data):
                if (self.directory / 'HALT.json').exists():
                    data['queue'] = [x for x in data['queue'] if x['pid'] != self.pid]
                    return False
                limit = read_json(self.directory / 'limit.json')['limit']
                if limit not in (5, 10, 20, 30, 40):
                    raise ValueError('Unapproved request concurrency limit')
                if len(data['active']) < limit and data['queue'] and data['queue'][0]['pid'] == self.pid:
                    item = data['queue'].pop(0)
                    item['admitted_at'] = now()
                    data['active'].append(item)
                    return item
                return None
            granted = transact(path, grant)
            if granted is False:
                raise PauseBeforeRequest('Intake paused before any request checkpoint or model invocation')
            if granted:
                self.held = True
                self.admitted = granted
                return
            time.sleep(.05)

    def release(self):
        if not self.held:
            return
        def remove(data):
            if sum(x['pid'] == self.pid for x in data['active']) != 1:
                raise ValueError('Missing or duplicate request slot')
            data['active'] = [x for x in data['active'] if x['pid'] != self.pid]
        transact(self.directory / 'requests.json', remove)
        self.held = False


class ControlledProtocol(SequenceProtocol):
    def __init__(self, admission):
        super().__init__()
        self.admission = admission

    def prompt(self, trial, turn, feedback=None, remaining=None):
        text = super().prompt(trial, turn, feedback, remaining)
        # Admission precedes the frozen run_trial's requested_at and durable
        # pending checkpoint. Queue waits are not counted as issued requests.
        self.admission.acquire(trial, turn)
        return text


class ControlledTransport:
    name = 'codex-native'
    def __init__(self, protocol, admission):
        self.inner = CodexTransport(protocol, config['turn_deadline_seconds'])
        self.admission = admission

    def request(self, *args):
        try:
            result = self.inner.request(*args)
            result['operational_admission'] = self.admission.admitted
            return result
        finally:
            self.admission.release()


def preflight(attempt):
    frozen_hashes()
    OP.mkdir(parents=True, exist_ok=True)
    directory = OP / ('preflight-' + attempt)
    directory.mkdir(parents=True, exist_ok=False)
    out = directory / 'readiness.json'
    if out.exists():
        raise ValueError('Preserve this preflight attempt; never overwrite or replay')
    report = {'run_id': RUN, 'ready': False, 'started_at': now(), 'errors': [], 'checks': [],
              'study_freeze_sha256': digest(FREEZE), 'executors': EXECUTORS,
              'code_sha256': digest(Path(__file__)), 'subject_invocations': 0}
    write_json(out, report)
    catalog = subprocess.run(['codex', 'debug', 'models'], capture_output=True, text=True, timeout=60)
    (directory / 'catalog.json').write_text(catalog.stdout)
    (directory / 'catalog.stderr.txt').write_text(catalog.stderr)
    data = json.loads(catalog.stdout)
    inventory = {m['slug']: m for m in (data if isinstance(data, list) else data['models'])}
    missing = [c['configuration_id'] for c in config['configurations'] if c['model'] not in inventory or
               c['effort'] not in [x['effort'] for x in inventory.get(c['model'], {}).get('supported_reasoning_levels', [])]]
    if catalog.returncode or missing or 'failed to refresh' in catalog.stderr.lower():
        report['errors'].append('Current exact model catalog unavailable: ' + str(missing))
    else:
        # Frozen CLI/transport/schema/context hashes are unchanged from the
        # successful 21 body inspections and four full continuity checks.
        previous = read_json(ROOT / 'sequence_replication/runtime/shared-preflight-01/readiness.json')
        if not previous['ready'] or previous['freeze_sha256'] != digest(FREEZE):
            raise ValueError('Previous common checks do not attest this frozen source')
        report['inherited_common_readiness_sha256'] = digest(ROOT / 'sequence_replication/runtime/shared-preflight-01/readiness.json')
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(execute_check, config, 500 + i, directory / 'checks' / executor,
                                  config['configurations'][i % 21], 1): executor for i, executor in enumerate(EXECUTORS)}
            for future in concurrent.futures.as_completed(futures):
                item = future.result()
                item['executor'] = futures[future]
                report['checks'].append(item)
                report['subject_invocations'] += item['invocations']
                if not item['passed']:
                    report['errors'].append('Executor native check failed: ' + item['executor'])
                write_json(out, report)
    report.update(ready=not report['errors'] and len(report['checks']) == 40, ended_at=now())
    write_json(out, report)
    if report['ready']:
        write_json(OP / 'readiness.json', report)
    print(json.dumps({'ready': report['ready'], 'checks': len(report['checks']),
                      'invocations': report['subject_invocations'], 'errors': report['errors']}))
    return 0 if report['ready'] else 2


def prepare():
    frozen_hashes()
    if CONTROLS.exists():
        raise ValueError('Expanded controls already exist; inspect rather than restart')
    legacy = read_json(ROOT / 'sequence_replication/runtime/collection-progress.json')
    if len(legacy['finished_workers']) != 10:
        raise ValueError('All original workers must drain before ownership is reassigned')
    readiness = read_json(OP / 'readiness.json')
    if not readiness['ready'] or readiness['study_freeze_sha256'] != digest(FREEZE) or readiness['code_sha256'] != digest(Path(__file__)):
        raise ValueError('Expanded executor readiness/source mismatch')
    all_trials, remaining, terminal, partial = [], [], [], []
    for w in config['workers']:
        manifest = read_json(ROOT / 'manifests' / RUN / f'worker-{w}.json')
        out = ROOT / 'work/worker-trees' / RUN / w / 'results' / RUN / ('worker-' + w)
        for trial in manifest['trials']:
            all_trials.append(trial)
            path = out / 'trials' / (trial['trial_id'].replace('/', '__') + '.json')
            if not path.exists():
                remaining.append(trial)
            else:
                state = read_json(path)
                if state['trial'] != trial:
                    raise ValueError('Changed original frozen trial')
                if state['status'] not in ('complete', 'failed', 'interrupted'):
                    partial.append(trial['trial_id'])
                else:
                    terminal.append(trial['trial_id'])
    if partial:
        raise ValueError('Drain left partial/pending sessions; reconcile before expansion: ' + str(partial[:3]))
    if len(all_trials) != 2520 or len(set(t['trial_id'] for t in all_trials)) != 2520:
        raise ValueError('Canonical roster invalid')
    random.Random(config['seeds']['assignment'] + 1001).shuffle(remaining)
    CONTROLS.mkdir(parents=True)
    write_json(CONTROLS / 'jobs.json', {'queue': remaining, 'claimed': {}, 'done': {}})
    write_json(CONTROLS / 'requests.json', {'queue': [], 'active': []})
    write_json(CONTROLS / 'limit.json', {'limit': 20, 'updated_at': now()})
    record = {'run_id': RUN, 'released_at': now(), 'scientific_protocol_unchanged': True,
              'study_freeze_sha256': digest(FREEZE), 'code_sha256': digest(Path(__file__)),
              'readiness_sha256': digest(OP / 'readiness.json'), 'original_terminal_ids': terminal,
              'remaining_ids': [t['trial_id'] for t in remaining], 'executors_ready': EXECUTORS,
              'original_finished_workers': legacy['finished_workers'], 'initial_request_limit': 20,
              'maximum_request_limit': 40, 'rounds': 10, 'assigned_total': 2520,
              'calibration_invocations': readiness['subject_invocations'],
              'original_manifest_sha256': {w: digest(ROOT / 'manifests' / RUN / f'worker-{w}.json') for w in config['workers']}}
    write_json(OP / 'launch.json', record)
    print(json.dumps({'terminal': len(terminal), 'remaining': len(remaining), 'ready_executors': 40}))


def worker(executor):
    frozen_hashes()
    launch = read_json(OP / 'launch.json')
    if executor not in launch['executors_ready'] or launch['study_freeze_sha256'] != digest(FREEZE) or launch['code_sha256'] != digest(Path(__file__)):
        raise ValueError('No matching expanded executor gate')
    with (CONTROLS / (executor + '.executor.lock')).open('a') as process_lock:
        fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        admission = Admission(CONTROLS, executor)
        protocol = ControlledProtocol(admission)
        transport = ControlledTransport(protocol, admission)
        try:
            while True:
                def claim(jobs):
                    if (CONTROLS / 'HALT.json').exists() or not jobs['queue']:
                        return None
                    t = jobs['queue'].pop(0)
                    if t['trial_id'] in jobs['claimed'] or t['trial_id'] in jobs['done']:
                        raise ValueError('Duplicate executor ownership')
                    jobs['claimed'][t['trial_id']] = {'executor': executor, 'pid': os.getpid(), 'at': now()}
                    return t
                trial = transact(CONTROLS / 'jobs.json', claim)
                if trial is None:
                    return 0
                owner = trial['worker_id']
                out = ROOT / 'work/worker-trees' / RUN / owner / 'results' / RUN / ('worker-' + owner)
                path = out / 'trials' / (trial['trial_id'].replace('/', '__') + '.json')
                if path.exists():
                    raise ValueError('New helper may claim only a never-started trial')
                (out / 'executor-provenance').mkdir(exist_ok=True)
                write_json(out / 'executor-provenance' / (executor + '.json'), {
                    'executor': executor, 'pid': os.getpid(), 'original_owner': owner,
                    'operational_launch_sha256': digest(OP / 'launch.json'),
                    'study_freeze_sha256': digest(FREEZE), 'last_claimed_trial': trial['trial_id']})
                locks = out / 'trial-locks'; locks.mkdir(exist_ok=True)
                with (locks / (path.stem + '.lock')).open('a') as trial_lock:
                    fcntl.flock(trial_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    state = run_trial(trial, protocol, transport, path, Path(config['subject_scratch_root']))
                def done(jobs):
                    if jobs['claimed'].pop(trial['trial_id'])['executor'] != executor:
                        raise ValueError('Executor ownership changed')
                    jobs['done'][trial['trial_id']] = {'executor': executor, 'status': state['status'], 'at': now()}
                transact(CONTROLS / 'jobs.json', done)
                print(json.dumps({'executor': executor, 'trial_id': trial['trial_id'], 'status': state['status']}), flush=True)
                if state['status'] == 'interrupted' or state.get('pending_turn') or (state['status'] != 'complete' and (not state['turns'] or not state['turns'][-1].get('ok'))):
                    write_json(CONTROLS / 'HALT.json', {'reason': state.get('error'), 'executor': executor, 'at': now()})
                    return 2
        except PauseBeforeRequest:
            print(json.dumps({'executor': executor, 'paused_before_request': True}), flush=True)
            return 0
        finally:
            admission.release()


SUMMARY_CACHE = {}


def snapshot():
    counts = collections.Counter()
    calls = measurements = 0
    completions = []
    seen = set()
    for w in config['workers']:
        folder = ROOT / 'work/worker-trees' / RUN / w / 'results' / RUN / ('worker-' + w) / 'trials'
        for path in folder.glob('*.json'):
            meta = path.stat()
            key = (str(path), meta.st_mtime_ns, meta.st_size)
            cached = SUMMARY_CACHE.get(str(path))
            if not cached or cached[0] != key:
                s = read_json(path)
                summary = {'id': s['trial']['trial_id'], 'status': s['status'],
                    'calls': len(s['turns']) + int(s.get('pending_turn') is not None),
                    'measurements': sum(r['local_turn'] == 3 and 'parsed' in r for r in s['turns']),
                    'completions': [(r['received_at'], r.get('duration_seconds')) for r in s['turns'] if r.get('ok')]}
                SUMMARY_CACHE[str(path)] = (key, summary)
            summary = SUMMARY_CACHE[str(path)][1]
            if summary['id'] in seen:
                raise ValueError('Duplicate scientific trial ID')
            seen.add(summary['id'])
            counts[summary['status']] += 1
            calls += summary['calls']; measurements += summary['measurements']
            completions.extend(summary['completions'])
    return counts, calls, measurements, completions


def coordinate():
    frozen_hashes()
    launch = read_json(OP / 'launch.json')
    logs = ROOT / 'work/expanded-logs' / RUN
    logs.mkdir(parents=True, exist_ok=True)
    processes, handles, finished = {}, [], {}
    def start(executor):
        out = (logs / (executor + '.stdout.log')).open('x')
        err = (logs / (executor + '.stderr.log')).open('x')
        handles.extend([out, err])
        processes[executor] = subprocess.Popen([sys.executable, str(Path(__file__)), 'worker', '--executor', executor],
                          cwd=ROOT, stdout=out, stderr=err)
    for executor in EXECUTORS[:20]: start(executor)
    write_json(OP / 'processes.json', {'coordinator_pid': os.getpid(), 'workers': {x:p.pid for x,p in processes.items()}, 'started_at': now()})
    stage, stage_started, stage_stamp, last_print = 20, time.monotonic(), now(), 0
    observations = []
    try:
        while True:
            counts, calls, measurements, completions = snapshot()
            for executor, process in processes.items():
                if executor not in finished and process.poll() is not None:
                    finished[executor] = process.returncode
                    if process.returncode and not (CONTROLS / 'HALT.json').exists():
                        write_json(CONTROLS / 'HALT.json', {'executor': executor, 'reason': 'Executor process failed', 'at': now()})
            req = read_json(CONTROLS / 'requests.json')
            moment = datetime.datetime.now(datetime.timezone.utc)
            ages = [(moment - datetime.datetime.fromisoformat(x['admitted_at'])).total_seconds() for x in req['active']]
            recent = [d for stamp, d in completions if stamp >= stage_stamp and d is not None]
            median = statistics.median(recent) if recent else None
            elapsed = time.monotonic() - stage_started
            halted = (CONTROLS / 'HALT.json').exists()
            limit = None
            if not halted and max(ages, default=0) > 240 and stage > 5: limit = 5
            elif not halted and max(ages, default=0) > 150 and stage > 10: limit = 10
            elif not halted and max(ages, default=0) > 120 and stage > 20: limit = 20
            elif not halted and stage < 40 and elapsed >= 120 and len(recent) >= 30 and max(ages, default=0) < 90 and median <= 60:
                limit = {5:10,10:20,20:30,30:40}[stage]
            if limit is not None:
                observations.append({'at': now(), 'old_limit': stage, 'new_limit': limit,
                    'elapsed_seconds': elapsed, 'completed_native_calls': len(recent),
                    'median_native_seconds': median, 'max_pending_seconds': max(ages, default=0)})
                stage, stage_started, stage_stamp = limit, time.monotonic(), now()
                write_json(CONTROLS / 'limit.json', {'limit': stage, 'updated_at': now()})
                if stage > len(processes):
                    for executor in EXECUTORS[len(processes):stage]: start(executor)
                    write_json(OP / 'processes.json', {'coordinator_pid': os.getpid(), 'workers': {x:p.pid for x,p in processes.items()}, 'updated_at': now()})
                write_json(OP / 'concurrency-observations.json', {'observations': observations})
                print(json.dumps({'event': 'concurrency_changed', **observations[-1]}), flush=True)
            progress = {'run_id': RUN, 'at': now(), 'complete': counts['complete'], 'failed': counts['failed'],
                'interrupted': counts['interrupted'], 'safe_partial': counts['active'], 'calls': calls,
                'measurements': measurements, 'active_limit': stage, 'active_trials': counts['active'],
                'active_requests': len(req['active']), 'queued_requests': len(req['queue']),
                'executor_processes': len(processes), 'maximum_pending_seconds': max(ages, default=0),
                'recent_median_seconds': median, 'recent_completed_native_calls': len(recent),
                'halted': halted, 'finished_workers': launch['original_finished_workers'],
                'finished_executors': finished, 'state': 'halted' if halted else 'collecting',
                'finished_workers_note': 'Original A-J processes intentionally drained; expanded executor completion is recorded separately.'}
            if len(finished) == len(processes):
                progress['state'] = 'finished' if not halted else 'halted'
            write_json(ROOT / 'sequence_replication/runtime/collection-progress.json', progress)
            write_json(OP / 'progress.json', progress)
            if time.monotonic() - last_print >= 20:
                print(json.dumps({'event': 'progress', **{k:v for k,v in progress.items() if k not in ['finished_workers','finished_executors']}}), flush=True)
                last_print = time.monotonic()
            if len(finished) == len(processes): break
            time.sleep(3)
    finally:
        for handle in handles: handle.close()
    return 2 if halted else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['preflight', 'prepare', 'worker', 'coordinate'])
    p.add_argument('--executor')
    p.add_argument('--attempt', default='02')
    args = p.parse_args()
    if args.command == 'preflight': return preflight(args.attempt)
    if args.command == 'prepare': prepare(); return 0
    if args.command == 'worker': return worker(args.executor)
    return coordinate()


if __name__ == '__main__':
    raise SystemExit(main())
