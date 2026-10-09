"""Stop new evaluation calls and drain existing ones under the same deadline."""
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
REPORT=ROOT/'preparation/current-runtime/systemic-drain-01.json'
assert not REPORT.exists()
assignment=read_json(ROOT/'preparation/current-runtime/executor-assignments-01.json')['executors']
inventory={}
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:inventory[int(p.name)]=p.joinpath('cmdline').read_bytes().decode().split('\0')[:-1]
    except (OSError,UnicodeError):pass
coordinators=[p for p,a in inventory.items()if len(a)==2 and a[1].endswith('/expanded_collect.py')]
assert len(coordinators)==1
os.kill(coordinators[0],signal.SIGSTOP)
records={}
for pid,args in inventory.items():
    if len(args)!=3 or not args[1].endswith('/expanded_executor.py'):continue
    e=args[2];w=assignment[e]['logical_worker']
    try:
        deadline=time.monotonic()+5
        while Path(f'/proc/{pid}/wchan').read_text().strip()!='hrtimer_nanosleep':
            assert time.monotonic()<deadline
            time.sleep(.005)
        os.kill(pid,signal.SIGSTOP)
    except FileNotFoundError:continue
    children=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            stat=proc.joinpath('stat').read_text();fields=stat[stat.rindex(')')+2:].split()
            if int(fields[1])==pid:children.append(int(proc.name))
        except (OSError,ValueError):pass
    assert len(children)==1,(e,children)
    child=children[0]
    command=Path(f'/proc/{child}/cmdline').read_bytes().decode().split('\0')[:-1]
    directory=ROOT/'work/worker-trees'/RUN/e/'results'/RUN/f'worker-{w}'
    states=[(p,read_json(p))for p in (directory/'trials').glob('*.json')if read_json(p).get('pending_turn')]
    assert len(states)==1,(e,len(states))
    path,state=states[0];request=state['pending_turn']
    records[e]={'logical_worker':w,'parent_pid':pid,'child_pid':child,'command':command,
                'trial_id':state['trial']['trial_id'],'state_path':str(path),'turn':request['turn'],
                'requested_at':request['requested_at'],'paused_at':now(),
                'deadline_unix':datetime.datetime.fromisoformat(request['requested_at']).timestamp()+300,
                'external_deadline_kill':False}
write_json(REPORT,{'started_at':now(),'status':'draining','workers':records,'model_invocations_added':0,
    'reason':'Multiple actual native 300-second timeouts. Global new-trial starts are closed while existing calls drain.',
    'deadline_note':'External watchdog conservatively enforces 300 seconds from the durable requested_at timestamp while parent wait loops are paused. No response arriving beyond that bound is accepted.'})
while True:
    waiting=[]
    for e,r in records.items():
        if 'observed_exit_code'in r:continue
        stat=Path(f'/proc/{r["child_pid"]}/stat').read_text();fields=stat[stat.rindex(')')+2:].split()
        if fields[0]=='Z':
            r['observed_exit_code']=os.waitstatus_to_exitcode(int(fields[49]));r['exit_observed_at']=now()
            print(json.dumps({'executor':e,'existing_call_exit':r['observed_exit_code'],'external_deadline_kill':r['external_deadline_kill']}),flush=True)
        else:
            if time.time()>=r['deadline_unix']and not r['external_deadline_kill']:
                os.killpg(r['child_pid'],signal.SIGKILL);r['external_deadline_kill']=True
            waiting.append(e)
    write_json(REPORT,{**read_json(REPORT),'workers':records,'updated_at':now()})
    if not waiting:break
    time.sleep(.1)
for r in records.values():os.kill(r['parent_pid'],signal.SIGKILL)
os.kill(coordinators[0],signal.SIGKILL)
write_json(REPORT,{**read_json(REPORT),'status':'all_existing_calls_drained','ended_at':now(),'workers':records})
print('No new evaluation call started during drain. Offline checkpoint reconciliation is required.',flush=True)
