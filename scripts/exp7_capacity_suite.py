"""Run bounded independent load stages; stop on a failed or uncertain stage."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from exp7_pre.runner import atomic_json


def passed(s):
    return (s['sessions_complete'] == s['sessions_planned'] and s['complete_session_audits_ok']
            and not s['uncertain_pending_states'] and not s['stop_reason'] and not any(s['diagnostics'].values()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    summaries = []

    def stage(name, pool, sessions, existing=False):
        if not existing:
            with (root / (name + '.log')).open('x') as log:
                result = subprocess.run([sys.executable, '-m', 'scripts.exp7_persistent_capacity_study',
                    '--root', str(root), '--stage', name, '--pool', str(pool), '--sessions', str(sessions),
                    '--account-interval', '1'], stdout=log, stderr=subprocess.STDOUT)
        else:
            result = None
        path = root / name / 'summary.json'
        if not path.exists():
            raise RuntimeError('Stage lacks a closed summary; preserve it without replay')
        data = json.loads(path.read_text())
        summaries.append(data)
        atomic_json(root / 'suite-summary.json', {'stages': summaries, 'main_run_remains_STOP': True})
        if not (root / 'backups' / name / 'receipt.json').exists():
            subprocess.run([sys.executable, '-m', 'scripts.exp7_capacity_backup', '--root', str(root),
                            '--stage', name], check=True)
        print(json.dumps({k: data.get(k) for k in ('stage','pool','sessions_complete','successful_turns',
             'successful_turns_per_minute','p95_response_seconds','diagnostics','stop_reason')}), flush=True)
        if not passed(data) or (result is not None and result.returncode):
            raise RuntimeError('Stage not passed; no later stage or automatic retry')
        return data

    stage('p1a', 1, 2, existing=True)
    stage('p2', 2, 4)
    stage('p3', 3, 6)
    stage('p4', 4, 8)
    p3, p4 = summaries[-2:]
    if p4['successful_turns_per_minute'] > p3['successful_turns_per_minute'] * 1.10:
        stage('p6', 6, 12)
        if summaries[-1]['successful_turns_per_minute'] > p4['successful_turns_per_minute'] * 1.10:
            previous = summaries[-1]
            stage('p8', 8, 16)
            if summaries[-1]['successful_turns_per_minute'] > previous['successful_turns_per_minute'] * 1.10:
                stage('p10', 10, 20)
    best = max(s['successful_turns_per_minute'] for s in summaries)
    chosen = min(s['pool'] for s in summaries if s['successful_turns_per_minute'] >= best * .95)
    stage('confirm-p' + str(chosen), chosen, max(4, chosen * 2))
    atomic_json(root / 'suite-summary.json', {'stages': summaries, 'main_run_remains_STOP': True,
        'recommended_tested_pool': chosen, 'account_interval_seconds': 1,
        'selection_rule': 'Smallest successful pool within 95% of maximum observed stage rate; confirmed with fresh technical sessions',
        'limits': 'Finite load measurement, two models/medium only, local shared limiter; no universal zero-429 guarantee'})


if __name__ == '__main__':
    main()
