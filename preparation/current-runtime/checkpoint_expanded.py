"""Commit only immutable terminal records and ready executor evidence."""
import json
from pathlib import Path
import subprocess
from archive_native import archive_trial
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
import fcntl
publication_lock=(ROOT/'work/coordinator/publication.lock').open('a')
fcntl.flock(publication_lock,fcntl.LOCK_EX)
assignments=json.loads((ROOT/'preparation/current-runtime/executor-assignments-01.json').read_text())['executors']
for e,a in assignments.items():
    w=a['logical_worker'];tree=ROOT/'work/worker-trees'/RUN/e
    relative=Path('results')/RUN/f'worker-{w}';directory=tree/relative
    paths=[]
    for state_path in (directory/'trials').glob('*.json'):
        state=json.loads(state_path.read_text())
        if state['status']in ('complete','failed','interrupted'):
            paths.extend([str(state_path.relative_to(tree)),str(state_path.with_suffix('.journal.jsonl').relative_to(tree))])
            paths.append(str(archive_trial(e,w,directory,state).relative_to(tree)))
    for name in ('provenance.json',f'executor-{e}-provenance.json',f'executor-{e}-resume-02.json'):
        if (directory/name).exists():paths.append(str(relative/name))
    for path in directory.glob('preflight*/readiness.json'):
        if json.loads(path.read_text()).get('ended_at'):paths.append(str(path.parent.relative_to(tree)))
    for path in directory.glob('recovery-*'):paths.append(str(path.relative_to(tree)))
    for path in directory.glob('systemic-drain-*'):paths.append(str(path.relative_to(tree)))
    if not paths:continue
    subprocess.run(['git','add','--',*paths],cwd=tree,check=True)
    if subprocess.run(['git','diff','--cached','--quiet'],cwd=tree).returncode:
        subprocess.run(['git','commit','-m',f'Executor {e.upper()}: checkpoint immutable results and readiness'],cwd=tree,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','push','-u','origin',f'worker/{RUN}/{e}'],cwd=tree,check=True,stdout=subprocess.DEVNULL)
    print(e,'checkpointed',flush=True)
