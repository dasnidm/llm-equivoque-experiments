"""Meaningful offline integrity and parser checks; no model calls."""
import copy
import itertools
import json
import unittest

from exp7_pre.protocol import (ARMS, PreProtocol, choice_branches,
    make_probe_policies, operate_step, phase, probe_policies, total_turns, validate_trial)
from sequence_replication.protocol import SequenceProtocol


def example(arm='J', kind='seq', rule='KK'):
    order = list('ABCD')
    return {'trial_id':'test','arm':arm,'kind':kind,'frame':'cards','n_rounds':10,
            'order':order,'targets':list('ABCDABCDAB') if kind=='seq' else ['A']*10,
            'stage_rule':rule,'probe_policies':make_probe_policies(order,20261030),
            'probe_arm':'explanation','prompt_variant':'p1'}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.p=PreProtocol()

    def test_exhaustive_forced_and_unforced_paths(self):
        for order in itertools.permutations('ABCD'):
            for target in 'ABCD':
                t=example(kind='obj');t['order']=list(order);t['targets']=[target]*10
                branches=choice_branches(t)
                self.assertEqual(len(branches),12)
                self.assertEqual({b['final'] for b in branches},{target})
            for rule in ('KK','KD','DK','DD'):
                t=example(kind='unforced',rule=rule);t['order']=list(order)
                branches=choice_branches(t)
                self.assertEqual({b['route'] for b in branches},{rule})
                self.assertEqual({b['final'] for b in branches},set('ABCD'))

    def test_original_first_thirty_prompts_and_schemas(self):
        historical=SequenceProtocol()
        for frame in ('cards','cats'):
            t=example('A');t['frame']=frame
            self.assertEqual(self.p.system(t),historical.data['system'])
            for r in range(1,11):
                remaining=list(t['order']);feedback=None
                for local in (1,2,3):
                    turn=(r-1)*3+local
                    self.assertEqual(self.p.prompt(t,turn,feedback,remaining),historical.prompt(t,turn,feedback,remaining))
                    self.assertEqual(self.p.schema(turn,remaining,frame,t),historical.schema(turn,remaining,frame,t))
                    if local in (1,2):
                        selection=remaining[:2] if local==1 else remaining[:1]
                        remaining,feedback=operate_step(t,r,local,remaining,selection)

    def test_all_arms_render_thirty_four_turns(self):
        for arm in ARMS:
            for kind in ('obj','seq','unforced'):
                t=example(arm,kind,'KD');validate_trial(t)
                rounds=[]
                for r in range(1,11):
                    remaining=list(t['order']);feedback=None
                    for local in (1,2,3):
                        turn=3*(r-1)+local
                        prompt=self.p.prompt(t,turn,feedback,remaining,rounds)
                        self.assertTrue(prompt)
                        if local in (1,2):
                            remaining,feedback=operate_step(t,r,local,remaining,remaining[:2] if local==1 else remaining[:1])
                    rounds.append({'remaining':remaining})
                for turn in range(31,35):
                    self.assertTrue(self.p.prompt(t,turn,rounds=rounds))
                self.assertEqual(total_turns(t),34)
                self.assertEqual(phase(t,34),(10,7))
                with self.assertRaises(ValueError):phase(t,35)

    def test_probe_text_and_policy_generation_ignore_target(self):
        t=example(kind='obj')
        text=self.p.prompt(t,32)
        for target in 'ABCD':
            u=copy.deepcopy(t);u['targets']=[target]*10
            self.assertEqual(text,self.p.prompt(u,32))
            self.assertEqual(u['probe_policies'],make_probe_policies(u['order'],20261030))
        # Across target assignments the gold is not an ordinal K,K,D,D constant.
        patterns={tuple(p['gold']['first_feedback'] for p in probe_policies({**t,'targets':[target]*10})) for target in 'ABCD'}
        self.assertGreater(len(patterns),1)
        self.assertTrue(all(set(p)=={'first','second_position'} for p in t['probe_policies']))
        u=copy.deepcopy(t);u['probe_policies'][0]['target']='A'
        with self.assertRaises(ValueError):validate_trial(u)

    def test_schema_interventions_are_turn_specific(self):
        for arm in ARMS:
            t=example(arm)
            self.assertEqual(self.p.schema(1,trial=t) is None,arm=='F')
            for turn in (3,30,33,34):
                self.assertEqual(self.p.schema(turn,trial=t) is None,arm in ('JS','N','F'))
            for turn in (31,32):
                self.assertEqual(self.p.schema(turn,trial=t) is None,arm in ('N','F'))
        t=example('R')
        self.assertIn('ack',self.p.schema(3,trial=t)['properties'])
        self.assertIn('impact',self.p.schema(30,trial=t)['properties'])
        self.assertNotIn('How much',self.p.prompt(t,3,'K',['A']))
        self.assertIn('How much',self.p.prompt(t,30,'K',['B']))

    def test_natural_ratings_partial_ambiguous_and_uncertain(self):
        t=example('N')
        v=self.p.parse_response('Freedom: 100\nImpact: 1\nCounterfactual: no',3,trial=t)
        self.assertEqual((v['freedom'],v['impact'],v['counterfactual']),(100,1,'no'))
        self.assertEqual(v['_parse']['status'],'valid')
        v=self.p.parse_response('Freedom: unsure\nImpact: 1\nCounterfactual: no',3,trial=t)
        self.assertIsNone(v['freedom'])
        self.assertEqual((v['impact'],v['counterfactual']),(1,'no'))
        v=self.p.parse_response('Impact: 1\nImpact: 100\nCounterfactual: no',3,trial=t)
        self.assertIsNone(v['impact'])
        self.assertEqual(v['_parse']['fields']['impact'],'ambiguous')
        v=self.p.parse_response('Impact: 101\nCounterfactual: uncertain',3,trial=t)
        self.assertIsNone(v['impact']);self.assertIsNone(v['counterfactual'])
        self.assertEqual(v['_parse']['fields']['counterfactual'],'uncertain')
        v=self.p.parse_response('{"freedom":100,"impact":1,"counterfactual":"no"}',3,trial=t)
        self.assertFalse(v['_parse']['format_compliant'])
        self.assertEqual(v['impact'],1)

    def test_invalid_json_never_invents_ratings(self):
        t=example()
        v=self.p.parse_response('{"impact":1,"impact":100,"counterfactual":"no"}',3,trial=t)
        self.assertIsNone(v['impact'])
        v=self.p.parse_response('{"impact":true,"counterfactual":"no"}',3,trial=t)
        self.assertIsNone(v['impact'])
        v=self.p.parse_response('cannot tell',3,trial=t)
        self.assertEqual(v['_parse']['status'],'unparseable')

    def test_natural_surface_variants_preserve_values_and_ambiguity(self):
        t=example('N')
        for raw in ('**Freedom:** 100\n**Impact:** 1\n**Counterfactual:** no',
                    '**Freedom**: **100**\n**Impact**: **1**\n**Counterfactual**: **no**'):
            v=self.p.parse_response(raw,3,trial=t)
            self.assertEqual((v['freedom'],v['impact'],v['counterfactual']),(100,1,'no'))
        v=self.p.parse_response('**Impact:** 1\nImpact: 100\n**Counterfactual:** yes or no',3,trial=t)
        self.assertIsNone(v['impact']);self.assertIsNone(v['counterfactual'])
        self.assertEqual(v['_parse']['fields']['impact'],'ambiguous')
        self.assertEqual(v['_parse']['fields']['counterfactual'],'ambiguous')
        v=self.p.parse_response('Policy 1: first_feedback = keep_selected; second_feedback = uncertain; final = **Ace of spades**',32,trial=t)
        self.assertEqual(v['policy_1']['final'],'A')
        v=self.p.parse_response('Policy 1: first_feedback = keep_selected; second_feedback = uncertain; final = Ace of spades or Ace of clubs',32,trial=t)
        self.assertIsNone(v['policy_1']['final'])
        self.assertEqual(v['_parse']['fields']['policy_1.final'],'ambiguous')

    def test_natural_choice_normalization_never_extracts_from_prose(self):
        t=example('F')
        for raw in ('Ace of spades, ace of clubs',
                    '**Ace of spades**, **Ace of clubs**',
                    '**Ace of spades, Ace of clubs**'):
            self.assertEqual(self.p.parse_response(raw,1,trial=t)['selection'],['A','B'])
        self.assertEqual(self.p.parse_response('**Ace of spades**',2,['A','B'],trial=t)['selection'],'A')
        for raw in ('Ace of spades, ACE OF SPADES',
                    'I choose Ace of spades, ace of clubs',
                    'Ace of spades, ace of clubs or ace of hearts'):
            with self.assertRaises(ValueError):self.p.parse_response(raw,1,trial=t)
        # Historical schema arms remain strict about the exact enum strings.
        with self.assertRaises(ValueError):
            self.p.parse_response('{"selection":["Ace of spades","ace of clubs"]}',1,trial=example('A'))

    def test_selection_validity(self):
        t=example('F')
        v=self.p.parse_response('ace of spades, ace of clubs',1,trial=t)
        self.assertEqual(v['selection'],['A','B'])
        with self.assertRaises(ValueError):self.p.parse_response('ace of spades, ace of spades',1,trial=t)
        with self.assertRaises(ValueError):self.p.parse_response('ace of diamonds',2,remaining=['A','B'],trial=t)
        t=example('K')
        v=self.p.parse_response('{"selection":["스페이드 에이스","클럽 에이스"]}',1,trial=t)
        self.assertEqual(v['selection'],['A','B'])
        self.assertIn('스페이드 에이스',self.p.schema(1,trial=t)['properties']['selection']['items']['enum'])

    def test_prediction_parser_separates_abstention_and_missing(self):
        t=example('N')
        v=self.p.parse_response('Policy 1: first_feedback = keep_selected; second_feedback = uncertain; final = ace of spades\nPolicy 2: first_feedback = discard_selected; second_feedback = keep_selected; final = uncertain',32,trial=t)
        self.assertEqual(v['policy_1'],{'first_feedback':'keep_selected','second_feedback':'uncertain','final':'A'})
        self.assertEqual(v['policy_2']['final'],'uncertain')
        self.assertIsNone(v['policy_3']['final'])
        self.assertEqual(v['_parse']['fields']['policy_1.second_feedback'],'uncertain')
        self.assertEqual(v['_parse']['fields']['policy_3.final'],'unparseable')
        t=example('K')
        raw={f'policy_{i}':{**p['gold'],'final':self.p.choice_names('cards',t)[p['gold']['final']]} for i,p in enumerate(probe_policies(t),1)}
        v=self.p.parse_response(json.dumps(raw,ensure_ascii=False),32,trial=t)
        self.assertTrue(v['_parse']['schema_valid'])
        for i,p in enumerate(probe_policies(t),1):self.assertEqual(v[f'policy_{i}'],p['gold'])

    def test_neutral_probe_and_disclosure(self):
        for arm in ARMS:
            t=example(arm);t['probe_arm']='neutral'
            self.assertNotIn('Briefly describe any inferred',self.p.prompt(t,31))
            key='acknowledgment'
            self.assertIn(key,self.p.canonical_schema(31,trial=t)['properties'])
            t=example(arm,'unforced','DD')
            disclosure=self.p.disclosure(t)
            self.assertIn('최종 대상은 미리 고정하지 않았습니다' if arm=='K' else 'final object was not fixed in advance',disclosure)


if __name__=='__main__':
    unittest.main()
