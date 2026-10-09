"""Calibrate 7, 10 and 17 executors against one unchanged 2,100-ID roster."""
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
STATUS=ROOT/'preparation/current-runtime/collection-progress.json'
assignments=json.loads((ROOT/'preparation/current-runtime/executor-assignments-01.json').read_text())['executors']
old=json.loads(STATUS.read_text())
calibration=old['calibration']
processes,handles,finished={},[],{}
stage=17
halted=False
stage_started=time.monotonic()
executor_trees={e:ROOT/'work/worker-trees'/RUN/e for e in assignments}
logs=ROOT/'work/process-logs'/RUN

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def snapshot():
    workers={w:{'counts':{},'assigned':300,'attempted':0,'subject_invocations':0,'seconds':[],
               'process_running':False,'exit_code':None} for w in 'abcdefg'}
    executors={}
    seen=set()
    for e,a in assignments.items():
        w=a['logical_worker'];directory=executor_trees[e]/'results'/RUN/f'worker-{w}'
        counts={};invocations=0
        for path in (directory/'trials').glob('*.json'):
            r=json.loads(path.read_text());trial_id=r['trial']['trial_id']
            if trial_id in seen:raise RuntimeError('Duplicate live trial record: '+trial_id)
            seen.add(trial_id)
            counts[r['status']]=counts.get(r['status'],0)+1
            workers[w]['counts'][r['status']]=workers[w]['counts'].get(r['status'],0)+1
            n=len(r['turns'])+int(r.get('pending_turn') is not None)
            invocations+=n
            workers[w]['subject_invocations']+=n
            workers[w]['seconds'].extend(t['duration_seconds'] for t in r['turns'] if t['duration_seconds'] is not None)
        running=e in processes and processes[e].poll() is None
        workers[w]['process_running']|=running
        executors[e]={'logical_worker':w,'assigned_remaining':len(a['trial_ids']),
            'counts':counts,'subject_invocations':invocations,'process_running':running,'exit_code':finished.get(e)}
    for w,v in workers.items():
        v['attempted']=sum(v['counts'].values())
        values=v.pop('seconds')
        v['median_recorded_turn_seconds']=statistics.median(values) if values else None
        members=[e for e,a in assignments.items() if a['logical_worker']==w]
        if all(e in finished for e in members):v['exit_code']=0 if all(finished[e]==0 for e in members) else 2
    return workers,executors

def publish(workers,executors):
    r={'run_id':RUN,'updated_at':now(),'active_limit':stage,'halted':halted,'workers':workers,
       'executors':executors,'calibration':calibration,
       'completed':sum(v['counts'].get('complete',0) for v in workers.values()),
       'attempted':sum(v['attempted'] for v in workers.values()),
       'subject_invocations':sum(v['subject_invocations'] for v in workers.values()),
       'execution_epoch':'expanded-01','executor_count':17,
       'note':'User-authorized execution subdivision. Original A–G manifests, 2,100 evaluation trial IDs and canonical model/effort/prompt matrix remain unchanged. Additional helper preflights are excluded.'}
    tmp=STATUS.with_suffix('.json.tmp');tmp.write_text(json.dumps(r,indent=2)+'\n');tmp.replace(STATUS)
    return r

def start(e):
    out=(logs/f'run-expanded-02-{e}.stdout.txt').open('x')
    err=(logs/f'run-expanded-02-{e}.stderr.txt').open('x');handles.extend([out,err])
    processes[e]=subprocess.Popen([sys.executable,str(ROOT/'work/coordinator/expanded_executor.py'),e],
                                  cwd=executor_trees[e],stdout=out,stderr=err)
    print(json.dumps({'event':'executor_started','executor':e,'logical_worker':assignments[e]['logical_worker'],
                      'active_limit':stage,'at':now()}),flush=True)

workers,executors=snapshot()
baseline={e:v['counts'].get('complete',0) for e,v in executors.items()}
for e in 'abcdefghijklmnopq':start(e)
last_print=0
try:
    while True:
        workers,executors=snapshot()
        for e,p in processes.items():
            if e not in finished and p.poll() is not None:
                finished[e]=p.returncode
                if p.returncode:halted=True
                print(json.dumps({'event':'executor_exited','executor':e,'exit_code':p.returncode,'halted':halted}),flush=True)
        if not halted and stage<17 and all(executors[e]['counts'].get('complete',0)-baseline[e]>=3 for e in processes):
            elapsed=time.monotonic()-stage_started
            n=sum(executors[e]['counts'].get('complete',0)-baseline[e] for e in processes)
            calibration.append({'active_limit':stage,'execution_epoch':'expanded-01','ended_at':now(),
                'elapsed_seconds':elapsed,'completed_trials':n,'completed_trials_per_minute':n*60/elapsed,
                'failed_trials':sum(v['counts'].get('failed',0) for v in workers.values()),
                'workload_note':'Mixed frozen model/effort subsequences. Operational calibration; stage compositions differ.'})
            stage=10 if stage==7 else 17
            stage_started=time.monotonic()
            baseline={e:v['counts'].get('complete',0) for e,v in executors.items()}
            for e in ('hij' if stage==10 else 'klmnopq'):start(e)
            print(json.dumps({'event':'concurrency_calibrated','new_limit':stage,'measurement':calibration[-1]}),flush=True)
        r=publish(workers,executors)
        if time.monotonic()-last_print>=30:
            print(json.dumps({'event':'progress',**{k:r[k] for k in ('completed','attempted','subject_invocations','active_limit','halted','updated_at')}}),flush=True)
            last_print=time.monotonic()
        if all(p.poll() is not None for p in processes.values()) and (halted or len(finished)==17):
            publish(*snapshot());break
        time.sleep(5)
finally:
    for h in handles:h.close()
raise SystemExit(2 if halted else 0)
