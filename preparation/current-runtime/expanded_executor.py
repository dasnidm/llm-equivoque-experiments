"""Execution-only subdivision; call the unchanged frozen four-turn runner."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'
executor = sys.argv[1]
assignment_path = ROOT / 'preparation/current-runtime/executor-assignments-01.json'
assignment = json.loads(assignment_path.read_text())
entry = assignment['executors'][executor]
worker = entry['logical_worker']
original = ROOT / 'work/worker-trees' / RUN / worker
tree = ROOT / 'work/worker-trees' / RUN / executor
sys.path.insert(0, str(original))
from equivoque.core import Protocol, digest, frozen_hashes, read_json, write_json
from equivoque.runner import run_trial, now
from equivoque.transport import CodexTransport

frozen_hashes()
gate = read_json(ROOT / 'preparation/current-runtime/coordinator-launch-03.json')
assert gate['executor_assignment_sha256'] == digest(assignment_path)
assert gate['executors_ready'] == list('abcdefghijklmnopq')
assert gate['freeze_sha256'] == digest(original / 'protocol/freeze.json')
assert gate['base_commit'] == assignment['base_commit']
for name, expected in read_json(original / 'protocol/freeze.json')['files'].items():
    assert digest(tree / name) == expected, name
revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert subprocess.run(['git','merge-base','--is-ancestor',gate['base_commit'],revision],cwd=tree).returncode == 0
readiness_path = Path(entry['readiness'])
readiness = read_json(readiness_path)
assert readiness['ready'] and readiness['base_commit'] == gate['base_commit']
assert readiness['freeze_sha256'] == gate['freeze_sha256']
manifest_path = original / 'manifests' / RUN / f'worker-{worker}.json'
assert readiness['manifest_sha256'] == digest(manifest_path)
manifest = read_json(manifest_path)
trials = {t['trial_id']:t for t in manifest['trials']}
directory = tree / 'results' / RUN / f'worker-{worker}'
directory.mkdir(parents=True,exist_ok=True)
claims = ROOT / 'work/coordinator/expanded-claims'
claims.mkdir(exist_ok=True)
process_lock = (claims / f'executor-{executor}.lock').open('a')
fcntl.flock(process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
profile_path = directory / f'executor-{executor}-provenance.json'
assert not profile_path.exists(), 'An existing executor run must be reviewed before any resumption'
write_json(profile_path,{'executor_id':executor,'logical_worker':worker,'started_at':now(),
    'execution_commit':revision,'approved_base_commit':gate['base_commit'],
    'freeze_sha256':gate['freeze_sha256'],'assignment_sha256':digest(assignment_path),
    'readiness_sha256':digest(readiness_path),'trial_ids':entry['trial_ids'],
    'note':'Frozen run_trial and native transport imported from the original logical-worker worktree. Only exclusive execution ownership is subdivided; subject paths, manifests, prompts, targets, effort, seeds and within-trial sequencing are unchanged.'})
protocol = Protocol()
transport = CodexTransport(protocol,read_json(original/'protocol/run.v1.json')['turn_deadline_seconds'])
for trial_id in entry['trial_ids']:
    trial = trials[trial_id]
    slug = trial_id.replace('/','__')
    lock = (claims/(slug+'.lock')).open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    marker = claims/(slug+'.owner.json')
    assert not marker.exists(), 'A trial already has a durable executor claim'
    # A–G keep their existing incomplete states. Helpers may only start absent IDs.
    if executor != worker:
        assert not (original/'results'/RUN/f'worker-{worker}'/'trials'/(slug+'.json')).exists()
    write_json(marker,{'executor_id':executor,'trial_id':trial_id,'claimed_at':now(),
                      'assignment_sha256':digest(assignment_path)})
    state = run_trial(trial,protocol,transport,directory/'trials'/(slug+'.json'),
                      original/'work'/RUN/worker)
    print(json.dumps({'executor':executor,'trial_id':trial_id,'status':state['status']}),flush=True)
    fcntl.flock(lock,fcntl.LOCK_UN)
    lock.close()
    if state['status'] != 'complete' and (not state['turns'] or not state['turns'][-1].get('ok')):
        raise SystemExit('Systemic/uncertain failure; no automatic replay or replacement')
print(json.dumps({'executor':executor,'event':'executor_finished','at':now()}),flush=True)
