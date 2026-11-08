"""Explicit pre-stream capacity retries beneath one persistent CLI turn.

Only a complete HTTP 429 with error.code=turn_rate_limit_exceeded is eligible.
Native retries remain disabled. No retry after a 200, streaming failure,
unknown completion, authentication error, quota error, or process failure.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

from exp7_header_probe import Gate, Relay, header_transport, safe_headers, now


def digest(value):
    return hashlib.sha256(value).hexdigest()


def retry_delay(headers, attempt):
    """Honor server time; fallback is bounded exponential backoff."""
    value = headers.get('retry-after')
    if value is not None:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = None
        if delay is not None and math.isfinite(delay):
            return max(.1, delay)
    try:
        delay = float(headers['retry-after-ms']) / 1000
        if math.isfinite(delay):
            return max(.1, delay)
    except (KeyError, ValueError):
        pass
    return min(60., 2. ** attempt)


class RetryGate(Gate):
    def halt(self, reason):
        with self.lock:
            if self.reason is None:
                self.reason = reason
                with (self.root / 'STOP.json').open('x') as out:
                    json.dump({'at': now(), 'reason': reason,
                               'logical_http_requests_admitted': self.count}, out, indent=2)
            self.stop.set()


class Admission:
    """One shared pacer and cooldown for every attempt, including retries."""
    def __init__(self, root, gate, interval, physical_limit=600, max_seconds=900):
        self.root, self.gate, self.interval = Path(root), gate, interval
        self.physical_limit, self.deadline = physical_limit, time.monotonic() + max_seconds
        self.lock = threading.Lock()
        self.next_start = self.cooldown_until = 0.
        self.count = 0
        self.events = []

    def _record(self, kind, **fields):
        event = {'at': now(), 'monotonic': time.monotonic(), 'kind': kind, **fields}
        self.events.append(event)
        with (self.root / 'admission.jsonl').open('a') as out:
            out.write(json.dumps(event) + '\n'); out.flush(); os.fsync(out.fileno())

    def admit(self, logical_id, attempt):
        while True:
            reason = None
            with self.lock:
                if self.gate.stop.is_set():
                    raise RuntimeError('Retry study STOP active; no send')
                if (self.root / 'HALT').exists() or (self.root.parent / 'HALT').exists():
                    reason = 'Operator HALT; preserve pending without replay'
                elif time.monotonic() >= self.deadline:
                    reason = 'Prespecified stage time budget reached'
                elif self.count >= self.physical_limit:
                    reason = 'Prespecified physical request budget reached'
                if reason is None:
                    delay = max(self.next_start, self.cooldown_until) - time.monotonic()
                    if delay <= 0:
                        self.count += 1
                        self.next_start = time.monotonic() + self.interval
                        self._record('admit', physical_ticket=self.count,
                                     logical_id=logical_id, attempt=attempt)
                        return self.count
            if reason is not None:
                self.gate.halt(reason)
                raise RuntimeError(reason)
            self.gate.stop.wait(min(delay, .1))

    def cooldown(self, delay, logical_id, attempt):
        with self.lock:
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + delay)
            self._record('cooldown', logical_id=logical_id, attempt=attempt,
                         delay_seconds=delay, until_monotonic=self.cooldown_until)


class CapacityRetryClient:
    def __init__(self, root, client, admission, secrets, max_retries=4, max_wait_seconds=240):
        self.root, self.client, self.admission = Path(root), client, admission
        self.secrets, self.max_retries, self.max_wait_seconds = secrets, max_retries, max_wait_seconds
        self.lock = threading.Lock()
        self.logical_count = 0
        self.records = []

    def _record(self, record):
        with self.lock:
            self.records.append(record)
            with (self.root / 'http-attempts.jsonl').open('a') as out:
                out.write(json.dumps(record) + '\n'); out.flush(); os.fsync(out.fileno())

    @contextmanager
    def stream(self, method, url, *, headers, content):
        with self.lock:
            self.logical_count += 1
            logical_id = self.logical_count
        began = time.monotonic()
        body_hash = digest(content)
        # OAuth CLI can compress the HTTP request. Treat its bytes opaquely;
        # parsing or recompressing them is unnecessary and could change a retry.
        encoding = next((v.lower() for k, v in headers.items() if k.lower() == 'content-encoding'), 'identity')
        encoding = encoding if encoding in ('identity', 'gzip', 'zstd', 'deflate', 'br') else 'other'
        for attempt in range(self.max_retries + 1):
            ticket = self.admission.admit(logical_id, attempt)
            started = time.monotonic()
            record = {'ticket': ticket, 'logical_id': logical_id, 'attempt': attempt,
                      'started_at': now(), 'started_monotonic': started,
                      'request_body_sha256': body_hash, 'request_body_bytes': len(content),
                      'request_content_encoding': encoding}
            retry = False
            try:
                with self.client.stream(method, url, headers=headers, content=content) as response:
                    secrets = tuple(self.secrets())
                    record.update(status=response.status_code, headers_at=now(),
                                  headers=safe_headers(response.headers, secrets))
                    if response.status_code >= 300:
                        data = response.read()
                        unsafe = any(secret and secret in data for secret in secrets)
                        if not unsafe:
                            path = self.root / 'http-errors' / f'{ticket:04d}.body'
                            path.parent.mkdir(exist_ok=True)
                            with path.open('xb') as out:
                                out.write(data); out.flush(); os.fsync(out.fileno())
                            record['error_body'] = {'path': path.relative_to(self.root).as_posix(), 'sha256': digest(data)}
                            try:
                                error = json.loads(data).get('error', {})
                                record['error'] = {k: error[k] for k in ('type', 'code', 'message') if k in error}
                            except (ValueError, TypeError):
                                error = {}
                        else:
                            error = {}
                            record['credential_reflection_withheld'] = True
                        eligible = (not unsafe and response.status_code == 429
                                    and isinstance(error, dict)
                                    and error.get('type') == 'rate_limit_error'
                                    and error.get('code') == 'turn_rate_limit_exceeded')
                        record['explicit_capacity_429'] = eligible
                        if eligible and attempt < self.max_retries:
                            delay = retry_delay(response.headers, attempt)
                            # Deterministic jitter affects scheduling, not scientific seeds.
                            jitter = .1 + int(body_hash[:4], 16) / 65535 * .3
                            delay += jitter
                            if time.monotonic() - began + delay <= self.max_wait_seconds:
                                self.admission.cooldown(delay, logical_id, attempt)
                                record.update(retry_scheduled=True, required_delay_seconds=delay)
                                retry = True
                        if not retry:
                            record['retry_scheduled'] = False
                    if not retry:
                        # Yield exactly once: never replay exceptions during SSE consumption.
                        yield response
                        return
            except Exception as exc:
                record['exception_type'] = type(exc).__name__
                self.admission.gate.halt('HTTP/stream completion uncertain; no automatic replay')
                raise
            finally:
                record.update(ended_at=now(), ended_monotonic=time.monotonic(),
                              duration_seconds=time.monotonic() - started)
                self._record(record)
        raise AssertionError('Retry loop exhausted without returning terminal response')

    def close(self):
        self.client.close()


def retry_relay(root, interval, logical_limit, *, upstream=None, offline=False,
                max_retries=4, physical_limit=600, max_seconds=900):
    gate = RetryGate(root, 0, logical_limit)
    kwargs = {'offline': offline}
    if upstream is not None:
        kwargs['upstream'] = upstream
    relay = Relay(root, gate, **kwargs)
    admission = Admission(root, gate, interval, physical_limit, max_seconds)
    client = CapacityRetryClient(root, relay.client, admission,
                                 lambda: tuple(relay._credential_values), max_retries)
    relay.client = client
    return relay, client, admission


def audit_retry_trial(trial, protocol, state_path, freeze, expected_url):
    """Reuse raw RPC/science audit, explicitly validate the new CLI config tail."""
    from exp7_pre.audit import audit_trial as scientific_audit
    from exp7_persistent.audit import audit_turn
    from exp7_header_probe import provider_config, BUNDLE
    from equivoque.transport import overrides
    state = json.loads(Path(state_path).read_text())
    report = scientific_audit(trial, protocol, state_path, freeze)
    errors = report['errors']
    previous = pid = None
    turn_ids = set()
    for index, turn in enumerate(state['turns'], 1):
        result = audit_turn(turn, expected_prompt=turn['prompt'], expected_system=protocol.system(trial),
                            expected_schema=turn['schema'], previous_session_id=previous,
                            expected_pid=pid, expected_trial=None)
        errors.extend(f'Turn {index}: {error}' for error in result['errors'])
        named = {Path(f['path']).name: Path(f['path']) for f in turn['raw_files']}
        expected = [turn['command'][0], 'app-server', '--stdio'] + overrides(named['subject-system.txt'], trial['effort'])
        expected += ['-c', 'model_catalog_json=' + json.dumps(str(named['model-catalog.json']))]
        for key, value in provider_config(expected_url).items():
            expected += ['-c', key + '=' + json.dumps(value)]
        if turn['command'] != expected:
            errors.append(f'Turn {index}: retry-profile command mismatch')
        if digest(named['model-catalog.json'].read_bytes()) != digest((BUNDLE / 'model-catalog.json').read_bytes()):
            errors.append(f'Turn {index}: frozen catalog mismatch')
        sent = [json.loads(line) for line in named['rpc-sent.jsonl'].read_text().splitlines()]
        received = [json.loads(line) for line in named['rpc-received.jsonl'].read_text().splitlines()]
        for message in sent:
            params = message.get('params', {})
            if message.get('method') == 'initialize' and params['clientInfo']['version'] != '0.167.0':
                errors.append('CLI initialize version mismatch')
            if message.get('method') == 'turn/start' and params.get('effort') != trial['effort']:
                errors.append(f'Turn {index}: effort mismatch')
            if message.get('method') == 'thread/start':
                config = {k: json.loads(v) for k, v in
                          (entry.split('=', 1) for entry in overrides(named['subject-system.txt'], trial['effort'])[1::2])}
                ack = next((m.get('result', {}) for m in received if m.get('id') == message['id']), {})
                if (params.get('model') != trial['model'] or params.get('config') != config
                        or ack.get('model') != trial['model'] or ack.get('reasoningEffort') != trial['effort']):
                    errors.append(f'Turn {index}: model/config mismatch')
        if turn.get('app_server_turn_id') in turn_ids:
            errors.append('Provider turn ID reused')
        turn_ids.add(turn.get('app_server_turn_id'))
        previous, pid = turn.get('session_id'), turn.get('process_pid')
    report['integrity_ok'] = not errors
    return report
