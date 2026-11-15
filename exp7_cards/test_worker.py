"""Offline tests of the card-specific operational adapter."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import itertools
import unittest
from unittest.mock import patch

from exp7_pre.runner import CallBudget
from .protocol import CardProtocol
from .runner import run_trial
from .schedule import MODELS, build, load_bundle, save
from .test_preparation import FakeTransport
from .worker import GatedTransport, calibration_trials, execute_job, owned_job, report_job_progress
from .coordination import GitCoordinator, card_readme, new_board


class _Gate:
    def __init__(self):
        self.stopped = threading.Event()
        self.coordinator = self
        self.reason = None
    def check(self):
        if self.stopped.is_set():
            raise RuntimeError('stopped')
    def observe(self, response):
        pass
    def set_stop(self, status, reason):
        self.reason = reason


class _Transport:
    name = 'fake'
    def __init__(self, result):
        self.result = result
    def request(self, *args, **kwargs):
        return self.result


class CardWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, cls.trials = build()

    def test_card_allocation_load_and_technical_scope(self):
        with tempfile.TemporaryDirectory() as d:
            save(d)
            plan = load_bundle(d)
            self.assertEqual((len(plan['trials']), len(plan['jobs'])), (8400, 280))
            for model in MODELS:
                technical = calibration_trials(plan['trials'], model)
                self.assertEqual([t['effort'] for t in technical], ['low', 'medium', 'high'])
                self.assertTrue(all(t['cohort'] == 'technical_calibration' and
                                    t['split'] == 'calibration' and t['frame'] == 'cards'
                                    for t in technical))
                self.assertTrue(all(t['trial_id'] not in {r['trial_id'] for r in plan['trials']}
                                    for t in technical))

    def test_real_card_runner_accepts_noncanonical_order(self):
        t = next(t for t in self.trials if t['order'] != list('ABCD') and t['kind'] == 'seq')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            transport = FakeTransport()
            state = run_trial(t, CardProtocol(), transport, p/'state.json', p/'native',
                              CallBudget(p/'budget.json', 'fixture', 34), 'a'*64)
            self.assertEqual(state['status'], 'complete')
            self.assertEqual([x['final'] for x in state['rounds']], t['targets'])
            self.assertEqual(len(transport.calls), 34)

    def test_pacing_required_and_compaction_stops(self):
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ', {'EXP7_CARDS_SHARED_RATE_FILE': str(Path(d)/'pace')}):
            gate = _Gate()
            transport = GatedTransport(_Transport({'ok': True, 'compaction_events': 1}), gate)
            result = transport.request()
            self.assertTrue(result['ok'])
            self.assertTrue(gate.stopped.is_set())
            self.assertIn('compaction', gate.reason)

    def test_progress_counts_unstarted_without_guessing(self):
        board = {'jobs': {'job-1': {'status': 'running', 'call_cap': 102}}}
        class Coordinator:
            def _mutate(self, label, fn): fn(board); return board
            def _job(self, board, model, owner, token, job, claim, allow_stop=False):
                return board['jobs'][job]
        bound = {'model': 'm', 'owner': 'o', 'model_token': 'x'}
        job = {'job_id': 'job-1', 'claim_token': 'y', 'n_trials': 3}
        report_job_progress(Coordinator(), bound, job, {'one': {'status': 'complete'}}, 34)
        self.assertEqual(board['jobs']['job-1']['counts'],
                         {'complete': 1, 'failed': 0, 'interrupted': 0, 'unstarted': 2})
        self.assertEqual(board['jobs']['job-1']['calls'], 34)

    def test_dashboard_shows_initial_and_technical_counts(self):
        job = {'job_id': 'job-1', 'model': 'example', 'trial_ids': ['one'],
               'n_trials': 1, 'call_cap': 34, 'stage': 'initial-50'}
        board = new_board('test-run', 'a'*64, 'b'*40, [job])
        board['models']['example']['technical_progress'] = {'finished': 2, 'failed': False}
        text = card_readme(board)
        self.assertIn('배정 1개', text)
        self.assertIn('| example | 2 / 3 |', text)

    def test_full_offline_coordinator_and_card_job(self):
        trial = next(t for t in self.trials if t['order'] != list('ABCD'))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            remote = p/'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            job = {'job_id': 'job-1', 'model': trial['model'], 'trial_ids': [trial['trial_id']],
                   'n_trials': 1, 'call_cap': 34, 'stage': 'initial-50'}
            board = new_board('test-run', 'a'*64, 'b'*40, [job], global_stop=False, global_max_concurrency=1)
            coordinator = GitCoordinator(str(remote), 'test-board', p/'cache')
            coordinator.bootstrap(board)
            token = coordinator.claim_model(trial['model'], 'test-owner', concurrency=1)
            bound = {'model': trial['model'], 'owner': 'test-owner', 'model_token': token, 'concurrency': 1}
            claimed = owned_job(coordinator, bound, p/'work')
            increments = itertools.count(100, 2)
            with patch('exp7_cards.worker.make_transport', return_value=FakeTransport()), \
                 patch('exp7_cards.worker.time.monotonic', side_effect=lambda: next(increments)), \
                 patch.dict('os.environ', {'EXP7_CARDS_SHARED_RATE_FILE': str(p/'pace')}):
                result = execute_job(claimed, bound, coordinator, {trial['trial_id']: trial},
                                     p/'work', 'c'*64, 300, transport_kind='persistent')
            self.assertEqual(result['counts']['complete'], 1)
            self.assertEqual(result['calls'], 34)
            row = coordinator.status()['jobs']['job-1']
            self.assertEqual((row['counts']['complete'], row['calls']), (1, 34))


if __name__ == '__main__':
    unittest.main()
