"""Keep 17 processes; measure and adapt whole-trial service concurrency."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
STATUS=ROOT/'preparation/current-runtime/collection-progress.json'
entries=json.loads((ROOT/'preparation/current-runtime/executor-assignments-02.json').read_text())['executors']
controls=ROOT/'work/coordinator/resume-02-controls'
old=json.loads(STATUS.read_text());calibration=old['calibration']
processes,handles,finished={},[],{}
stage=2;halted=False;started=time.monotonic();stage_stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
baseline=old['completed'];baseline_failures=sum(v['counts'].get('failed',0)for v in old['workers'].values())
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def snapshot():
    workers={w:{'counts':{},'assigned':300,'attempted':0,'subject_invocations':0,'process_running':False,'exit_code':None}for w in 'abcdefg'}
    executors={};seen=set();ages=[];durations=[]
    for e,a in entries.items():
        w=a['logical_worker'];d=ROOT/'work/worker-trees'/RUN/e/'results'/RUN/f'worker-{w}'
        counts={};invocations=0
        for p in(d/'trials').glob('*.json'):
            s=json.loads(p.read_text());key=s['trial']['trial_id'];assert key not in seen;seen.add(key)
            counts[s['status']]=counts.get(s['status'],0)+1
            workers[w]['counts'][s['status']]=workers[w]['counts'].get(s['status'],0)+1
            n=len(s['turns'])+int(s.get('pending_turn')is not None);invocations+=n
            if s.get('pending_turn'):
                ages.append((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(s['pending_turn']['requested_at'])).total_seconds())
            durations.extend(t['duration_seconds']for t in s['turns']if t['requested_at']>=stage_stamp and t['duration_seconds']is not None)
        running=e in processes and processes[e].poll()is None
        workers[w]['process_running']|=running;workers[w]['subject_invocations']+=invocations
        executors[e]={'logical_worker':w,'assigned_remaining':len(a['trial_ids']),'counts':counts,
            'subject_invocations':invocations,'process_running':running,'exit_code':finished.get(e)}
    for w,v in workers.items():
        v['attempted']=sum(v['counts'].values());members=[e for e,a in entries.items()if a['logical_worker']==w]
        if all(e in finished for e in members):v['exit_code']=0 if all(finished[e]==0 for e in members)else 2
    return workers,executors,ages,durations
def publish(workers,executors,ages,durations):
    q=json.loads((controls/'queue.json').read_text())
    r={'run_id':RUN,'updated_at':now(),'active_limit':stage,'halted':halted,'workers':workers,'executors':executors,
       'calibration':calibration,'completed':sum(v['counts'].get('complete',0)for v in workers.values()),
       'attempted':sum(v['attempted']for v in workers.values()),
       'subject_invocations':sum(v['subject_invocations']for v in workers.values()),
       'executor_count':17,'execution_epoch':'resume-02','execution_state':'collecting'if not halted else 'systemic_failure_gate_closed',
       'active_trials':len(q['active']),'queued_executors':len(q['queue']),
       'old_terminal_failure_count':baseline_failures,'maximum_pending_seconds':max(ages,default=0),
       'note':'Seventeen original executors with fair whole-trial permits. Failed/completed IDs omitted from resumption. The frozen four-turn runner and all subject/model/case parameters are unchanged.'}
    tmp=STATUS.with_suffix('.json.tmp');tmp.write_text(json.dumps(r,indent=2)+'\n');tmp.replace(STATUS)
    return r
for e in entries:
    logs=ROOT/'work/process-logs'/RUN
    out=(logs/f'run-resume-02-{e}.stdout.txt').open('x');err=(logs/f'run-resume-02-{e}.stderr.txt').open('x')
    handles.extend([out,err])
    processes[e]=subprocess.Popen([sys.executable,str(ROOT/'work/coordinator/resume_executor_02.py'),e],
                                 cwd=ROOT/'work/worker-trees'/RUN/e,stdout=out,stderr=err)
last_print=0
try:
    while True:
        workers,executors,ages,durations=snapshot()
        for e,p in processes.items():
            if e not in finished and p.poll()is not None:
                finished[e]=p.returncode
                if p.returncode:halted=True
                print(json.dumps({'event':'executor_exited','executor':e,'exit_code':p.returncode}),flush=True)
        if(controls/'HALT.json').exists():halted=True
        if halted and not(controls/'HALT.json').exists():(controls/'HALT.json').write_text(json.dumps({'at':now(),'reason':'Executor failed; stop new trial grants'})+'\n')
        completed=sum(v['counts'].get('complete',0)for v in workers.values())
        elapsed=time.monotonic()-started
        median=sorted(durations)[len(durations)//2]if durations else None
        change=None;reason=None
        if not halted and stage>7 and max(ages,default=0)>90:
            change=7;reason='Pending native response exceeded 90 seconds; reduce new trial intake before the frozen deadline'
        elif not halted and stage>2 and max(ages,default=0)>150:
            change=2;reason='Long response delay; reduce new trial intake while existing trials complete'
        elif not halted and stage<17 and elapsed>=60 and completed-baseline>=10 and max(ages,default=0)<60 and median is not None and median<=20:
            change={2:4,4:7,7:10,10:17}[stage];reason='Measured completions and native response latency support increased intake'
        if change is not None:
            measurement={'execution_epoch':'resume-02','active_limit':stage,'ended_at':now(),
                'elapsed_seconds':elapsed,'completed_trials':completed-baseline,
                'completed_trials_per_minute':(completed-baseline)*60/elapsed,
                'median_recent_native_seconds':median,'maximum_pending_seconds':max(ages,default=0),
                'new_limit':change,'reason':reason,'workload_note':'Operational mixed-model observation, not a randomized scaling experiment.'}
            calibration.append(measurement);stage=change
            tmp=(controls/'limit.json.tmp');tmp.write_text(json.dumps({'limit':stage,'updated_at':now()})+'\n');tmp.replace(controls/'limit.json')
            started=time.monotonic();stage_stamp=now();baseline=completed
            print(json.dumps({'event':'concurrency_changed','measurement':measurement}),flush=True)
        r=publish(workers,executors,ages,durations)
        if time.monotonic()-last_print>=30:
            print(json.dumps({'event':'progress',**{k:r[k]for k in('updated_at','completed','attempted','subject_invocations','active_limit','active_trials','queued_executors','halted')}}),flush=True);last_print=time.monotonic()
        if len(finished)==17:publish(*snapshot());break
        time.sleep(5)
finally:
    for h in handles:h.close()
raise SystemExit(2 if halted else 0)
