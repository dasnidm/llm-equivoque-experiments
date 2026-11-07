"""Explicit native study launcher with immutable schedules and source hashes.

Commands without 'run' or 'preflight' are offline. Failed sessions are preserved
and never replaced or retried. Authentication must be repaired by the user.
"""
import argparse
from collections import Counter
import fcntl
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from equivoque.core import ROOT
from .audit import audit_batch
from .protocol import ARMS, PreProtocol, validate_trial
from .runner import CallBudget, atomic_json, run_trial
from .transport import NativeTransport, command_for, subject_directory, unexpected_items, failure_events


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_text())
def timestamp(): return datetime.now(timezone.utc).isoformat()


def source_signature(frozen):
    files={k:v for k,v in frozen['files'].items() if not k.startswith('manifests/')}
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def result_dir(manifest): return ROOT/'results'/manifest['run_id']


def source_paths():
    paths=list((ROOT/'exp7_pre').glob('*.py'))
    paths += [ROOT/'exp7_pre/prompts.json',ROOT/'exp7_pre/design.json',
              ROOT/'equivoque/core.py',ROOT/'equivoque/transport.py',
              ROOT/'sequence_replication/protocol.py',ROOT/'sequence_replication/schedule.py',
              ROOT/'sequence_replication/protocol/prompts.json',ROOT/'sequence_replication/protocol/run.json']
    return sorted(set(paths))


def freeze(manifest_path):
    manifest_path=Path(manifest_path).resolve();manifest=load(manifest_path)
    for trial in manifest['trials']: validate_trial(trial)
    out=result_dir(manifest);out.mkdir(parents=True,exist_ok=True)
    p=out/'freeze.json'
    if p.exists():
        verify(manifest_path)
        return p
    paths=source_paths()+[manifest_path]
    files={str(f.relative_to(ROOT)):sha(f) for f in paths}
    frozen=out/'frozen-source';frozen.mkdir(exist_ok=False)
    for f in paths:
        target=frozen/f.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(f,target)
    atomic_json(p,{'run_id':manifest['run_id'],'created_at':timestamp(),
                  'manifest':str(manifest_path.relative_to(ROOT)),
                  'planned_sessions':len(manifest['trials']),'call_cap':manifest['call_cap'],
                  'cli_version':subprocess.check_output(['codex','--version'],text=True).strip(),
                  'files':files,'source_archive':'frozen-source'})
    return p


def verify(manifest_path):
    manifest_path=Path(manifest_path).resolve();manifest=load(manifest_path)
    p=result_dir(manifest)/'freeze.json';data=load(p)
    if data['run_id']!=manifest['run_id'] or data['call_cap']!=manifest['call_cap']:
        raise ValueError('Frozen run identity or call limit differs')
    if str(manifest_path.relative_to(ROOT))!=data['manifest']:
        raise ValueError('Manifest path differs from the freeze')
    for rel,digest in data['files'].items():
        if sha(ROOT/rel)!=digest: raise ValueError('Frozen file changed: '+rel)
        if sha(p.parent/'frozen-source'/rel)!=digest: raise ValueError('Frozen archive changed: '+rel)
    if subprocess.check_output(['codex','--version'],text=True).strip()!=data['cli_version']:
        raise ValueError('Native CLI version changed')
    return manifest,sha(p)


