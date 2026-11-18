"""Offline protocol, allocation and endpoint checks; no model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from exp7_cards.protocol import CardProtocol
from exp7_cards.test_preparation import FakeTransport
from exp7_pre.runner import CallBudget, run_trial
from .features import risk_rows
from .protocol import ZeroCardProtocol
from .schedule import audit, build


class ZeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, cls.trials = build()
        cls.trial = cls.trials[0]

    def test_allocation_is_a_new_run(self):
        self.assertEqual(audit(self.meta, self.trials)['trials'], 8400)
        self.assertTrue(all(t['trial_id'].startswith('z0-') for t in self.trials))
        self.assertFalse(self.meta['ready_for_live_collection'])

    def test_prompts_and_schemas_at_all_measurements(self):
        p = ZeroCardProtocol()
        for turn in list(range(3, 31, 3)) + [33, 34]:
            prompt = p.prompt(self.trial, turn, 'K', ['A'])
            self.assertIn('0 = no freedom', prompt)
            self.assertIn('0 = no effect', prompt)
            self.assertIn('100 = extreme impact', prompt)
            self.assertNotIn('Reply as JSON', prompt)
            self.assertNotIn('Your chosen card', prompt)
            schema = p.schema(turn, ['A'], 'cards', self.trial)
            for key in ('freedom', 'impact'):
                self.assertEqual((schema['properties'][key]['minimum'],
                                  schema['properties'][key]['maximum']), (0, 100))
        old = CardProtocol().schema(3, ['A'], 'cards', self.trial)
        self.assertEqual(old['properties']['impact']['minimum'], 1)

    def test_card_fields_and_game_prompt(self):
        p = ZeroCardProtocol()
        for turn, remaining, key in ((1, self.trial['order'], 'cards'),
                                     (2, self.trial['order'][:2], 'card')):
            schema = p.schema(turn, remaining, 'cards', self.trial)
            self.assertEqual(schema['required'], [key])
            self.assertNotIn('selection', schema['properties'])
            prompt = p.prompt(self.trial, turn, 'K' if turn == 2 else None, remaining)
            self.assertNotIn('selection', prompt.lower())
            self.assertNotIn('JSON', prompt)
        names = p.base.choice_names('cards', {**self.trial, 'arm': 'A'})
        pair = [names[x] for x in self.trial['order'][:2]]
        parsed = p.parse_response(json.dumps({'cards': pair}), 1,
                                  self.trial['order'], 'cards', self.trial)
        self.assertEqual(parsed['selection'], self.trial['order'][:2])
        for invalid in ({'selection': pair}, {'cards': [pair[0], pair[0]]}):
            with self.assertRaises(ValueError):
                p.parse_response(json.dumps(invalid), 1, self.trial['order'], 'cards', self.trial)
        for arm in ('explanation', 'neutral'):
            prompt = p.prompt({**self.trial, 'probe_arm': arm}, 31, None, ['A'])
            self.assertNotIn('JSON', prompt)
        self.assertNotIn('JSON', p.prompt(self.trial, 32, None, ['A']))
        disclosed = p.prompt(self.trial, 34, None, ['A'])
        self.assertIn('| First tap |', disclosed)
        self.assertNotIn('keep_selected', disclosed)

    def test_parser_zero_boundaries_and_invalids(self):
        p = ZeroCardProtocol()
        for turn in (3, 33, 34):
            for n in (0, 1, 100):
                parsed = p.parse_response(json.dumps({'freedom': n, 'impact': n,
                                                      'counterfactual': 'no'}),
                                          turn, ['A'], 'cards', self.trial)
                self.assertEqual((parsed['freedom'], parsed['impact']), (n, n))
                self.assertTrue(parsed['_parse']['schema_valid'])
                self.assertEqual(parsed['_parse']['status'], 'valid')
            for n in (-1, 101, True, 0.0):
                parsed = p.parse_response(json.dumps({'freedom': n, 'impact': n,
                                                      'counterfactual': 'no'}),
                                          turn, ['A'], 'cards', self.trial)
                self.assertIsNone(parsed['impact'])
                self.assertFalse(parsed['_parse']['schema_valid'])

    def test_both_games_finish_all_turns_with_zero_scores(self):
        for game in ('obj', 'seq'):
            trial = next(t for t in self.trials if t['game'] == game)
            with tempfile.TemporaryDirectory() as d:
                p = Path(d)
                transport = FakeTransport()
                state = run_trial(trial, ZeroCardProtocol(), transport, p/'state.json',
                                  p/'scratch', CallBudget(p/'budget.json', 'offline', 34), 'a'*64)
                self.assertEqual(state['status'], 'complete', state.get('error'))
                self.assertEqual(transport.calls, list(range(1, 35)))
                self.assertEqual([r['final'] for r in state['rounds']], trial['targets'])
                self.assertEqual(state['turns'][2]['parsed']['impact'], 0)
                rows, reason = risk_rows(state)
                self.assertEqual(len(rows), 10)
                self.assertEqual(reason, 'ten_rounds_observed')
                state = copy.deepcopy(state)
                state['turns'][2]['parsed']['counterfactual'] = 'no'
                rows, reason = risk_rows(state)
                self.assertEqual(len(rows), 1)
                self.assertEqual(reason, 'first_joint_report')


if __name__ == '__main__':
    unittest.main()
