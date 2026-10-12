"""Durable sequential sessions; pending native requests are never replayed."""
import fcntl
import json
from pathlib import Path
import subprocess
import uuid
from equivoque.core import ROOT, digest, operate, read_json, write_json
from equivoque.runner import now, append_event
from equivoque.transport import CodexTransport
from equivoque2.runner import archive_native
from equivoque2.scheduler import Permit
from .protocol import CONFIG, FREEZE, PROMPTS, SequenceProtocol, frozen_hashes, phase


def run_trial(trial, protocol, transport, state_path, scratch):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True,exist_ok=True)
    if state_path.exists():
        state = read_json(state_path)
        if state['trial'] != trial: raise ValueError('Existing trial differs from frozen assignment')
        if state['status'] in ('complete','failed','interrupted'): return state
        if state.get('pending_turn') is not None:
            state.update(status='interrupted',ended_at=now(),error='Uncertain pending turn; replay prohibited')
            write_json(state_path,state)
            return state
    else:
        state = {'trial':trial,'status':'active','started_at':now(),'session_id':None,
                 'turns':[],'pending_turn':None,'scratch_id':str(uuid.uuid4()),
                 'transport':transport.name,'protocol_sha256':digest(protocol.path),
                 'rounds':[{'round':i,'order':trial['order'],'target':target,
                            'remaining':list(trial['order']),'route':''}
                           for i,target in enumerate(trial['targets'],1)]}
        write_json(state_path,state)
    native = Path(scratch)/state['scratch_id']
    result_root = state_path.parent.parent
    archive = result_root/'native-raw'/trial['trial_id'].replace('/','__')
    for turn in range(len(state['turns'])+1,3*trial['n_rounds']+4):
        r, local = phase(trial,turn)
        current = state['rounds'][r-1]
        feedback = current['route'][-1] if current['route'] else None
        prompt = protocol.prompt(trial,turn,feedback,current['remaining'])
        schema = protocol.schema(turn,current['remaining'],trial['frame'],trial)
        request = {'turn':turn,'round':r,'local_turn':local,'prompt':prompt,'schema':schema,
                   'requested_at':now(),'session_id_before':state['session_id']}
        state['pending_turn'] = request
        write_json(state_path,state)
        append_event(state_path.with_suffix('.journal.jsonl'), {'type':'request_checkpoint',**request})
        try:
            result = transport.request(trial,prompt,schema,state['session_id'],native,turn)
        except Exception as error:
            state.update(status='interrupted',ended_at=now(),error=f'{type(error).__name__}: {error}')
            if native.exists(): state['pending_raw_files'] = archive_native(native,archive,result_root)
            write_json(state_path,state)
            return state
        record = {**request,**result,'received_at':now()}
        if transport.name == 'codex-native': record['raw_files'] = archive_native(native,archive,result_root)
        append_event(state_path.with_suffix('.journal.jsonl'), {'type':'response_checkpoint',**record})
        state['pending_turn'] = None
        state['session_id'] = result['session_id'] if result['ok'] else state['session_id'] or result.get('session_id')
        state['turns'].append(record)
        if not result['ok']:
            state.update(status='failed',ended_at=now(),error='Native transport/session/isolation failure')
            write_json(state_path,state)
            return state
        try:
            parsed = protocol.parse_response(result['text'],turn,current['remaining'],trial['frame'],trial)
            record['parsed'] = parsed
            if local in (1,2):
                selection = parsed['selection'] if local == 1 else [parsed['selection']]
                current['remaining'], operation = operate(current['remaining'],selection,current['target'])
                current['route'] += operation
        except (ValueError,TypeError) as error:
            state.update(status='failed',ended_at=now(),error=f'Response validation: {error}')
            write_json(state_path,state)
            return state
        write_json(state_path,state)
    state.update(status='complete',ended_at=now())
    write_json(state_path,state)
    return state


def check_gate(manifest_path,ready_path,launch_path):
    frozen_hashes()
    config, manifest = read_json(CONFIG),read_json(manifest_path)
    expected = ROOT/'manifests'/config['run_id']/f"worker-{manifest['worker_id']}.json"
    ready, launch = read_json(ready_path),read_json(launch_path)
    if digest(manifest_path)!=digest(expected) or manifest['run_id']!=config['run_id']:
        raise ValueError('Wrong manifest')
    if (not ready['ready'] or ready['worker_id']!=manifest['worker_id'] or
        ready['manifest_sha256']!=digest(expected) or ready['freeze_sha256']!=digest(FREEZE)):
        raise ValueError('Worker readiness mismatch')
    if (launch['run_id']!=config['run_id'] or launch['freeze_sha256']!=digest(FREEZE) or
        launch['workers_ready']!=config['workers'] or
        launch['readiness_sha256'][manifest['worker_id']]!=digest(ready_path) or
        launch['shared_service_sha256']!=ready['shared_service_sha256'] or
        launch['base_commit']!=ready['base_commit']):
        raise ValueError('All-worker coordinator release missing or mismatched')
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    subprocess.run(['git','merge-base','--is-ancestor',ready['base_commit'],revision],cwd=ROOT,check=True)
    return config, manifest, ready, revision


def run_worker(manifest_path,ready_path,launch_path,controls):
    config, manifest, ready, revision = check_gate(manifest_path,ready_path,launch_path)
    w = manifest['worker_id']
    out = ROOT/'results'/config['run_id']/f'worker-{w}'
    out.mkdir(parents=True,exist_ok=True)
    lock = (out/'.runner.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    provenance = {'run_id':config['run_id'],'worker_id':w,'base_commit':ready['base_commit'],
                  'execution_commit':revision,'freeze_sha256':digest(FREEZE),
                  'protocol_sha256':digest(PROMPTS),'manifest_sha256':digest(manifest_path),
                  'launch_sha256':digest(launch_path),'started_at':now()}
    if (out/'provenance.json').exists():
        old = read_json(out/'provenance.json')
        for key in ('run_id','worker_id','base_commit','freeze_sha256','protocol_sha256','manifest_sha256','launch_sha256'):
            if old[key]!=provenance[key]: raise ValueError('Resume provenance mismatch')
    else: write_json(out/'provenance.json',provenance)
    protocol = SequenceProtocol()
    transport = CodexTransport(protocol,config['turn_deadline_seconds'])
    permit = Permit(controls,w,config['concurrency_stages'])
    try:
        for trial in manifest['trials']:
            path = out/'trials'/(trial['trial_id'].replace('/','__')+'.json')
            if path.exists() and read_json(path)['status'] in ('complete','failed','interrupted'): continue
            if not permit.acquire(trial['trial_id']): return False
            try:
                state = run_trial(trial,protocol,transport,path,Path(config['subject_scratch_root']))
                print(json.dumps({'worker':w,'trial_id':trial['trial_id'],'status':state['status'],'at':now()}),flush=True)
                if state['status']!='complete' and (not state['turns'] or not state['turns'][-1].get('ok')):
                    permit.halt({'worker':w,'reason':state.get('error'),'at':now()})
                    return False
            finally: permit.release()
    finally:
        permit.lock.close()
        lock.close()
    return True
