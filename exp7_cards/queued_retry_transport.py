"""FIFO admission with live-session retries and durable retry evidence.

This is a separate operational prototype, not the frozen scientific worker.
Only a confirmed terminal turn failure is eligible for retry; unknown sends,
changed history, tool events and compaction are held without implicit replay.
"""
from collections import Counter, deque
from itertools import count
import json
import os
from pathlib import Path
import re
import threading
import time

from equivoque.transport import overrides, provider_schema
import exp7_persistent.transport as native
from exp7_pre.runner import append_event


def _fsync_directory(path):
    fd = os.open(Path(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
    # A verified terminal failure, not an inferred code or ambiguous send, is
    # the basis for retry, even if the server omits error details. All safe
    # terminal error classes follow the user's rule.
    return True


def observed_error_code(result):
    for event in result.get('events', []):
        if event.get('type') != 'error':
            continue
        text = str(event.get('message', ''))
        match = re.search(r'(?:status:\s*)?(429\s+Too Many Requests|(?:500|502|503|504)\b)',text,re.I)
        if match:
            return int(match.group(1)[:3])
    return None


class ProcessExited(RuntimeError):
    """The original process ended; this sample cannot meet the protocol."""


class FairAdmissionQueue:
    """FIFO admission, not a rate limiter; model calls execute concurrently.

    A local pipe write is not held under the condition lock: a broken or full
    pipe in one subject therefore cannot block every other subject. Admission
    order is FIFO; actual wall-clock writes may overlap or exchange order.
    """
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = deque()
        self.sequence = count(1)
        self.dispatched = deque(maxlen=10000)
        self.dispatch_total = 0

    def admit(self, key, alive):
        with self.condition:
            ticket = (next(self.sequence), key)
            self.pending.append(ticket)
            try:
                while self.pending[0] != ticket:
                    if not alive():
                        raise ProcessExited('Process exited while awaiting queue admission')
                    self.condition.wait(timeout=0.1)
                if not alive():
                    raise ProcessExited('Process exited before queue admission')
                self.pending.popleft()
                self.dispatched.append(ticket)
                self.dispatch_total += 1
                self.condition.notify_all()
                return ticket[0]
            finally:
                if ticket in self.pending:
                    self.pending.remove(ticket)
                    self.condition.notify_all()


class QueuedRetryTransport(native.PersistentTransport):
    name = 'codex-app-server-persistent-queued-retry-v1'

    def __init__(self, *, admission_queue=None, **kwargs):
        if kwargs.get('min_start_interval', 0):
            raise ValueError('Queued retries use no artificial pacing')
        super().__init__(**kwargs)
        self.admission_queue = admission_queue or FairAdmissionQueue()
        self.before_send = None
        self.after_close = None
        self.meter_lock = threading.Lock()
        self.sent_stamps = deque(maxlen=10000)
        self.attempt_statuses = deque(maxlen=10000)
        self.total_sent = 0
        self.attempt_counts = Counter()
        self.failed_processes = {}
        self.held_processes = {}
        self.watcher_lock = threading.Lock()
        self.watchers = set()
        self.watcher_errors = {}

    def _install_queue(self, c, key):
        original_send, original_receive = c.send, c.receive
        if hasattr(c,'stderr_consumed'):
            def incremental_stderr():
                # Re-reading the entire growing CLI log on every retry becomes
                # quadratic and can exhaust memory during unlimited retries.
                with c.stderr_path.open('rb') as stream:
                    stream.seek(0,os.SEEK_END)
                    if stream.tell() < c.stderr_consumed:
                        raise ValueError('Process diagnostics log was truncated')
                    stream.seek(c.stderr_consumed)
                    data=stream.read()
                c.stderr_consumed += len(data)
                return data.decode('utf-8',errors='replace')
            c.consume_stderr=incremental_stderr
        def queued_send(message, sent):
            if message.get('method') == 'turn/start':
                self.admission_queue.admit(key, lambda: c.process.poll() is None)
                if self.before_send:
                    self.before_send()
                if c.process.poll() is not None:
                    raise ProcessExited('Process exited before local send')
                if c.closed:
                    raise RuntimeError('Live process has a locally closed session; hold for inspection')
                with self.meter_lock:
                    self.sent_stamps.append(time.monotonic())
                    self.total_sent += 1
            return original_send(message, sent)
        def live_receive(deadline, received, messages):
            # No response is not proof of failure. Continue waiting on the
            # same process rather than replaying or killing a live subject.
            while True:
                try:
                    return original_receive(deadline, received, messages)
                except TimeoutError:
                    if c.process.poll() is not None:
                        raise ProcessExited('Process exited during response wait')
                    if self.before_send:
                        self.before_send()
                    deadline = time.monotonic() + self.timeout
        c.send, c.receive = queued_send, live_receive

    def _process_alive(self, key):
        return self.process_state(key) == 'alive'

    def process_state(self, key):
        with self._map_lock:
            c = self._conversations.get(key)
        if c is None:
            reason = self.failed_processes.get(key,{}).get('reason')
            if reason == 'process_not_started':return 'not_started'
            return 'exited' if reason else 'unknown'
        return 'alive' if c.process.poll() is None else 'exited'

    def close_trial(self, trial_id):
        if trial_id in self.held_processes and self._process_alive(trial_id):
            raise RuntimeError('Held live process requires explicit reconciliation')
        return super().close_trial(trial_id)

    def close(self):
        if self.held_processes:
            raise RuntimeError('Held processes require reconciliation before transport closure')
        return super().close()

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
        if not callable(self.before_send):
            key = trial.get('trial_id')
            with self._map_lock:
                if key and key not in self._conversations and session_id is None and turn == 1:
                    self.failed_processes[key] = {'reason':'process_not_started','type':'MissingSendGate'}
            raise RuntimeError('A stop and storage gate is required before sending')
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
                try:
                    c = native._Conversation(self._command(trial, system_path), subject, directory, signature)
                except Exception as exc:
                    self.failed_processes[key] = {'reason':'process_not_started','type':type(exc).__name__}
                    raise ProcessExited('Process could not start') from exc
                c.completed_turn_ids = []
                self._install_queue(c, key)
                self._conversations[key] = c
        if not c.lock.acquire(blocking=False):
            raise RuntimeError('Concurrent turns on same thread')
        try:
            if c.closed or c.signature != signature or c.thread_id != session_id:
                raise ValueError('Thread or frozen configuration mismatch')
            if c.last_turn is not None and turn != c.last_turn + 1:
                raise ValueError('Turn sequence mismatch')
            retry_count = 0
            retry_journal = directory/f'turn-{turn:02d}-retries.journal.jsonl'
            for attempt_number in count(1):
                if self.before_send:
                    self.before_send()
                attempt = directory/f'turn-{turn:02d}-attempt-{attempt_number:02d}'
                attempt.mkdir(exist_ok=False)
                _fsync_directory(directory)
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
                    status = {'ok':result['ok'],'retryable':can_retry,'turn':turn,
                              'attempt':attempt_number,'http_status':observed_error_code(result)}
                    self.attempt_statuses.append(status)
                    self.attempt_counts['attempts'] += 1
                    self.attempt_counts['success' if result['ok'] else 'error'] += 1
                    if can_retry:self.attempt_counts['requeued'] += 1
                    if status['http_status'] == 429:self.attempt_counts['rpc_429'] += 1
                if can_retry:
                    self._rollback(c, attempt, tid, c.completed_turn_ids, time.monotonic()+self.timeout)
                    retry = {'attempt':attempt_number,'turn_id':tid,
                             'raw_files':[{'path':str(p),'sha256':native.digest(p)} for p in sorted(attempt.iterdir()) if p.is_file()]}
                    # Durable before the next send, even if the controlling
                    # process crashes while another retry is in flight.
                    append_event(retry_journal, retry)
                    if retry_count == 0:
                        _fsync_directory(directory)
                    retry_count += 1
                    continue
                c.last_turn = turn
                if result['ok']:
                    c.completed_turn_ids.append(tid)
                else:
                    # A live process with scientifically unsafe or unverified
                    # output is preserved for inspection, not discarded.
                    self.held_processes[key] = {'reason':'unrecoverable_or_unsafe_turn'}
                result.update(session_id=c.thread_id,app_server_turn_id=tid,process_pid=c.process.pid,
                    command=c.command,stderr=stderr,exit_code=0,timeout=False,
                    duration_seconds=time.monotonic()-started,startup_notices=0,
                    metadata_fallback='fallback metadata' in stderr.lower(),malformed_event_lines=0,
                    provider_schema=effective,retry_count=retry_count,
                    raw_files=[{'path':str(p),'sha256':native.digest(p)} for p in
                               [system_path,*([directory/'model-catalog.json'] if self.catalog_path else []),
                                *([retry_journal] if retry_journal.exists() else []),
                                *sorted(p for p in attempt.iterdir() if p.is_file())]])
                return result
        except Exception as exc:
            exit_code = c.process.poll()
            if exit_code is not None or isinstance(exc, ProcessExited):
                self.failed_processes[key] = {'reason':'process_exited','exit_code':exit_code}
                c.close()
            else:
                self.held_processes[key] = {'reason':'live_process_unresolved','type':type(exc).__name__}
            try:
                exc.transport_diagnostics = c.consume_stderr()
            except (OSError,ValueError) as diagnostic_error:
                exc.transport_diagnostics = 'Diagnostics unavailable: '+type(diagnostic_error).__name__
            raise
        finally:
            c.lock.release()
