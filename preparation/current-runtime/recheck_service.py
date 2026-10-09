"""Shared live model/effort readiness after draining actual request timeouts."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import threading
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import Protocol,read_json,write_json,digest,frozen_hashes
from equivoque.runner import now
from equivoque.transport import CodexTransport
RUN='equivoque-2026-10-09-v1'
OUT=ROOT/'preparation/current-runtime/service-preflight-01'
assert not OUT.exists();OUT.mkdir()
frozen_hashes();protocol=Protocol();config=read_json(ROOT/'protocol/run.v1.json')
assert subprocess.check_output(['codex','--version'],text=True).strip()==config['codex_version']
auth=subprocess.run(['codex','login','status'],capture_output=True,text=True,check=True)
assert(auth.stdout+auth.stderr).strip()=='Logged in using ChatGPT'
assert read_json(ROOT/'preparation/current-runtime/access-health-01.json')['ready']
settings=read_json(ROOT/'preparation/current-runtime/executor-assignments-01.json')
stop=threading.Event();mutex=threading.Lock();completed=[]
summary=OUT/'readiness.json'
def publish():
    write_json(summary,{'run_id':RUN,'base_commit':settings['base_commit'],
        'freeze_sha256':digest(ROOT/'protocol/freeze.json'),'ready':False,
        'subject_invocations':sum(r.get('invoked',False)for r in completed),
        'checks':completed,'updated_at':now(),'maximum_concurrency':2,
        'note':'Shared service checks after actual timeouts. Per-executor frozen context/native-session isolation remains unchanged and is inherited by hash, never silently repeated as evaluation.'})
publish()
def check(c):
    if stop.is_set():r={'configuration_id':c['configuration_id'],'invoked':False,'ok':False,'reason':'Not started after a failed service check'}
    else:
        result=CodexTransport(protocol,config['turn_deadline_seconds']).request(c,'Reply with the JSON object {"ready":true}.',
            {'type':'object','additionalProperties':False,'required':['ready'],'properties':{'ready':{'type':'boolean'}}},None,
            ROOT/'work/coordinator/service-preflight-01'/c['configuration_id'],1)
        write_json(OUT/(c['configuration_id']+'.json'),result)
        try:valid=result['ok']and json.loads(result['text'])=={'ready':True}
        except(json.JSONDecodeError,TypeError):valid=False
        r={'configuration_id':c['configuration_id'],'invoked':True,'ok':valid,
           'duration_seconds':result['duration_seconds'],'timeout':result['timeout'],'exit_code':result['exit_code']}
        if not valid:stop.set()
    with mutex:completed.append(r);publish()
    print(json.dumps(r),flush=True)
    return r
with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:reports=list(pool.map(check,config['configurations']))
ready=all(r['ok']for r in reports)
write_json(summary,{**read_json(summary),'ready':ready,'ended_at':now()})
if not ready:raise SystemExit('Actual shared service blocker remains; no collection release')
for e,a in settings['executors'].items():
    w=a['logical_worker'];tree=ROOT/'work/worker-trees'/RUN/e
    for name,expected in read_json(tree/'protocol/freeze.json')['files'].items():assert digest(tree/name)==expected
    inherited=Path(a['readiness']);old=read_json(inherited);assert old['ready']and old['base_commit']==settings['base_commit']
    output=tree/'results'/RUN/f'worker-{w}'/f'preflight-service-resume-01-executor-{e}'
    output.mkdir()
    write_json(output/'readiness.json',{'run_id':RUN,'worker_id':w,'executor_id':e,'base_commit':settings['base_commit'],
        'freeze_sha256':digest(tree/'protocol/freeze.json'),'manifest_sha256':old['manifest_sha256'],
        'ready':True,'live':True,'subject_invocations':0,'ended_at':now(),
        'inherited_context_and_native_readiness':str(inherited),'inherited_readiness_sha256':digest(inherited),
        'shared_live_service_readiness':str(summary),'shared_live_service_sha256':digest(summary),
        'errors':[],'note':'All 21 model/effort pairs freshly passed shared live checks at concurrency 2. Frozen source, tool/context isolation, CLI, account route and each executor native-session checks are unchanged. Shared calls are counted once in the service preflight, not once per executor.'})
print('All 21 shared access checks pass; all 17 unchanged executor profiles revalidated.',flush=True)
