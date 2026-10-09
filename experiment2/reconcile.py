"""Recover uniquely completed durable native responses with zero model calls."""
import datetime
import json
from pathlib import Path
import shutil
import subprocess

from equivoque.core import ROOT, digest, operate, read_json, write_json
from equivoque.runner import append_event, now
from equivoque.transport import overrides, provider_schema
from equivoque2.audit import audit_worker
from equivoque2.protocol import CONFIG, RepeatedProtocol, frozen_hashes, phase
from equivoque2.runner import archive_native


def main():
    config, protocol = read_json(CONFIG), RepeatedProtocol()
    evidence = ROOT / 'experiment2/runtime/runtime-recovery-01.json'
    if evidence.exists():
        raise ValueError('Recovery already recorded; never duplicate it')
    frozen_hashes()
    processes = read_json(ROOT / 'experiment2/runtime/processes-01.json')
    for pid in [processes['coordinator_pid'], *processes['workers'].values()]:
        stat = Path(f'/proc/{pid}/stat')
        if stat.exists() and stat.read_text().rsplit(')', 1)[1].split()[0] != 'Z':
            raise ValueError('Original process still live: ' + str(pid))
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():
            continue
        try:
            argv = (item / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if argv and b'codex' in Path(argv[0].decode(errors='replace')).name.encode() and any(
                config['run_id'].encode() in argument for argument in argv[1:]):
            raise ValueError('Native subject still live: ' + item.name)
    recovered = []
    for w in config['workers']:
        tree = ROOT / 'work/worker-trees' / config['run_id'] / w
        freeze = read_json(tree / 'experiment2/protocol/freeze.json')
        if any(digest(tree / p) != h for p,h in freeze['files'].items()):
            raise ValueError('Worker source changed')
        directory = tree / 'results' / config['run_id'] / f'worker-{w}'
        for path in sorted((directory / 'trials').glob('*.json')):
            state = read_json(path)
            if state['status'] != 'active':
                continue
            q = state.get('pending_turn')
            if not q:
                continue
            turn, trial = q['turn'], state['trial']
            rnd, local = phase(turn)
            current = state['rounds'][rnd - 1]
            feedback = current['route'][-1] if current['route'] else None
            assert q['prompt'] == protocol.prompt(trial, turn, feedback, current['remaining'])
            assert q['schema'] == protocol.schema(turn, current['remaining'], trial['frame'])
            assert q['session_id_before'] == state['session_id']
            assert turn == len(state['turns']) + 1
            scratch = tree / 'work/subject-sessions' / config['run_id'] / w / state['scratch_id']
            raw = scratch / f'turn-{turn:02d}.events.jsonl'
            events = [json.loads(line) for line in raw.read_text().splitlines()]
            messages = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
                        and e.get('item', {}).get('type') == 'agent_message']
            completed = [e for e in events if e.get('type') == 'turn.completed']
            ids = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
            tools = [e.get('item', {}).get('type') for e in events if e.get('type') in ('item.started','item.completed')
                and e.get('item', {}).get('type') in ('command_execution','mcp_tool_call','web_search','file_change','collab_agent_tool_call')]
            stderr = (scratch / f'turn-{turn:02d}.stderr.txt').read_text()
            if (len(messages) != 1 or len(completed) != 1 or len(ids) != 1 or tools or
                    events[-1]['type'] != 'turn.completed' or any(e.get('type') == 'turn.failed' for e in events) or
                    'fallback metadata' in (json.dumps(events) + stderr).lower()):
                raise ValueError('Pending response cannot be uniquely recovered: ' + str(path))
            assert not state['session_id'] or ids[0] == state['session_id']
            elapsed_bound = raw.stat().st_mtime - datetime.datetime.fromisoformat(q['requested_at']).timestamp()
            assert 0 <= elapsed_bound <= config['turn_deadline_seconds']
            schema_path = scratch / f'turn-{turn:02d}.schema.json'
            system = scratch / 'subject-system.txt'
            assert read_json(schema_path) == provider_schema(q['schema'])
            assert system.read_text() == protocol.data['system']
            parsed = protocol.parse_response(messages[0], turn, current['remaining'], trial['frame'])
            saved = directory / 'recovery-01' / path.stem
            saved.mkdir(parents=True, exist_ok=False)
            shutil.copyfile(path, saved / 'state-before.json')
            shutil.copyfile(path.with_suffix('.journal.jsonl'), saved / 'journal-before.jsonl')
            before_sha = digest(path)
            command = ['codex', 'exec'] + (['resume'] if state['session_id'] else [])
            command += ['--ignore-user-config','--ignore-rules','--skip-git-repo-check','--json','--model',trial['model'],
                        '--output-schema', str(schema_path.resolve())]
            command += overrides(system, trial['effort'])
            command += [state['session_id'],'-'] if state['session_id'] else [
                '--sandbox','read-only','-C',str((scratch / 'subject').resolve()),'-']
            received = datetime.datetime.fromtimestamp(raw.stat().st_mtime, datetime.timezone.utc).isoformat()
            record = {**q, 'ok': True, 'session_id': ids[0], 'text': messages[0], 'events': events,
                'stderr': stderr, 'command': command, 'exit_code': None, 'timeout': False,
                'duration_seconds': None, 'usage': completed[0].get('usage'), 'tool_events': [],
                'metadata_fallback': False, 'malformed_event_lines': 0, 'provider_schema': provider_schema(q['schema']),
                'provider_schema_note': 'uniqueItems omitted; local duplicate validation retained.',
                'received_at': received, 'recovered_at': now(), 'recovered_from_durable_events': True,
                'command_reconstructed': True, 'durable_events_sha256': digest(raw),
                'completion_elapsed_upper_bound_seconds': elapsed_bound,
                'recovery_note': 'Environment reconnection terminated the parent workers. Existing native files contain exactly one schema-valid agent message and one final turn.completed event within the frozen deadline, with matching session, pending prompt, schemas, and system; no tools or metadata fallback. No request was replayed. Parent-observed CLI exit status and monotonic duration are unavailable and remain null. Operational WebSocket reconnect diagnostics are preserved verbatim; the final native completion is the recovery evidence.'}
            record['raw_files'] = archive_native(scratch, directory / 'native-raw' / trial['trial_id'].replace('/', '__'), directory)
            append_event(path.with_suffix('.journal.jsonl'), {'type':'response_checkpoint', **record})
            record['parsed'] = parsed
            state['turns'].append(record)
            state.update(session_id=ids[0], pending_turn=None)
            if local in (1,2):
                selection = parsed['selection']
                current['remaining'], operation = operate(current['remaining'], selection if local == 1 else [selection], trial['target'])
                current['route'] += operation
            if turn == 10:
                state.update(status='complete', ended_at=received)
            write_json(path, state)
            recovered.append({'worker':w, 'trial_id':trial['trial_id'], 'turn':turn,
                'state_before_sha256':before_sha, 'durable_events_sha256':digest(raw),
                'model_invocations_added':0, 'exit_code':None, 'duration_seconds':None})
        audit = audit_worker(tree / 'manifests' / config['run_id'] / f'worker-{w}.json', directory)
        assert audit['integrity_ok'], audit['errors']
    write_json(evidence, {'at':now(), 'reason':'Runtime reconnection interrupted coordinator and workers.',
        'recovered_turns':recovered, 'model_invocations_added':0, 'frozen_protocol_unchanged':True,
        'unknown_exit_status_turns':len(recovered), 'unknown_duration_turns':len(recovered),
        'resume_rule':'Start only the unrequested next turn, preserve all original native sessions and trial IDs.'})
    print(json.dumps({'recovered_turns':len(recovered), 'model_invocations_added':0, 'all_worker_audits_passed':True}))


if __name__ == '__main__':
    main()
