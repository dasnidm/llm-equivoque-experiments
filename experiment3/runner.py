"""One native request per assigned task; durable checkpoint; no replay."""
import fcntl
import json
from pathlib import Path
import subprocess
import uuid

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque.runner import append_event, now
from equivoque.transport import CodexTransport
from equivoque2.runner import archive_native
from equivoque2.scheduler import Permit
from .protocol import CONFIG, FREEZE, PROMPTS, PilotProtocol, frozen_hashes


def run_task(trial, directory, scratch, transport=None):
    directory, scratch = Path(directory), Path(scratch)
    path = directory / 'trials' / (trial['trial_id'].replace('/', '__') + '.json')
    if path.exists():
        state = read_json(path)
        if state['trial'] != trial:
            raise ValueError('Existing task differs')
        if state['status'] == 'active':
            state.update(status='interrupted', ended_at=now(), error='Uncertain request; replay prohibited')
            write_json(path, state)
        return state
    protocol = PilotProtocol()
    transport = transport or CodexTransport(protocol, read_json(CONFIG)['turn_deadline_seconds'])
    state = {'trial': trial, 'status': 'active', 'started_at': now(), 'scratch_id': str(uuid.uuid4()),
             'protocol_sha256': digest(PROMPTS), 'transport': transport.name,
             'request': {'prompt': protocol.prompt(trial), 'schema': protocol.schema(frame=trial['frame']),
                         'session_id_before': None, 'requested_at': now()}, 'result': None}
    write_json(path, state)
    append_event(path.with_suffix('.journal.jsonl'), {'type': 'request_checkpoint', **state['request']})
    native = scratch / state['scratch_id']
    archive = directory / 'native-raw' / trial['trial_id'].replace('/', '__')
    try:
        result = transport.request(trial, state['request']['prompt'], state['request']['schema'], None, native, 1)
        result['received_at'] = now()
        if transport.name == 'codex-native':
            result['raw_files'] = archive_native(native, archive, directory)
        state['result'] = result
        append_event(path.with_suffix('.journal.jsonl'), {'type': 'response_checkpoint', **result})
        if not result['ok']:
            raise ValueError('Transport/session/tool-isolation failure')
        state['response'] = protocol.parse(result['text'], trial['frame'])
        state['correct'] = protocol.score(trial, state['response'])
        state['status'] = 'complete'
    except Exception as error:
        state.update(status='failed' if state['result'] is not None else 'interrupted', error=f'{type(error).__name__}: {error}')
        if state['result'] is None and native.exists():
            state['pending_raw_files'] = archive_native(native, archive, directory)
    state['ended_at'] = now()
    write_json(path, state)
    return state


def gate(manifest_path, ready_path, launch_path):
    frozen_hashes()
    config, manifest = read_json(CONFIG), read_json(manifest_path)
    ready, launch = read_json(ready_path), read_json(launch_path)
    expected = ROOT / 'manifests' / config['run_id'] / f"worker-{manifest['worker_id']}.json"
    if digest(manifest_path) != digest(expected) or manifest['run_id'] != config['run_id']:
        raise ValueError('Wrong assigned manifest')
    if not ready['ready'] or ready['manifest_sha256'] != digest(expected) or ready['worker_id'] != manifest['worker_id']:
        raise ValueError('Worker not ready')
    if (launch['run_id'] != config['run_id'] or launch['workers_ready'] != config['workers'] or
        launch['freeze_sha256'] != digest(FREEZE) or ready['freeze_sha256'] != digest(FREEZE) or
        launch['readiness_sha256'][manifest['worker_id']] != digest(ready_path) or
        launch['base_commit'] != ready['base_commit'] or launch['shared_service_sha256'] != ready['shared_service_sha256']):
        raise ValueError('No matching all-worker coordinator gate')
    subprocess.run(['git','merge-base','--is-ancestor',ready['base_commit'],'HEAD'],cwd=ROOT,check=True)
    return config, manifest, ready, launch


def worker(manifest_path, ready_path, launch_path, controls):
    config, manifest, ready, launch = gate(manifest_path, ready_path, launch_path)
    w = manifest['worker_id']
    directory = ROOT / 'results' / config['run_id'] / f'worker-{w}'
    lock = (directory / '.runner.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    write_json(directory / 'provenance.json', {'run_id': config['run_id'], 'worker_id': w,
               'base_commit': ready['base_commit'], 'freeze_sha256': digest(FREEZE),
               'manifest_sha256': digest(manifest_path), 'protocol_sha256': digest(PROMPTS),
               'schedule_sha256': manifest['schedule_sha256'], 'launch_sha256': digest(launch_path), 'started_at': now()})
    permit = Permit(controls, w, config['concurrency_stages'])
    try:
        for trial in manifest['trials']:
            if not permit.acquire(trial['trial_id']):
                return False
            try:
                state = run_task(trial, directory, ROOT / 'work/subject-sessions' / config['run_id'] / w)
                print(json.dumps({'worker': w, 'trial_id': trial['trial_id'], 'status': state['status'], 'at': now()}), flush=True)
                if state['status'] != 'complete' and (not state['result'] or not state['result']['ok']):
                    permit.halt({'worker': w, 'trial_id': trial['trial_id'], 'at': now(), 'reason': state.get('error')})
                    return False
            finally:
                permit.release()
    finally:
        permit.lock.close()
        lock.close()
    return True
