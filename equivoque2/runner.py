"""Ten sequential native turns, exact raw archives, and no uncertain replay."""
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from equivoque.core import ROOT, digest, operate, read_json, write_json
from equivoque.runner import append_event, now
from equivoque.transport import CodexTransport
from .protocol import CONFIG, FREEZE, RepeatedProtocol, frozen_hashes, phase


def archive_native(scratch, destination, result_root):
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for source in sorted(Path(scratch).glob('*')):
        if not source.is_file():
            continue
        if source.name != 'subject-system.txt' and not (
                source.name.startswith('turn-') and source.name.endswith(
                    ('.schema.json', '.events.jsonl', '.stderr.txt'))):
            raise ValueError('Unexpected native scratch file: ' + source.name)
        target = destination / source.name
        if target.exists():
            if digest(target) != digest(source):
                raise ValueError('Native file would be overwritten: ' + source.name)
        else:
            shutil.copyfile(source, target)
        files.append({'path': str(target.relative_to(result_root)), 'sha256': digest(target)})
    write_json(destination / 'files.json', {'files': files})
    return files


def run_trial(trial, protocol, transport, state_path, scratch):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        state = read_json(state_path)
        if state['trial'] != trial:
            raise ValueError('Existing trial differs from frozen manifest')
        if state['status'] in ('complete', 'failed', 'interrupted'):
            return state
        if state.get('pending_turn') is not None:
            state.update(status='interrupted', ended_at=now(),
                         error='Uncertain pending turn; automatic replay prohibited')
            write_json(state_path, state)
            return state
    else:
        state = {'trial': trial, 'status': 'active', 'started_at': now(),
                 'session_id': None, 'turns': [], 'pending_turn': None,
                 'scratch_id': str(uuid.uuid4()), 'transport': transport.name,
                 'protocol_sha256': digest(protocol.path),
                 'rounds': [{'round': i, 'order': order, 'remaining': list(order), 'route': ''}
                            for i, order in enumerate(trial['round_orders'], 1)]}
        write_json(state_path, state)
    native = Path(scratch) / state['scratch_id']
    result_root = state_path.parent if state_path.name == 'native-session-check.json' else state_path.parent.parent
    archive = result_root / 'native-raw' / trial['trial_id'].replace('/', '__')
    for turn in range(len(state['turns']) + 1, 11):
        round_number, local_turn = phase(turn)
        current = state['rounds'][round_number - 1]
        feedback = current['route'][-1] if current['route'] else None
        prompt = protocol.prompt(trial, turn, feedback, current['remaining'])
        schema = protocol.schema(turn, current['remaining'], trial['frame'])
        request = {'turn': turn, 'round': round_number, 'local_turn': local_turn,
                   'prompt': prompt, 'schema': schema, 'requested_at': now(),
                   'session_id_before': state['session_id']}
        state['pending_turn'] = request
        write_json(state_path, state)
        append_event(state_path.with_suffix('.journal.jsonl'), {'type': 'request_checkpoint', **request})
        try:
            result = transport.request(trial, prompt, schema, state['session_id'], native, turn)
        except Exception as error:
            state.update(status='interrupted', ended_at=now(), error=f'{type(error).__name__}: {error}')
            if native.exists():
                state['pending_raw_files'] = archive_native(native, archive, result_root)
            write_json(state_path, state)
            return state
        record = {**request, **result, 'received_at': now()}
        if transport.name == 'codex-native':
            record['raw_files'] = archive_native(native, archive, result_root)
        append_event(state_path.with_suffix('.journal.jsonl'), {'type': 'response_checkpoint', **record})
        state['pending_turn'] = None
        state['turns'].append(record)
        state['session_id'] = result['session_id']
        if not result['ok']:
            state.update(status='failed', error='Transport/session/tool-isolation failure', ended_at=now())
            write_json(state_path, state)
            return state
        try:
            parsed = protocol.parse_response(result['text'], turn, current['remaining'], trial['frame'])
            record['parsed'] = parsed
            if local_turn in (1, 2):
                selection = parsed['selection']
                current['remaining'], operation = operate(current['remaining'],
                    selection if local_turn == 1 else [selection], trial['target'])
                current['route'] += operation
        except (ValueError, TypeError) as error:
            state.update(status='failed', error=f'Response validation: {error}', ended_at=now())
            write_json(state_path, state)
            return state
        write_json(state_path, state)
    state.update(status='complete', ended_at=now())
    write_json(state_path, state)
    return state


