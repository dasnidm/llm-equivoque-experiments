"""Offline integration checks for a full main conversation and no replay."""
import json
from pathlib import Path
import tempfile
import unittest

from .protocol import MainProtocol, phase, operate_step, probe_policies
from .runner import CallBudget, atomic_json, run_trial
from .test_protocol import example


class FakeTransport:
    name = 'offline-main-fixture'

    def __init__(self, protocol, fail_at=None, raise_at=None, changed_at=None, invalid_at=None):
        self.protocol = protocol
        self.calls = []
        self.remaining = list('ABCD')
        self.fail_at, self.raise_at = fail_at, raise_at
        self.changed_at, self.invalid_at = changed_at, invalid_at

    def request(self, trial, prompt, schema, system, session_id, directory, turn):
        self.calls.append({'turn':turn, 'session_id_before':session_id, 'schema':schema})
        if turn == self.raise_at:
            raise RuntimeError('Uncertain request result')
        r, local = phase(trial, turn)
        names = self.protocol.choice_names(trial['frame'], trial)
        natural = trial['format'].endswith('_natural')
        korean = trial['format'] == 'ko_natural'
        if local == 1:
            self.remaining = list('ABCD')
            selected = self.remaining[:2]
            answer = [names[x] for x in selected]
            self.remaining, _ = operate_step(trial, r, local, self.remaining, selected)
            text = ', '.join(answer) if natural else json.dumps({'selection':answer}, ensure_ascii=False)
        elif local == 2:
            selected = self.remaining[:1]
            answer = names[selected[0]]
            self.remaining, _ = operate_step(trial, r, local, self.remaining, selected)
            text = answer if natural else json.dumps({'selection':answer}, ensure_ascii=False)
        elif local == 3 and trial['arm'] == 'R_A' and r < 10:
            text = '{"ack":"ok"}'
        elif local in (3, 6, 7):
            text = ('자유도: 100\n영향력: 1\n반사실: 아니요' if korean
                    else 'Freedom: 100\nImpact: 1\nCounterfactual: no' if natural
                    else '{"freedom":100,"impact":1,"counterfactual":"no"}')
        elif local == 4:
            key = 'rule' if trial['probe_arm'] == 'explanation' else 'acknowledgment'
            text = '판단하기 부족합니다.' if korean else 'Insufficient information.'
            if not natural:
                text = json.dumps({key:text}, ensure_ascii=False)
        else:
            gold = [p['gold'] for p in probe_policies(trial)]
            if not natural:
                text = json.dumps({f'policy_{i}':{**row,'final':names[row['final']]} for i,row in enumerate(gold,1)},ensure_ascii=False)
            elif korean:
                words = {'keep_selected':'유지','discard_selected':'제거'}
                text = '\n'.join(f'선택 방식 {i}: 첫 피드백 = {words[row["first_feedback"]]}; 둘째 피드백 = {words[row["second_feedback"]]}; 최종 = {names[row["final"]]}' for i,row in enumerate(gold,1))
            else:
                text = '\n'.join(f'Policy {i}: first_feedback = {row["first_feedback"]}; second_feedback = {row["second_feedback"]}; final = {names[row["final"]]}' for i,row in enumerate(gold,1))
        if turn == self.invalid_at:
            text = 'ambiguous choice'
        return {'ok':turn != self.fail_at, 'text':text,
                'session_id':'changed' if turn == self.changed_at else 'offline-session-'+trial['trial_id'],
                'events':[], 'stderr':'', 'raw_files':[]}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.protocol = MainProtocol()
        self.freeze = 'a'*64

    def run_case(self, trial, transport, limit=34):
        return run_trial(trial, self.protocol, transport, self.root/(trial['trial_id']+'.json'),
                         self.root/'scratch', CallBudget(self.root/(trial['trial_id']+'-budget.json'),'main-test',limit), self.freeze)

    def test_full_conversations_preserve_assignment_and_all_measurements(self):
        for arm in ('en_schema','en_natural','ko_schema','ko_natural','R_A'):
            for game in ('obj','seq','KK','KD','DK','DD'):
                trial = example(arm, game, trial_id=arm+'-'+game)
                transport = FakeTransport(self.protocol)
                state = self.run_case(trial, transport)
                self.assertEqual(state['status'], 'complete', state.get('error'))
                self.assertEqual(len(state['turns']), 34)
                self.assertEqual(state['trial'], trial)
                self.assertIsNone(transport.calls[0]['session_id_before'])
                self.assertTrue(all(c['session_id_before'] == state['session_id'] for c in transport.calls[1:]))
                self.assertEqual(state['turns'][29]['parsed']['counterfactual'], 'no')
                self.assertEqual(state['turns'][31]['parsed']['_parse']['status'], 'valid')
                self.assertEqual(state['turns'][33]['parsed']['impact'], 1)
                if arm == 'R_A':
                    self.assertTrue(all(state['turns'][3*r+2]['parsed'].get('ack') == 'ok' for r in range(9)))
                    self.assertTrue(all('impact' not in state['turns'][3*r+2]['parsed'] for r in range(9)))
                if game in ('obj','seq'):
                    self.assertEqual([r['final'] for r in state['rounds']], trial['targets'])
                else:
                    self.assertEqual([r['route'] for r in state['rounds']], [game]*10)
                self.run_case(trial, transport)
                self.assertEqual(len(transport.calls), 34)

    def test_invalid_trial_cannot_consume_calls(self):
        trial = example(order=list('BACD'))
        transport = FakeTransport(self.protocol)
        with self.assertRaises(ValueError):
            self.run_case(trial, transport)
        self.assertEqual(transport.calls, [])
        self.assertFalse((self.root/'main-example-budget.json').exists())

    def test_uncertain_call_and_terminal_failure_never_replayed(self):
        for key, option, status in [('uncertain','raise_at','interrupted'),('transport','fail_at','failed'),('session','changed_at','failed'),('choice','invalid_at','failed')]:
            trial = example(trial_id=key)
            transport = FakeTransport(self.protocol, **{option:2})
            state = self.run_case(trial, transport)
            self.assertEqual(state['status'], status)
            self.run_case(trial, transport)
            self.assertEqual(len(transport.calls), 2)
            if option == 'raise_at':
                self.assertEqual(state['pending_turn']['turn'], 2)

    def test_budget_and_freeze_guard_before_new_calls(self):
        trial = example()
        transport = FakeTransport(self.protocol)
        state = self.run_case(trial, transport, limit=2)
        self.assertEqual(state['status'], 'budget_exhausted')
        self.assertEqual(len(transport.calls), 2)
        with self.assertRaises(ValueError):
            run_trial(trial,self.protocol,transport,self.root/'main-example.json',self.root/'scratch',
                      CallBudget(self.root/'main-example-budget.json','main-test',2),'b'*64)
        self.assertEqual(len(transport.calls),2)


if __name__ == '__main__':
    unittest.main()
