"""Detached operational supervisor for the owner's twenty-worker continuation."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from equivoque.core import ROOT, read_json, write_json
from equivoque.runner import append_event, now
from equivoque2.protocol import CONFIG, frozen_hashes
from experiment2.coordinate import snapshot, tree


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launch', required=True)
    args = parser.parse_args()
    frozen_hashes()
    config = read_json(CONFIG)
    runtime = ROOT / 'experiment2/runtime'
    authorization = read_json(runtime / 'resume-authorization-01.json')
    assert authorization['ready'] and authorization['active_limit'] == 20
    controls = ROOT / 'work/coordinator' / config['run_id'] / 'controls-resume-01'
    controls.mkdir(parents=True, exist_ok=False)
    write_json(controls / 'queue.json', {'queue':[], 'active':[]})
    write_json(controls / 'limit.json', {'limit':20, 'updated_at':now(), 'source':'explicit_owner_instruction'})
    logs = ROOT / 'work/process-logs' / config['run_id']
    processes, handles, finished = {}, [], {}
    for w in config['workers']:
        out = (logs / f'run-resume-01-{w}.stdout.txt').open('x')
        err = (logs / f'run-resume-01-{w}.stderr.txt').open('x')
        handles.extend([out,err])
        command = [sys.executable,'-m','equivoque2','run','--manifest',f"manifests/{config['run_id']}/worker-{w}.json",
            '--readiness',f"results/{config['run_id']}/worker-{w}/preflight-01/readiness.json",
            '--launch',str(Path(args.launch).resolve()),'--controls',str(controls)]
        processes[w] = subprocess.Popen(command,cwd=tree(config,w),stdout=out,stderr=err,start_new_session=True)
    write_json(runtime / 'processes-resume-01.json', {'coordinator_pid':os.getpid(),
        'workers':{w:p.pid for w,p in processes.items()}, 'controls':str(controls),'started_at':now(),
        'owner_active_limit':20, 'detached':True})
    last_print = 0
    try:
        while True:
            workers, ages, durations = snapshot(config)
            for w,p in processes.items():
                if w not in finished and p.poll() is not None:
                    finished[w] = p.returncode
                    print(json.dumps({'event':'worker_exited','worker':w,'exit_code':p.returncode}),flush=True)
                    if p.returncode and not (controls / 'HALT.json').exists():
                        write_json(controls / 'HALT.json',{'at':now(),'worker':w,'reason':'Worker exited with failure'})
            queue = read_json(controls / 'queue.json')
            halted = (controls / 'HALT.json').exists()
            completed = sum(r['counts'].get('complete',0) for r in workers.values())
            attempted = sum(r['attempted'] for r in workers.values())
            active = sum(r['counts'].get('active',0) for r in workers.values())
            progress = {'run_id':config['run_id'],'updated_at':now(),'workers':workers,'completed':completed,
                'attempted':attempted,'failed':sum(r['counts'].get('failed',0) for r in workers.values()),
                'interrupted':sum(r['counts'].get('interrupted',0) for r in workers.values()),
                'subject_invocations':sum(r['subject_invocations'] for r in workers.values()),
                'worker_processes':20,'active_limit':20,'active_trials':len(queue['active']),
                'queued_workers':len(queue['queue']),'halted':halted,'maximum_pending_seconds':max(ages,default=0),
                'finished_workers':finished,'operational_attempt':'resume-01',
                'state':'finished' if len(finished)==20 and attempted==420 and active==0 else 'halted' if halted else 'collecting'}
            write_json(runtime / 'collection-progress.json',progress)
            if time.monotonic()-last_print>=20:
                brief={k:v for k,v in progress.items() if k!='workers'}
                append_event(runtime / 'progress-history.jsonl',brief)
                print(json.dumps({'event':'progress',**brief}),flush=True)
                last_print=time.monotonic()
            if len(finished)==20:
                break
            time.sleep(3)
    finally:
        for handle in handles:
            handle.close()
    return 2 if halted else 0


if __name__=='__main__':
    raise SystemExit(main())
