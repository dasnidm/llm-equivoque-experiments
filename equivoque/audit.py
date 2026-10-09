"""Audit manifest membership, exact prompts, selections, routes, and sessions."""
import collections
import json
from pathlib import Path

from .core import Protocol, digest, operate, parse_response, read_json, write_json


def audit_worker(manifest_path, directory, allow_simulation=False):
    manifest = read_json(manifest_path)
    expected = {trial['trial_id']: trial for trial in manifest['trials']}
    counts = collections.Counter()
    errors = []
    actual_ids = set()
    sessions = {}
    configurations = collections.Counter()
    route_counts = collections.Counter()
    protocol = Protocol()
    directory = Path(directory)
    invocation_count = 0
    valid_pre = valid_post = 0
    for path in sorted((directory / 'trials').glob('*.json')):
        state = read_json(path)
        trial = state.get('trial', {})
        trial_id = trial.get('trial_id')
        if trial_id not in expected or trial != expected[trial_id]:
            errors.append(f'Unassigned or changed trial: {path.name}')
            continue
        if trial_id in actual_ids:
            errors.append(f'Duplicate trial: {trial_id}')
        actual_ids.add(trial_id)
        if state.get('protocol_sha256') != digest(protocol.path):
            errors.append(f'Changed protocol hash: {trial_id}')
        if state.get('transport') != 'codex-native' and not allow_simulation:
            errors.append(f'Nonexperimental transport: {trial_id}')
        journal_path = path.with_suffix('.journal.jsonl')
        journal = [json.loads(line) for line in
                   journal_path.read_text().splitlines()] if journal_path.exists() else []
        requests = [item for item in journal if item.get('type') == 'request_checkpoint']
        responses = [item for item in journal if item.get('type') == 'response_checkpoint']
        expected_requests = len(state.get('turns', [])) + int(state.get('pending_turn') is not None)
        if len(requests) != expected_requests or len(responses) != len(state.get('turns', [])):
            errors.append(f'Missing or duplicate raw journal events: {trial_id}')
        for record, raw in zip(state.get('turns', []), responses):
            if any(record.get(key) != raw.get(key) for key in
                   ('text', 'events', 'prompt', 'schema', 'session_id', 'ok')):
                errors.append(f'Raw journal discrepancy: {trial_id}')
        counts[state.get('status', 'unknown')] += 1
        turns = state.get('turns', [])
        invocation_count += len(turns) + int(state.get('pending_turn') is not None)
        remaining, route, session = trial['order'], '', None
        for index, record in enumerate(turns, 1):
            if record.get('turn') != index or index > 4:
                errors.append(f'Nonsequential turns: {trial_id}')
                break
            feedback = route[-1] if route else None
            if record.get('prompt') != protocol.prompt(trial, index, feedback, remaining):
                errors.append(f'Prompt mismatch: {trial_id} turn {index}')
            if record.get('schema') != protocol.schema(index, remaining):
                errors.append(f'Schema mismatch: {trial_id} turn {index}')
            if record.get('session_id_before') != session:
                errors.append(f'Broken request continuity: {trial_id} turn {index}')
            returned_session = record.get('session_id')
            if session and returned_session != session:
                errors.append(f'Changed session: {trial_id} turn {index}')
            session = returned_session
            if record.get('tool_events'):
                errors.append(f'Subject tool use: {trial_id} turn {index}')
            if not record.get('ok'):
                if state.get('status') == 'complete':
                    errors.append(f'Failed response in completed trial: {trial_id}')
                break
            try:
                parsed = parse_response(record['text'], index, remaining)
            except (ValueError, TypeError) as error:
                if state.get('status') == 'complete' or 'parsed' in record:
                    errors.append(f'Invalid parsed response: {trial_id}: {error}')
                break
            if record.get('parsed') != parsed:
                errors.append(f'Parsed/raw discrepancy: {trial_id} turn {index}')
            if index < 3:
                selection = parsed['selection']
                remaining, operation = operate(remaining,
                    selection if index == 1 else [selection], trial['target'])
                route += operation
            elif index == 3:
                valid_pre += 1
            else:
                valid_post += 1
        if state.get('route') != route or state.get('remaining') != remaining:
            errors.append(f'Route/remaining-set mismatch: {trial_id}')
        if session:
            if session in sessions and sessions[session] != trial_id:
                errors.append(f'Reused session: {trial_id}')
            sessions[session] = trial_id
        if state.get('status') == 'complete':
            if len(turns) != 4 or remaining != [trial['target']]:
                errors.append(f'Incomplete or wrong-final completed trial: {trial_id}')
            configurations[(trial['configuration_id'], trial['frame'])] += 1
            route_counts[(trial['configuration_id'], trial['frame'], route)] += 1
    counts['unattempted'] = len(expected) - len(actual_ids)
    report = {'run_id': manifest['run_id'], 'worker_id': manifest['worker_id'],
              'assigned': len(expected), 'attempted': len(actual_ids),
              'counts': dict(counts), 'valid_pre': valid_pre,
              'valid_post': valid_post, 'subject_invocations': invocation_count,
              'actual_http_requests': None,
              'http_count_note': 'Native CLI may retry HTTP internally; raw events are retained.',
              'manifest_sha256': digest(manifest_path),
              'completed_by_configuration_frame': [
                  {'configuration_id': key[0], 'frame': key[1], 'count': value}
                  for key, value in sorted(configurations.items())],
              'routes': [{'configuration_id': key[0], 'frame': key[1],
                          'route': key[2], 'count': value}
                         for key, value in sorted(route_counts.items())],
              'session_ids': sessions, 'errors': errors, 'integrity_ok': not errors,
              'collection_finished': not errors and counts['unattempted'] == 0
                                     and counts.get('active', 0) == 0}
    write_json(directory / 'audit.json', report)
    return report
