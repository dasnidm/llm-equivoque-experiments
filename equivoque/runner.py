"""Sequential four-turn trials, durable checkpoints, and fail-closed resume."""
from __future__ import annotations

import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import uuid

from .core import ROOT, Protocol, digest, frozen_hashes, operate
from .core import read_json, write_json
from .transport import CodexTransport


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def append_event(path, event):
    import os
    with Path(path).open('a') as handle:
        handle.write(json.dumps(event, sort_keys=True) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def run_trial(trial, protocol, transport, state_path, scratch):
    state_path = Path(state_path)
    if state_path.exists():
        state = read_json(state_path)
        if state['trial'] != trial:
            raise ValueError('Existing trial differs from manifest')
        if state['status'] in ('complete', 'failed', 'interrupted'):
            return state
        if state.get('pending_turn') is not None:
            state.update(status='interrupted',
                         error='Uncertain pending turn; automatic replay prohibited',
                         ended_at=now())
            write_json(state_path, state)
            return state
    else:
        state = {'trial': trial, 'status': 'active', 'started_at': now(),
                 'session_id': None, 'turns': [], 'route': '',
                 'remaining': trial['order'], 'pending_turn': None,
                 'scratch_id': str(uuid.uuid4()), 'transport': transport.name,
                 'protocol_sha256': digest(protocol.path)}
        write_json(state_path, state)
    for turn in range(len(state['turns']) + 1, 5):
        feedback = state['route'][-1] if state['route'] else None
        prompt = protocol.prompt(trial, turn, feedback, state['remaining'])
        schema = protocol.schema(turn, state['remaining'], trial['frame'])
        request = {'turn': turn, 'prompt': prompt, 'schema': schema,
                   'requested_at': now(), 'session_id_before': state['session_id']}
        state['pending_turn'] = request
        write_json(state_path, state)
        append_event(state_path.with_suffix('.journal.jsonl'),
                     {'type': 'request_checkpoint', **request})
        try:
            result = transport.request(trial, prompt, schema, state['session_id'],
                                       Path(scratch) / state['scratch_id'], turn)
        except Exception as error:
            state.update(status='interrupted', ended_at=now(),
                         error=f'{type(error).__name__}: {error}')
            write_json(state_path, state)
            return state
        record = {**request, **result, 'received_at': now()}
        append_event(state_path.with_suffix('.journal.jsonl'),
                     {'type': 'response_checkpoint', **record})
        state['pending_turn'] = None
        state['turns'].append(record)
        state['session_id'] = result['session_id']
        if not result['ok']:
            state.update(status='failed', error='Transport/session/tool-isolation failure',
                         ended_at=now())
            write_json(state_path, state)
            return state
        try:
            parsed = protocol.parse_response(result['text'], turn,
                                             state['remaining'], trial['frame'])
            record['parsed'] = parsed
            if turn < 3:
                selected = parsed['selection']
                selection = selected if turn == 1 else [selected]
                state['remaining'], operation = operate(
                    state['remaining'], selection, trial['target'])
                state['route'] += operation
        except (ValueError, TypeError) as error:
            state.update(status='failed', error=f'Response validation: {error}',
                         ended_at=now())
            write_json(state_path, state)
            return state
        write_json(state_path, state)
    state.update(status='complete', ended_at=now())
    write_json(state_path, state)
    return state


def run_worker(manifest_path, result_directory, readiness_path, launch_path):
    freeze = frozen_hashes()
    manifest = read_json(manifest_path)
    config = read_json(ROOT / 'protocol/run.v1.json')
    readiness = read_json(readiness_path)
    launch = read_json(launch_path)
    expected_manifest = ROOT / 'manifests' / config['run_id'] / (
        'worker-' + manifest['worker_id'] + '.json')
    if digest(manifest_path) != digest(expected_manifest):
        raise ValueError('Wrong manifest')
    if (not readiness.get('ready') or readiness['worker_id'] != manifest['worker_id']
            or readiness['manifest_sha256'] != digest(manifest_path)
            or readiness['freeze_sha256'] != digest(ROOT / 'protocol/freeze.json')):
        raise ValueError('Missing or mismatched worker readiness')
    if (launch.get('run_id') != config['run_id'] or
            launch.get('freeze_sha256') != digest(ROOT / 'protocol/freeze.json') or
            set(launch.get('workers_ready', [])) != set('abcdefg')):
        raise ValueError('No coordinator release for all seven workers')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                       cwd=ROOT, text=True).strip()
    if readiness['base_commit'] != launch['base_commit']:
        raise ValueError('Readiness and launch use different source commits')
    if subprocess.run(['git', 'merge-base', '--is-ancestor',
                       readiness['base_commit'], revision], cwd=ROOT).returncode:
        raise ValueError('Execution revision is not descended from the approved source')
    expected_directory = ROOT / 'results' / config['run_id'] / (
        'worker-' + manifest['worker_id'])
    directory = Path(result_directory).resolve()
    if directory != expected_directory.resolve():
        raise ValueError('Output must be the assigned result directory')
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / '.runner.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise ValueError('Another runner already holds this worker shard') from error
    protocol = Protocol()
    transport = CodexTransport(protocol, config['turn_deadline_seconds'])
    provenance = {
        'run_id': config['run_id'], 'worker_id': manifest['worker_id'],
        'base_commit': readiness['base_commit'],
        'freeze_sha256': digest(ROOT / 'protocol/freeze.json'),
        'manifest_sha256': digest(manifest_path),
        'protocol_sha256': digest(protocol.path),
        'schedule_sha256': manifest['schedule_sha256']}
    provenance_path = directory / 'provenance.json'
    if provenance_path.exists():
        previous = read_json(provenance_path)
        if any(previous.get(key) != value for key, value in provenance.items()):
            raise ValueError('Existing worker provenance differs from this run')
        provenance = previous
        provenance.setdefault('resumed_at', []).append(now())
    else:
        provenance['started_at'] = now()
    provenance['execution_commit'] = revision
    write_json(provenance_path, provenance)
    try:
        for trial in manifest['trials']:
            slug = trial['trial_id'].replace('/', '__')
            state = run_trial(trial, protocol, transport,
                              directory / 'trials' / (slug + '.json'),
                              ROOT / 'work' / config['run_id'] / manifest['worker_id'])
            print(json.dumps({'trial_id': trial['trial_id'], 'status': state['status']}),
                  flush=True)
            # Systemic access/tool failures stop the shard rather than exhausting
            # all 300 trials under a broken environment.
            if state['status'] != 'complete' and (
                    not state['turns'] or not state['turns'][-1].get('ok')):
                break
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return freeze
