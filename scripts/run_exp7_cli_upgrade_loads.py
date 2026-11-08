"""Run prespecified fresh technical stages sequentially; halt at any failure."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/workspace/work/exp7-cli-upgrade-20261108')
STABLE = WORK / 'cli-0.167.0/codex'
RAW_BRANCH = 'cli-upgrade/equivoque-2026-11-08-cli-upgrade-v1'
MODELS = ['gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-6-astra',
          'gpt-6-luna', 'gpt-6-sol', 'gpt-6.1-sol', 'gpt-6.1-terra']
PLAN = [
    {'stage': 'old-i-a3-rpm80-p4', 'version': '0.159.0-alpha.3', 'binary': '/opt/codex/bin/codex', 'pool': 4, 'sessions': 4, 'interval': .75},
    {'stage': 'stable-i-rpm100-p6', 'version': '0.167.0', 'binary': str(STABLE), 'pool': 6, 'sessions': 6, 'interval': .6},
    {'stage': 'stable-i-models8-rpm160-p8', 'version': '0.167.0', 'binary': str(STABLE), 'pool': 8, 'sessions': 8, 'interval': .375, 'models': MODELS},
    {'stage': 'stable-i-models2-rpm110-p8', 'version': '0.167.0', 'binary': str(STABLE), 'pool': 8, 'sessions': 8, 'interval': 60 / 110},
]


def now():
    return datetime.now(timezone.utc).isoformat()


def assert_no_other_probe():
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, PermissionError):
            continue
        if len(args) > 1 and args[1].endswith(b'scripts/exp7_cli_upgrade_probe.py'):
            raise RuntimeError('A previous comparison process has not exited; no new stage started')


def main():
    assert_no_other_probe()
    plan_path = WORK / 'load-suite-plan.json'
    with plan_path.open('x') as out:
        json.dump({'created_at': now(), 'plan': PLAN, 'sample_inclusion': False,
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'stop_policy': 'Any unsuccessful stage or unconfirmed backup stops the suite. No STOP is cleared and no request is replayed.'}, out, indent=2)
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    for stage in PLAN:
        name = stage['stage']
        command = [sys.executable, str(ROOT / 'scripts/exp7_cli_upgrade_probe.py'),
                   '--root', str(WORK), '--stage', name, '--version', stage['version'],
                   '--binary', stage['binary'], '--pool', str(stage['pool']),
                   '--sessions', str(stage['sessions']), '--account-interval', str(stage['interval']), '--sqlite-isolation']
        if stage.get('models'):
            command += ['--models', *stage['models']]
        print(json.dumps({'at': now(), 'stage': name, 'status': 'starting', 'pool': stage['pool']}), flush=True)
        with (WORK / (name + '.operator.log')).open('x') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=env)
        # Backup a closed failure as well; uncertainty must never be discarded.
        if (WORK / name / 'summary.json').exists():
            backup = subprocess.run([sys.executable, str(ROOT / 'scripts/exp7_capacity_backup.py'),
                                     '--root', str(WORK), '--stage', name, '--branch', RAW_BRANCH],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
            with (WORK / (name + '.backup.log')).open('x') as log:
                log.write(backup.stdout); log.write(backup.stderr)
            if backup.returncode:
                print(json.dumps({'at': now(), 'stage': name, 'status': 'stopped_at_backup_failure'}), flush=True)
                return 3
        else:
            print(json.dumps({'at': now(), 'stage': name, 'status': 'stopped_before_closed_summary'}), flush=True)
            return 2
        summary = json.loads((WORK / name / 'summary.json').read_text())
        print(json.dumps({'at': now(), 'stage': name, 'exit_code': result.returncode,
                          'complete': summary['sessions_complete'], 'turns': summary['successful_turns'],
                          'turns_per_minute': summary['successful_turns_per_minute'],
                          'diagnostics': summary['diagnostics'], 'stop_reason': summary['stop_reason']}), flush=True)
        if result.returncode:
            return result.returncode
        assert_no_other_probe()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
