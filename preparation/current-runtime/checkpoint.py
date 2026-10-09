"""Publish immutable terminal trial records; never snapshots a live trial."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'
record_path = ROOT / 'work/coordinator/checkpoint-counts.json'
previous = json.loads(record_path.read_text()) if record_path.exists() else {}
changed = []
for worker in 'abcdefg':
    tree = ROOT / 'work/worker-trees' / RUN / worker
    directory = tree / 'results' / RUN / f'worker-{worker}'
    states = [(path, json.loads(path.read_text())) for path in (directory / 'trials').glob('*.json')]
    terminal = [path for path, state in states if state['status'] in ('complete', 'failed', 'interrupted')]
    if len(terminal) < previous.get(worker, 0) + 50:
        continue
    paths = []
    for path in terminal:
        paths.append(str(path.relative_to(tree)))
        journal = path.with_suffix('.journal.jsonl')
        if journal.exists():
            paths.append(str(journal.relative_to(tree)))
    paths.append(str((directory / 'provenance.json').relative_to(tree)))
    subprocess.run(['git', '-C', str(tree), 'add', '--', *paths], check=True)
    if subprocess.run(['git', '-C', str(tree), 'diff', '--cached', '--quiet']).returncode:
        subprocess.run(['git', '-C', str(tree), 'commit', '-m',
                        f'Worker {worker.upper()}: checkpoint {len(terminal)} terminal trials'],
                       check=True, stdout=subprocess.DEVNULL)
        changed.append(worker)
    previous[worker] = len(terminal)
    print(worker, len(terminal), flush=True)
if changed:
    subprocess.run(['git', 'push', 'origin', *[f'worker/{RUN}/{w}' for w in changed]], cwd=ROOT, check=True)
record_path.write_text(json.dumps(previous, indent=2) + '\n')
