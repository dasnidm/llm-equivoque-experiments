"""Launch one guarded local worker per model for the initial stage.

All child processes share the same VM-local pace file. This is not a
distributed account-rate limiter; do not start workers on other VMs in parallel.
"""
from pathlib import Path
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

from exp7_pre.runner import atomic_json
from .schedule import MODELS

ROOT = Path(__file__).resolve().parents[1]
REMOTE = 'https://github.com/dasnidm/llm-equivoque-experiments.git'
BOARD = 'exp7/cards-200-coordination-20261115'
RESULTS = 'exp7/cards-200-results-20261115'


def child(model, work_root, freeze):
    work_root = Path(work_root).resolve()
    env = os.environ.copy()
    env['EXP7_CARDS_SHARED_RATE_FILE'] = str(work_root / 'account-pace.lock')
    # Detect native retries hidden from the RPC success surface.
    env['RUST_LOG'] = 'codex_core::responses_retry=warn,error'
    args = ['--freeze', str(Path(freeze).resolve()), '--remote', REMOTE,
            '--coordination-branch', BOARD, '--results-prefix', RESULTS,
            '--work-dir', str(work_root / 'workers' / model), '--model', model,
            '--concurrency', '1', '--transport', 'persistent', '--request-interval', '1.2']
    for stage in ('prepare', 'run'):
        command = [sys.executable, '-m', 'exp7_cards.worker', stage, *args]
        print(json.dumps({'model': model, 'stage': stage, 'status': 'starting'}), flush=True)
        result = subprocess.run(command, cwd=ROOT, env=env)
        print(json.dumps({'model': model, 'stage': stage, 'return_code': result.returncode}), flush=True)
        if result.returncode:
            # Worker failure never authorizes another scientific request.
            # Attempt to stop the common board; preserve all pending evidence.
            from .coordination import GitCoordinator
            try:
                coordinator = GitCoordinator(REMOTE, BOARD, work_root/'emergency-coordination.git')
                coordinator.set_stop(True, 'Card-study supervisor observed worker failure; inspect before resuming')
            except Exception as exc:
                print('Could not confirm remote STOP:', type(exc).__name__, flush=True)
            return result.returncode
    return 0


def start(work_root, freeze):
    from .worker import verify_freeze
    from .coordination import GitCoordinator
    frozen, digest = verify_freeze(freeze)
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (work_root/'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = work_root/'launch.json'
        if manifest.exists():
            raise RuntimeError('Launch manifest exists; inspect existing workers rather than starting duplicates')
        if (work_root/'account-pace.lock').exists():
            raise RuntimeError('Pace file already exists; inspect previous activity before launch')
        board = GitCoordinator(REMOTE, BOARD, work_root/'launch-coordination.git').status()
        if (board.get('global_stop') or board.get('run_id') != frozen['run_id']
                or board.get('manifest_sha256') != frozen['manifest_sha256']
                or board.get('freeze_sha256') != digest
                or board.get('global_max_concurrency', 0) < len(MODELS)
                or set(board.get('models', {})) != set(MODELS)
                or any(m.get('owner') for m in board['models'].values())
                or any(j.get('status') != 'open' for j in board.get('jobs', {}).values())):
            raise RuntimeError('Board is stopped, occupied, or does not match this frozen allocation')
        (work_root/'account-pace.lock').touch(mode=0o600, exist_ok=False)
        logs = work_root/'logs'
        logs.mkdir(mode=0o700)
        info = {'status': 'starting', 'source': str(ROOT), 'freeze': str(Path(freeze).resolve()),
                'board': BOARD, 'workers': []}
        atomic_json(manifest, info)
        for model in MODELS:
            with (logs/(model+'.log')).open('ab', buffering=0) as out:
                process = subprocess.Popen([sys.executable, '-m', 'exp7_cards.supervise',
                    '--child', '--model', model, '--work-root', str(work_root), '--freeze', str(Path(freeze).resolve())],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                    start_new_session=True)
            info['workers'].append({'model': model, 'pid': process.pid, 'log': str(logs/(model+'.log'))})
            atomic_json(manifest, info)
            time.sleep(1)
        info['status'] = 'launched'
        atomic_json(manifest, info)
    return info


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root', required=True)
    parser.add_argument('--freeze', required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--model', choices=MODELS)
    args = parser.parse_args()
    if args.child:
        if not args.model:
            parser.error('--child requires --model')
        sys.exit(child(args.model, args.work_root, args.freeze))
    print(json.dumps(start(args.work_root, args.freeze), indent=2))
