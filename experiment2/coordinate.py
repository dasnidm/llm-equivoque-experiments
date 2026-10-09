"""Launch, measure concurrency, and monitor 20 worker processes."""
import argparse
import concurrent.futures
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from equivoque.core import ROOT, read_json, write_json
from equivoque.runner import append_event, now
from equivoque2.protocol import CONFIG, frozen_hashes


def tree(config, worker):
    return ROOT / 'work/worker-trees' / config['run_id'] / worker


def snapshot(config):
    workers, seen, ages, durations = {}, set(), [], []
    for w in config['workers']:
        d = tree(config, w) / 'results' / config['run_id'] / f'worker-{w}'
        counts, calls, measurements = {}, 0, [0] * 4
        for p in (d / 'trials').glob('*.json'):
            s = read_json(p)
            if s['trial']['trial_id'] in seen:
                raise ValueError('Duplicate trial in active worker trees')
            seen.add(s['trial']['trial_id'])
            counts[s['status']] = counts.get(s['status'], 0) + 1
            calls += len(s['turns']) + int(s.get('pending_turn') is not None)
            for i, turn in enumerate((3, 6, 9, 10)):
                measurements[i] += int(len(s['turns']) >= turn and 'parsed' in s['turns'][turn - 1])
            if s.get('pending_turn'):
                ages.append((datetime.datetime.now(datetime.timezone.utc) -
                             datetime.datetime.fromisoformat(s['pending_turn']['requested_at'])).total_seconds())
            durations.extend((t['received_at'], t['duration_seconds']) for t in s['turns']
                             if t.get('duration_seconds') is not None)
        workers[w] = {'assigned': 21, 'attempted': sum(counts.values()), 'counts': counts,
                      'subject_invocations': calls, 'valid_measurements': measurements}
    return workers, ages, durations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('preflight', 'run'), required=True)
    parser.add_argument('--shared')
    parser.add_argument('--launch')
    parser.add_argument('--attempt', default='01')
    parser.add_argument('--preflight-concurrency', type=int, default=4)
    args = parser.parse_args()
    frozen_hashes()
    config = read_json(CONFIG)
    logs = ROOT / 'work/process-logs' / config['run_id']
    logs.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / 'experiment2/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    if args.phase == 'preflight':
        if not args.shared or not 1 <= args.preflight_concurrency <= 20:
            raise ValueError('Shared readiness and a valid preflight concurrency required')
        def execute(w):
            out = logs / f'preflight-{args.attempt}-{w}.stdout.txt'
            err = logs / f'preflight-{args.attempt}-{w}.stderr.txt'
            with out.open('x') as o, err.open('x') as e:
                command = [sys.executable, '-m', 'equivoque2', 'preflight',
                    '--manifest', f"manifests/{config['run_id']}/worker-{w}.json",
                    '--output', f"results/{config['run_id']}/worker-{w}/preflight-{args.attempt}",
                    '--shared', str(Path(args.shared).resolve())]
                p = subprocess.run(command, cwd=tree(config, w), stdout=o, stderr=e)
            result = {'worker': w, 'exit_code': p.returncode, 'at': now()}
            print(json.dumps(result), flush=True)
            return result
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.preflight_concurrency) as pool:
            reports = list(pool.map(execute, config['workers']))
        write_json(runtime / f'worker-preflight-{args.attempt}.json', {'workers': reports})
        return 0 if all(r['exit_code'] == 0 for r in reports) else 2
    if not args.launch:
        raise ValueError('Collection requires a coordinator launch record')
    controls = ROOT / 'work/coordinator' / config['run_id'] / f'controls-{args.attempt}'
    controls.mkdir(parents=True, exist_ok=False)
    write_json(controls / 'queue.json', {'queue': [], 'active': []})
    write_json(controls / 'limit.json', {'limit': 2, 'updated_at': now()})
    processes, handles, finished = {}, [], {}
    for w in config['workers']:
        o = (logs / f'run-{args.attempt}-{w}.stdout.txt').open('x')
        e = (logs / f'run-{args.attempt}-{w}.stderr.txt').open('x')
        handles.extend([o, e])
        command = [sys.executable, '-m', 'equivoque2', 'run',
            '--manifest', f"manifests/{config['run_id']}/worker-{w}.json",
            '--readiness', f"results/{config['run_id']}/worker-{w}/preflight-{args.attempt}/readiness.json",
            '--launch', str(Path(args.launch).resolve()), '--controls', str(controls)]
        processes[w] = subprocess.Popen(command, cwd=tree(config, w), stdout=o, stderr=e)
    stage, started, last_print, baseline = 2, time.monotonic(), 0, 0
    stage_stamp, observations = now(), []
    write_json(runtime / f'processes-{args.attempt}.json', {'coordinator_pid': __import__('os').getpid(),
        'workers': {w: p.pid for w, p in processes.items()}, 'controls': str(controls), 'started_at': now()})
    try:
        while True:
            workers, ages, durations = snapshot(config)
            for w, p in processes.items():
                if w not in finished and p.poll() is not None:
                    finished[w] = p.returncode
                    print(json.dumps({'event': 'worker_exited', 'worker': w, 'exit_code': p.returncode}), flush=True)
                    if p.returncode and not (controls / 'HALT.json').exists():
                        write_json(controls / 'HALT.json', {'at': now(), 'worker': w, 'reason': 'Worker exited with failure'})
            halted = (controls / 'HALT.json').exists()
            complete = sum(r['counts'].get('complete', 0) for r in workers.values())
            elapsed = time.monotonic() - started
            recent = sorted(d for stamp, d in durations if stamp >= stage_stamp)
            median = recent[len(recent) // 2] if recent else None
            limit, reason = None, None
            if not halted and stage > 5 and max(ages, default=0) > 90:
                limit, reason = 5, 'Pending response exceeds 90 seconds; reduce new trial intake'
            elif not halted and stage > 2 and max(ages, default=0) > 150:
                limit, reason = 2, 'Pending response exceeds 150 seconds; reduce new trial intake'
            elif (not halted and stage < 20 and elapsed >= 30 and complete - baseline >= 4 and
                  max(ages, default=0) < 60 and median is not None and median <= 20):
                limit, reason = {2: 5, 5: 10, 10: 20}[stage], 'Measured completions and native delays support increased intake'
            if limit is not None:
                observation = {'ended_at': now(), 'old_limit': stage, 'new_limit': limit,
                    'elapsed_seconds': elapsed, 'completed_trials': complete - baseline,
                    'completed_trials_per_minute': (complete - baseline) * 60 / elapsed,
                    'median_recent_native_seconds': median, 'maximum_pending_seconds': max(ages, default=0),
                    'reason': reason, 'note': 'Operational scheduling, not a randomized scaling comparison.'}
                observations.append(observation)
                write_json(runtime / 'concurrency-observations.json', {'observations': observations})
                stage, started, stage_stamp, baseline = limit, time.monotonic(), now(), complete
                write_json(controls / 'limit.json', {'limit': stage, 'updated_at': now()})
                print(json.dumps({'event': 'concurrency_changed', **observation}), flush=True)
            q = read_json(controls / 'queue.json')
            progress = {'run_id': config['run_id'], 'updated_at': now(), 'workers': workers,
                'completed': complete, 'attempted': sum(r['attempted'] for r in workers.values()),
                'failed': sum(r['counts'].get('failed', 0) for r in workers.values()),
                'interrupted': sum(r['counts'].get('interrupted', 0) for r in workers.values()),
                'subject_invocations': sum(r['subject_invocations'] for r in workers.values()),
                'worker_processes': 20, 'active_limit': stage, 'active_trials': len(q['active']),
                'queued_workers': len(q['queue']), 'halted': halted,
                'maximum_pending_seconds': max(ages, default=0), 'finished_workers': finished,
                'state': 'finished' if len(finished) == 20 and complete == 420 else 'halted' if halted else 'collecting'}
            write_json(runtime / 'collection-progress.json', progress)
            if time.monotonic() - last_print >= 20:
                brief = {k: v for k, v in progress.items() if k != 'workers'}
                append_event(runtime / 'progress-history.jsonl', brief)
                print(json.dumps({'event': 'progress', **brief}), flush=True)
                last_print = time.monotonic()
            if len(finished) == 20:
                break
            time.sleep(3)
    finally:
        for h in handles:
            h.close()
    return 2 if halted else 0


if __name__ == '__main__':
    raise SystemExit(main())
