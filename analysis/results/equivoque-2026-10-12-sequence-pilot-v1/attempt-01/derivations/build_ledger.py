"""Preserve every physical calibration/evaluation attempt without double counting carried evidence."""
import argparse
import collections
import json
import sys
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True)
a=p.parse_args();root=Path(a.root);run='equivoque-2026-10-12-sequence-pilot-v1'
sys.path.insert(0,str(root))
from equivoque.core import digest, read_json, write_json
from experiment7.audit import audit_worker
paths=list((root/'experiment7/runtime').rglob('trials/*.json'))
paths+=list((root/'results'/run).glob('worker-*/preflight-*/check/trials/*.json'))
paths+=list((root/'results'/run).glob('worker-*/trials/*.json'))
rows=[];sessions=set();cal_sessions=set();eval_sessions=set();audits=[]
scratch=root/'work/ledger-audits';scratch.mkdir(parents=True,exist_ok=True)
for i,path in enumerate(sorted(set(paths))):
    s=read_json(path);t=s['trial'];evaluation=t['trial_id'].startswith(run+'/')
    # Some trial IDs use the pilot prefix differently; calibration is explicitly tagged.
    evaluation=not t['trial_id'].startswith('calibration/')
    sid=s.get('session_id')
    if sid:
        if sid in sessions:raise ValueError('Duplicate physical native session '+sid)
        sessions.add(sid);(eval_sessions if evaluation else cal_sessions).add(sid)
    if s['status']=='active':raise ValueError('Ledger cannot finalize an active native session')
    responses=s['turns'];calls=len(responses)+int(s.get('pending_turn') is not None)
    rows.append({'path':str(path.relative_to(root)),'state_sha256':digest(path),'trial_id':t['trial_id'],
                 'scope':'evaluation' if evaluation else 'excluded_calibration','configuration_id':t['configuration_id'],
                 'frame':t['frame'],'kind':t['kind'],'n_rounds':t['n_rounds'],'session_id':sid,'status':s['status'],
                 'attempted_invocations':calls,'returned_records':len(responses),
                 'successful_native_returns':sum(bool(r.get('ok')) for r in responses),
                 'parsed_returns':sum('parsed' in r for r in responses),
                 'valid_pre_disclosure_measurements':sum(r['local_turn']==3 and 'parsed' in r for r in responses),
                 'errors':[e.get('message',e.get('error',{}).get('message')) for r in responses for e in r.get('events',[]) if e.get('type') in ('error','turn.failed')],
                 'started_at':s['started_at'],'ended_at':s.get('ended_at'),'error':s.get('error')})
    if not evaluation:
        manifest=scratch/f'{i}.json';write_json(manifest,{'run_id':run,'worker_id':'technical-audit','trials':[t]})
        result=audit_worker(manifest,path.parent.parent)
        if not result['integrity_ok']:raise ValueError('Calibration raw audit failed '+str(result['errors']))
        audits.append({'state_path':str(path.relative_to(root)),'audit':result})
if cal_sessions & eval_sessions:raise ValueError('Calibration session contaminated evaluation')
scopes={}
for scope in ('excluded_calibration','evaluation'):
    group=[r for r in rows if r['scope']==scope]
    scopes[scope]={'physical_sessions':len(group),'attempted_invocations':sum(r['attempted_invocations'] for r in group),
                   'successful_native_returns':sum(r['successful_native_returns'] for r in group),
                   'valid_measurements':sum(r['valid_pre_disclosure_measurements'] for r in group),
                   'status_counts':dict(collections.Counter(r['status'] for r in group))}
write_json(a.output,{'run_id':run,'counting_unit':'runner invocation; excludes unobservable native HTTP retries',
                     'calibration_and_evaluation_sessions_disjoint':True,'all_attempts':rows,'scopes':scopes,
                     'calibration_raw_audits':audits,'carried_forward_readiness':'Counts physical state files once, not repeated references in composed readiness reports.',
                     'cost':'Not estimated; resume token counters are not billing measures.'})
print(json.dumps(scopes))
