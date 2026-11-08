"""Stop intake if the explicit Astra continuation exits without verified evidence."""
import sys
import time
from pathlib import Path
from exp7_main_v2.coordination import GitCoordinator, utc_now


def alive(pid):
    try:
        # Zombie processes are finished even if kill(pid, 0) still succeeds.
        stat = Path('/proc') / str(pid) / 'stat'
        return stat.read_text().rsplit(') ', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False


def main():
    pid = int(sys.argv[1])
    while alive(pid):
        time.sleep(15)
    work = Path('/workspace/work/exp7-persistent-v1-astra')
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', work / 'coordination.git')
    def check(board):
        status = board['models']['gpt-6-astra'].setdefault('technical_status', {})
        if not status.get('readiness_and_backup_verified'):
            if not board['global_stop']:
                board.update(global_stop=True, stop_reason='Astra continuation exited without verified readiness and backup',
                             stop_updated_at=utc_now())
            status.update(failed=True, readiness_and_backup_verified=False)
    c._mutate('Record completion guard result for Astra technical continuation', check)


if __name__ == '__main__':
    main()
