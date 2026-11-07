"""Offline protocol invariants; no subject inference or network calls."""
import copy
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import unittest

from exp7_pre.protocol import PreProtocol
from .protocol import (
    ARMS, FORMATS, GAMES, KO_SCHEMA_SYSTEM, MainProtocol, validate_trial,
    make_probe_policies, phase, total_turns, operate_step, probe_policies,
)


def example(arm='en_schema', game='seq', frame='cards', **updates):
    forced = game in ('obj', 'seq')
    trial = dict(trial_id='main-example', run_id='offline-main', model='fake',
                 effort='low', frame=frame, arm=arm,
                 format='en_schema' if arm == 'R_A' else arm,
                 game=game, kind=game if forced else 'unforced',
                 stage_rule=None if forced else game, order=list('ABCD'),
                 targets=list('ACBDBADCAB') if game == 'seq' else ['A']*10 if game == 'obj' else [],
                 n_rounds=10, probe_arm='explanation',
                 probe_policies=make_probe_policies(list('ABCD'), 20261107))
    trial.update(updates)
    return trial


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = MainProtocol()

    def test_every_format_game_frame_renders_all_turns(self):
        for arm, game, frame in itertools.product(ARMS, GAMES, ('cards', 'cats')):
            trial = example(arm, game, frame)
            original = copy.deepcopy(trial)
            self.assertTrue(validate_trial(trial))
            rounds = []
            for r in range(1, 11):
                remaining = list('ABCD')
                feedback = None
                for local in (1, 2, 3):
                    turn = (r-1)*3+local
                    text = self.protocol.prompt(trial, turn, feedback, remaining, rounds)
                    self.assertTrue(text)
                    schema = self.protocol.schema(turn, remaining, frame, trial)
                    self.assertEqual(schema is None, trial['format'].endswith('_natural'))
                    if arm == 'ko_natural':
                        self.assertNotIn('JSON', text)
                    if local < 3:
                        selected = remaining[:2] if local == 1 else remaining[:1]
                        remaining, feedback = operate_step(trial, r, local, remaining, selected)
                rounds.append({'remaining': remaining, 'final': remaining[0]})
            for turn in range(31, 35):
                text = self.protocol.prompt(trial, turn, rounds=rounds)
                self.assertTrue(text)
                if arm == 'ko_natural':
                    self.assertNotIn('JSON', text)
            self.assertEqual(total_turns(trial), 34)
            self.assertEqual(trial, original)

    def test_historical_english_schema_and_natural_stimuli_unchanged(self):
        old = PreProtocol()
        for main_arm, pre_arm in [('en_schema', 'A'), ('en_natural', 'F'), ('ko_schema', 'K')]:
            for frame in ('cards', 'cats'):
                trial = example(main_arm, 'seq', frame)
                prior = {**trial, 'arm': pre_arm}
                for r in range(1, 11):
                    for local, feedback, remaining in [(1, None, list('ABCD')), (2, 'K', list('AB')), (2, 'D', list('CD')), (3, 'K', ['A']), (3, 'D', ['B'])]:
                        turn = (r-1)*3+local
                        self.assertEqual(self.protocol.prompt(trial, turn, feedback, remaining), old.prompt(prior, turn, feedback, remaining))
        self.assertEqual(self.protocol.system(example('ko_schema')), KO_SCHEMA_SYSTEM)
        self.assertEqual(self.protocol.system(example('en_schema')), old.system({**example(), 'arm': 'A'}))
        self.assertNotIn('JSON', self.protocol.system(example('ko_natural')))

    def test_r_is_a_matched_and_only_mid_rating_differs(self):
        for game, frame in itertools.product(GAMES, ('cards', 'cats')):
            a = example('en_schema', game, frame)
            r = example('R_A', game, frame)
            self.assertEqual(self.protocol.system(a), self.protocol.system(r))
            for turn in range(1, 35):
                round_no, local = phase(a, turn)
                remaining = list('ABCD') if local == 1 else list('AB') if local == 2 else ['A']
                rounds = [{'remaining':['A'], 'final':'A'} for _ in range(10)]
                a_text = self.protocol.prompt(a, turn, 'K', remaining, rounds)
                r_text = self.protocol.prompt(r, turn, 'K', remaining, rounds)
                a_schema = self.protocol.schema(turn, remaining, frame, a)
                r_schema = self.protocol.schema(turn, remaining, frame, r)
                if local == 3 and round_no < 10:
                    self.assertNotEqual(a_text, r_text)
                    self.assertNotIn('How much', r_text)
                    self.assertNotIn('counterfactual', r_text)
                    self.assertEqual(r_schema['required'], ['ack'])
                else:
                    self.assertEqual(a_text, r_text)
                    self.assertEqual(a_schema, r_schema)

    def test_invalid_crossed_assignments_rejected_before_render(self):
        invalid = [example(order=list('BACD')), example(n_rounds=40),
                   example('R_A', format='ko_schema'), example('en_schema', measurement='round10_only'),
                   example('en_natural', format='en_schema'), example('en_schema', 'seq', targets=['A']*10),
                   example('en_schema', 'KK', targets=['A']*10), example('en_schema', 'obj', stage_rule='KK')]
        for trial in invalid:
            with self.assertRaises(ValueError):
                self.protocol.prompt(trial, 1)

    def test_forcing_and_fixed_rules_all_valid_choices(self):
        for target in 'ABCD':
            trial = example('en_schema', 'obj', targets=[target]*10)
            for first in itertools.combinations('ABCD', 2):
                remaining, _ = operate_step(trial, 1, 1, list('ABCD'), list(first))
                for second in remaining:
                    final, _ = operate_step(trial, 1, 2, remaining, [second])
                    self.assertEqual(final, [target])
        for game in ('KK', 'KD', 'DK', 'DD'):
            trial = example('en_schema', game)
            outcomes = set()
            for first in itertools.combinations('ABCD', 2):
                remaining, a1 = operate_step(trial, 1, 1, list('ABCD'), list(first))
                for second in remaining:
                    final, a2 = operate_step(trial, 1, 2, remaining, [second])
                    self.assertEqual(a1+a2, game)
                    outcomes.add(final[0])
            self.assertEqual(outcomes, set('ABCD'))

    def test_probe_question_independent_of_hidden_target(self):
        for arm in ARMS:
            base = example(arm, 'obj')
            prompts = [self.protocol.prompt({**base, 'targets':[target]*10}, 32) for target in 'ABCD']
            self.assertEqual(len(set(prompts)), 1)
            patterns = {tuple(p['gold']['first_feedback'] for p in probe_policies({**base, 'targets':[target]*10})) for target in 'ABCD'}
            self.assertGreater(len(patterns), 1)

    def test_korean_natural_choices_and_ratings_conservative(self):
        trial = example('ko_natural')
        self.assertEqual(self.protocol.parse_response('스페이드 에이스, 클럽 에이스', 1, trial=trial)['selection'], ['A','B'])
        for text in ['나는 스페이드 에이스, 클럽 에이스를 고릅니다', '스페이드 에이스, 스페이드 에이스']:
            with self.assertRaises(ValueError):
                self.protocol.parse_response(text, 1, trial=trial)
        result = self.protocol.parse_response('자유도: 100\n영향력: 1\n반사실: 아니요', 3, trial=trial)
        self.assertEqual((result['freedom'], result['impact'], result['counterfactual']), (100,1,'no'))
        self.assertTrue(result['_parse']['format_compliant'])
        result = self.protocol.parse_response('**자유도:** **100**\n**영향력:** **1**\n**반사실:** **예**', 3, trial=trial)
        self.assertEqual((result['freedom'], result['impact'], result['counterfactual']), (100,1,'yes'))
        result = self.protocol.parse_response('자유도: 모름\n영향력: 1\n영향력: 100\n반사실: 예 또는 아니요', 3, trial=trial)
        self.assertIsNone(result['freedom'])
        self.assertIsNone(result['impact'])
        self.assertIsNone(result['counterfactual'])
        self.assertEqual(result['_parse']['fields']['impact'], 'ambiguous')
        self.assertEqual(result['_parse']['fields']['counterfactual'], 'ambiguous')

    def test_korean_natural_predictions_preserve_missing_and_uncertainty(self):
        trial = example('ko_natural')
        text = ('선택 방식 1: 첫 피드백 = 유지; 둘째 피드백 = 불확실; 최종 = 스페이드 에이스\n'
                '선택 방식 2: 첫 피드백 = 제거; 둘째 피드백 = 유지; 최종 = 불확실\n'
                '선택 방식 3: 첫 피드백 = 유지; 첫 피드백 = 제거; 최종 = 스페이드 에이스')
        result = self.protocol.parse_response(text, 32, trial=trial)
        self.assertEqual(result['policy_1'], {'first_feedback':'keep_selected', 'second_feedback':'uncertain', 'final':'A'})
        self.assertEqual(result['policy_2']['final'], 'uncertain')
        self.assertEqual(result['_parse']['fields']['policy_3.first_feedback'], 'ambiguous')
        self.assertIsNone(result['policy_4']['final'])
        self.assertEqual(result['_parse']['fields']['policy_4.final'], 'unparseable')

    def test_json_when_natural_requested_keeps_noncompliance(self):
        trial = example('ko_natural')
        result = self.protocol.parse_response(json.dumps({'freedom':100,'impact':1,'counterfactual':'no'}), 3, trial=trial)
        self.assertEqual(result['impact'], 1)
        self.assertFalse(result['_parse']['format_compliant'])
        result = self.protocol.parse_response('{"impact":1,"impact":100,"counterfactual":"no"}', 3, trial=trial)
        self.assertIsNone(result['impact'])

    def test_shared_instance_has_no_cross_format_mutation(self):
        trials = [example(arm) for arm in ARMS]
        expected = [self.protocol.prompt(t, 3, 'K', ['A']) for t in trials]
        with ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(lambda i: self.protocol.prompt(trials[i % len(trials)],3,'K',['A']), range(100)))
        self.assertEqual(outputs, [expected[i % len(trials)] for i in range(100)])


if __name__ == '__main__':
    unittest.main()
