"""Recover uniquely completed native turns from files, with zero model calls."""
import datetime
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equivoque.core import Protocol, digest, frozen_hashes, operate, read_json, write_json
from equivoque.runner import append_event, now
from equivoque.transport import overrides, provider_schema

RUN = 'equivoque-2026-10-09-v1'
if (ROOT / 'preparation/current-runtime/runtime-recovery-01.json').exists():
    raise SystemExit('Existing recovery evidence is preserved; do not overwrite or replay it')
frozen_hashes()
protocol = Protocol()
recovered = []
for worker in 'abcdefg':
    tree = ROOT / 'work/worker-trees' / RUN / worker
    output = tree / 'results' / RUN / f'worker-{worker}'
    for path in (output / 'trials').glob('*.json'):
        state = read_json(path)
        if state['status'] != 'active' or not state.get('pending_turn'):
            continue
        request = state['pending_turn']
        turn, trial = request['turn'], state['trial']
        scratch = tree / 'work' / RUN / worker / state['scratch_id']
        raw = scratch / f'turn-{turn:02d}.events.jsonl'
        stderr_path = scratch / f'turn-{turn:02d}.stderr.txt'
        events = [json.loads(line) for line in raw.read_text().splitlines()]
        messages = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
                    and e.get('item', {}).get('type') == 'agent_message']
        completed = [e for e in events if e.get('type') == 'turn.completed']
        ids = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
        tools = [e.get('item', {}).get('type') for e in events
                 if e.get('type') in ('item.started', 'item.completed') and
                 e.get('item', {}).get('type') in ('command_execution', 'mcp_tool_call',
                    'web_search', 'file_change', 'collab_agent_tool_call')]
        stderr = stderr_path.read_text()
        if (len(messages) != 1 or len(completed) != 1 or len(ids) != 1 or tools or
                events[-1]['type'] != 'turn.completed' or
                any(e.get('type') == 'turn.failed' for e in events) or
                'fallback metadata' in (json.dumps(events) + stderr).lower()):
            raise SystemExit('Pending turn is not uniquely recoverable: ' + str(path))
        if state['session_id'] and ids[0] != state['session_id']:
            raise SystemExit('Recovered turn changes native session')
        feedback = state['route'][-1] if state['route'] else None
        if request['prompt'] != protocol.prompt(trial, turn, feedback, state['remaining']):
            raise SystemExit('Pending prompt differs from frozen protocol')
        if request['schema'] != protocol.schema(turn, state['remaining'], trial['frame']):
            raise SystemExit('Pending canonical schema differs')
        schema_path = scratch / f'turn-{turn:02d}.schema.json'
        if read_json(schema_path) != provider_schema(request['schema']):
            raise SystemExit('Durable provider schema differs')
        system = scratch / 'subject-system.txt'
        if system.read_text() != protocol.data['system']:
            raise SystemExit('Durable subject system text differs')
        parsed = protocol.parse_response(messages[0], turn, state['remaining'], trial['frame'])
        command = ['codex', 'exec'] + (['resume'] if state['session_id'] else [])
        command += ['--ignore-user-config', '--ignore-rules', '--skip-git-repo-check',
                    '--json', '--model', trial['model'], '--output-schema', str(schema_path)]
        command += overrides(system, trial['effort'])
        command += [state['session_id'], '-'] if state['session_id'] else [
            '--sandbox', 'read-only', '-C', str(scratch / 'subject'), '-']
        saved = output / 'recovery-01' / path.stem
        saved.mkdir(parents=True, exist_ok=False)
        for source in (raw, stderr_path, schema_path, system):
            shutil.copyfile(source, saved / source.name)
        received = datetime.datetime.fromtimestamp(raw.stat().st_mtime,
                    datetime.timezone.utc).isoformat()
        record = {**request, 'ok': True, 'session_id': ids[0], 'text': messages[0],
            'events': events, 'stderr': stderr, 'command': command,
            'exit_code': None, 'timeout': False, 'duration_seconds': None,
            'usage': completed[0]['usage'], 'tool_events': [], 'metadata_fallback': False,
            'malformed_event_lines': 0, 'provider_schema': provider_schema(request['schema']),
            'provider_schema_note': 'uniqueItems omitted; local duplicate validation retained.',
            'received_at': received, 'recovered_at': now(),
            'recovered_from_durable_events': True, 'command_reconstructed': True,
            'recovery_note': 'One final turn.completed event, one schema-valid agent response, matching session/system/prompt/schema, zero tools. No model request was made. Original process exit code and monotonic latency are unavailable; received_at is the durable event-file timestamp.',
            'durable_events_sha256': digest(raw)}
        append_event(path.with_suffix('.journal.jsonl'), {'type': 'response_checkpoint', **record})
        record['parsed'] = parsed
        state['turns'].append(record)
        state['session_id'] = ids[0]
        state['pending_turn'] = None
        if turn < 3:
            choice = parsed['selection']
            state['remaining'], operation = operate(state['remaining'],
                choice if turn == 1 else [choice], trial['target'])
            state['route'] += operation
        if turn == 4:
            state.update(status='complete', ended_at=received)
        write_json(path, state)
        recovered.append({'worker_id': worker, 'trial_id': trial['trial_id'],
                          'turn': turn, 'session_id': ids[0],
                          'durable_events_sha256': digest(raw), 'model_invocations_added': 0})
        print(worker, turn, state['status'], flush=True)
write_json(ROOT / 'preparation/current-runtime/runtime-recovery-01.json', {
    'recovered_at': now(), 'recovered_turns': recovered, 'model_invocations_added': 0,
    'frozen_protocol_unchanged': True,
    'reason': 'Coordinator/worker processes stopped during runtime reattachment; native CLI children completed their already-requested turns and left final durable event streams.'})
