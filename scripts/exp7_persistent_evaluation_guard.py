"""Fail closed if the evaluation worker exits with unfinished assigned work."""
import argparse
from pathlib import Path
import time

from exp7_main_v2.coordination import GitCoordinator, utc_now
from scripts.exp7_persistent_completion_guard import alive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--worker-pid', required=True, type=int)
    args = parser.parse_args()
    while alive(args.worker_pid):
        time.sleep(15)
    work = args.work_dir.resolve()
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', work / 'coordination.git')
    def check(board):
        outstanding = [j for j in board['jobs'].values() if j['model'] == 'gpt-6-astra'
                       and j['status'] != 'complete']
        if outstanding and not board['global_stop']:
            board.update(global_stop=True,
                         stop_reason='Astra evaluation worker exited with unfinished jobs; inspect preserved state',
                         stop_updated_at=utc_now())
    c._mutate('Inspect Astra evaluation worker exit', check)


if __name__ == '__main__':
    main()
