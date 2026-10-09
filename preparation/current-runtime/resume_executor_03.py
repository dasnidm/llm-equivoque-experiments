"""Fair trial permits wrap only scheduling; the frozen runner is unchanged."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
executor=sys.argv[1]
assignment_path=ROOT/'preparation/current-runtime/executor-assignments-03.json'
import json
assignment=json.loads(assignment_path.read_text());entry=assignment['executors'][executor]
worker=entry['logical_worker'];original=ROOT/'work/worker-trees'/RUN/worker
tree=ROOT/'work/worker-trees'/RUN/executor
sys.path.insert(0,str(original))
from equivoque.core import Protocol,read_json,write_json,digest,frozen_hashes
from equivoque.runner import run_trial,now
from equivoque.transport import CodexTransport
gate=read_json(ROOT/'preparation/current-runtime/coordinator-launch-05.json')
assert digest(assignment_path)==gate['executor_assignment_sha256']
assert gate['executors_ready']==list('abcdefghijklmnopq')
assert gate['freeze_sha256']==digest(original/'protocol/freeze.json')
ready=read_json(entry['readiness']);assert ready['ready']and ready['base_commit']==gate['base_commit']
assert ready['shared_live_service_sha256']==gate['shared_live_service_sha256']
frozen_hashes()
for name,expected in read_json(tree/'protocol/freeze.json')['files'].items():assert digest(tree/name)==expected
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert subprocess.run(['git','merge-base','--is-ancestor',gate['base_commit'],revision],cwd=tree).returncode==0
directory=tree/'results'/RUN/f'worker-{worker}'
controls=ROOT/'work/coordinator/resume-03-controls'
process_lock=(controls/f'executor-{executor}.lock').open('a')
fcntl.flock(process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
profile=directory/f'executor-{executor}-resume-03.json';assert not profile.exists()
write_json(profile,{'executor_id':executor,'logical_worker':worker,'started_at':now(),
    'execution_commit':revision,'base_commit':gate['base_commit'],'freeze_sha256':gate['freeze_sha256'],
    'assignment_sha256':digest(assignment_path),'trial_ids':entry['trial_ids'],
    'note':'Recovery epoch 03. Same original exclusive ownership and frozen native runner, with fair whole-trial permits. Failed and completed IDs are excluded.'})
scheduler_lock=(controls/'scheduler.lock').open('a')
pid=os.getpid()
def transact(action):
    fcntl.flock(scheduler_lock,fcntl.LOCK_EX)
    try:
        q=read_json(controls/'queue.json');result=action(q);write_json(controls/'queue.json',q);return result
    finally:fcntl.flock(scheduler_lock,fcntl.LOCK_UN)
def acquire(trial_id):
    def enqueue(q):
        assert not any(x['pid']==pid for x in q['queue']+q['active'])
        q['queue'].append({'pid':pid,'executor_id':executor,'trial_id':trial_id,'queued_at':now()})
    transact(enqueue)
    while True:
        def grant(q):
            if(controls/'HALT.json').exists():
                q['queue']=[x for x in q['queue']if x['pid']!=pid];return False
            limit=read_json(controls/'limit.json')['limit']
            assert limit in (2,4,7,10,17)
            if len(q['active'])<limit and q['queue']and q['queue'][0]['pid']==pid:
                item=q['queue'].pop(0);item['granted_at']=now();q['active'].append(item);return True
            return None
        answer=transact(grant)
        if answer is not None:return answer
        time.sleep(.05)
def release():
    def remove(q):
        assert sum(x['pid']==pid for x in q['active'])==1
        q['active']=[x for x in q['active']if x['pid']!=pid]
    transact(remove)
protocol=Protocol();transport=CodexTransport(protocol,read_json(original/'protocol/run.v1.json')['turn_deadline_seconds'])
manifest=read_json(original/'manifests'/RUN/f'worker-{worker}.json')
assert ready['manifest_sha256']==digest(original/'manifests'/RUN/f'worker-{worker}.json')
trials={t['trial_id']:t for t in manifest['trials']}
claims=controls/'claims';claims.mkdir(exist_ok=True)
for trial_id in entry['trial_ids']:
    if not acquire(trial_id):raise SystemExit(0)
    try:
        trial=trials[trial_id];slug=trial_id.replace('/','__');path=directory/'trials'/(slug+'.json')
        if path.exists():
            existing=read_json(path);assert existing['status']=='active'and not existing.get('pending_turn')and existing['trial']==trial
        marker=claims/(slug+'.json');assert not marker.exists()
        write_json(marker,{'trial_id':trial_id,'executor_id':executor,'claimed_at':now(),'assignment_sha256':digest(assignment_path)})
        state=run_trial(trial,protocol,transport,path,original/'work'/RUN/worker)
        print(json.dumps({'executor':executor,'trial_id':trial_id,'status':state['status'],'at':now()}),flush=True)
        if state['status']!='complete'and(not state['turns']or not state['turns'][-1].get('ok')):
            write_json(controls/'HALT.json',{'executor':executor,'trial_id':trial_id,'at':now(),'reason':state.get('error')})
            raise SystemExit(2)
    finally:release()
print(json.dumps({'executor':executor,'event':'executor_finished','at':now()}),flush=True)
