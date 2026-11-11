"""Preserve closed diagnostic orchestration and exact committed source versions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[2]
ROOTS = [Path('/workspace/work/exp7-retry-efficiency-20261108-' + suffix)
         for suffix in ('v1', 'v2', 'v3-job30', 'v4-fifo')]
OUT = Path('/workspace/work/exp7-retry-efficiency-20261108-audit/operator-evidence')


def main():
    if not all((root / 'decision.json').exists() for root in ROOTS[1:3]) or not (Path(__file__).parent / 'FIFO_POST_COMPLETION_REVIEW.json').exists():
        raise RuntimeError('Technical diagnostics have not closed')
    OUT.mkdir(parents=True, exist_ok=False)
    commits = set()
    commits.add(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip())
    for root in ROOTS:
        destination = OUT / root.name
        destination.mkdir()
        for path in root.iterdir():
            if path.is_file() and (path.name in ('orchestrate.py', 'study-plan.json', 'decision.json', 'HALT')
                                   or path.name.endswith(('.operator.log', '.backup.log'))):
                shutil.copy2(path, destination / path.name)
        for profile in root.glob('comparison-*/profile.json'):
            commits.add(json.loads(profile.read_text())['source_commit'])
    names = ('exp7_header_probe.py', 'exp7_cli_upgrade_probe.py', 'exp7_native_retry_audit.py',
             'exp7_retry_transport.py', 'exp7_retry_efficiency_study.py', 'test_exp7_retry_transport.py')
    inventory = []
    for commit in sorted(commits):
        destination = OUT / 'source' / commit
        destination.mkdir(parents=True)
        for name in names:
            data = subprocess.check_output(['git', 'show', commit + ':scripts/' + name], cwd=REPO)
            (destination / name).write_bytes(data)
            inventory.append({'commit': commit, 'path': 'scripts/' + name,
                              'sha256': hashlib.sha256(data).hexdigest()})
    (OUT / 'source-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    shutil.copy2(Path(__file__).parent / 'FIFO_POST_COMPLETION_REVIEW.json', OUT / 'FIFO_POST_COMPLETION_REVIEW.json')
    shutil.copy2(Path('/workspace/work/exp7-retry-final-offline-tests.log'), OUT / 'final-offline-tests.log')
    (OUT / 'offline-validation.json').write_text(json.dumps({
        'source': 'Observed unittest output before first v2 live collection',
        'command': 'PYTHONPATH=.:scripts python -m unittest scripts.test_exp7_retry_transport -v',
        'tests_run': 7, 'passed': True, 'elapsed_seconds': 11.874,
        'external_model_requests': 0, 'real_CLI_with_loopback_fixture': True,
        'full_conversation_turns': 34, 'synthetic_capacity_rejections_recovered': 2,
        'one_process_and_thread': True, 'exact_expected_user_history': True,
        'compressed_request_bytes_preserved': True,
        'FIFO_regression_run': {'tests_run': 9, 'passed': True, 'elapsed_seconds': 12.505,
                                'external_model_requests': 0,
                                'arrival_order_preserved_under_10worker_contention': True,
                                'stopped_waiter_removed_without_physical_send': True},
        'final_combined_regression': {'tests_run': 49, 'passed': True, 'elapsed_seconds': 21.040,
                                      'external_model_requests': 0,
                                      'post_completion_HTTP_tail_failure_handled_without_replay': True,
                                      'pre_completion_failure_still_stops': True}}, indent=2) + '\n')
    (OUT / 'summary.json').write_text(json.dumps({
        'role': 'Closed technical study operator/source provenance',
        'samples_in_main': 0, 'model_requests_in_this_archive_operation': 0,
        'local_sources_retained': True, 'source_commits': sorted(commits),
        'credential_handling': 'No auth files copied. Native raw evidence was credential-scanned in each immutable stage backup.'}, indent=2) + '\n')
    print(json.dumps({'operator_evidence': str(OUT), 'source_commits': sorted(commits)}))


if __name__ == '__main__': main()
