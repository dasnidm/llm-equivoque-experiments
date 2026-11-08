"""Publish metadata-only evaluation metrics while a single worker is alive."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from exp7_main_v2.coordination import GitCoordinator
from scripts.exp7_persistent_completion_guard import alive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--worker-pid', required=True, type=int)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    identity = json.loads((work / 'identity.private.json').read_text())
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', work / 'coordination.git')
    while alive(args.worker_pid):
        if (work / 'jobs').is_dir():
            raw = subprocess.check_output([sys.executable, '-m', 'scripts.exp7_persistent_evaluation_metrics',
                                           '--work-dir', str(work), '--concurrency', str(identity['concurrency'])], text=True)
            metrics = json.loads(raw)
            metrics['monitor_updated_at'] = datetime.now(timezone.utc).isoformat()
            with (work / 'evaluation-metrics.jsonl').open('a') as log:
                log.write(json.dumps(metrics) + '\n')
            def update(board):
                item = c._model(board, identity['model'], identity['owner'], identity['model_token'], allow_stop=True)
                if board['run_id'] != identity['run_id'] or item['concurrency'] != identity['concurrency']:
                    raise ValueError('Board identity or reservation mismatch')
                item['evaluation_status'] = metrics
            c._mutate('Publish Astra evaluation telemetry', update)
            print(json.dumps(metrics), flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
