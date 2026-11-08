"""Loopback-only tests, including a real 34-turn CLI recovery conversation."""
from concurrent.futures import ThreadPoolExecutor
import http.server
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

import httpx

from exp7_header_probe import BUNDLE, header_transport
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.runner import run_trial
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.worker import verify_freeze
from exp7_pre.runner import CallBudget
from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper, prompt_texts
from exp7_retry_transport import retry_relay, audit_retry_trial

BINARY = Path(os.environ.get('CODEX_TEST_BINARY', '/workspace/work/exp7-cli-upgrade-20261108/cli-0.167.0/codex'))
CAPACITY = {'error': {'type': 'rate_limit_error', 'code': 'turn_rate_limit_exceeded', 'message': 'Synthetic capacity'}}


class RetryTransportTests(unittest.TestCase):
    def setUp(self):
        import exp7_persistent.transport as native
        self.native_classes = native.PersistentTransport, native._Conversation

    def tearDown(self):
        import exp7_persistent.transport as native
        native.PersistentTransport, native._Conversation = self.native_classes

    @unittest.skipUnless(BINARY.is_file(), 'Set CODEX_TEST_BINARY to the supported CLI 0.167.0')
    def test_full_34_turn_real_cli_retry_preserves_exact_body_and_history(self):
        with tempfile.TemporaryDirectory() as temp, LocalResponses(schema_answers=True) as service:
            root = Path(temp)
            seen, failed_positions = [], set()
            class Handler(service.server.RequestHandlerClass):
                def do_POST(self):
                    data = self.rfile.read(int(self.headers['Content-Length']))
                    body = json.loads(data)
                    seen.append(data)
                    position = len(service.requests)
                    if position in (0, 16) and position not in failed_positions:
                        failed_positions.add(position)
                        payload = json.dumps(CAPACITY).encode()
                        self.send_response(429); self.send_header('Retry-After', '1')
                        self.send_header('Content-Type', 'application/json')
                    else:
                        payload = ''.join('data: ' + json.dumps(event) + '\n\n'
                                          for event in service.events(body, 'https', None)).encode()
                        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers(); self.wfile.write(payload); self.wfile.flush()
            service.server.RequestHandlerClass = Handler
            relay, client, admission = retry_relay(root, 0, 34, upstream=service.base_url, offline=True)
            wrapper_root = root / 'fixture'; wrapper_root.mkdir()
            wrapper = make_cli_wrapper(wrapper_root, BINARY, relay.base_url)
            transport = header_transport(wrapper, relay.base_url)
            templates = load_bundle(BUNDLE)['trials']
            template = next(t for t in templates if t['model'] == 'gpt-6-astra' and t['effort'] == 'medium'
                            and t['arm'] == 'en_schema' and t['frame'] == 'cards' and t['game'] == 'seq')
            trial = {**template, 'trial_id': 'offline-retry-34', 'cohort': 'technical_retry_efficiency'}
            _, freeze = verify_freeze(BUNDLE / 'freeze.json', check_cli=False)
            state_path = root / 'state.json'
            try:
                with relay:
                    run_trial(trial, MainProtocol(), transport, state_path, root / 'native',
                              CallBudget(root / 'budget.json', trial['run_id'], 34), freeze)
            finally:
                transport.close()
            state = json.loads(state_path.read_text())
            self.assertEqual(state['status'], 'complete', state.get('error'))
            self.assertEqual(len(seen), 36)
            self.assertEqual(relay.received_requests, 34)
            self.assertEqual(len(service.requests), 34)
            self.assertEqual(len({t['process_pid'] for t in state['turns']}), 1)
            self.assertEqual(len({t['session_id'] for t in state['turns']}), 1)
            self.assertEqual(sum(t['tool_events'] for t in state['turns']), 0)
            environment = prompt_texts(service.requests[0]['body'])[:-1]
            self.assertEqual(len(environment), 1)
            self.assertTrue(environment[0].startswith('<environment_context>'))
            for index, request in enumerate(service.requests, 1):
                body = request['body']
                self.assertEqual(prompt_texts(body), environment + [t['prompt'] for t in state['turns'][:index]])
                self.assertEqual(body['model'], trial['model'])
                self.assertEqual(body['reasoning']['effort'], trial['effort'])
            groups = {}
            for record in client.records:
                groups.setdefault(record['logical_id'], []).append(record)
            recovered = [group for group in groups.values() if len(group) > 1]
            self.assertEqual(len(recovered), 2)
            for group in recovered:
                self.assertEqual(len({r['request_body_sha256'] for r in group}), 1)
                self.assertEqual(group[0]['status'], 429)
                self.assertEqual(group[1]['status'], 200)
                self.assertGreaterEqual(group[1]['started_monotonic'] - group[0]['ended_monotonic'], .99)
            report = audit_retry_trial(trial, MainProtocol(), state_path, freeze, relay.base_url)
            self.assertTrue(report['integrity_ok'], report['errors'])

    def run_simple(self, responder, *, max_retries=4, token=None, break_stream=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = []
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    data = self.rfile.read(int(self.headers['Content-Length']))
                    calls.append(data)
                    status, body = responder(self, len(calls))
                    payload = json.dumps(body).encode()
                    self.send_response(status); self.send_header('Retry-After', '0.1')
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload) + (100 if break_stream else 0)))
                    self.end_headers(); self.wfile.write(payload); self.wfile.flush()
                    if break_stream:
                        self.close_connection = True
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                relay, client, admission = retry_relay(root, 0, 1,
                    upstream=f'http://127.0.0.1:{server.server_port}', offline=True, max_retries=max_retries)
                with relay:
                    headers = {'Authorization': 'Bearer ' + token} if token else {}
                    if break_stream:
                        with self.assertRaises(httpx.HTTPError):
                            httpx.post(relay.base_url + '/responses', json={}, headers=headers)
                        response = None
                    else:
                        response = httpx.post(relay.base_url + '/responses', json={}, headers=headers)
                if token:
                    for path in root.rglob('*'):
                        if path.is_file(): self.assertNotIn(token.encode(), path.read_bytes())
                    self.assertNotIn(token, response.text)
                return calls, client.records, relay.gate.stop.is_set(), response
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_noncapacity_quota_429_is_not_replayed(self):
        calls, records, stopped, response = self.run_simple(
            lambda h, n: (429, {'error': {'type': 'insufficient_quota', 'code': 'insufficient_quota'}}))
        self.assertEqual(len(calls), 1); self.assertTrue(stopped)
        self.assertEqual(response.status_code, 429)

    def test_partial_200_never_replays_uncertain_completion(self):
        calls, records, stopped, _ = self.run_simple(lambda h, n: (200, {'partial': True}), break_stream=True)
        self.assertEqual(len(calls), 1); self.assertTrue(stopped)
        self.assertIn('exception_type', records[0])

    def test_retry_limit_counts_physical_attempts_and_stops(self):
        calls, records, stopped, response = self.run_simple(lambda h, n: (429, CAPACITY), max_retries=1)
        self.assertEqual(len(calls), 2); self.assertEqual(calls[0], calls[1])
        self.assertTrue(stopped); self.assertEqual(response.status_code, 429)

    def test_reflected_auth_is_neither_retained_nor_retried(self):
        token = 'offline-reflection-retry-test-541206'
        def reflect(handler, number):
            return 429, {'error': {**CAPACITY['error'], 'message': handler.headers['Authorization']}}
        calls, _, stopped, _ = self.run_simple(reflect, token=token)
        self.assertEqual(len(calls), 1); self.assertTrue(stopped)

    def test_shared_cooldown_blocks_all_workers(self):
        from exp7_retry_transport import Admission, RetryGate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); gate = RetryGate(root, 0, 20)
            admission = Admission(root, gate, .005)
            admission.cooldown(.2, 1, 0)
            until = admission.cooldown_until
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(lambda i: admission.admit(i, 0), range(3)))
            self.assertEqual(len(results), 3)
            self.assertTrue(all(row['monotonic'] >= until for row in admission.events if row['kind'] == 'admit'))

    def test_compressed_request_is_retried_without_decode_or_reencode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); received = []
            data = gzip.compress(b'{"input":[{"role":"user","content":"SAME QUESTION"}]}')
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    body = self.rfile.read(int(self.headers['Content-Length']))
                    received.append((body, self.headers.get('Content-Encoding')))
                    payload = json.dumps(CAPACITY if len(received) == 1 else {'ok': True}).encode()
                    self.send_response(429 if len(received) == 1 else 200)
                    self.send_header('Retry-After', '0.1')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers(); self.wfile.write(payload); self.wfile.flush()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                relay, client, _ = retry_relay(root, 0, 1,
                    upstream=f'http://127.0.0.1:{server.server_port}', offline=True)
                with relay:
                    response = httpx.post(relay.base_url + '/responses', content=data,
                                          headers={'Content-Encoding': 'gzip', 'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(received, [(data, 'gzip'), (data, 'gzip')])
                self.assertEqual(len(client.records), 2)
                self.assertFalse(relay.gate.stop.is_set())
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_shared_queue_preserves_arrival_order_under_contention(self):
        from exp7_retry_transport import Admission, RetryGate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); gate = RetryGate(root, 0, 50)
            admission = Admission(root, gate, .005)
            admission.cooldown(.2, 0, 0)
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(lambda i: admission.admit(i, 0), range(10)))
            enqueued = [row['logical_id'] for row in admission.events if row['kind'] == 'enqueue']
            admitted = [row['logical_id'] for row in admission.events if row['kind'] == 'admit']
            self.assertEqual(admitted, enqueued)
            self.assertEqual(len(results), 10)
            self.assertFalse(admission.queue)

    def test_stopped_waiter_leaves_no_queue_entry_or_physical_attempt(self):
        from exp7_retry_transport import Admission, RetryGate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); gate = RetryGate(root, 0, 2)
            admission = Admission(root, gate, 0)
            gate.halt('Synthetic existing STOP')
            with self.assertRaises(RuntimeError): admission.admit(1, 0)
            self.assertFalse(admission.queue)
            self.assertEqual(admission.count, 0)

    @unittest.skipUnless(BINARY.is_file(), 'Set CODEX_TEST_BINARY to the supported CLI 0.167.0')
    def test_HTTP_tail_failure_after_complete_SSE_does_not_replay_or_STOP(self):
        with tempfile.TemporaryDirectory() as temp, LocalResponses() as service:
            root = Path(temp)
            class Handler(service.server.RequestHandlerClass):
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    payload = ''.join('data: ' + json.dumps(event) + '\n\n'
                                      for event in service.events(body, 'https', None)).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(payload) + 100))
                    self.end_headers(); self.wfile.write(payload); self.wfile.flush()
                    self.close_connection = True
            service.server.RequestHandlerClass = Handler
            relay, client, _ = retry_relay(root, 0, 1, upstream=service.base_url, offline=True)
            fixture = root / 'fixture'; fixture.mkdir()
            wrapper = make_cli_wrapper(fixture, BINARY, relay.base_url)
            transport = header_transport(wrapper, relay.base_url)
            try:
                with relay:
                    result = transport.request({'trial_id': 'offline-complete-tail', 'model': 'gpt-6-astra', 'effort': 'medium'},
                                               'Reply exactly OK.', None, 'Synthetic close check.', None, root / 'native', 1)
            finally:
                transport.close()
            self.assertTrue(result['ok'], result.get('protocol_violations'))
            self.assertEqual(result['text'], 'ACK1')
            self.assertEqual(len(service.requests), 1)
            self.assertEqual(len(client.records), 1)
            self.assertTrue(client.records[0]['post_completion_close_handled_without_replay'])
            self.assertFalse(relay.gate.stop.is_set())


if __name__ == '__main__': unittest.main()
