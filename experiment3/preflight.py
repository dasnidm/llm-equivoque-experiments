"""Shared model access and all 20 single-turn worker readiness checks."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import uuid

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque.runner import now
from equivoque.transport import CodexTransport
from equivoque.isolation import inspect_request
from equivoque2.runner import archive_native
from .protocol import CONFIG, FREEZE, PilotProtocol, frozen_hashes
from .runner import run_task


def shared(directory):
    frozen_hashes()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    config, protocol = read_json(CONFIG), PilotProtocol()
    report = {'run_id': config['run_id'], 'ready': False, 'errors': [], 'started_at': now(),
              'freeze_sha256': digest(FREEZE), 'base_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'subject_invocations': 0, 'checks': [], 'inspections': []}
    try:
        version = subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=30)
        auth = subprocess.run(['codex','login','status'],capture_output=True,text=True,timeout=30)
        report['cli_version'] = version.stdout.strip()
        report['auth_route'] = (auth.stdout + auth.stderr).strip()
        if report['cli_version'] != config['cli_version'] or auth.returncode or 'Logged in using ChatGPT' not in report['auth_route']:
            raise ValueError('Pinned CLI or ChatGPT login unavailable')
        catalog = subprocess.run(['codex','debug','models'],capture_output=True,text=True,timeout=60)
        (directory/'catalog.json').write_text(catalog.stdout)
        (directory/'catalog.stderr.txt').write_text(catalog.stderr)
        if catalog.returncode or 'fallback metadata' in catalog.stderr.lower():
            raise ValueError('Refreshed catalog unavailable')
        data = json.loads(catalog.stdout)
        inventory = {m['slug']:m for m in (data if isinstance(data,list) else data['models'])}
        for c in config['configurations']:
            if c['model'] not in inventory or c['effort'] not in [r['effort'] for r in inventory[c['model']].get('supported_reasoning_levels',[])]:
                raise ValueError('Unavailable configuration: '+c['configuration_id'])
        report['catalog_sha256'] = digest(directory/'catalog.json')
        for c in config['configurations']:
            result = inspect_request(protocol,c,directory/'offline-isolation'/c['configuration_id'],directory/'catalog.json')
            report['inspections'].append(result)
            if not result['passed']:
                raise ValueError('Offline isolation failed: '+c['configuration_id'])
        write_json(directory/'readiness.json', report)
        development = read_json(ROOT/'experiment3/protocol/development-cases.json')['cases']
        def check(c):
            trial={**c,'frame':'cards','procedure':'keep_selected','claim':'conflicting','case':development[0],
                   'trial_id':'calibration/shared/'+c['configuration_id']}
            out = directory/'checks'/c['configuration_id']
            state=run_task(trial,out,ROOT/'work/service-preflight'/config['run_id']/str(uuid.uuid4()))
            return {'configuration_id':c['configuration_id'],'passed':state['status']=='complete',
                    'session_id':state.get('result',{}).get('session_id')}
        # Bounded live calibration: every combination, one new session each.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for r in pool.map(check,config['configurations']):
                report['subject_invocations'] += 1
                report['checks'].append(r)
                if not r['passed']:
                    report['errors'].append('Live/schema check failed: '+r['configuration_id'])
                write_json(directory/'readiness.json',report)
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'] and len(report['checks'])==21, ended_at=now())
    write_json(directory/'readiness.json',report)
    return report


def worker(manifest_path, directory, shared_path):
    frozen_hashes()
    config, protocol, service = read_json(CONFIG), PilotProtocol(), read_json(shared_path)
    manifest, directory = read_json(manifest_path), Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    report = {'run_id':config['run_id'],'worker_id':manifest['worker_id'],'ready':False,'errors':[],
              'started_at':now(),'subject_invocations':0,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'freeze_sha256':digest(FREEZE),'manifest_sha256':digest(manifest_path),'shared_service_sha256':digest(shared_path)}
    try:
        expected=ROOT/'manifests'/config['run_id']/f"worker-{manifest['worker_id']}.json"
        if digest(expected)!=digest(manifest_path) or manifest['run_id']!=config['run_id']:
            raise ValueError('Wrong manifest')
        if not service['ready'] or service['freeze_sha256']!=digest(FREEZE) or service['base_commit']!=report['base_commit']:
            raise ValueError('Shared readiness source mismatch')
        catalog=Path(shared_path).parent/'catalog.json'
        if digest(catalog)!=service['catalog_sha256']:
            raise ValueError('Catalog hash mismatch')
        i=config['workers'].index(manifest['worker_id'])
        c=config['configurations'][i]
        inspection=inspect_request(protocol,c,directory/'offline-isolation',catalog)
        report['inspection']=inspection
        if not inspection['passed']:
            raise ValueError('Worker native request isolation failed')
        dev=read_json(ROOT/'experiment3/protocol/development-cases.json')['cases'][1+i%7]
        trial={**c,'frame':'cards' if i%2 else 'cats','procedure':'fixed_target' if i%2 else 'keep_selected',
               'claim':('neutral','congruent','conflicting')[i%3],'case':dev,
               'trial_id':'calibration/worker/'+manifest['worker_id']}
        report['subject_invocations']=1
        write_json(directory/'readiness.json',report)
        state=run_task(trial,directory,ROOT/'work/worker-preflight'/config['run_id']/manifest['worker_id'])
        report['session_id']=state.get('result',{}).get('session_id')
        if state['status']!='complete':
            raise ValueError('Single-turn worker schema/session check failed')
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'] and report['subject_invocations']==1,ended_at=now())
    write_json(directory/'readiness.json',report)
    return report


def release(paths, shared_path, output):
    frozen_hashes()
    config, service=read_json(CONFIG),read_json(shared_path)
    reports=[read_json(p) for p in paths]
    if Path(output).exists():
        raise ValueError('Launch record already exists')
    if (not service['ready'] or len(reports)!=20 or {r['worker_id'] for r in reports}!=set(config['workers']) or
        service['freeze_sha256']!=digest(FREEZE) or any(not r['ready'] or r['freeze_sha256']!=digest(FREEZE) or
        r['base_commit']!=service['base_commit'] or r['shared_service_sha256']!=digest(shared_path) for r in reports)):
        raise ValueError('All 20 workers and shared model access must pass at one source')
    sessions=[r['session_id'] for r in reports]+[r['session_id'] for r in service['checks']]
    if len(sessions)!=len(set(sessions)) or not all(sessions):
        raise ValueError('Calibration sessions not unique')
    for r in reports:
        if r['manifest_sha256']!=digest(ROOT/'manifests'/config['run_id']/f"worker-{r['worker_id']}.json"):
            raise ValueError('Manifest changed')
    record={'run_id':config['run_id'],'scope':'pilot_only','released_at':now(),'base_commit':service['base_commit'],
            'freeze_sha256':digest(FREEZE),'workers_ready':config['workers'],'evaluation_tasks':2016,
            'shared_service_sha256':digest(shared_path),'readiness_sha256':{r['worker_id']:digest(p) for r,p in zip(reports,paths)},
            'non_evaluation_invocations':service['subject_invocations']+sum(r['subject_invocations'] for r in reports)}
    write_json(output,record)
    return record
