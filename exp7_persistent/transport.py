"""Keep one Codex app-server process and thread for an entire trial.

Each trial owns its process, so a failed/uncertain turn cannot affect another
trial's connection. No wrapper retries, automatic process replacement, or
replay occur. Wire JSON-RPC and derived events are stored separately.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import tomllib

from equivoque.transport import overrides, provider_schema
from exp7_pre.transport import digest, subject_directory, HOST_DISABLED_NOTICE

SUPPORTED_CLI_VERSION = 'codex-cli 0.159.0-alpha.3'


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as out:
        out.write(value)
        out.flush()
        os.fsync(out.fileno())


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def isolation_preflight(subject):
    """Standalone app-server cannot express exec's ignore-config/rules flags.

    Refuse nonempty user/project configuration instead of silently inheriting
    it. The OS administrator's configuration still applies, as it does to exec.
    Existing authentication and native histories stay in their original home.
    """
    native_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    roots = {native_home, *(p / '.codex' for p in [Path(subject), *Path(subject).parents])}
    for root in sorted(roots):
        config = root / 'config.toml'
        if config.exists() and tomllib.loads(config.read_text()):
            raise ValueError(f'Persistent transport requires an empty user/project config: {config}')
        rules = root / 'rules'
        if rules.exists() and any(p.is_file() for p in rules.rglob('*')):
            raise ValueError(f'Persistent transport cannot ignore user/project rules: {rules}')


def _usage(value):
    keys = {'inputTokens': 'input_tokens', 'cachedInputTokens': 'cached_input_tokens',
            'cacheWriteInputTokens': 'cache_write_input_tokens', 'outputTokens': 'output_tokens',
            'reasoningOutputTokens': 'reasoning_output_tokens'}
    return {dst: value.get(src, 0) for src, dst in keys.items()}


def validate_startup(messages, thread_id):
    """Reject unknown startup errors rather than losing them at the turn boundary."""
    for message in messages:
        method, params = message.get('method', ''), message.get('params', {})
        if method in ('error', 'warning', 'configWarning', 'guardianWarning'):
            notice = params.get('message') or params.get('error', {}).get('message')
            if notice != HOST_DISABLED_NOTICE:
                raise ValueError('Unrecognized app-server startup diagnostic: ' + str(notice))
        if method in ('model/rerouted', 'thread/compacted', 'item/started', 'item/completed'):
            raise ValueError('Unexpected app-server startup model/item event')
        if method == 'thread/started' and params.get('thread', {}).get('id') != thread_id:
            raise ValueError('Unexpected thread during startup')


def normalize_turn(messages, thread_id, turn_id):
    """Deterministically derive runner fields from an original RPC trace.

    This is an adapter, never a claim that derived exec-style events are native
    exec output. The matching original trace is always retained and hashed.
    """
    events = [{'type': 'thread.started', 'thread_id': thread_id}, {'type': 'turn.started'}]
    items, completed, errors, violations = {}, [], [], []
    token_usage = None
    recovery = 0
    compactions = 0
    https_fallback = False
    for message in messages:
        method, p = message.get('method', ''), message.get('params', {})
        if not isinstance(p, dict):
            violations.append('Malformed notification parameters')
            continue
        scoped = {'thread/tokenUsage/updated', 'item/completed', 'item/started', 'turn/completed', 'error'}
        if method in scoped and p.get('threadId') != thread_id:
            violations.append('Missing or unexpected thread ID')
            continue
        if p.get('threadId') not in (None, thread_id):
            violations.append('Unexpected thread ID')
            continue
        event_turn = p.get('turnId') or (p.get('turn') or {}).get('id')
        if event_turn is not None and event_turn != turn_id:
            violations.append('Unexpected turn ID')
            continue
        if 'id' in message and 'method' in message:
            violations.append('Unexpected server request (tools/approval/auth)')
        if method == 'thread/tokenUsage/updated':
            token_usage = p.get('tokenUsage')
        elif method == 'item/completed':
            item = p.get('item', {})
            if not item.get('id') or item['id'] in items:
                violations.append('Missing or duplicate completed item ID')
            else:
                items[item['id']] = item
        elif method == 'item/started':
            if p.get('item', {}).get('type') not in ('agentMessage', 'reasoning', 'userMessage'):
                violations.append('Forbidden item started')
        elif method == 'turn/completed':
            completed.append(p.get('turn', {}))
        elif method == 'error':
            error = p.get('error', {})
            errors.append({'message': error.get('message', str(error)),
                           'will_retry': p.get('willRetry', False),
                           'details': error})
            if p.get('willRetry'):
                recovery += 1
        elif method == 'thread/compacted':
            compactions += 1
        elif method == 'model/rerouted':
            violations.append('Provider changed the frozen model')
        elif method in ('warning', 'configWarning', 'guardianWarning'):
            text = p.get('message', '')
            if text == HOST_DISABLED_NOTICE:
                continue
            if str(text).startswith('Falling back from WebSockets to HTTPS transport.'):
                https_fallback = True
                recovery += 1
            else:
                violations.append('Unrecognized server warning: ' + str(text))
    terminal = completed[-1] if len(completed) == 1 else {}
    if len(completed) != 1 or terminal.get('status') != 'completed':
        violations.append('Missing, duplicated, or unsuccessful terminal turn')
    # Terminal items may be a partial view. Verify any copies against the item
    # notifications; never invent a second answer from both representations.
    for item in terminal.get('items', []):
        if item.get('id') not in items or items[item['id']] != item:
            violations.append('Terminal item disagrees with completed-item stream')
    forbidden = [i for i in items.values() if i.get('type') not in ('userMessage', 'reasoning', 'agentMessage')]
    answers = [i.get('text', '') for i in items.values() if i.get('type') == 'agentMessage']
    if len(answers) != 1:
        violations.append('Expected exactly one assistant response')
    if forbidden:
        violations.append('Subject used a forbidden tool/item')
    if any(not e['will_retry'] for e in errors):
        violations.append('Unrecovered server error')
    if not isinstance(token_usage, dict) or not all(isinstance(token_usage.get(k), dict) for k in ('total', 'last')):
        violations.append('Missing usage evidence')
        token_usage = {'total': {}, 'last': {}}
    for item in items.values():
        if item.get('type') == 'userMessage':
            continue
        adapted = dict(item)
        adapted['type'] = {'agentMessage': 'agent_message'}.get(item.get('type'), item.get('type'))
        events.append({'type': 'item.completed', 'item': adapted})
    for error in errors:
        events.append({'type': 'error', **error})
    if terminal.get('error'):
        violations.append('Terminal turn contains an error')
        events.append({'type': 'error', 'message': str(terminal['error'])})
    ok = not violations
    events.append({'type': 'turn.completed' if ok else 'turn.failed',
                   'usage': _usage(token_usage['total']), 'violations': violations})
    return {'ok': ok, 'events': events, 'text': answers[-1] if answers else '',
            'usage': _usage(token_usage['total']), 'usage_last': _usage(token_usage['last']),
            'tool_events': len(forbidden), 'compaction_events': compactions,
            'recovered_transport_events': recovery, 'https_fallback': https_fallback,
            'protocol_violations': violations}


class _Conversation:
    def __init__(self, command, subject, directory, signature):
        self.command, self.subject, self.directory = command, subject, directory
        self.signature = signature
        self.thread_id = None
        self.last_turn = None
        self.lock = threading.Lock()
        self.next_id = 0
        self.closed = False
        self.stderr_consumed = 0
        self.final_files = None
        self.queue = queue.Queue()
        self.stderr_path = directory / 'process.stderr.log'
        self.stderr_file = self.stderr_path.open('xb')
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr_file, cwd=subject, start_new_session=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for raw in self.process.stdout:
                self.queue.put(raw)
        finally:
            self.queue.put(None)

    def send(self, message, sent):
        raw = (_json(message) + '\n').encode()
        sent.write(raw); sent.flush(); os.fsync(sent.fileno())
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def receive(self, deadline, received, messages):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('App-server response deadline exceeded; no replay')
        try:
            raw = self.queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError('App-server response deadline exceeded; no replay') from exc
        if raw is None:
            raise RuntimeError('App-server exited before completion; no replay')
        received.write(raw); received.flush(); os.fsync(received.fileno())
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError('Malformed app-server message')
        messages.append(message)
        # Never approve or execute a server-originated request from a subject.
        if 'method' in message and 'id' in message:
            raise RuntimeError('Unexpected server request; tool/auth interaction denied')
        return message

    def rpc(self, method, params, deadline, sent, received, messages):
        self.next_id += 1
        request_id = self.next_id
        self.send({'id': request_id, 'method': method, 'params': params}, sent)
        while True:
            message = self.receive(deadline, received, messages)
            if message.get('id') == request_id:
                if 'error' in message:
                    raise RuntimeError('App-server RPC error: ' + _json(message['error']))
                if 'result' not in message:
                    raise ValueError('Missing app-server RPC result')
                return message['result']
            if 'id' in message:
                raise ValueError('Unexpected app-server response ID')

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.stderr_file.close()

    def consume_stderr(self):
        data = self.stderr_path.read_bytes()
        tail = data[self.stderr_consumed:].decode('utf-8', errors='replace')
        self.stderr_consumed = len(data)
        return tail


class PersistentTransport:
    name = 'codex-app-server-persistent-v1'

    def __init__(self, timeout=300, codex_binary='codex', min_start_interval=0.0, catalog_path=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        if not math.isfinite(min_start_interval) or min_start_interval < 0:
            raise ValueError('request interval must be finite and nonnegative')
        self.timeout, self.codex_binary = timeout, str(codex_binary)
        self.min_start_interval = min_start_interval
        self.catalog_path = Path(catalog_path).resolve() if catalog_path else None
        self.catalog_sha256 = digest(self.catalog_path) if self.catalog_path else None
        self._conversations, self._map_lock = {}, threading.Lock()
        self._start_lock, self._next_start = threading.Lock(), 0.0
        self._closed = False
        self._cli_verified = False
        self.before_send = None
        self.after_close = None

    def _command(self, trial, system_path):
        if not self._cli_verified:
            version = subprocess.check_output([self.codex_binary, '--version'], text=True, timeout=10).strip()
            if version != SUPPORTED_CLI_VERSION:
                raise ValueError(f'Persistent protocol requires {SUPPORTED_CLI_VERSION}; found {version}')
            self._cli_verified = True
        command = [self.codex_binary, 'app-server', '--stdio']
        command += overrides(system_path, trial['effort'])
        if self.catalog_path:
            if digest(self.catalog_path) != self.catalog_sha256:
                raise ValueError('Frozen model catalog changed')
            snapshot = system_path.parent / 'model-catalog.json'
            if not snapshot.exists():
                _write(snapshot, self.catalog_path.read_text())
            if digest(snapshot) != self.catalog_sha256:
                raise ValueError('Conversation model catalog differs from frozen snapshot')
            command += ['-c', 'model_catalog_json=' + json.dumps(str(snapshot))]
        return command

    def _pace(self):
        with self._start_lock:
            delay = max(0.0, self._next_start - time.monotonic())
            if delay:
                time.sleep(delay)
            self._next_start = time.monotonic() + self.min_start_interval

    def request(self, trial, prompt, schema, system, session_id, directory, turn):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        subject = subject_directory(directory)
        subject.mkdir(parents=True, exist_ok=True)
        os.chmod(subject, 0o700)
        system_path = directory / 'subject-system.txt'
        if system_path.exists():
            if system_path.read_text() != system:
                raise ValueError('A session cannot change its system instruction')
        else:
            _write(system_path, system)
        attempt = directory / f'turn-{turn:02d}'
        attempt.mkdir(exist_ok=False)
        _write(attempt / 'prompt.txt', prompt)
        effective = provider_schema(schema) if schema is not None else None
        if effective is not None:
            _write(attempt / 'schema.json', _json(effective) + '\n')
        key = trial['trial_id']
        signature = (str(directory), trial['model'], trial['effort'], digest(system_path))
        with self._map_lock:
            if self._closed:
                raise RuntimeError('Transport closed')
            conversation = self._conversations.get(key)
            if conversation is None:
                # A prior process log means this process would be an implicit
                # retry/restart. Migration of old partial trials is deliberate,
                # not performed by this fresh-trial transport.
                if session_id is not None or turn != 1:
                    raise ValueError('Persistent transport requires a fresh trial; no automatic resume/replay')
                isolation_preflight(subject)
                self._pace()
                if self.before_send:
                    self.before_send()
                conversation = _Conversation(self._command(trial, system_path), subject, directory, signature)
                self._conversations[key] = conversation
        if not conversation.lock.acquire(blocking=False):
            raise RuntimeError('Concurrent turns on the same trial are forbidden')
        try:
            if conversation.closed or conversation.signature != signature:
                raise ValueError('Conversation closed or frozen inputs changed')
            if conversation.thread_id != session_id or (conversation.last_turn is not None and turn != conversation.last_turn + 1):
                raise ValueError('Thread/turn sequence mismatch; no replay')
            self._pace()
            if self.before_send:
                self.before_send()
            started = time.monotonic()
            deadline = started + self.timeout
            messages = []
            with (attempt / 'rpc-sent.jsonl').open('xb') as sent, (attempt / 'rpc-received.jsonl').open('xb') as received:
                if conversation.thread_id is None:
                    conversation.rpc('initialize', {'clientInfo': {'name': 'codex_exec', 'version': '0.159.0-alpha.3'},
                                     'capabilities': {'experimentalApi': True}}, deadline, sent, received, messages)
                    conversation.send({'method': 'initialized'}, sent)
                    config = {k: json.loads(v) for k, v in (entry.split('=', 1) for entry in overrides(system_path, trial['effort'])[1::2])}
                    result = conversation.rpc('thread/start', {
                        'model': trial['model'], 'cwd': str(subject), 'approvalPolicy': 'never',
                        'sandbox': 'read-only', 'ephemeral': False, 'historyMode': 'paginated',
                        'allowProviderModelFallback': False, 'dynamicTools': [], 'config': config,
                    }, deadline, sent, received, messages)
                    if (result.get('model') != trial['model'] or result.get('reasoningEffort') != trial['effort']
                            or result.get('cwd') != str(subject) or result.get('approvalPolicy') != 'never'
                            or result.get('sandbox', {}).get('type') != 'readOnly'
                            or result.get('instructionSources')):
                        raise ValueError('App-server effective model/instructions/permissions differ from trial')
                    conversation.thread_id = result['thread']['id']
                    validate_startup(messages, conversation.thread_id)
                # Exclude startup notifications from turn normalization; preserve
                # every startup byte in this first turn's original RPC file.
                turn_begin = len(messages)
                if self.before_send:
                    self.before_send()
                response = conversation.rpc('turn/start', {
                    'threadId': conversation.thread_id, 'turnTrigger': 'exec',
                    'input': [{'type': 'text', 'text': prompt, 'text_elements': []}],
                    'cwd': str(subject), 'approvalPolicy': 'never', 'effort': trial['effort'],
                    'outputSchema': effective,
                }, deadline, sent, received, messages)
                turn_id = response['turn']['id']
                while not any(m.get('method') == 'turn/completed' and m.get('params', {}).get('threadId') == conversation.thread_id
                              and m.get('params', {}).get('turn', {}).get('id') == turn_id for m in messages[turn_begin:]):
                    conversation.receive(deadline, received, messages)
            result = normalize_turn(messages[turn_begin:], conversation.thread_id, turn_id)
            stderr = conversation.consume_stderr()
            _write(attempt / 'stderr.txt', stderr)
            if 'fallback metadata' in stderr.lower():
                result['ok'] = False
                result['protocol_violations'].append('Fallback model metadata')
            _write(attempt / 'events.jsonl', ''.join(_json(e) + '\n' for e in result['events']))
            _write(attempt / 'adapter.json', _json({'transport': self.name, 'process_pid': conversation.process.pid,
                   'thread_id': conversation.thread_id, 'turn_id': turn_id, 'command': conversation.command,
                   'normalization_start_index': turn_begin, 'catalog_sha256': self.catalog_sha256,
                   'events_are_derived': True}) + '\n')
            conversation.last_turn = turn
            result.update(session_id=conversation.thread_id, app_server_turn_id=turn_id,
                          process_pid=conversation.process.pid, command=conversation.command,
                          stderr=stderr, exit_code=0, timeout=False, duration_seconds=time.monotonic()-started,
                          startup_notices=0, metadata_fallback='fallback metadata' in stderr.lower(),
                          malformed_event_lines=0, provider_schema=effective,
                          raw_files=[{'path': str(p), 'sha256': digest(p)} for p in
                                     [system_path, *([directory/'model-catalog.json'] if self.catalog_path else []), *sorted(attempt.iterdir())]])
            if not result['ok']:
                conversation.close()
            return result
        except Exception as exc:
            # The runner retains its pending checkpoint and hashes emitted files.
            # Do not fabricate a failed response or replay a possibly sent turn.
            conversation.close()
            # Keep native details in private evidence and expose them to the
            # worker gate without adding them to ordinary exception messages.
            exc.transport_diagnostics = conversation.consume_stderr()
            diagnostic_events = [m for m in locals().get('messages', [])
                                 if m.get('method') in ('error', 'warning', 'configWarning')]
            exc.transport_diagnostics += '\n' + _json(diagnostic_events)
            raise
        finally:
            conversation.lock.release()

    def close_trial(self, trial_id):
        with self._map_lock:
            conversation = self._conversations.pop(trial_id, None)
        if conversation is not None:
            with conversation.lock:
                conversation.close()
                tail = conversation.consume_stderr()
                if conversation.final_files is None:
                    close_path = conversation.directory / 'close-diagnostics.json'
                    _write(close_path, _json({'transport': self.name, 'process_pid': conversation.process.pid,
                           'process_exit_code': conversation.process.returncode, 'stderr_tail': tail}) + '\n')
                    conversation.final_files = [{'path': str(p), 'sha256': digest(p)}
                                                for p in (conversation.stderr_path, close_path)]
                if tail and self.after_close:
                    self.after_close({'ok': True, 'stderr': tail, 'events': []})
                return conversation.final_files
        return []

    def close(self):
        with self._map_lock:
            self._closed = True
            keys = list(self._conversations)
        for key in keys:
            self.close_trial(key)
