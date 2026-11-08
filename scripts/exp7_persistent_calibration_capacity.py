"""Open a technical reservation when a previous owned calibration has verified."""
import json
import time
from pathlib import Path

from exp7_main_v2.coordination import GitCoordinator


def step(board):
    if board['global_stop']:
        return None, 'STOP: controller exits without resetting it'
    owned = [item for item in board['models'].values() if item.get('owner')]
    statuses = [item.get('technical_status', {}) for item in owned]
    if any(s.get('failed') or any(s.get('diagnostics', {}).values()) for s in statuses):
        return None, 'Technical failure or 429 requires inspection'
    active = sum(not s.get('readiness_and_backup_verified', False) for s in statuses)
    if len(owned) >= len(board['models']) or active >= 2:
        return None, 'No additional technical admission'
    desired = min(len(board['models']), len(owned) + 1)
    if desired <= board['global_max_concurrency']:
        return None, 'Existing cap already allows an admission'
    return desired, 'Open one reservation after verified technical completion; max two unverified owners'


def main():
    cache = Path('/workspace/work/exp7-persistent-v1-control/coordination.git')
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', cache)
    while True:
        board = c.status()
        desired, reason = step(board)
        print(json.dumps({'cap': board['global_max_concurrency'], 'desired': desired, 'reason': reason}), flush=True)
        if board['global_stop'] or reason == 'Technical failure or 429 requires inspection':
            return
        if desired is not None:
            def change(current):
                recalculated, _ = step(current)
                if recalculated != desired:
                    raise ValueError('Capacity state changed; controller stops for inspection')
                current['global_max_concurrency'] = desired
            c._mutate('Technical reservation cap ' + str(desired) + ': previous readiness and backup verified', change)
        time.sleep(60)


if __name__ == '__main__':
    main()
