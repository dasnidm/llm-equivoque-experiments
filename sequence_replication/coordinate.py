"""Ten worker processes with durable progress and latency-sensitive intake."""
import argparse
import concurrent.futures
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from equivoque.core import ROOT,read_json,write_json
from equivoque.runner import now,append_event
from .protocol import CONFIG,frozen_hashes


def tree(config,w):return ROOT/'work/worker-trees'/config['run_id']/w


def snapshot(config):
    workers,ages,durations,seen={},[],[],set()
    for w in config['workers']:
        out=tree(config,w)/'results'/config['run_id']/f'worker-{w}'
        counts={};calls=measurements=0
        for path in (out/'trials').glob('*.json'):
            s=read_json(path);tid=s['trial']['trial_id']
            if tid in seen:raise ValueError('Duplicate active trial')
            seen.add(tid);counts[s['status']]=counts.get(s['status'],0)+1
            calls+=len(s['turns'])+int(s.get('pending_turn') is not None)
            measurements+=sum(r['local_turn']==3 and 'parsed' in r for r in s['turns'])
            if s.get('pending_turn'):
                ages.append((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(s['pending_turn']['requested_at'])).total_seconds())
            durations.extend((r['received_at'],r['duration_seconds']) for r in s['turns'] if r.get('duration_seconds') is not None)
        workers[w]={'assigned':len(read_json(ROOT/'manifests'/config['run_id']/f'worker-{w}.json')['trials']),
                    'counts':counts,'calls':calls,'measurements':measurements}
    return workers,ages,durations


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['preflight','run'],required=True)
    p.add_argument('--shared');p.add_argument('--launch');p.add_argument('--attempt',default='01')
    args=p.parse_args();frozen_hashes();config=read_json(CONFIG)
    logs=ROOT/'work/process-logs'/config['run_id'];logs.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'sequence_replication/runtime';runtime.mkdir(parents=True,exist_ok=True)
    if args.phase=='preflight':
        def execute(w):
            with (logs/f'preflight-{args.attempt}-{w}.stdout.txt').open('x') as out,(logs/f'preflight-{args.attempt}-{w}.stderr.txt').open('x') as err:
                cmd=[sys.executable,'-m','sequence_replication','preflight','--manifest',f"manifests/{config['run_id']}/worker-{w}.json",
                     '--output',f"results/{config['run_id']}/worker-{w}/preflight-{args.attempt}",'--shared',str(Path(args.shared).resolve())]
                result=subprocess.run(cmd,cwd=tree(config,w),stdout=out,stderr=err)
            item={'worker':w,'exit_code':result.returncode,'at':now()};print(json.dumps(item),flush=True);return item
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:reports=list(pool.map(execute,config['workers']))
        write_json(runtime/f'worker-preflight-{args.attempt}.json',{'workers':reports})
        return 0 if all(r['exit_code']==0 for r in reports) else 2
    if not args.launch:raise ValueError('Coordinator gate required')
    controls=ROOT/'work/coordinator'/config['run_id']/f'controls-{args.attempt}';controls.mkdir(parents=True,exist_ok=False)
    write_json(controls/'queue.json',{'queue':[],'active':[]});write_json(controls/'limit.json',{'limit':config['initial_concurrency'],'updated_at':now()})
    processes,handles,finished={},[],{}
    for w in config['workers']:
        out=(logs/f'run-{args.attempt}-{w}.stdout.txt').open('x');err=(logs/f'run-{args.attempt}-{w}.stderr.txt').open('x');handles.extend([out,err])
        cmd=[sys.executable,'-m','sequence_replication','run','--manifest',f"manifests/{config['run_id']}/worker-{w}.json",
             '--readiness',f"results/{config['run_id']}/worker-{w}/preflight-{args.attempt}/readiness.json",
             '--launch',str(Path(args.launch).resolve()),'--controls',str(controls)]
        processes[w]=subprocess.Popen(cmd,cwd=tree(config,w),stdout=out,stderr=err)
    write_json(runtime/f'processes-{args.attempt}.json',{'coordinator_pid':__import__('os').getpid(),'workers':{w:p.pid for w,p in processes.items()},'controls':str(controls),'started_at':now()})
    stage=config['initial_concurrency'];stage_start=time.monotonic();stage_stamp=now();last_print=0;observations=[]
    try:
        while True:
            workers,ages,durations=snapshot(config)
            for w,process in processes.items():
                if w not in finished and process.poll() is not None:
                    finished[w]=process.returncode;print(json.dumps({'event':'worker_exit','worker':w,'code':process.returncode}),flush=True)
                    if process.returncode and not (controls/'HALT.json').exists():write_json(controls/'HALT.json',{'worker':w,'reason':'Worker failed','at':now()})
            halted=(controls/'HALT.json').exists();recent=[d for stamp,d in durations if stamp>=stage_stamp]
            median=statistics.median(recent) if recent else None;elapsed=time.monotonic()-stage_start
            limit=reason=None
            if not halted and stage>2 and max(ages,default=0)>240:limit,reason=2,'Pending age above 240 seconds'
            elif not halted and stage>5 and max(ages,default=0)>150:limit,reason=5,'Pending age above 150 seconds'
            elif not halted and stage<config['maximum_concurrency'] and elapsed>=30 and len(recent)>=8 and max(ages,default=0)<120 and median<=60:
                limit,reason=min(config['maximum_concurrency'],{2:5,5:10}[stage]),'Measured native-call throughput and pending ages'
            if limit is not None:
                item={'at':now(),'old_limit':stage,'new_limit':limit,'elapsed_seconds':elapsed,'completed_native_calls':len(recent),
                      'median_native_seconds':median,'max_pending_seconds':max(ages,default=0),'reason':reason}
                observations.append(item);write_json(runtime/'concurrency-observations.json',{'observations':observations})
                stage=limit;stage_start=time.monotonic();stage_stamp=now();write_json(controls/'limit.json',{'limit':stage,'updated_at':now()})
                print(json.dumps({'event':'concurrency_changed',**item}),flush=True)
            q=read_json(controls/'queue.json')
            complete=sum(r['counts'].get('complete',0) for r in workers.values())
            progress={'run_id':config['run_id'],'at':now(),'workers':workers,'complete':complete,
                      'failed':sum(r['counts'].get('failed',0) for r in workers.values()),
                      'interrupted':sum(r['counts'].get('interrupted',0) for r in workers.values()),
                      'calls':sum(r['calls'] for r in workers.values()),'measurements':sum(r['measurements'] for r in workers.values()),
                      'active_limit':stage,'active_trials':len(q['active']),'queued':len(q['queue']),
                      'maximum_pending_seconds':max(ages,default=0),'halted':halted,'finished_workers':finished,
                      'state':'finished' if len(finished)==len(config['workers']) else 'halted' if halted else 'collecting'}
            write_json(runtime/'collection-progress.json',progress)
            if time.monotonic()-last_print>=20:
                brief={k:v for k,v in progress.items() if k!='workers'};append_event(runtime/'progress-history.jsonl',brief)
                print(json.dumps({'event':'progress',**brief}),flush=True);last_print=time.monotonic()
            if len(finished)==len(config['workers']):break
            time.sleep(3)
    finally:
        for h in handles:h.close()
    return 2 if halted else 0


if __name__=='__main__':raise SystemExit(main())
