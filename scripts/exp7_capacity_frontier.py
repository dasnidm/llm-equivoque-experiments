"""Bounded request-rate frontier after a successful low-rate pool sweep."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from exp7_pre.runner import atomic_json
from scripts.exp7_capacity_suite import passed


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    baseline = json.loads((root / 'suite-summary.json').read_text())
    if not baseline.get('recommended_tested_pool') or not all(passed(s) for s in baseline['stages']):
        raise RuntimeError('Baseline suite incomplete or failed; no frontier sends')
    observations = []
    for name, pool, sessions, interval in [('rpm80-p4',4,8,.75),('rpm100-p6',6,6,.6),
                                           ('rpm110-p8',8,8,60/110),('rpm120-p8',8,8,.5)]:
        with (root / (name + '.log')).open('x') as log:
            result = subprocess.run([sys.executable,'-m','scripts.exp7_persistent_capacity_study',
                '--root',str(root),'--stage',name,'--pool',str(pool),'--sessions',str(sessions),
                '--account-interval',str(interval),'--per-model-workers'],stdout=log,stderr=subprocess.STDOUT)
        summary = json.loads((root/name/'summary.json').read_text())
        observations.append(summary)
        atomic_json(root/'frontier-summary.json',{'stages':observations,'main_run_remains_STOP':True})
        subprocess.run([sys.executable,'-m','scripts.exp7_capacity_backup','--root',str(root),'--stage',name],check=True)
        print(json.dumps({k:summary.get(k) for k in ('stage','pool','successful_turns','successful_turns_per_minute',
            'p95_response_seconds','diagnostics','stop_reason')}),flush=True)
        if result.returncode or not passed(summary):
            atomic_json(root/'frontier-summary.json',{'stages':observations,'main_run_remains_STOP':True,
                'stopped_at':name,'reason':'First failed, uncertain or rate-limited stage; no replay or further sends'})
            return


if __name__ == '__main__':
    main()
