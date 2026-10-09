"""Pause parents, drain existing CLI calls, preserve them without any replay."""
import datetime
import json
import os
from pathlib import Path
import signal
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import read_json,write_json
from equivoque.runner import now
RUN='equivoque-2026-10-09-v1'
out=ROOT/'preparation/current-runtime/expansion-drain-01.json'
assert not out.exists()
assert read_json(ROOT/'preparation/current-runtime/helper-readiness-01.json')['ready']

def processes():
    result={}
    for p in Path('/proc').iterdir():
        if p.name.isdigit():
            try:result[int(p.name)]=p.joinpath('cmdline').read_bytes().decode().split('\0')[:-1]
            except (OSError,UnicodeError):pass
    return result

inventory=processes()
coordinators=[p for p,args in inventory.items() if len(args)==2 and args[1].endswith('/resume_collect.py')]
assert len(coordinators)==1
coordinator=coordinators[0]
os.kill(coordinator,signal.SIGSTOP)
for p,args in inventory.items():
    if len(args)==2 and args[1].endswith('work/coordinator/postprocess.py'):
        os.kill(p,signal.SIGTERM)
workers={}
for w in 'abcdefg':
    marker=f'manifests/{RUN}/worker-{w}.json'
    ids=[p for p,args in inventory.items() if len(args)>4 and args[1:4]==['-m','equivoque','run'] and marker in args]
    assert len(ids)==1,(w,ids)
    pid=ids[0]
    # subprocess.communicate's native wait loop is outside all checkpoint writes.
    deadline=time.monotonic()+10
    while Path(f'/proc/{pid}/wchan').read_text().strip() not in ('hrtimer_nanosleep','do_signal_stop'):
        assert time.monotonic()<deadline,'Could not pause outside checkpoint writes'
        time.sleep(.01)
    os.kill(pid,signal.SIGSTOP)
    children=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            stat=proc.joinpath('stat').read_text();fields=stat[stat.rindex(')')+2:].split()
            if int(fields[1])==pid:children.append(int(proc.name))
        except (OSError,ValueError):pass
    assert len(children)==1,(w,children)
    child=children[0]
    command=Path(f'/proc/{child}/cmdline').read_bytes().decode().split('\0')[:-1]
    if command:assert command[0]=='codex' and command[1]=='exec'
    directory=ROOT/'work/worker-trees'/RUN/w/'results'/RUN/f'worker-{w}'
    active=[(p,read_json(p)) for p in (directory/'trials').glob('*.json') if read_json(p).get('pending_turn')]
    assert len(active)==1
    state_path,state=active[0]
    if not command:
        from equivoque.transport import overrides
        scratch=ROOT/'work/worker-trees'/RUN/w/'work'/RUN/w/state['scratch_id']
        turn=state['pending_turn']['turn'];session=state['session_id']
        command=['codex','exec']+(['resume'] if session else [])
        command+=['--ignore-user-config','--ignore-rules','--skip-git-repo-check','--json','--model',state['trial']['model'],'--output-schema',str(scratch/f'turn-{turn:02d}.schema.json')]
        command+=overrides(scratch/'subject-system.txt',state['trial']['effort'])
        command+=[session,'-'] if session else ['--sandbox','read-only','-C',str(scratch/'subject'),'-']
    journal=[json.loads(line) for line in state_path.with_suffix('.journal.jsonl').read_text().splitlines()]
    assert len([j for j in journal if j['type']=='request_checkpoint'])==len(state['turns'])+1
    assert len([j for j in journal if j['type']=='response_checkpoint'])==len(state['turns'])
    workers[w]={'parent_pid':pid,'child_pid':child,'command':command,
                'trial_id':state['trial']['trial_id'],'turn':state['pending_turn']['turn'],
                'paused_at':now(),'requested_at':state['pending_turn']['requested_at']}
write_json(out,{'started_at':now(),'workers':workers,'status':'draining-existing-requests',
                'model_invocations_added':0,'reason':'User-authorized increase of executor processes from 7 to 17.'})
old=ROOT/'preparation/current-runtime/collection-progress.json'
backup=ROOT/'preparation/current-runtime/collection-progress-before-expansion-01.json'
assert not backup.exists();backup.write_bytes(old.read_bytes())
deadline=time.monotonic()+300
while True:
    waiting=[]
    for w,record in workers.items():
        if 'observed_exit_code' in record:continue
        raw=Path(f'/proc/{record["child_pid"]}/stat').read_text()
        fields=raw[raw.rindex(')')+2:].split()
        if fields[0]=='Z':
            record['observed_wait_status']=int(fields[49])
            record['observed_exit_code']=os.waitstatus_to_exitcode(int(fields[49]))
            record['exit_observed_at']=now()
            print(json.dumps({'worker':w,'drained_turn':record['turn'],'exit_code':record['observed_exit_code']}),flush=True)
        else:waiting.append(w)
    if not waiting:break
    assert time.monotonic()<deadline,'Existing native request has not drained; preserve paused state for review'
    time.sleep(.25)
assert all(r['observed_exit_code']==0 for r in workers.values()),'Existing request failed; expansion must remain gated'
write_json(out,{'started_at':read_json(out)['started_at'],'ended_at':now(),'workers':workers,
    'status':'drained-existing-requests','model_invocations_added':0,
    'reason':'User-authorized increase of executor processes from 7 to 17.',
    'exit_code_evidence':'Linux /proc child zombie stat exit_code field, converted with os.waitstatus_to_exitcode. Parents were paused in subprocess wait; existing native calls completed normally.'})
for r in workers.values():os.kill(r['parent_pid'],signal.SIGKILL)
os.kill(coordinator,signal.SIGKILL)
print('Existing native calls drained; no pending call was replayed. Offline checkpoint reconciliation is required.',flush=True)
