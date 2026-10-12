"""Meaningful roster, pairing, replay, audit and prospective analysis checks."""
import collections
import csv
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from equivoque.core import ROOT, branches, read_json, write_json
from experiment7.test_sequence import SimulationTransport
from .protocol import CONFIG, SequenceProtocol, phase, probe_policies
from .schedule import build, development_trial
from .runner import run_trial
from .audit import audit_worker
from .analyze import paired_estimate, export


class ReplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_json(CONFIG)
        cls.protocol = SequenceProtocol()
        cls.cases, cls.assigned = build(cls.config)
        cls.trials = [t for g in cls.assigned.values() for t in g]

    def test_exact_roster_balanced_shards_and_matched_cases(self):
        self.assertEqual((self.cases, self.assigned), build(self.config))
        self.assertEqual(len(self.trials), 2520)
        self.assertEqual(len({t['trial_id'] for t in self.trials}), 2520)
        self.assertEqual(len(self.config['configurations']), 21)
        cells = collections.Counter((t['configuration_id'], t['frame'], t['kind']) for t in self.trials)
        self.assertEqual(len(cells), 84)
        self.assertEqual(set(cells.values()), {30})
        self.assertEqual({len(g) for g in self.assigned.values()}, {252})
        for group in self.assigned.values():
            counts = collections.Counter((t['configuration_id'], t['frame'], t['kind']) for t in group)
            self.assertEqual(len(counts), 84)
            self.assertEqual(set(counts.values()), {3})
        signatures = collections.defaultdict(set)
        for t in self.trials:
            self.assertEqual(len(t['targets']), 10)
            self.assertEqual(t['targets'], [t['order'][p-1] for p in t['positions']])
            signatures[t['case_id'], t['kind']].add(tuple(t['positions']))
        self.assertEqual({len(v) for v in signatures.values()}, {1})
        self.assertEqual(sum(3*t['n_rounds'] + 3 for t in self.trials), 83160)

    def test_target_margins_layout_uniqueness_and_balanced_sequences(self):
        for field in ('target_identity', 'target_position'):
            self.assertEqual(sorted(collections.Counter(c[field] for c in self.cases).values()), [7, 7, 8, 8])
        self.assertEqual(len({(tuple(c['abstract_order']), c['target_identity']) for c in self.cases}), 30)
        for c in self.cases:
            self.assertEqual(sorted(collections.Counter(c['positions']).values()), [2, 2, 3, 3])
            self.assertEqual(c['positions'][0], c['target_position'])
            self.assertEqual(c['abstract_order'][c['target_position']-1], c['target_identity'])
        for i in (100, 210, 211, 212, 213, 300):
            t = development_trial(self.config, i, n_rounds=10)
            self.assertTrue(t['trial_id'].startswith('calibration/'))
            self.assertTrue(t['case_id'].startswith('development-'))

    def test_all_legal_paths_no_early_disclosure_and_card_code_leakage(self):
        representatives = {}
        for t in self.trials:
            representatives.setdefault((t['case_id'], t['frame'], t['kind']), t)
        for t in representatives.values():
            for target in set(t['targets']):
                rows = branches(t['order'], target)
                self.assertEqual(len(rows), 12)
                self.assertEqual({r['final'] for r in rows}, {target})
            for turn in range(1, 34):
                _, local = phase(t, turn)
                text = self.protocol.prompt(t, turn, 'K', t['order'][:2])
                if t['frame'] == 'cards':
                    self.assertIsNone(re.search(r'\b[A-D]\b', text))
                if turn <= 30:
                    self.assertNotIn('predetermined', text)
                    self.assertNotIn('fixed according', text)
                if local in (3, 6):
                    self.assertTrue(text.endswith(self.protocol.data['frames'][t['frame']]['evaluation']))
            self.assertIn('Fixed final objects by round', self.protocol.prompt(t, 33))
            self.assertEqual(len(probe_policies(t)), 4)

    def test_every_setting_frame_schedule_session_simulation(self):
        reps = {}
        for t in self.trials:
            reps.setdefault((t['configuration_id'], t['frame'], t['kind']), t)
        transport = SimulationTransport()
        sessions = set()
        with tempfile.TemporaryDirectory() as tmp:
            for i, t in enumerate(reps.values()):
                path = Path(tmp) / str(i) / 'trials/trial.json'
                state = run_trial(t, self.protocol, transport, path, Path(tmp) / 'scratch')
                self.assertEqual(state['status'], 'complete')
                self.assertEqual(len(state['turns']), 33)
                self.assertEqual({r['remaining'][0] for r in state['rounds']}, set(t['targets']))
                self.assertNotIn(state['session_id'], sessions)
                sessions.add(state['session_id'])
                run_trial(t, self.protocol, transport, path, Path(tmp) / 'scratch')
        self.assertEqual(transport.calls, 84 * 33)

    def test_failed_and_uncertain_turns_are_not_replayed(self):
        t = self.trials[0]
        tr = SimulationTransport(fail_at=11)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trials/t.json'
            state = run_trial(t, self.protocol, tr, path, tmp)
            self.assertEqual(state['status'], 'failed')
            run_trial(t, self.protocol, tr, path, tmp)
            self.assertEqual(tr.calls, 11)
            state.update(status='active', pending_turn={'turn': 12})
            write_json(path, state)
            self.assertEqual(run_trial(t, self.protocol, tr, path, tmp)['status'], 'interrupted')
            self.assertEqual(tr.calls, 11)

    def test_native_file_hash_tampering_is_detected(self):
        t = self.trials[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / 'manifest.json'
            write_json(manifest, {'run_id': self.config['run_id'], 'worker_id': t['worker_id'], 'trials': [t]})
            run_trial(t, self.protocol, SimulationTransport(native=True), root / 'trials/t.json', root / 'scratch')
            self.assertTrue(audit_worker(manifest, root)['integrity_ok'])
            next((root / 'native-raw').glob('*/turn-01.stderr.txt')).write_text('TAMPERED')
            self.assertFalse(audit_worker(manifest, root)['integrity_ok'])

    def test_pairing_missingness_and_sparse_bootstrap_denominators(self):
        ids = [f'case-{i:03d}' for i in range(1, 31)]
        samples = np.random.default_rng(2).integers(0, 30, (2000, 30))
        left, right = {c: 1 for c in ids}, {c: 0 for c in ids}
        result = paired_estimate(left, right, ids, samples)
        self.assertEqual(result['estimate'], 1)
        self.assertEqual(result['ci_low'], 1)
        self.assertEqual(result['paired_cases'], 30)
        result = paired_estimate({c: 1 for c in ids[:7]}, {c: 0 for c in ids[3:10]}, ids, samples)
        self.assertEqual(result['paired_cases'], 4)
        self.assertEqual(result['status'], 'insufficient')
        self.assertIsNone(result['ci_low'])

    def test_analysis_audits_partial_roster_and_excludes_disclosure(self):
        chosen = {}
        first = self.config['configurations'][0]['configuration_id']
        for t in self.trials:
            if t['configuration_id'] == first:
                chosen.setdefault((t['frame'], t['kind']), t)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for w, group in self.assigned.items():
                write_json(root / 'manifests' / self.config['run_id'] / f'worker-{w}.json',
                           {'run_id': self.config['run_id'], 'worker_id': w, 'trials': group})
            for t in chosen.values():
                path = root / 'results' / self.config['run_id'] / f"worker-{t['worker_id']}" / 'trials' / (t['trial_id'].replace('/', '__') + '.json')
                run_trial(t, self.protocol, SimulationTransport(native=True), path, root / 'scratch')
            with patch('sequence_replication.analyze.frozen_hashes', return_value={}):
                result = export(root, root / 'analysis')
            self.assertEqual(result['assigned'], 2520)
            self.assertEqual(result['attempted'], 4)
            self.assertEqual(result['valid_measurements'], 40)
            with (root / 'analysis/tables/trials.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual({r['first_joint'] for r in rows}, {'4'})
            self.assertEqual({r['prediction_matches'] for r in rows}, {'12'})
            self.assertEqual({r['persistent_to_round10'] for r in rows}, {'1'})
            self.assertEqual(len(list((root / 'analysis/figures').glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