def check_gate(manifest_path, readiness_path, launch_path):
    frozen_hashes()
    config = read_json(CONFIG)
    manifest = read_json(manifest_path)
    expected = ROOT / 'manifests' / config['run_id'] / f"worker-{manifest['worker_id']}.json"
    ready, launch = read_json(readiness_path), read_json(launch_path)
    if manifest['run_id'] != config['run_id'] or digest(manifest_path) != digest(expected):
        raise ValueError('Wrong experiment 2 manifest')
    if (not ready.get('ready') or ready['worker_id'] != manifest['worker_id'] or
            ready['manifest_sha256'] != digest(expected) or ready['freeze_sha256'] != digest(FREEZE)):
        raise ValueError('Worker readiness missing or mismatched')
    if (launch['run_id'] != config['run_id'] or launch['freeze_sha256'] != digest(FREEZE) or
            launch['workers_ready'] != config['workers'] or
            launch['readiness_sha256'][manifest['worker_id']] != digest(readiness_path) or
            launch['shared_service_sha256'] != ready['shared_service_sha256'] or
            launch['base_commit'] != ready['base_commit']):
        raise ValueError('No matching coordinator release for all 20 workers')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    subprocess.run(['git', 'merge-base', '--is-ancestor', ready['base_commit'], revision], cwd=ROOT, check=True)
    return config, manifest, ready, launch, revision


def run_worker(manifest_path, readiness_path, launch_path, controls):
    from .scheduler import Permit
    config, manifest, ready, launch, revision = check_gate(manifest_path, readiness_path, launch_path)
    worker = manifest['worker_id']
    directory = ROOT / 'results' / config['run_id'] / f'worker-{worker}'
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / '.runner.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provenance = {'run_id': config['run_id'], 'worker_id': worker,
        'base_commit': ready['base_commit'], 'execution_commit': revision,
        'freeze_sha256': digest(FREEZE), 'manifest_sha256': digest(manifest_path),
        'protocol_sha256': digest(ROOT / 'experiment2/protocol/prompts.json'),
        'schedule_sha256': manifest['schedule_sha256'], 'launch_sha256': digest(launch_path)}
    p = directory / 'provenance.json'
    if p.exists():
        old = read_json(p)
        if any(old.get(key) != value for key, value in provenance.items() if key != 'execution_commit'):
            raise ValueError('Worker provenance differs on resume')
        provenance = {**old, 'execution_commit': revision, 'resumed_at': old.get('resumed_at', []) + [now()]}
    else:
        provenance['started_at'] = now()
    write_json(p, provenance)
    protocol = RepeatedProtocol()
    transport = CodexTransport(protocol, config['turn_deadline_seconds'])
    permit = Permit(controls, worker, config['concurrency_stages'])
    try:
        for trial in manifest['trials']:
            path = directory / 'trials' / (trial['trial_id'].replace('/', '__') + '.json')
            if path.exists() and read_json(path)['status'] in ('complete', 'failed', 'interrupted'):
                continue
            if not permit.acquire(trial['trial_id']):
                return False
            try:
                state = run_trial(trial, protocol, transport, path, ROOT / 'work/subject-sessions' / config['run_id'] / worker)
                print(json.dumps({'worker': worker, 'trial_id': trial['trial_id'],
                                  'status': state['status'], 'at': now()}), flush=True)
                if state['status'] != 'complete' and (not state['turns'] or not state['turns'][-1].get('ok')):
                    write_json(Path(controls) / 'HALT.json', {'worker': worker,
                        'trial_id': trial['trial_id'], 'at': now(), 'reason': state.get('error')})
                    return False
            finally:
                permit.release()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return True
