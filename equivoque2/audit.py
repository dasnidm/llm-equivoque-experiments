"""Reconstruct all three rounds and check journals and exact native files."""
import collections
import json
from pathlib import Path

from equivoque.core import digest, operate, read_json, write_json
from equivoque.transport import provider_schema
from .protocol import RepeatedProtocol, phase


def audit_worker(manifest_path, directory, allow_simulation=False):
    manifest, directory = read_json(manifest_path), Path(directory)
    expected = {t['trial_id']: t for t in manifest['trials']}
    protocol = RepeatedProtocol()
    counts, valid = collections.Counter(), collections.Counter()
    errors, sessions, seen, raw_verified = [], {}, set(), set()
    invocation_count = 0
    routes = collections.Counter()
    for path in sorted((directory / 'trials').glob('*.json')):
        state = read_json(path)
        trial = state.get('trial', {})
        trial_id = trial.get('trial_id')
        if trial_id not in expected or trial != expected[trial_id]:
            errors.append('Unassigned or changed trial: ' + path.name)
            continue
        if trial_id in seen:
            errors.append('Duplicate trial: ' + trial_id)
        seen.add(trial_id)
        counts[state['status']] += 1
        if state.get('protocol_sha256') != digest(protocol.path):
            errors.append('Protocol hash differs: ' + trial_id)
        native = state.get('transport') == 'codex-native'
        if not native and not allow_simulation:
            errors.append('Nonexperimental transport: ' + trial_id)
        journal_path = path.with_suffix('.journal.jsonl')
        journal = [json.loads(line) for line in journal_path.read_text().splitlines()] if journal_path.exists() else []
        requests = [j for j in journal if j.get('type') == 'request_checkpoint']
        responses = [j for j in journal if j.get('type') == 'response_checkpoint']
        turns = state['turns']
        invocation_count += len(turns) + int(state.get('pending_turn') is not None)
        if len(requests) != len(turns) + int(state.get('pending_turn') is not None) or len(responses) != len(turns):
            errors.append('Missing or duplicate journal events: ' + trial_id)
        reconstructed = [{'round': i, 'order': order, 'remaining': list(order), 'route': ''}
                         for i, order in enumerate(trial['round_orders'], 1)]
        session = None
        for index, record in enumerate(turns, 1):
            if index > 9 or record.get('turn') != index:
                errors.append('Nonsequential turns: ' + trial_id)
                break
            round_number, local_turn = phase(index)
            current = reconstructed[round_number - 1]
            feedback = current['route'][-1] if current['route'] else None
            prompt = protocol.prompt(trial, index, feedback, current['remaining'])
            schema = protocol.schema(index, current['remaining'], trial['frame'])
            if record.get('prompt') != prompt or record.get('schema') != schema:
                errors.append(f'Prompt/schema mismatch: {trial_id} turn {index}')
            if record.get('round') != round_number or record.get('local_turn') != local_turn:
                errors.append('Changed round metadata: ' + trial_id)
            if index <= len(responses) and any(record.get(k) != responses[index - 1].get(k)
                    for k in ('text', 'events', 'prompt', 'schema', 'session_id', 'ok', 'raw_files')):
                errors.append('Raw journal discrepancy: ' + trial_id)
            if index <= len(requests) and any(record.get(k) != requests[index - 1].get(k)
                    for k in ('turn', 'prompt', 'schema', 'session_id_before', 'requested_at')):
                errors.append('Request journal discrepancy: ' + trial_id)
            if record.get('session_id_before') != session or (session and record.get('session_id') != session):
                errors.append('Broken native session continuity: ' + trial_id)
            session = record.get('session_id')
            if record.get('tool_events') or record.get('metadata_fallback'):
                errors.append('Tool use or metadata fallback: ' + trial_id)
            if native:
                if record.get('provider_schema') != provider_schema(schema):
                    errors.append('Provider schema differs: ' + trial_id)
                files = record.get('raw_files', [])
                if not files:
                    errors.append('Missing native raw files: ' + trial_id)
                for item in files:
                    source = directory / item['path']
                    if directory.resolve() not in source.resolve().parents or not source.is_file() or digest(source) != item['sha256']:
                        errors.append('Native file missing or changed: ' + item['path'])
                    else:
                        raw_verified.add(str(source))
                by_name = {Path(item['path']).name: directory / item['path'] for item in files}
                required = [f'turn-{index:02d}.events.jsonl', f'turn-{index:02d}.stderr.txt',
                            f'turn-{index:02d}.schema.json', 'subject-system.txt']
                if not all(name in by_name and by_name[name].is_file() for name in required):
                    errors.append('Incomplete native archive: ' + trial_id)
                else:
                    native_events, malformed = [], 0
                    for line in by_name[required[0]].read_text().splitlines():
                        try:
                            native_events.append(json.loads(line))
                        except ValueError:
                            malformed += 1
                    try:
                        mismatch = (json.loads(by_name[required[2]].read_text()) != provider_schema(schema) or
                            by_name['subject-system.txt'].read_text() != protocol.data['system'] or
                            by_name[required[1]].read_text() != record['stderr'] or
                            native_events != record['events'] or malformed != record.get('malformed_event_lines', 0))
                    except ValueError:
                        mismatch = True
                    if mismatch:
                        errors.append('Native archive/record discrepancy: ' + trial_id)
            if not record.get('ok'):
                if state['status'] == 'complete':
                    errors.append('Failed response in complete trial: ' + trial_id)
                break
            try:
                parsed = protocol.parse_response(record['text'], index, current['remaining'], trial['frame'])
            except (ValueError, TypeError):
                if state['status'] == 'complete' or 'parsed' in record:
                    errors.append('Invalid parsed response: ' + trial_id)
                break
            if record.get('parsed') != parsed:
                errors.append('Parsed/raw discrepancy: ' + trial_id)
            if local_turn in (1, 2):
                selected = parsed['selection']
                current['remaining'], operation = operate(current['remaining'],
                    selected if local_turn == 1 else [selected], trial['target'])
                current['route'] += operation
            else:
                measurement = 3 if index == 9 else round_number
                valid[f'm{measurement}'] += 1
                routes[(trial['configuration_id'], trial['frame'], round_number, current['route'])] += 1
        if reconstructed != state.get('rounds'):
            errors.append('Round engine state differs: ' + trial_id)
        if state['status'] == 'complete' and (len(turns) != 9 or any(r['remaining'] != [trial['target']] for r in reconstructed)):
            errors.append('Incomplete or wrong final complete trial: ' + trial_id)
        if session:
            if session in sessions and sessions[session] != trial_id:
                errors.append('Reused native session: ' + trial_id)
            sessions[session] = trial_id
    counts['unattempted'] = len(expected) - len(seen)
    report = {'run_id': manifest['run_id'], 'worker_id': manifest['worker_id'],
        'assigned': len(expected), 'attempted': len(seen), 'counts': dict(counts),
        'valid_measurements': dict(valid), 'subject_invocations': invocation_count,
        'manifest_sha256': digest(manifest_path), 'session_ids': sessions,
        'raw_files_verified': len(raw_verified), 'errors': errors,
        'routes': [{'configuration_id': k[0], 'frame': k[1], 'round': k[2], 'route': k[3], 'count': v}
                   for k, v in sorted(routes.items())],
        'integrity_ok': not errors, 'collection_finished': not errors and
            counts['unattempted'] == 0 and counts.get('active', 0) == 0,
        'actual_http_attempts': None, 'billing_cost': None}
    write_json(directory / 'audit.json', report)
    return report
