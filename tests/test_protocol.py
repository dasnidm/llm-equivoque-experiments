import collections
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from equivoque.audit import audit_worker
from equivoque.core import ROOT, Protocol, branches, digest, parse_response
from equivoque.core import read_json, write_json
from equivoque.runner import run_trial
from equivoque.schedule import build


class FakeTransport:
    name = 'simulation-only'

    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def request(self, trial, prompt, schema, session_id, directory, attempt):
        self.calls += 1
        session_id = session_id or str(uuid.uuid4())
        if attempt == self.fail_at:
            return {'ok': False, 'session_id': session_id, 'text': '',
                    'events': [], 'tool_events': [], 'usage': None}
        if attempt == 1:
            answer = {'selection': ['A', 'B']}
        elif attempt == 2:
            answer = {'selection': schema['properties']['selection']['enum'][0]}
        else:
            answer = {'freedom': 95, 'impact': 75 if attempt == 3 else 1,
                      'counterfactual': 'yes' if attempt == 3 else 'no'}
        return {'ok': True, 'session_id': session_id,
                'text': json.dumps(answer), 'events': [], 'tool_events': [],
                'duration_seconds': 0.0, 'usage': {'input_tokens': 0, 'output_tokens': 0}}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = Protocol()
        self.config = read_json(ROOT / 'protocol/run.v1.json')

    def test_all_orders_targets_and_prompts(self):
        checked = 0
        for order in itertools.permutations('ABCD'):
            for target in order:
                rows = branches(order, target)
                self.assertEqual(len(rows), 12)
                for frame in ('cards', 'cats'):
                    trial = {'frame': frame, 'order': list(order), 'target': target}
                    table = self.protocol.table(trial)
                    self.assertEqual(len(table.splitlines()), 14)
                    for row in rows:
                        self.assertEqual(row['final'], target)
                        for turn in (1, 2, 3, 4):
                            feedback = row['route'][0 if turn == 2 else 1]
                            prompt = self.protocol.prompt(trial, turn, feedback, row['remaining'])
                            self.assertNotIn('{final_object}', prompt)
                            self.assertNotIn('happily', prompt)
                            if turn < 4:
                                self.assertNotIn('was fixed', prompt)
                            if turn > 2:
                                self.assertTrue(prompt.endswith(
                                    self.protocol.data['frames'][frame]['evaluation']))
                        checked += 1
        self.assertEqual(checked, 2304)

    def test_exact_balanced_disjoint_assignment(self):
        cases, assigned = build(self.config)
        self.assertEqual((cases, assigned), build(self.config))
        self.assertEqual(len({(c['target'], tuple(c['order'])) for c in cases}), 50)
        for counter in (collections.Counter(c['target'] for c in cases),
                        collections.Counter(c['order'].index(c['target']) for c in cases)):
            self.assertEqual(sorted(counter.values()), [12, 12, 13, 13])
        all_ids = set()
        for worker, trials in assigned.items():
            self.assertEqual(len(trials), 300)
            self.assertEqual(collections.Counter(t['frame'] for t in trials),
                             {'cards': 150, 'cats': 150})
            by_config = collections.Counter(t['configuration_id'] for t in trials)
            self.assertEqual(collections.Counter(by_config.values()), {14: 18, 16: 3})
            pairs = collections.defaultdict(list)
            for trial in trials:
                self.assertNotIn(trial['trial_id'], all_ids)
                all_ids.add(trial['trial_id'])
                pairs[(trial['configuration_id'], trial['case_id'])].append(trial)
            for pair in pairs.values():
                self.assertEqual({t['frame'] for t in pair}, {'cards', 'cats'})
                self.assertEqual(pair[0]['order'], pair[1]['order'])
                self.assertEqual(pair[0]['target'], pair[1]['target'])
        self.assertEqual(len(all_ids), 2100)

    def test_invalid_answers_rejected(self):
        for value in ('0', '101', '1.5', 'true'):
            with self.assertRaises(ValueError):
                parse_response('{"freedom":' + value + ',"impact":1,"counterfactual":"no"}', 3)
        with self.assertRaises(ValueError):
            parse_response('{"selection":["A","A"]}', 1)
        with self.assertRaises(ValueError):
            parse_response('{"selection":"A"}', 2, ['C', 'D'])

    def test_full_2100_trial_simulation_and_audits(self):
        # Mock data stay in a temporary directory and are rejected by the
        # ordinary experimental audit. This checks orchestration, not science.
        _, assigned = build(self.config)
        transport = FakeTransport()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for worker, trials in assigned.items():
                manifest = root / f'worker-{worker}.json'
                write_json(manifest, {'worker_id': worker, 'run_id': self.config['run_id'],
                                      'trials': trials})
                directory = root / worker
                for trial in trials:
                    path = directory / 'trials' / (trial['trial_id'].replace('/', '__') + '.json')
                    state = run_trial(trial, self.protocol, transport, path, root / 'scratch')
                    self.assertEqual(state['status'], 'complete')
                    self.assertEqual(len({t['session_id'] for t in state['turns']}), 1)
                    self.assertEqual(state['remaining'], [trial['target']])
                report = audit_worker(manifest, directory, allow_simulation=True)
                self.assertTrue(report['integrity_ok'], report['errors'][:2])
                self.assertEqual(report['counts']['complete'], 300)
                self.assertEqual(report['subject_invocations'], 1200)
                self.assertEqual(len(report['session_ids']), 300)
                before = transport.calls
                run_trial(trials[0], self.protocol, transport,
                    directory / 'trials' / (trials[0]['trial_id'].replace('/', '__') + '.json'),
                    root / 'scratch')
                self.assertEqual(transport.calls, before)
            self.assertEqual(transport.calls, 8400)
            self.assertFalse(audit_worker(manifest, directory)['integrity_ok'])

    def test_failures_and_uncertain_resume_not_replayed(self):
        _, assigned = build(self.config)
        trial = assigned['a'][0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'trial.json'
            transport = FakeTransport(fail_at=4)
            state = run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(state['status'], 'failed')
            self.assertIn('parsed', state['turns'][2])
            run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(transport.calls, 4)
            state['status'] = 'active'
            state['pending_turn'] = {'turn': 4}
            write_json(path, state)
            state = run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(state['status'], 'interrupted')
            self.assertEqual(transport.calls, 4)

    def test_audit_detects_tampered_raw_record(self):
        _, assigned = build(self.config)
        trial = assigned['a'][0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / 'manifest.json'
            write_json(manifest, {'worker_id': 'a', 'run_id': self.config['run_id'],
                                  'trials': [trial]})
            path = root / 'results/trials/trial.json'
            state = run_trial(trial, self.protocol, FakeTransport(), path, root / 'scratch')
            state['turns'][2]['text'] = '{"freedom":95,"impact":99,"counterfactual":"yes"}'
            write_json(path, state)
            report = audit_worker(manifest, root / 'results', allow_simulation=True)
            self.assertFalse(report['integrity_ok'])
            self.assertTrue(any('Raw journal' in e for e in report['errors']))


if __name__ == '__main__':
    unittest.main()
