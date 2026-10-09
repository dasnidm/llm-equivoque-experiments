"""Create seven result branches/worktrees from one validated base commit."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    base = git('rev-parse', args.base)
    if git('status', '--porcelain'):
        raise ValueError('Commit the preparation files before creating worktrees')
    for worker in 'abcdefg':
        branch = f'worker/{args.run_id}/{worker}'
        directory = ROOT / 'work/worker-trees' / args.run_id / worker
        if directory.exists():
            if git('-C', str(directory), 'rev-parse', 'HEAD') != base:
                raise ValueError('Existing worktree is at another revision')
            continue
        directory.parent.mkdir(parents=True, exist_ok=True)
        exists = subprocess.run(['git', 'show-ref', '--verify', '--quiet',
                                 'refs/heads/' + branch], cwd=ROOT).returncode == 0
        if exists:
            if git('rev-parse', branch) != base:
                raise ValueError('Existing result branch is at another revision')
            subprocess.run(['git', 'worktree', 'add', str(directory), branch],
                           cwd=ROOT, check=True)
        else:
            subprocess.run(['git', 'worktree', 'add', '-b', branch, str(directory), base],
                           cwd=ROOT, check=True)
        print(f'{worker.upper()}: {branch} -> {directory}')


if __name__ == '__main__':
    main()
