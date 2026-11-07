"""Read-only integrity checks for original persistent app-server RPC evidence."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from equivoque.transport import overrides, provider_schema
from exp7_pre.audit import audit_trial as scientific_audit_trial
from .transport import normalize_turn, PersistentTransport, validate_startup


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path):
    values = [json.loads(line) for line in Path(path).read_text().splitlines()]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError('RPC/event rows must be objects')
    return values


def audit_turn(record, *, expected_prompt, expected_system, expected_schema,
               previous_session_id=None, expected_pid=None, expected_trial=None):
    """Check one retained response; never invoke the CLI or submit a request."""
    errors = []
    required = {'subject-system.txt', 'prompt.txt', 'rpc-sent.jsonl',
                'rpc-received.jsonl', 'stderr.txt', 'events.jsonl', 'adapter.json'}
    files = record.get('raw_files', [])
    named = {}
    for entry in files:
        try:
            path = Path(entry['path'])
            if path.name in named:
                errors.append('Duplicate raw artifact name: ' + path.name)
            named[path.name] = path
            if not path.is_file() or _digest(path) != entry['sha256']:
                errors.append('Raw file hash mismatch: ' + path.name)
        except (KeyError, TypeError, OSError):
            errors.append('Malformed or unreadable raw artifact')
    if not required <= named.keys():
        errors.append('Missing required raw artifacts: ' + ', '.join(sorted(required - named.keys())))
    if errors:
        return {'integrity_ok': False, 'errors': errors}
    try:
        if record.get('prompt') != expected_prompt or named['prompt.txt'].read_text() != expected_prompt:
            errors.append('Prompt mismatch')
        if named['subject-system.txt'].read_text() != expected_system:
            errors.append('System instruction mismatch')
        effective = provider_schema(expected_schema) if expected_schema is not None else None
        if record.get('schema') != expected_schema or record.get('provider_schema') != effective:
            errors.append('Recorded schema mismatch')
        if effective is None:
            if 'schema.json' in named:
                errors.append('Unexpected provider schema artifact')
        elif 'schema.json' not in named or json.loads(named['schema.json'].read_text()) != effective:
            errors.append('Provider schema artifact mismatch')
        adapter = json.loads(named['adapter.json'].read_text())
        sent, received, events = (_jsonl(named[key]) for key in
                                   ('rpc-sent.jsonl', 'rpc-received.jsonl', 'events.jsonl'))
        thread_id, turn_id = record.get('session_id'), record.get('app_server_turn_id')
        pid = record.get('process_pid')
        if not isinstance(thread_id, str) or not thread_id or not isinstance(turn_id, str) or not turn_id:
            errors.append('Missing provider thread or turn ID')
        if type(pid) is not int or pid <= 0 or (expected_pid is not None and pid != expected_pid):
            errors.append('Process PID mismatch')
        if previous_session_id is not None and thread_id != previous_session_id:
            errors.append('Conversation thread changed')
        if record.get('session_id_before') != previous_session_id:
            errors.append('Previous session ID mismatch')
        for key, expected in {'transport': PersistentTransport.name, 'process_pid': pid,
                              'thread_id': thread_id, 'turn_id': turn_id,
                              'command': record.get('command'), 'events_are_derived': True}.items():
            if adapter.get(key) != expected:
                errors.append('Adapter metadata mismatch: ' + key)
        command = record.get('command', [])
        if len(command) < 3 or command[1:3] != ['app-server', '--stdio']:
            errors.append('Invalid persistent CLI command')
        if expected_trial and len(command) >= 3:
            fixed = [command[0], 'app-server', '--stdio'] + overrides(
                named['subject-system.txt'], expected_trial['effort'])
            tail = command[len(fixed):]
            if command[:len(fixed)] != fixed:
                errors.append('Frozen CLI configuration mismatch')
            catalog_hash = adapter.get('catalog_sha256')
            if catalog_hash is None:
                if tail or 'model-catalog.json' in named:
                    errors.append('Unexpected extra CLI configuration')
            elif (len(tail) != 2 or tail[0] != '-c'
                  or not tail[1].startswith('model_catalog_json=')):
                errors.append('Frozen model catalog command mismatch')
            else:
                snapshot = named.get('model-catalog.json')
                catalog_path = json.loads(tail[1].split('=', 1)[1])
                if snapshot is None or _digest(snapshot) != catalog_hash:
                    errors.append('Frozen model catalog snapshot hash mismatch')
                elif (snapshot.parent != named['subject-system.txt'].parent
                      or str(snapshot) != catalog_path):
                    errors.append('Frozen model catalog snapshot path mismatch')
        starts = [m for m in sent if m.get('method') == 'turn/start']
        if len(starts) != 1:
            errors.append('Expected exactly one turn/start submission; replay or omission')
            return {'integrity_ok': False, 'errors': errors}
        start = starts[0]
        params = start.get('params', {})
        expected_input = [{'type': 'text', 'text': expected_prompt, 'text_elements': []}]
        if params.get('input') != expected_input:
            errors.append('Original RPC prompt mismatch')
        if params.get('outputSchema') != effective or 'outputSchema' not in params:
            errors.append('Original RPC schema mismatch')
        if params.get('threadId') != thread_id:
            errors.append('Original RPC thread mismatch')
        if params.get('approvalPolicy') != 'never' or params.get('turnTrigger') != 'exec':
            errors.append('Original RPC turn policy mismatch')
        if expected_trial and params.get('effort') != expected_trial['effort']:
            errors.append('Original RPC effort mismatch')
        ids = [m['id'] for m in sent if 'id' in m]
        if len(ids) != len(set(ids)):
            errors.append('Duplicate outbound RPC request ID')
        for request_id in ids:
            matches = [m for m in received if m.get('id') == request_id]
            if len(matches) != 1 or 'result' not in matches[0] or 'error' in matches[0]:
                errors.append('Missing or duplicate successful RPC acknowledgement')
        if any('id' in m and (m['id'] not in ids or 'method' in m) for m in received):
            errors.append('Unexpected RPC response or server request')
        acks = [m for m in received if m.get('id') == start.get('id')]
        if len(acks) != 1 or acks[0].get('result', {}).get('turn', {}).get('id') != turn_id:
            errors.append('RPC turn acknowledgement mismatch')
        first = previous_session_id is None
        expected_methods = ['initialize', 'initialized', 'thread/start', 'turn/start'] if first else ['turn/start']
        if [m.get('method') for m in sent] != expected_methods:
            errors.append('Unexpected RPC submission sequence or process restart')
        boundary = 0
        if first:
            threads = [m for m in sent if m.get('method') == 'thread/start']
            if len(threads) != 1:
                errors.append('Missing or duplicate fresh-thread submission')
            else:
                thread_start = threads[0]
                tp = thread_start.get('params', {})
                thread_acks = [(i, m) for i, m in enumerate(received) if m.get('id') == thread_start.get('id')]
                if len(thread_acks) == 1:
                    boundary = thread_acks[0][0] + 1
                    response = thread_acks[0][1].get('result', {})
                    if response.get('thread', {}).get('id') != thread_id:
                        errors.append('Fresh-thread acknowledgement mismatch')
                    if (response.get('cwd') != tp.get('cwd') or response.get('approvalPolicy') != 'never'
                            or response.get('sandbox', {}).get('type') != 'readOnly' or response.get('instructionSources')):
                        errors.append('Effective thread isolation mismatch')
                    if expected_trial and (response.get('model') != expected_trial['model'] or response.get('reasoningEffort') != expected_trial['effort']):
                        errors.append('Effective model or effort mismatch')
                if (tp.get('approvalPolicy') != 'never' or tp.get('sandbox') != 'read-only'
                        or tp.get('ephemeral') is not False or tp.get('allowProviderModelFallback') is not False
                        or tp.get('dynamicTools') != [] or tp.get('historyMode') != 'paginated'):
                    errors.append('Fresh-thread policy mismatch')
                if params.get('cwd') != tp.get('cwd'):
                    errors.append('Turn and thread working directories differ')
                if expected_trial:
                    wanted_config = {k: json.loads(v) for k, v in
                        (entry.split('=', 1) for entry in overrides(named['subject-system.txt'], expected_trial['effort'])[1::2])}
                    if tp.get('config') != wanted_config or tp.get('model') != expected_trial['model']:
                        errors.append('Frozen thread configuration mismatch')
        if type(adapter.get('normalization_start_index')) is not int or adapter['normalization_start_index'] != boundary:
            errors.append('Normalization boundary mismatch')
        if first:
            validate_startup(received[:boundary], thread_id)
        normalized = normalize_turn(received[boundary:], thread_id, turn_id)
        stderr = named['stderr.txt'].read_text()
        fallback = 'fallback metadata' in stderr.lower()
        if fallback:
            normalized['ok'] = False
            normalized['protocol_violations'].append('Fallback model metadata')
        if events != normalized['events']:
            errors.append('Derived events differ from original RPC')
        if 'event_count' in record and record['event_count'] != len(events):
            errors.append('Event count mismatch')
        for key, value in normalized.items():
            if key != 'events' and record.get(key) != value:
                errors.append('Normalized result mismatch: ' + key)
        if record.get('metadata_fallback') != fallback:
            errors.append('Metadata fallback classification mismatch')
        terminals = [m.get('params', {}) for m in received[boundary:] if m.get('method') == 'turn/completed']
        if len(terminals) != 1 or terminals[0].get('threadId') != thread_id or terminals[0].get('turn', {}).get('id') != turn_id:
            errors.append('Terminal thread/turn identity mismatch')
        if record.get('ok') and (record.get('exit_code') != 0 or record.get('timeout') is not False
                                or record.get('malformed_event_lines') != 0):
            errors.append('Successful record has process/parse failure')
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        errors.append('Malformed persistent evidence: ' + type(exc).__name__)
    return {'integrity_ok': not errors, 'errors': errors}


def audit_trial(expected_trial, protocol, state_path, expected_freeze_sha256):
    """Replay scientific state, then audit every retained original RPC exchange."""
    report = scientific_audit_trial(expected_trial, protocol, state_path, expected_freeze_sha256)
    path = Path(state_path)
    if not path.exists():
        return report
    state = json.loads(path.read_text())
    errors = report['errors']
    if state.get('transport') != PersistentTransport.name:
        errors.append('Wrong transport for persistent audit')
    previous, pid, turn_ids = None, None, set()
    for index, record in enumerate(state.get('turns', []), 1):
        result = audit_turn(record, expected_prompt=record.get('prompt'),
                            expected_system=protocol.system(expected_trial), expected_schema=record.get('schema'),
                            previous_session_id=previous, expected_pid=pid, expected_trial=expected_trial)
        errors.extend(f'Turn {index}: {error}' for error in result['errors'])
        turn_id = record.get('app_server_turn_id')
        if turn_id in turn_ids:
            errors.append(f'Turn {index}: provider turn ID reused')
        turn_ids.add(turn_id)
        previous, pid = record.get('session_id'), record.get('process_pid')
    report['integrity_ok'] = not errors
    return report


def audit_batch(assignments, protocol, state_paths, expected_freeze_sha256):
    if len(assignments) != len(state_paths):
        raise ValueError('Assignment and state path counts differ')
    rows = [audit_trial(t, protocol, p, expected_freeze_sha256) for t, p in zip(assignments, state_paths)]
    sessions = [r['session_id'] for r in rows if r['session_id']]
    tickets = [ticket for r in rows for ticket in r['tickets']]
    errors = []
    if len(set(sessions)) != len(sessions):
        errors.append('Session ID reused across trials')
    if len(set(tickets)) != len(tickets):
        errors.append('Call-budget ticket reused')
    return {'assigned': len(rows), 'statuses': dict(Counter(r['status'] for r in rows)),
            'integrity_ok': not errors and all(r['integrity_ok'] for r in rows),
            'complete': sum(r['status'] == 'complete' for r in rows), 'errors': errors, 'trials': rows}