def preflight(manifest_path,output,timeout):
    """Two requests/profile: schema on, then off in the same fresh session."""
    manifest,freeze_digest=verify(manifest_path);out=Path(output).resolve()
    if out.exists(): raise ValueError('Use a new preflight output path; records are immutable')
    out.mkdir(parents=True)
    transport=NativeTransport(timeout=timeout)
    records=[]
    provenance={'evaluation_run_id':manifest['run_id'].replace('-calibration',''),
                'checked_manifest_sha256':sha(manifest_path),'checked_freeze_sha256':freeze_digest,
                'source_signature':source_signature(load(result_dir(manifest)/'freeze.json')),
                'cli_version':subprocess.check_output(['codex','--version'],text=True).strip()}
    for p in manifest['profiles']:
        directory=out/(p['model']+'-'+p['effort'])
        system='Respond in the requested format. This is an access and format check.'
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
        one=transport.request(p,'Return {"ok":true}.',schema,system,None,directory,1)
        records.append({'profile':p,'turn':1,**{k:v for k,v in one.items() if k not in ('events','stderr')}})
        atomic_json(out/'records.json',records)
        if not one['ok']:
            atomic_json(out/'support.json',{**provenance,'passed':False,'profiles':manifest['profiles'],'created_at':timestamp(),
                                         'error':'Access or schema check failed. Do not run evaluation.','records_sha256':sha(out/'records.json')})
            print(json.dumps({'passed':False,'profile':p,'error':'Access/schema check failed; inspect raw logs.'}),flush=True)
            return False
        try: correct=json.loads(one['text'])=={'ok':True}
        except ValueError: correct=False
        two=transport.request(p,'Return only the bare text READY, with no JSON, punctuation, or explanation.',None,system,one['session_id'],directory,2)
        records.append({'profile':p,'turn':2,**{k:v for k,v in two.items() if k not in ('events','stderr')}})
        atomic_json(out/'records.json',records)
        if not correct or not two['ok'] or two['text'].strip()!='READY':
            atomic_json(out/'support.json',{**provenance,'passed':False,'profiles':manifest['profiles'],'created_at':timestamp(),
                                         'error':'Same-session schema removal/response check failed.','records_sha256':sha(out/'records.json')})
            print(json.dumps({'passed':False,'profile':p,'error':'Format check failed; no substitution.'}),flush=True)
            return False
    atomic_json(out/'support.json',{**provenance,'passed':True,'profiles':manifest['profiles'],'created_at':timestamp(),
                                  'logical_invocations':len(records),'records_sha256':sha(out/'records.json')})
    print(json.dumps({'passed':True,'support_file':str(out/'support.json'),'logical_invocations':len(records)}),flush=True)
    return True


def status(manifest_path):
    from collections import Counter
    manifest=load(manifest_path);out=result_dir(manifest)
    states=[load(out/'states'/(t['trial_id']+'.json')) if (out/'states'/(t['trial_id']+'.json')).exists() else None
            for t in manifest['trials']]
    budget=load(out/'budget.json') if (out/'budget.json').exists() else None
    result={'run_id':manifest['run_id'],'assigned':len(states),
            'statuses':dict(Counter(s['status'] if s else 'unstarted' for s in states)),
            'recorded_responses':sum(len(s['turns']) for s in states if s),
            'reserved_attempts':budget['used'] if budget else 0,
            'pending_requests':sum(s.get('pending_turn') is not None for s in states if s),
            'accounting_note':'Reservations include uncertain attempts; recorded responses and reservations are not exact wire or billing counts. Preflight is separate.',
            'budget':budget}
    print(json.dumps(result,indent=2),flush=True)
    return result


