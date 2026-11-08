"""One explicit continuation of Astra calibration, preserving both snapshots."""
import subprocess
import sys
from pathlib import Path

from exp7_main_v2.coordination import GitCoordinator, utc_now


def main():
    work = Path('/workspace/work/exp7-persistent-v1-astra')
    bundle = Path('manifests/equivoque-2026-11-08-exp7-persistent-v1')
    command = [sys.executable, '-m', 'exp7_main_v2.worker', 'prepare',
               '--freeze', str(bundle / 'freeze.json'), '--coordination-branch', 'exp7/persistent-v1-coordination',
               '--results-prefix', 'exp7/persistent-v1-results', '--work-dir', str(work),
               '--model', 'gpt-6-astra', '--owner', 'vm-persistent-astra', '--concurrency', '1',
               '--transport', 'persistent', '--request-interval', '1',
               '--model-catalog', str(bundle / 'model-catalog.json')]
    with (work / 'prepare-continuation.log').open('x') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    with (work / 'calibration-final-backup.log').open('x') as log:
        backup = subprocess.run([sys.executable, '-m', 'scripts.exp7_persistent_calibration_backup',
                                 '--work-dir', str(work), '--snapshot', 'final'], stdout=log, stderr=subprocess.STDOUT)
    verification = None
    if not result.returncode and not backup.returncode:
        verification = subprocess.run([sys.executable, '-m', 'scripts.exp7_persistent_technical_board',
                                       '--work-dir', str(work)])
    if result.returncode or backup.returncode or (verification is not None and verification.returncode):
        c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                           'exp7/persistent-v1-coordination', work / 'coordination.git')
        def fail(board):
            if not board['global_stop']:
                board.update(global_stop=True, stop_reason='Astra continued technical calibration, final backup or verification failed',
                             stop_updated_at=utc_now())
            status = board['models']['gpt-6-astra'].setdefault('technical_status', {})
            status.update(failed=True, readiness_and_backup_verified=False,
                          continuation_exit=result.returncode, final_backup_exit=backup.returncode,
                          verification_exit=None if verification is None else verification.returncode)
        c._mutate('Stop after Astra continued calibration, final backup or verification failure', fail)
        raise SystemExit('Calibration, backup or verification failed; STOP preserved')


if __name__ == '__main__':
    main()
