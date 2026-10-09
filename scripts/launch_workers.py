"""Run one bounded worker process in each prepared worktree."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--phase', choices=('preflight', 'run'), required=True)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--launch')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 7:
        raise ValueError('Concurrency must be 1–7')
    if args.phase == 'run' and not args.launch:
        raise ValueError('Collection requires the coordinator launch record')

    def execute(worker):
        directory = ROOT / 'work/worker-trees' / args.run_id / worker
        if not directory.exists():
            raise ValueError(f'Missing worktree: {worker}')
        manifest = f'manifests/{args.run_id}/worker-{worker}.json'
        output = f'results/{args.run_id}/worker-{worker}'
        if args.phase == 'preflight':
            command = [sys.executable, '-m', 'equivoque', 'preflight',
                       '--manifest', manifest, '--output', output + '/preflight', '--live']
        else:
            command = [sys.executable, '-m', 'equivoque', 'run',
                       '--manifest', manifest, '--output', output,
                       '--readiness', output + '/preflight/readiness.json',
                       '--launch', str(Path(args.launch).resolve())]
        logs = ROOT / 'work/process-logs' / args.run_id
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / f'{args.phase}-{worker}.stdout.txt').open('a') as out, (
                logs / f'{args.phase}-{worker}.stderr.txt').open('a') as err:
            result = subprocess.run(command, cwd=directory, stdout=out, stderr=err)
        return {'worker_id': worker, 'phase': args.phase, 'exit_code': result.returncode}

    # Each process runs sequential turns and trials. The pool bounds active
    # model requests, even though all seven shards are assigned.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(execute, worker) for worker in 'abcdefg']
        reports = [future.result() for future in concurrent.futures.as_completed(futures)]
    print(json.dumps(sorted(reports, key=lambda r: r['worker_id']), indent=2))
    return 0 if all(r['exit_code'] == 0 for r in reports) else 2


if __name__ == '__main__':
    raise SystemExit(main())
