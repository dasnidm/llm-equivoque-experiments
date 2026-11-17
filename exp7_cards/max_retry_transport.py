"""Independent technical transport: immediate retries, no pacing.

Only explicit terminal 429/selected 5xx failures can be retried.  A failed
turn is removed using thread/revert, then paginated history must exactly match
the previously completed turn IDs. All RPCs and failed attempts remain on
disk. An uncertain send, changed history, tool event or compaction is never
implicitly replayed. This transport is NOT the frozen scientific worker.
"""
import json
from pathlib import Path
import re
import threading
import time

from equivoque.transport import overrides, provider_schema
import exp7_persistent.transport as native


def retryable(result, messages, thread_id, turn_id):
    if result.get('ok') or result.get('tool_events') or result.get('compaction_events'):
        return False
    expected_failure = {'Missing, duplicated, or unsuccessful terminal turn',
                        'Expected exactly one assistant response', 'Unrecovered server error',
                        'Missing usage evidence', 'Terminal turn contains an error'}
    if set(result.get('protocol_violations', [])) - expected_failure:
        return False
    terms = [m.get('params', {}) for m in messages if m.get('method') == 'turn/completed']
    if (len(terms) != 1 or terms[0].get('threadId') != thread_id
            or terms[0].get('turn', {}).get('id') != turn_id
            or terms[0].get('turn', {}).get('status') != 'failed'):
        return False
    for m in messages:
        method = m.get('method')
        if method in ('thread/compacted', 'model/rerouted', 'configWarning', 'guardianWarning') or ('id' in m and method):
            return False
        if method == 'warning':
            warning = str(m.get('params', {}).get('message', ''))
            # The base adapter already recognizes this transport fallback;
            # it does not imply the model changed or a tool was invoked.
            if not warning.startswith('Falling back from WebSockets to HTTPS transport.'):
                return False
    errors = [e for e in result.get('events', []) if e.get('type') == 'error']
    if not errors:
        return False
    # Actual observed 429 uses "last status: 429 Too Many Requests".
    # Avoid matching token counts, UUIDs or a mere "retry_429=false".
    return any(re.search(r'\b(?:status:\s*)?(?:429\s+Too Many Requests|(?:500|502|503|504)\b)',
                         str(e.get('message', '')), re.I) for e in errors)


def observed_error_code(result):
    for event in result.get('events', []):
        if event.get('type') != 'error':
            continue
        text = str(event.get('message', ''))
        match = re.search(r'(?:status:\s*)?(429\s+Too Many Requests|(?:500|502|503|504)\b)',text,re.I)
        if match:
            return int(match.group(1)[:3])
    return None


