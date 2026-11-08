"""Wait for the shared technical gate, then launch exactly one evaluation worker."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

from exp7_main_v2.coordination import GitCoordinator
from exp7_main_v2.worker import verify_freeze
from scripts.exp7_persistent_gate import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    with (work / 'evaluation-gate.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_once(work)


def run_once(work):
    identity = json.loads((work / 'identity.private.json').read_text())
    bundle = Path('manifests/equivoque-2026-11-08-exp7-persistent-v1')
    freeze = bundle / 'freeze.json'
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', work / 'coordination.git')
    while True:
        _, digest = verify_freeze(freeze)
        result = evaluate(c.status(), identity, digest)
        print(json.dumps(result), flush=True)
        if result['terminal']:
            raise RuntimeError('Technical gate requires inspection; no worker launched')
        if result['ready']:
            break
        time.sleep(60)
    command = [sys.executable, '-m', 'exp7_main_v2.worker', 'run', '--freeze', str(freeze),
               '--coordination-branch', 'exp7/persistent-v1-coordination',
               '--results-prefix', 'exp7/persistent-v1-results', '--work-dir', str(work),
               '--model', identity['model'], '--owner', identity['owner'],
               '--concurrency', str(identity['concurrency']), '--transport', 'persistent',
               '--request-interval', '1', '--model-catalog', str(bundle / 'model-catalog.json')]
    # Exactly one launch. No restart, replay, replacement, or STOP reset.
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
