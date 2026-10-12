"""Operational admission tests; no live inference or evaluation files."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from expanded import Admission, ControlledProtocol, ControlledTransport, PauseBeforeRequest, ROOT, config
from equivoque.core import read_json, write_json
from sequence_replication.protocol import SequenceProtocol
from sequence_replication.schedule import build
from sequence_replication.runner import run_trial
from sequence_replication.audit import audit_worker
from experiment7.test_sequence import SimulationTransport


class NoopAdmission:
    def __init__(self, block_at=None):
        self.held = False
        self.admitted = {}
        self.block_at = block_at
    def acquire(self, trial, turn):
        if turn == self.block_at:
            raise PauseBeforeRequest('SIMULATION ONLY')
        self.held = True
    def release(self):
        self.held = False


class ExpandedTests(unittest.TestCase):
    def test_every_prompt_and_schema_is_byte_identical(self):
        cases, shards = build(config)
        representatives = {}
        for group in shards.values():
            for t in group:
                representatives.setdefault((t['case_id'], t['frame'], t['kind']), t)
        base, controlled = SequenceProtocol(), ControlledProtocol(NoopAdmission())
        for t in representatives.values():
            for turn in range(1, 34):
                self.assertEqual(base.prompt(t, turn, 'K', t['order'][:2]),
                                 controlled.prompt(t, turn, 'K', t['order'][:2]))
                self.assertEqual(base.schema(turn, t['order'][:2], t['frame'], t),
                                 controlled.schema(turn, t['order'][:2], t['frame'], t))

    def test_request_slots_are_bounded_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_json(directory / 'requests.json', {'queue': [], 'active': []})
            write_json(directory / 'limit.json', {'limit': 5})
            maximum = [0]
            lock = threading.Lock()
            def execute(i):
                lease = Admission(directory, 'simulation-' + str(i)); lease.pid = 1000+i
                for turn in range(1, 4):
                    lease.acquire({'trial_id': 'simulation-' + str(i)}, turn)
                    n = len(read_json(directory / 'requests.json')['active'])
                    with lock: maximum[0] = max(maximum[0], n)
                    time.sleep(.03)
                    lease.release()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(execute, range(8)))
            self.assertLessEqual(maximum[0], 5)
            self.assertGreater(maximum[0], 1)
            self.assertEqual(read_json(directory / 'requests.json'), {'queue': [], 'active': []})

    def test_pause_precedes_checkpoint_and_resume_never_replays(self):
        trial = next(iter(build(config)[1].values()))[0]
        lease = NoopAdmission(block_at=3)
        protocol = ControlledProtocol(lease)
        transport = ControlledTransport(protocol, lease)
        transport.inner = SimulationTransport(native=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'trials/trial.json'
            with self.assertRaises(PauseBeforeRequest):
                run_trial(trial, protocol, transport, path, root / 'scratch')
            state = read_json(path)
            self.assertEqual(len(state['turns']), 2)
            self.assertIsNone(state['pending_turn'])
            self.assertEqual(transport.inner.calls, 2)
            lease.block_at = None
            state = run_trial(trial, protocol, transport, path, root / 'scratch')
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(transport.inner.calls, 33)
            self.assertFalse(lease.held)
            manifest = root / 'manifest.json'
            write_json(manifest, {'run_id': config['run_id'], 'worker_id': trial['worker_id'], 'trials': [trial]})
            self.assertTrue(audit_worker(manifest, root)['integrity_ok'])


if __name__ == '__main__':
    unittest.main()
