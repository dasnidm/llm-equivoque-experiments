"""Prepare 20 sparse result worktrees without duplicating experiment 1 raw data."""
import argparse
from pathlib import Path
import subprocess

from equivoque.core import ROOT, read_json
from equivoque2.protocol import CONFIG, frozen_hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    frozen_hashes()
    config = read_json(CONFIG)
    base = subprocess.check_output(['git', 'rev-parse', args.base], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('Commit the preparation before creating worktrees')
    subprocess.run(['git', 'config', 'extensions.worktreeConfig', 'true'], cwd=ROOT, check=True)
    for worker in config['workers']:
        branch = f"worker/{config['run_id']}/{worker}"
        tree = ROOT / 'work/worker-trees' / config['run_id'] / worker
        if tree.exists():
            if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree, text=True).strip() != base:
                raise ValueError('Existing worktree differs from approved source')
            continue
        tree.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'worktree', 'add', '--no-checkout', '-b', branch, str(tree), base], cwd=ROOT, check=True)
        patterns = ['/*', '!/*/', '/equivoque/', '/equivoque2/', '/experiment2/',
                    '/protocol/', '/tests/', '/scripts/', '/manifests/' + config['run_id'] + '/',
                    '/results/' + config['run_id'] + '/']
        subprocess.run(['git', 'sparse-checkout', 'set', '--no-cone', '--stdin'],
                       input='\n'.join(patterns) + '\n', cwd=tree, text=True, check=True)
        print(worker.upper() + ': ' + branch, flush=True)


if __name__ == '__main__':
    main()