class MaxRetryTransport(native.PersistentTransport):
    name = 'codex-app-server-persistent-technical-max-retry-v1'

    def __init__(self, *, max_attempts=5, **kwargs):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError('max_attempts must be between 1 and 20')
        if kwargs.get('min_start_interval', 0):
            raise ValueError('This technical experiment uses no pacing')
        super().__init__(**kwargs)
        self.max_attempts = max_attempts
        self.before_send = None
        self.after_close = None
        self.meter_lock = threading.Lock()
        self.sent_stamps = []
        self.attempt_statuses = []

    def _rollback(self, c, directory, turn_id, expected_ids, deadline):
        with (directory/'revert-sent.jsonl').open('xb') as sent, (directory/'revert-received.jsonl').open('xb') as received:
            messages = []
            reverted = c.rpc('thread/revert', {'threadId': c.thread_id, 'beforeTurnId': turn_id},
                             deadline, sent, received, messages)
            if reverted.get('thread', {}).get('id') != c.thread_id:
                raise ValueError('Rollback returned a different thread')
            listed = c.rpc('thread/turns/list', {'threadId': c.thread_id, 'sortDirection': 'asc',
                                                'limit': 100, 'itemsView': 'summary'},
                           deadline, sent, received, messages)
            actual = [t.get('id') for t in listed.get('data', [])]
            if listed.get('nextCursor') is not None or actual != expected_ids:
                raise ValueError('History after rollback does not match completed turns')

    def request(self, trial, prompt, schema, system, session_id, directory, turn):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        subject = native.subject_directory(directory)
        subject.mkdir(parents=True, exist_ok=True, mode=0o700)
        system_path = directory/'subject-system.txt'
        if system_path.exists():
            if system_path.read_text() != system:
                raise ValueError('Session system changed')
        else:
            native._write(system_path, system)
        effective = provider_schema(schema) if schema is not None else None
        key = trial['trial_id']
        signature = (str(directory), trial['model'], trial['effort'], native.digest(system_path))
        with self._map_lock:
            if self._closed:
                raise RuntimeError('Transport closed')
            c = self._conversations.get(key)
            if c is None:
                if session_id is not None or turn != 1:
                    raise ValueError('Fresh technical thread required')
                native.isolation_preflight(subject)
                c = native._Conversation(self._command(trial, system_path), subject, directory, signature)
                c.completed_turn_ids = []
                self._conversations[key] = c
        if not c.lock.acquire(blocking=False):
            raise RuntimeError('Concurrent turns on same thread')
        try:
            if c.closed or c.signature != signature or c.thread_id != session_id:
                raise ValueError('Thread or frozen configuration mismatch')
            if c.last_turn is not None and turn != c.last_turn + 1:
                raise ValueError('Turn sequence mismatch')
            retries = []
            for attempt_number in range(1, self.max_attempts+1):
                if self.before_send:
                    self.before_send()
                attempt = directory/f'turn-{turn:02d}-attempt-{attempt_number:02d}'
                attempt.mkdir(exist_ok=False)
                native._write(attempt/'prompt.txt', prompt)
                if effective is not None:
                    native._write(attempt/'schema.json', native._json(effective)+'\n')
                started, messages = time.monotonic(), []
                deadline = started + self.timeout
                with (attempt/'rpc-sent.jsonl').open('xb') as sent, (attempt/'rpc-received.jsonl').open('xb') as received:
                    if c.thread_id is None:
                        c.rpc('initialize', {'clientInfo': {'name':'codex_exec','version':'0.159.0-alpha.3'},
                                            'capabilities': {'experimentalApi': True}}, deadline, sent, received, messages)
                        c.send({'method':'initialized'}, sent)
                        config = {k: json.loads(v) for k,v in (x.split('=',1) for x in overrides(system_path,trial['effort'])[1::2])}
                        response = c.rpc('thread/start', {'model':trial['model'],'cwd':str(subject),
                            'approvalPolicy':'never','sandbox':'read-only','ephemeral':False,'historyMode':'paginated',
                            'allowProviderModelFallback':False,'dynamicTools':[],'config':config}, deadline,sent,received,messages)
                        if (response.get('model') != trial['model'] or response.get('reasoningEffort') != trial['effort']
                            or response.get('cwd') != str(subject) or response.get('approvalPolicy') != 'never'
                            or response.get('sandbox',{}).get('type') != 'readOnly' or response.get('instructionSources')):
                            raise ValueError('Effective subject settings changed')
                        c.thread_id = response['thread']['id']
                        native.validate_startup(messages, c.thread_id)
                    boundary = len(messages)
                    if self.before_send:
                        self.before_send()
                    with self.meter_lock:
                        self.sent_stamps.append(time.monotonic())
                    response = c.rpc('turn/start', {'threadId':c.thread_id,'turnTrigger':'exec',
                        'input':[{'type':'text','text':prompt,'text_elements':[]}],'cwd':str(subject),
                        'approvalPolicy':'never','effort':trial['effort'],'outputSchema':effective},
                        deadline,sent,received,messages)
                    tid = response['turn']['id']
                    while not any(m.get('method') == 'turn/completed' and m.get('params',{}).get('threadId') == c.thread_id
                                  and m.get('params',{}).get('turn',{}).get('id') == tid for m in messages[boundary:]):
                        c.receive(deadline,received,messages)
                result = native.normalize_turn(messages[boundary:], c.thread_id, tid)
                stderr = c.consume_stderr()
                native._write(attempt/'stderr.txt', stderr)
                if 'fallback metadata' in stderr.lower():
                    result['ok'] = False
                    result['protocol_violations'].append('Fallback model metadata')
                native._write(attempt/'events.jsonl',''.join(native._json(e)+'\n' for e in result['events']))
                native._write(attempt/'adapter.json',native._json({'transport':self.name,'process_pid':c.process.pid,
                    'thread_id':c.thread_id,'turn_id':tid,'command':c.command,'normalization_start_index':boundary,
                    'catalog_sha256':self.catalog_sha256,'events_are_derived':True})+'\n')
                can_retry = retryable(result, messages[boundary:], c.thread_id, tid) and 'fallback metadata' not in stderr.lower()
                with self.meter_lock:
                    self.attempt_statuses.append({'ok':result['ok'],'retryable':can_retry,'turn':turn,
                                                  'attempt':attempt_number,'http_status':observed_error_code(result)})
                if can_retry and attempt_number < self.max_attempts:
                    self._rollback(c, attempt, tid, c.completed_turn_ids, time.monotonic()+self.timeout)
                    retries.append({'attempt':attempt_number,'turn_id':tid,
                        'raw_files':[{'path':str(p),'sha256':native.digest(p)} for p in sorted(attempt.iterdir()) if p.is_file()]})
                    continue
                c.last_turn = turn
                if result['ok']:
                    c.completed_turn_ids.append(tid)
                else:
                    c.close()
                result.update(session_id=c.thread_id,app_server_turn_id=tid,process_pid=c.process.pid,
                    command=c.command,stderr=stderr,exit_code=0,timeout=False,
                    duration_seconds=time.monotonic()-started,startup_notices=0,
                    metadata_fallback='fallback metadata' in stderr.lower(),malformed_event_lines=0,
                    provider_schema=effective,retry_records=retries,
                    raw_files=[{'path':str(p),'sha256':native.digest(p)} for p in
                               [system_path,*([directory/'model-catalog.json'] if self.catalog_path else []),
                                *sorted(p for p in attempt.iterdir() if p.is_file())]])
                return result
        except Exception as exc:
            c.close()
            exc.transport_diagnostics = c.consume_stderr()
            raise
        finally:
            c.lock.release()
