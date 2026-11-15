"""Real CLI over a loopback-only fake model service; no live inference."""
import os
from pathlib import Path
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import unittest

from exp7_persistent.audit import audit_trial
from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
from exp7_pre.runner import CallBudget
from .fast_transport import FastPersistentTransport
from .protocol import CardProtocol
from .runner import run_trial
from .schedule import build


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'set CODEX_TEST_BINARY and EXP7_TEST_CATALOG for loopback CLI test')
class FastRealCliTests(unittest.TestCase):
    def test_complete_34_turns_with_existing_rpc_audit(self):
        _, trials = build()
        trial = next(t for t in trials if t['model'] == 'gpt-6-astra' and t['effort'] == 'high' and t['game'] == 'seq')
        with tempfile.TemporaryDirectory() as d, LocalResponses(schema_answers=True) as service:
            root = Path(d)
            wrapper = make_cli_wrapper(root, os.environ['CODEX_TEST_BINARY'], service.base_url)
            transport = FastPersistentTransport(pace_path=root/'pace', target_rpm=1000,
                                                timeout=30, codex_binary=str(wrapper),
                                                catalog_path=os.environ['EXP7_TEST_CATALOG'])
            transport.before_send = lambda: None
            transport.stop_requested = lambda: False
            try:
                state = run_trial(trial, CardProtocol(), transport, root/'state.json', root/'native',
                                  CallBudget(root/'budget.json', 'fixture', 34), 'a'*64)
                self.assertEqual(state['status'], 'complete', state.get('error'))
                self.assertEqual(len(service.requests), 34)
                self.assertEqual(len({t['session_id'] for t in state['turns']}), 1)
                self.assertEqual(len({t['process_pid'] for t in state['turns']}), 1)
                audited = audit_trial(trial, CardProtocol(), root/'state.json', 'a'*64)
                self.assertTrue(audited['integrity_ok'], audited['errors'])
                exposed = [item for request in service.warmups for item in request['body'].get('input', [])
                           if item.get('type') == 'additional_tools' and item.get('tools')]
                if os.environ.get('EXP7_EXPECT_NO_TOOLS') == '1':
                    self.assertFalse(exposed, 'no-tool catalogue unexpectedly advertised tools')
                else:
                    self.assertTrue(exposed, 'reassess the known legacy tool exposure')
            finally:
                transport.close()

    def test_independent_conversations_are_not_serialized(self):
        class SlowResponses(LocalResponses):
            def __init__(self):
                super().__init__()
                self.arrivals, self.completions = [], []
            def events(self, body, transport, connection_id):
                if body.get('generate') is not False:
                    self.arrivals.append(time.monotonic())
                    time.sleep(1.0)
                    self.completions.append(time.monotonic())
                return super().events(body, transport, connection_id)
        with tempfile.TemporaryDirectory() as d, SlowResponses() as service:
            root = Path(d)
            wrapper = make_cli_wrapper(root, os.environ['CODEX_TEST_BINARY'], service.base_url)
            transport = FastPersistentTransport(pace_path=root/'pace', target_rpm=1000,
                                                timeout=30, codex_binary=str(wrapper),
                                                catalog_path=os.environ['EXP7_TEST_CATALOG'])
            transport.before_send = lambda: None
            transport.stop_requested = lambda: False
            barrier = threading.Barrier(2)
            def request(i):
                barrier.wait(timeout=10)
                t = {'trial_id': f'parallel-{i}', 'model': 'gpt-6-astra', 'effort': 'high'}
                return transport.request(t, 'Synthetic question.', None, 'Synthetic system.', None, root/f'native-{i}', 1)
            try:
                # Initialize the fixture's shared SQLite home before opening
                # app-servers concurrently; otherwise first-run DB creation
                # races and tests a fixture startup failure, not pacing.
                warm_trial = {'trial_id': 'db-warmup', 'model': 'gpt-6-astra', 'effort': 'high'}
                warm = transport.request(warm_trial, 'Initialize fixture.', None, 'Synthetic system.', None,
                                         root/'native-warmup', 1)
                self.assertTrue(warm['ok'])
                transport.close_trial(warm_trial['trial_id'])
                service.arrivals.clear();service.completions.clear()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(request, range(2)))
                self.assertTrue(all(r['ok'] for r in results))
                self.assertEqual(len(service.arrivals), 2)
                self.assertLess(service.arrivals[1], service.completions[0])
            finally:
                transport.close()


if __name__ == '__main__':
    unittest.main()