def audit(manifest_path):
    manifest,digest=verify(manifest_path);out=result_dir(manifest)
    result=audit_batch(manifest['trials'],PreProtocol(),[out/'states'/(t['trial_id']+'.json') for t in manifest['trials']],digest)
    result['run_id']=manifest['run_id'];result['updated_at']=timestamp()
    atomic_json(out/'audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='trials'},indent=2))
    return result


def verify_support(path,manifest):
    path=Path(path);support=load(path);frozen=load(result_dir(manifest)/'freeze.json')
    if not support.get('passed') or support['profiles']!=manifest['profiles']:
        raise ValueError('Successful exact-profile preflight is required')
    if support.get('evaluation_run_id')!=manifest['run_id'].replace('-calibration',''):
        raise ValueError('Access check belongs to a different study')
    if support.get('source_signature')!=source_signature(frozen) or support.get('cli_version')!=frozen['cli_version']:
        raise ValueError('Preflight source or CLI changed')
    records_path=path.parent/'records.json'
    if sha(records_path)!=support['records_sha256']:raise ValueError('Preflight records changed')
    records=load(records_path)
    if len(records)!=2*len(manifest['profiles']):raise ValueError('Incomplete access checks')
    for i,p in enumerate(manifest['profiles']):
        first,second=records[2*i:2*i+2]
        if any(r.get('profile')!=p or not r.get('ok') for r in (first,second)):
            raise ValueError('Profile access check failed')
        if [first.get('turn'),second.get('turn')]!=[1,2]:
            raise ValueError('Access check turn order differs')
        if not first.get('session_id') or first['session_id']!=second.get('session_id') or first.get('provider_schema') is None or second.get('provider_schema') is not None:
            raise ValueError('Schema-removal check is invalid')
        if json.loads(first['text'])!={'ok':True} or second['text'].strip()!='READY':
            raise ValueError('Access response is invalid')
        raw_directories=[]
        for r in (first,second):
            if not r.get('raw_files'):raise ValueError('Missing native access evidence')
            for raw in r['raw_files']:
                if sha(raw['path'])!=raw['sha256']:raise ValueError('Native access evidence changed')
            named={Path(x['path']).name:Path(x['path']) for x in r['raw_files']}
            if not {'subject-system.txt','prompt.txt','events.jsonl','stderr.txt'}<=set(named) or len(named)!=len(r['raw_files']):
                raise ValueError('Incomplete access raw files')
            raw_directories.append(named['events.jsonl'].parent.parent)
            if named['subject-system.txt'].read_text()!='Respond in the requested format. This is an access and format check.':
                raise ValueError('Access system mismatch')
            expected_prompt='Return {"ok":true}.' if r['turn']==1 else 'Return only the bare text READY, with no JSON, punctuation, or explanation.'
            if named['prompt.txt'].read_text()!=expected_prompt:raise ValueError('Access prompt mismatch')
            if r['turn']==1:
                expected_schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
                if 'schema.json' not in named or load(named['schema.json'])!=expected_schema or r['provider_schema']!=expected_schema or '--output-schema' not in r['command']:
                    raise ValueError('Access schema missing or changed')
            elif 'schema.json' in named or '--output-schema' in r['command']:
                raise ValueError('Schema unexpectedly retained on access resume')
            expected_command=command_for(p,named['subject-system.txt'],subject_directory(named['events.jsonl'].parent.parent),
                                         None if r['turn']==1 else first['session_id'],named.get('schema.json'))
            if r.get('command')!=expected_command:
                raise ValueError('Access native command or requested configuration mismatch')
            events=[json.loads(line) for line in named['events.jsonl'].read_text().splitlines()]
            messages=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
            ids=[e['thread_id'] for e in events if e.get('type')=='thread.started']
            usages=[e.get('usage') for e in events if e.get('type')=='turn.completed']
            forbidden=bool(unexpected_items(events) or failure_events(events))
            fallback='fallback metadata' in named['stderr.txt'].read_text().lower() or any('fallback metadata' in str(e).lower() for e in events)
            if messages!=[r['text']] or not usages or usages[-1]!=r.get('usage') or forbidden or fallback or (ids and ids[-1]!=r['session_id']) or (r['turn']==1 and not ids):
                raise ValueError('Access metadata differs from native events')
            if r.get('exit_code')!=0 or r.get('timeout'):raise ValueError('Access process did not succeed')
        if raw_directories[0]!=raw_directories[1]:
            raise ValueError('Access checks used different session directories')
    return support


def verify_calibration(path,manifest):
    """Replay exact study calibration and check parsability, never answer direction."""
    from .analyze import rating,status as field_status,FIELDS
    path=Path(path).resolve();frozen=load(path.parent/'freeze.json')
    cal_manifest,cal_digest=verify(ROOT/frozen['manifest'])
    if cal_manifest['purpose']!='calibration' or cal_manifest['run_id'].replace('-calibration','')!=manifest['run_id']:
        raise ValueError('Calibration belongs to a different study')
    if cal_manifest['profiles']!=manifest['profiles'] or path.parent!=result_dir(cal_manifest):
        raise ValueError('Calibration profile/path mismatch')
    if source_signature(frozen)!=source_signature(load(result_dir(manifest)/'freeze.json')):
        raise ValueError('Calibration used different source code')
    if {c['structure_sha256'] for c in cal_manifest['cases']}&{c['structure_sha256'] for c in manifest['cases']}:
        raise ValueError('Calibration cases overlap evaluation')
    ca=audit_batch(cal_manifest['trials'],PreProtocol(),[path.parent/'states'/(t['trial_id']+'.json') for t in cal_manifest['trials']],cal_digest)
    if not ca['integrity_ok'] or ca['complete']!=len(cal_manifest['trials']) or ca['assigned']<24:
        raise ValueError('Calibration did not complete with verified integrity')
    if Counter((t['arm'],t['kind']) for t in cal_manifest['trials'])!=Counter({(a,k):1 for a in ARMS for k in ('obj','seq','unforced')}):
        raise ValueError('Calibration must cover each arm and procedure exactly once')
    counts={arm:Counter() for arm in ARMS}
    for t in cal_manifest['trials']:
        counts.setdefault(t['arm'],Counter());c=counts[t['arm']]
        s=load(path.parent/'states'/(t['trial_id']+'.json'))
        for record in s['turns']:
            turn=record['turn'];parsed=record.get('parsed',{})
            if (turn<=30 and turn%3==0 and (t['arm']!='R' or turn==30)) or turn in (33,34):
                c['rating_total']+=1;c['rating_valid']+=rating(parsed)['joint'] is not None
            if turn==32:
                for k in range(1,5):
                    for field in FIELDS:
                        c['prediction_total']+=1;c['prediction_valid']+=field_status(parsed,f'policy_{k}.{field}') in ('valid','uncertain')
    quality={'counts':{k:dict(v) for k,v in counts.items()},'criteria':'Each arm >=90% interpretable joint ratings and >=90% interpretable/uncertain prediction components; no response-value criterion.',
             'passed':all(c['rating_total'] and c['prediction_total'] and c['rating_valid']/c['rating_total']>=.9 and c['prediction_valid']/c['prediction_total']>=.9 for c in counts.values())}
    atomic_json(path.parent/'quality_gate.json',quality)
    if not quality['passed']:raise ValueError('Calibration parser/format gate failed; inspect raw responses before evaluation')
    return quality


def run(args):
    manifest,_=verify(args.manifest);out=result_dir(manifest)
    with (out/'.launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run_locked(args)


def run_locked(args):
    manifest,digest=verify(args.manifest);out=result_dir(manifest)
    verify_support(args.support,manifest)
    if manifest['purpose']!='calibration':
        if not args.calibration_audit: raise ValueError('Calibration audit path is required for evaluation')
        verify_calibration(args.calibration_audit,manifest)
    if not 1 <= args.per_model_concurrency <= 40:
        raise ValueError('Per-model concurrency must be between 1 and 40')
    settings={'timeout_seconds':args.timeout,'concurrency':args.concurrency,
              'per_model_concurrency':args.per_model_concurrency,
              'concurrency_scope':'Live healthy launcher only; after abrupt termination inspect pending state and native processes before any separate run.',
              'wall_hours_per_launch':args.wall_hours,'max_new_sessions_per_launch':args.max_sessions,
              'automatic_retries':0,'choice_format_retries':0,'replace_failed_sessions':False,
              'support_sha256':sha(args.support),'calibration_audit_sha256':sha(args.calibration_audit) if args.calibration_audit else None}
    launch_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    atomic_json(out/'launches'/(launch_id+'.json'),{'at':timestamp(),**settings})
    budget=CallBudget(out/'budget.json',manifest['run_id'],manifest['call_cap'])
    protocol=PreProtocol();transport=NativeTransport(args.timeout)
    pending=[]
    for t in manifest['trials']:
        p=out/'states'/(t['trial_id']+'.json')
        if p.exists():
            existing=load(p)
            if existing.get('pending_turn') is not None:
                # The previous launcher may have died after sending the call.
                # Its native child can still be running even though the launch
                # lock was released. Never start other sessions silently.
                raise ValueError('Uncertain pending request in '+t['trial_id']+
                                 '; inspect raw files/native processes and resolve before launching; no request was replayed')
            if existing['status']=='active':pending.append(t)
        else:pending.append(t)
    if args.max_sessions is not None: pending=pending[:args.max_sessions]
    started=time.monotonic();deadline=started+args.wall_hours*3600
    total=0;stop=False
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        active={}
        active_by_model=Counter()
        def submit_next():
            if stop or time.monotonic()>=deadline: return False
            # Preserve pre-randomized ordering among eligible trials, but do
            # not let a saturated model block other models' available slots.
            index=next((i for i,t in enumerate(pending)
                        if active_by_model[t['model']] < args.per_model_concurrency),None)
            if index is None:return False
            t=pending.pop(index)
            f=pool.submit(run_trial,t,protocol,transport,out/'states'/(t['trial_id']+'.json'),out/'native-raw',budget,digest)
            active[f]=t;active_by_model[t['model']]+=1
            return True
        while len(active)<args.concurrency and submit_next():pass
        while active:
            done,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
            if not done:
                print(json.dumps({'type':'heartbeat','active_sessions':len(active),'active_by_model':dict(active_by_model),'finished_this_launch':total,'elapsed_seconds':round(time.monotonic()-started)}),flush=True)
                continue
            for f in done:
                t=active.pop(f)
                active_by_model[t['model']]-=1
                if not active_by_model[t['model']]:del active_by_model[t['model']]
                try: s=f.result()
                except Exception as exc:
                    print(json.dumps({'type':'launcher_exception','trial':t['trial_id'],'error':repr(exc)}),flush=True)
                    stop=True;continue
                total+=1
                print(json.dumps({'type':'session_finished','trial':t['trial_id'],'model':t['model'],'arm':t['arm'],'kind':t['kind'],
                                  'status':s['status'],'turns':len(s['turns']),'finished_this_launch':total}),flush=True)
                # A transport failure often indicates expired auth or provider capacity.
                # Pause scheduling new sessions; preserve concurrent results and all failures.
                if s['status'] in ('interrupted','budget_exhausted','failed'):
                    stop=True
            while len(active)<args.concurrency and submit_next():pass
    status(args.manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('freeze','verify','status','audit','preflight','run'))
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--support',type=Path)
    p.add_argument('--calibration-audit',type=Path)
    p.add_argument('--concurrency',type=int,default=8)
    p.add_argument('--per-model-concurrency',type=int,default=2)
    p.add_argument('--timeout',type=int,default=300)
    p.add_argument('--wall-hours',type=float,default=8)
    p.add_argument('--max-sessions',type=int)
    a=p.parse_args()
    if not 1<=a.concurrency<=40 or not 1<=a.per_model_concurrency<=40 or a.timeout<=0 or a.wall_hours<=0 or (a.max_sessions is not None and a.max_sessions<1):
        p.error('Invalid bounds')
    if a.command=='freeze':print(freeze(a.manifest))
    elif a.command=='verify':print(json.dumps({'valid':True,'freeze_sha256':verify(a.manifest)[1]}))
    elif a.command=='status':status(a.manifest)
    elif a.command=='audit':audit(a.manifest)
    elif a.command=='preflight':
        if not a.output:p.error('--output is required')
        if not preflight(a.manifest,a.output,a.timeout):raise SystemExit(2)
    else:
        if not a.support:p.error('--support is required')
        run(a)


if __name__=='__main__':main()
