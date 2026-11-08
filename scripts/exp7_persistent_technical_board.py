"""Publish a metadata-only technical status to the owned model on the shared board."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from exp7_main_v2.coordination import GitCoordinator


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work-dir', required=True, type=Path)
    args = p.parse_args()
    work = args.work_dir.resolve()
    identity = json.loads((work / 'identity.private.json').read_text())
    model, owner = identity['model'], identity['owner']
    attempt = work / 'calibration' / 'attempt-01'
    metrics = json.loads(subprocess.check_output([sys.executable, '-m',
        'scripts.exp7_persistent_technical_metrics', '--work-dir', str(work),
        '--concurrency', str(identity['concurrency'])], text=True))
    progress = json.loads((attempt / 'progress.json').read_text()) if (attempt / 'progress.json').exists() else {}
    receipt = work / 'calibration-backups' / 'attempt-01' / 'receipt.json'
    readiness = attempt / 'readiness.json'
    status = {'updated_at': datetime.now(timezone.utc).isoformat(),
              'attempt': '01', 'finished': progress.get('finished', 0), 'assigned': 18,
              'failed': progress.get('failed', False),
              'readiness_file_present': readiness.exists(),
              'backup_receipt_present': receipt.exists(),
              'successful_turns': metrics['successful_turns'],
              'successful_turns_per_minute': metrics['successful_turns_per_minute'],
              'p95_seconds': metrics['p95_recorded_duration_seconds'],
              'local_pending_peak': metrics['observed_local_pending_peak'],
              'diagnostics': metrics['diagnostics']}
    coordinator = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                                 'exp7/persistent-v1-coordination', work / 'coordination.git')
    def update(board):
        item = coordinator._model(board, model, owner, identity['model_token'], allow_stop=True)
        if board['run_id'] != identity['run_id'] or item['concurrency'] != identity['concurrency']:
            raise ValueError('Board identity or reservation mismatch')
        item['technical_status'] = status
    coordinator._mutate('Technical status for ' + model, update)
    print(json.dumps(status))


if __name__ == '__main__':
    main()
