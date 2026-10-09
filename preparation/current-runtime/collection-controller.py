"""Coordinator-only concurrency calibration; frozen worker runner is unchanged."""
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'
LAUNCH = ROOT / 'preparation/current-runtime/coordinator-launch.json'
STATUS = ROOT / 'preparation/current-runtime/collection-progress.json'
LOGS = ROOT / 'work/process-logs' / RUN
processes, handles, finished = {}, [], {}
stage = 2
stage_started = time.monotonic()
stage_baseline = {w: 0 for w in 'abcdefg'}
calibration = []
halted = False


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def snapshot():
    workers = {}
    for w in 'abcdefg':
        directory = ROOT / 'work/worker-trees' / RUN / w / 'results' / RUN / f'worker-{w}'
        counts, turns, seconds, last = {}, 0, [], None
        for path in (directory / 'trials').glob('*.json'):
            record = json.loads(path.read_text())
            status = record['status']
            counts[status] = counts.get(status, 0) + 1
            turns += len(record['turns']) + int(record.get('pending_turn') is not None)
            seconds.extend(t['duration_seconds'] for t in record['turns'])
            stamp = record.get('ended_at', record['started_at'])
            if last is None or stamp > last['timestamp']:
                last = {'trial_id': record['trial']['trial_id'], 'status': status,
                        'timestamp': stamp, 'error': record.get('error')}
        workers[w] = {'counts': counts, 'assigned': 300,
            'attempted': sum(counts.values()), 'subject_invocations': turns,
            'median_recorded_turn_seconds': statistics.median(seconds) if seconds else None,
            'last': last, 'process_running': w in processes and processes[w].poll() is None,
            'exit_code': finished.get(w)}
    return workers


def publish(workers):
    record = {'run_id': RUN, 'updated_at': now(), 'active_limit': stage,
        'halted': halted, 'workers': workers, 'calibration': calibration,
        'completed': sum(w['counts'].get('complete', 0) for w in workers.values()),
        'attempted': sum(w['attempted'] for w in workers.values()),
        'subject_invocations': sum(w['subject_invocations'] for w in workers.values()),
        'note': 'Calibration uses the existing frozen evaluation roster, adds no trials or calls, and does not change prompts or choices.'}
    temporary = STATUS.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(STATUS)
    return record


def start(w):
    tree = ROOT / 'work/worker-trees' / RUN / w
    output = f'results/{RUN}/worker-{w}'
    stdout = (LOGS / f'run-{w}.stdout.txt').open('x')
    stderr = (LOGS / f'run-{w}.stderr.txt').open('x')
    handles.extend([stdout, stderr])
    command = [sys.executable, '-m', 'equivoque', 'run',
        '--manifest', f'manifests/{RUN}/worker-{w}.json', '--output', output,
        '--readiness', output + '/preflight-04/readiness.json', '--launch', str(LAUNCH)]
    processes[w] = subprocess.Popen(command, cwd=tree, stdout=stdout, stderr=stderr)
    print(json.dumps({'event': 'worker_started', 'worker': w, 'limit': stage, 'at': now()}), flush=True)


if not LAUNCH.exists():
    raise SystemExit('Coordinator launch gate absent; no collection')
if STATUS.exists():
    raise SystemExit('Existing progress record; explicitly inspect/resume rather than relaunch')
if any((ROOT / 'work/worker-trees' / RUN / w / 'results' / RUN / f'worker-{w}' / 'trials').exists() for w in 'abcdefg'):
    raise SystemExit('Existing evaluation records; this initial calibration controller must not replay them')

start('a')
start('b')
last_print = 0
try:
    while True:
        workers = snapshot()
        for w, process in processes.items():
            if w not in finished and process.poll() is not None:
                finished[w] = process.returncode
                audit_path = ROOT / 'work/worker-trees' / RUN / w / 'results' / RUN / f'worker-{w}' / 'audit.json'
                audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
                if process.returncode or not audit.get('integrity_ok') or not audit.get('collection_finished'):
                    halted = True
                print(json.dumps({'event': 'worker_exited', 'worker': w, 'exit_code': process.returncode,
                    'collection_finished': audit.get('collection_finished'), 'halted': halted}), flush=True)
        current = publish(workers)
        active = [w for w in processes if w not in finished]
        if not halted and stage < 7 and all(
                workers[w]['counts'].get('complete', 0) - stage_baseline[w] >= 5 for w in processes):
            elapsed = time.monotonic() - stage_started
            completed = sum(workers[w]['counts'].get('complete', 0) - stage_baseline[w] for w in processes)
            calibration.append({'active_limit': stage, 'ended_at': now(),
                'elapsed_seconds': elapsed, 'completed_trials': completed,
                'completed_trials_per_minute': completed * 60 / elapsed,
                'failed_trials': sum(workers[w]['counts'].get('failed', 0) for w in processes),
                'workload_note': 'Frozen mixed model/effort execution order; stage mixes differ. This is operational calibration, not a randomized scaling experiment.'})
            # Response-validation failures remain data. Any terminated systemic
            # transport/access failure blocks expansion instead of resampling.
            stage = 4 if stage == 2 else 7
            stage_started = time.monotonic()
            stage_baseline = {w: workers[w]['counts'].get('complete', 0) for w in 'abcdefg'}
            for w in ('cd' if stage == 4 else 'efg'):
                start(w)
            print(json.dumps({'event': 'concurrency_calibrated', 'new_limit': stage,
                'measurement': calibration[-1]}), flush=True)
        if time.monotonic() - last_print >= 30:
            print(json.dumps({'event': 'progress', 'completed': current['completed'],
                'attempted': current['attempted'], 'subject_invocations': current['subject_invocations'],
                'active_limit': stage, 'halted': halted, 'at': now()}), flush=True)
            last_print = time.monotonic()
        if not active and (halted or len(finished) == 7):
            publish(snapshot())
            break
        time.sleep(5)
finally:
    for handle in handles:
        handle.close()

raise SystemExit(2 if halted else 0)
