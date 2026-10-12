"""Seven model checks, all 20 workers, four full-length excluded checks."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import uuid
from equivoque.core import ROOT,digest,read_json,write_json
from equivoque.runner import now
from equivoque.transport import CodexTransport
from equivoque.isolation import inspect_request
from .protocol import CONFIG,FREEZE,SequenceProtocol,frozen_hashes
from .runner import run_trial
from .schedule import development_trial


def execute_check(config,index,directory,configuration=None,n_rounds=1):
    protocol=SequenceProtocol()
    trial=development_trial(config,index,configuration,n_rounds)
    out=Path(directory)
    state=run_trial(trial,protocol,CodexTransport(protocol,config['turn_deadline_seconds']),
                    out/'trials'/(trial['trial_id'].replace('/','__')+'.json'),
                    Path(config['subject_scratch_root']))
    return {'trial_id':trial['trial_id'],'configuration_id':trial['configuration_id'],
            'frame':trial['frame'],'kind':trial['kind'],'rounds':n_rounds,
            'passed':state['status']=='complete','session_id':state.get('session_id'),
            'invocations':len(state['turns'])+int(state.get('pending_turn') is not None),
            'error':state.get('error')}


def shared(directory):
    frozen_hashes();config=read_json(CONFIG);p=SequenceProtocol();directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    report={'run_id':config['run_id'],'ready':False,'started_at':now(),'errors':[],
            'freeze_sha256':digest(FREEZE),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'checks':[],'long_checks':[],'inspections':[],'subject_invocations':0}
    try:
        version=subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=30)
        auth=subprocess.run(['codex','login','status'],capture_output=True,text=True,timeout=30)
        report.update(cli_version=version.stdout.strip(),auth_route=(auth.stdout+auth.stderr).strip())
        if report['cli_version']!=config['cli_version'] or auth.returncode or 'Logged in using ChatGPT' not in report['auth_route']:
            raise ValueError('Pinned CLI/ChatGPT auth unavailable')
        catalog=subprocess.run(['codex','debug','models'],capture_output=True,text=True,timeout=60)
        (directory/'catalog.json').write_text(catalog.stdout);(directory/'catalog.stderr.txt').write_text(catalog.stderr)
        if (catalog.returncode or 'fallback metadata' in catalog.stderr.lower() or
            'failed to refresh' in catalog.stderr.lower()):
            raise ValueError('Refreshed catalog unavailable; cached output does not establish access')
        data=json.loads(catalog.stdout);inventory={m['slug']:m for m in (data if isinstance(data,list) else data['models'])}
        for c in config['configurations']:
            if c['model'] not in inventory or c['effort'] not in [r['effort'] for r in inventory[c['model']].get('supported_reasoning_levels',[])]:
                raise ValueError('Unavailable requested setting: '+c['configuration_id'])
            inspection=inspect_request(p,c,directory/'offline-isolation'/c['configuration_id'],directory/'catalog.json')
            report['inspections'].append(inspection)
            if not inspection['passed']:raise ValueError('Native isolation failed: '+c['configuration_id'])
        report['catalog_sha256']=digest(directory/'catalog.json');write_json(directory/'readiness.json',report)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(execute_check,config,100+i,directory/'short'/c['configuration_id'],c,1) for i,c in enumerate(config['configurations'])]
            for future in concurrent.futures.as_completed(futures):
                check=future.result();report['checks'].append(check);report['subject_invocations']+=check['invocations']
                if not check['passed']:report['errors'].append('Live check failed: '+check['configuration_id'])
                write_json(directory/'readiness.json',report)
        if report['errors']:raise ValueError('Shared short checks failed; no long checks launched')
        # Four full sessions span frames and both schedules. Fixed development IDs,
        # independent of the evaluation sequence; no replacements or resampling.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            chosen=[(210,config['configurations'][3]),(211,config['configurations'][6]),
                    (212,config['configurations'][3]),(213,config['configurations'][6])]
            futures=[pool.submit(execute_check,config,i,directory/'long'/str(i),c,30) for i,c in chosen]
            for future in concurrent.futures.as_completed(futures):
                check=future.result();report['long_checks'].append(check);report['subject_invocations']+=check['invocations']
                if not check['passed']:report['errors'].append('Long continuity failed: '+check['trial_id'])
                write_json(directory/'readiness.json',report)
    except Exception as error:report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'] and len(report['checks'])==7 and len(report['long_checks'])==4,ended_at=now())
    write_json(directory/'readiness.json',report)
    return report


def worker(manifest_path,directory,shared_path):
    frozen_hashes();config=read_json(CONFIG);directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    manifest=read_json(manifest_path);service=read_json(shared_path);w=manifest['worker_id']
    report={'run_id':config['run_id'],'worker_id':w,'ready':False,'errors':[],'started_at':now(),
            'subject_invocations':0,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'freeze_sha256':digest(FREEZE),'manifest_sha256':digest(manifest_path),'shared_service_sha256':digest(shared_path)}
    try:
        expected=ROOT/'manifests'/config['run_id']/f'worker-{w}.json'
        if digest(expected)!=digest(manifest_path) or manifest['run_id']!=config['run_id']:raise ValueError('Wrong worker manifest')
        if not service['ready'] or service['freeze_sha256']!=digest(FREEZE) or service['base_commit']!=report['base_commit']:
            raise ValueError('Shared readiness source mismatch')
        catalog=Path(shared_path).parent/'catalog.json'
        if digest(catalog)!=service['catalog_sha256']:raise ValueError('Catalog changed')
        index=config['workers'].index(w);c=config['configurations'][index%7]
        report['inspection']=inspect_request(SequenceProtocol(),c,directory/'offline-isolation',catalog)
        if not report['inspection']['passed']:raise ValueError('Worker native tool/context inspection failed')
        check=execute_check(config,300+index,directory/'check',c,1)
        report.update(subject_invocations=check['invocations'],session_id=check['session_id'],check=check)
        if not check['passed']:raise ValueError('Worker native schema/session check failed')
    except Exception as error:report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'],ended_at=now());write_json(directory/'readiness.json',report)
    return report


def release(paths,shared_path,output):
    frozen_hashes();config=read_json(CONFIG);service=read_json(shared_path);reports=[read_json(p) for p in paths]
    if Path(output).exists():raise ValueError('Coordinator release already exists')
    if (not service['ready'] or len(reports)!=20 or {r['worker_id'] for r in reports}!=set(config['workers']) or
        any(not r['ready'] or r['base_commit']!=service['base_commit'] or r['freeze_sha256']!=digest(FREEZE) or
            r['shared_service_sha256']!=digest(shared_path) for r in reports)):
        raise ValueError('All workers must pass at the shared source revision')
    if service['freeze_sha256']!=digest(FREEZE):raise ValueError('Shared freeze mismatch')
    sessions=[r['session_id'] for r in reports]+[r['session_id'] for r in service['checks']+service['long_checks']]
    if not all(sessions) or len(set(sessions))!=len(sessions):raise ValueError('Calibration sessions missing or duplicated')
    for r in reports:
        if r['manifest_sha256']!=digest(ROOT/'manifests'/config['run_id']/f"worker-{r['worker_id']}.json"):
            raise ValueError('Manifest changed')
    record={'run_id':config['run_id'],'scope':'pilot_only','evaluation_sessions':28,'released_at':now(),
            'base_commit':service['base_commit'],'freeze_sha256':digest(FREEZE),'workers_ready':config['workers'],
            'shared_service_sha256':digest(shared_path),'readiness_sha256':{r['worker_id']:digest(p) for r,p in zip(reports,paths)},
            'calibration_sessions':len(sessions),'calibration_invocations':service['subject_invocations']+sum(r['subject_invocations'] for r in reports)}
    write_json(output,record);return record
