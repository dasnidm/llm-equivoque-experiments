"""Audit and publish one terminal shard using a fresh tool credential environment."""
import argparse
import fcntl
import json
import subprocess

from equivoque.core import ROOT, digest, read_json
from equivoque2.audit import audit_worker
from equivoque2.protocol import CONFIG, FREEZE, frozen_hashes


def main():
    config = read_json(CONFIG)
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True, choices=config['workers'])
    args = parser.parse_args()
    frozen_hashes()
    progress = read_json(ROOT / 'experiment2/runtime/collection-progress.json')
    assert progress['state'] == 'finished' and len(progress['finished_workers']) == 20
    w = args.worker
    tree = ROOT / 'work/worker-trees' / config['run_id'] / w
    branch = f"worker/{config['run_id']}/{w}"
    assert subprocess.check_output(['git','branch','--show-current'],cwd=tree,text=True).strip() == branch
    freeze = read_json(tree / 'experiment2/protocol/freeze.json')
    assert digest(tree / 'experiment2/protocol/freeze.json') == digest(FREEZE)
    assert all(digest(tree / p) == h for p,h in freeze['files'].items())
    directory = tree / 'results' / config['run_id'] / f'worker-{w}'
    with (directory / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audit = audit_worker(tree / 'manifests' / config['run_id'] / f'worker-{w}.json', directory)
        assert audit['integrity_ok'] and audit['collection_finished'], audit['errors']
        (directory / 'COMPLETION.md').write_text('# Experiment 2 worker ' + w.upper() + '\n\n'
            + 'Collection finished. Frozen protocol and raw integrity passed.\n\n'
            + 'Assigned: 21. Status counts: ' + json.dumps(audit['counts']) + '.\n'
            + 'Evaluation invocations: ' + str(audit['subject_invocations']) + '.\n'
            + 'Valid measurements: ' + json.dumps(audit['valid_measurements']) + '.\n'
            + 'Native files verified: ' + str(audit['raw_files_verified']) + '.\n'
            + 'One durable completed response was recovered after runtime reconnection;\n'
            + 'no request was replayed. Original parent-observed duration/exit status\n'
            + 'for that turn remains unknown; calibration is excluded from evaluation.\n')
        subprocess.run(['git','add','--sparse','--',str(directory.relative_to(tree))],cwd=tree,check=True)
        if subprocess.run(['git','diff','--cached','--quiet'],cwd=tree).returncode:
            subprocess.run(['git','commit','-m','Finalize experiment 2 worker ' + w.upper()],cwd=tree,check=True,
                stdout=subprocess.DEVNULL)
        subprocess.run(['git','push','origin','HEAD:refs/heads/' + branch],cwd=tree,check=True)
        print(json.dumps({'worker':w,'counts':audit['counts'],'subject_invocations':audit['subject_invocations'],
            'raw_files_verified':audit['raw_files_verified'],'head':subprocess.check_output(
                ['git','rev-parse','HEAD'],cwd=tree,text=True).strip()}),flush=True)


if __name__ == '__main__':
    main()
