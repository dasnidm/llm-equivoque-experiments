"""Publish immutable completed records and integrate audited worker branches."""
import argparse
import json
from pathlib import Path
import subprocess

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque2.audit import audit_worker
from equivoque2.protocol import CONFIG, FREEZE, frozen_hashes


def git(directory, *args):
    return subprocess.check_output(['git', *args], cwd=directory, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('checkpoint', 'finalize', 'integrate'), required=True)
    args = parser.parse_args()
    frozen_hashes()
    config = read_json(CONFIG)
    records, all_ids, all_sessions = [], set(), set()
    if args.phase == 'integrate':
        if git(ROOT, 'status', '--porcelain'):
            raise ValueError('Commit coordinator evidence before integration')
        for w in config['workers']:
            branch = f"worker/{config['run_id']}/{w}"
            subprocess.run(['git', 'fetch', 'origin', branch], cwd=ROOT, check=True)
            if git(ROOT, 'rev-parse', branch) != git(ROOT, 'rev-parse', 'origin/' + branch):
                raise ValueError('Local worker branch differs from remote')
            subprocess.run(['git', 'merge', '--no-ff', '-m', 'Integrate experiment 2 worker ' + w.upper(), branch], cwd=ROOT, check=True)
        return 0
    for w in config['workers']:
        tree = ROOT / 'work/worker-trees' / config['run_id'] / w
        branch = f"worker/{config['run_id']}/{w}"
        if git(tree, 'branch', '--show-current') != branch:
            raise ValueError('Wrong worker branch')
        directory = tree / 'results' / config['run_id'] / f'worker-{w}'
        paths = []
        if args.phase == 'finalize':
            audit = audit_worker(tree / 'manifests' / config['run_id'] / f'worker-{w}.json', directory)
            if not audit['integrity_ok'] or not audit['collection_finished']:
                raise ValueError('Worker incomplete or audit failed: ' + w)
            manifest = read_json(tree / 'manifests' / config['run_id'] / f'worker-{w}.json')
            ids = {t['trial_id'] for t in manifest['trials']}
            if all_ids & ids or all_sessions & set(audit['session_ids']):
                raise ValueError('Duplicate evaluation IDs or sessions across workers')
            all_ids |= ids
            all_sessions |= set(audit['session_ids'])
            (directory / 'COMPLETION.md').write_text('# Experiment 2 worker ' + w.upper() + '\n\n'
                + 'Collection finished. Frozen protocol and raw integrity passed.\n\n'
                + 'Assigned: 21. Status counts: ' + json.dumps(audit['counts']) + '.\n'
                + 'Evaluation invocations: ' + str(audit['subject_invocations']) + '.\n'
                + 'Valid measurements: ' + json.dumps(audit['valid_measurements']) + '.\n'
                + 'Native files verified: ' + str(audit['raw_files_verified']) + '.\n')
            paths = [str(directory.relative_to(tree))]
            records.append({'worker': w, 'audit_sha256': digest(directory / 'audit.json'),
                            'counts': audit['counts'], 'subject_invocations': audit['subject_invocations']})
        else:
            for preflight in directory.glob('preflight-*'):
                if (preflight / 'readiness.json').exists() and read_json(preflight / 'readiness.json').get('ended_at'):
                    paths.append(str(preflight.relative_to(tree)))
            if (directory / 'provenance.json').exists():
                paths.append(str((directory / 'provenance.json').relative_to(tree)))
            for state_path in (directory / 'trials').glob('*.json'):
                state = read_json(state_path)
                if state['status'] not in ('complete', 'failed', 'interrupted'):
                    continue
                paths.extend([str(state_path.relative_to(tree)), str(state_path.with_suffix('.journal.jsonl').relative_to(tree))])
                native = directory / 'native-raw' / state['trial']['trial_id'].replace('/', '__')
                if native.exists():
                    paths.append(str(native.relative_to(tree)))
        if paths:
            subprocess.run(['git', 'add', '--sparse', '--', *paths], cwd=tree, check=True)
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=tree).returncode
        if changed:
            subprocess.run(['git', 'commit', '-m', ('Finalize' if args.phase == 'finalize' else 'Checkpoint') + ' experiment 2 worker ' + w.upper()], cwd=tree, check=True)
        subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/' + branch], cwd=tree, check=True)
        print(json.dumps({'worker': w, 'phase': args.phase, 'remote_head': git(tree, 'rev-parse', 'HEAD')}), flush=True)
    if args.phase == 'finalize':
        if len(all_ids) != 420:
            raise ValueError('Finalized union is not exactly 420 trials')
        write_json(ROOT / 'experiment2/runtime/finalized-workers.json', {
            'run_id': config['run_id'], 'trials': len(all_ids), 'unique_sessions': len(all_sessions),
            'freeze_sha256': digest(FREEZE), 'workers': records})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
