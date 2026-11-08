"""Sequential unpaced technical stages; preserve every STOP and raw record."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from exp7_pre.runner import atomic_json

REPO = Path(__file__).resolve().parents[1]
STAGES = [('p10-unpaced', 20), ('p20-unpaced', 20), ('p40-unpaced', 40)]


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--study-id', required=True, help='Use a new technical study ID; never reuse a completed cohort')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    record = {'run_id': args.study_id, 'started_at': now(),
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
              'VMs_measured': 1, 'samples_in_main': 0, 'rate_cap': None,
              'retry_wait_scope': 'request', 'stages': []}
    for profile, sessions in STAGES:
        if (root / 'HALT').exists():
            record['operator_halt'] = True
            break
        command = [sys.executable, str(REPO / 'scripts/exp7_retry_efficiency_study.py'),
                   '--root', str(root / profile), '--study-id', record['run_id'],
                   '--binary', str(args.binary.resolve()), '--profile', profile,
                   '--sessions', str(sessions), '--physical-budget', '10000',
                   '--max-retries', '20', '--max-wait-seconds', '900',
                   '--stage-seconds', '1800', '--retry-wait-scope', 'request']
        stage = {'profile': profile, 'sessions': sessions, 'started_at': now(), 'command': command}
        record['stages'].append(stage)
        with (root / (profile + '.stdout')).open('x') as out, (root / (profile + '.stderr')).open('x') as err:
            process = subprocess.Popen(command, cwd=REPO, stdout=out, stderr=err)
            stage['pid'] = process.pid
            atomic_json(root / 'sweep.json', record)
            stage['exit_code'] = process.wait()
        stage['ended_at'] = now()
        atomic_json(root / 'sweep.json', record)
        print(json.dumps({k: stage[k] for k in ('profile', 'exit_code', 'ended_at')}), flush=True)
        if stage['exit_code']:
            record['halt_reason'] = 'Stage did not pass; no replacement or automatic STOP release'
            break
    record['ended_at'] = now()
    atomic_json(root / 'sweep.json', record)


if __name__ == '__main__':
    main()
