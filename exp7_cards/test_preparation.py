"""Offline tests only: no model calls and no network access."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from exp7_main.protocol import MainProtocol
from exp7_pre.protocol import phase
from exp7_pre.runner import CallBudget, run_trial
from .protocol import CardProtocol, adapt
from .features import risk_rows
from .context_probe_summary import summarize
from .schedule import audit, audit_jobs, build, make_jobs, save


def example(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    if schema.get('type') == 'object':
        return {k: example(schema['properties'][k]) for k in schema.get('required', [])}
    if schema.get('type') == 'array':
        item = schema['items']
        if 'enum' in item:
            return item['enum'][:schema.get('minItems', 1)]
        return [example(item)] * schema.get('minItems', 1)
    if schema.get('type') == 'integer':
        return schema.get('minimum', 1)
    if schema.get('type') == 'string':
        return 'unsure'
    raise ValueError(f'Unknown schema: {schema}')


class FakeTransport:
    name = 'card-offline-fixture'

    def __init__(self):
        self.calls = []

    def request(self, trial, prompt, schema, system, session_id, directory, turn):
        self.calls.append(turn)
        return {'ok': True, 'session_id': 'offline-only',
                'text': json.dumps(example(schema)), 'raw_files': []}


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, cls.trials = build()

    def test_all_assignments_and_families(self):
        self.assertEqual(audit(self.meta, self.trials),
                         {'passed': True, 'cells': 42, 'cases': 200, 'trials': 8400, 'calls': 285600})

    def test_tampered_split_rejected(self):
        rows = copy.deepcopy(self.trials)
        rows[0]['split'] = 'holdout' if rows[0]['split'] == 'development' else 'development'
        with self.assertRaises(ValueError):
            audit(self.meta, rows)

    def test_jobs_partition_and_stage_separation(self):
        jobs = make_jobs(self.trials)
        self.assertEqual(audit_jobs(self.trials, jobs), {'jobs': 280, 'initial_jobs': 70})
        jobs[1]['trial_ids'][0] = jobs[0]['trial_ids'][0]
        with self.assertRaises(ValueError):
            audit_jobs(self.trials, jobs)

    def test_bundle_reproducible_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            save(d)
            first = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            save(d)
            self.assertEqual(first, {p.name: p.read_bytes() for p in Path(d).iterdir()})
            rows = [json.loads(line) for line in gzip.decompress(first['assignments.jsonl.gz']).splitlines()]
            self.assertEqual(audit(json.loads(first['schedule.json']), rows)['trials'], 8400)
            (Path(d) / 'audit.json').write_text('different')
            with self.assertRaises(FileExistsError):
                save(d)

    def test_existing_protocol_parity_at_canonical_order(self):
        trial = copy.deepcopy(self.trials[0])
        trial['order'] = list('ABCD')
        old, new = MainProtocol(), CardProtocol()
        self.assertEqual(old.system(trial), new.system(trial))
        for turn, feedback, remaining in [(1, None, list('ABCD')), (2, 'K', list('AB')),
                                           (3, 'D', ['A']), (31, None, ['A']),
                                           (32, None, ['A']), (33, None, ['A']), (34, None, ['A'])]:
            self.assertEqual(old.prompt(trial, turn, feedback, remaining),
                             new.prompt(trial, turn, feedback, remaining))
            self.assertEqual(old.schema(turn, remaining, 'cards', trial),
                             new.schema(turn, remaining, 'cards', trial))

    def test_both_games_complete_with_real_protocol_and_fake_transport(self):
        for game in ('obj', 'seq'):
            trial = next(t for t in self.trials if t['game'] == game and t['order'] != list('ABCD'))
            adapt(trial)
            with tempfile.TemporaryDirectory() as d:
                p = Path(d)
                transport = FakeTransport()
                state = run_trial(trial, CardProtocol(), transport, p/'state.json', p/'scratch',
                                  CallBudget(p/'budget.json', 'offline', 34), 'a'*64)
                self.assertEqual(state['status'], 'complete', state.get('error'))
                self.assertEqual(transport.calls, list(range(1, 35)))
                self.assertEqual(state['session_id'], 'offline-only')
                self.assertEqual([r['final'] for r in state['rounds']], trial['targets'])
                self.assertTrue(all('parsed' in x for x in state['turns']))
                self.assertEqual(len([x for x in state['turns'] if phase(trial, x['turn'])[1] == 3]), 10)
                rows, reason = risk_rows(state)
                self.assertEqual(len(rows), 10)
                self.assertEqual(reason, 'ten_rounds_observed')

    def test_features_stop_on_first_joint_report_and_keep_kd_between_rounds(self):
        t = next(x for x in self.trials if x['game'] == 'obj')
        state = {'trial': t, 'rounds': [
            {'round': 1, 'route': 'KK', 'final': 'A'},
            {'round': 2, 'route': 'DD', 'final': 'A'},
            {'round': 3, 'route': 'DD', 'final': 'A'}],
            'turns': [{'turn': 3, 'parsed': {'impact': 100, 'counterfactual': 'yes'}},
                      {'turn': 6, 'parsed': {'impact': 100, 'counterfactual': 'no'}},
                      {'turn': 9, 'parsed': {'impact': 1, 'counterfactual': 'no'}}]}
        rows, reason = risk_rows(state)
        self.assertEqual(reason, 'first_joint_report')
        self.assertEqual([r['first_joint_report'] for r in rows], [0, 0, 1])
        self.assertEqual([r['same_result_run_length'] for r in rows], [1, 2, 3])
        # KK|DD|DD: probabilities after anchor are 1/2, 1/3, 1/2, 2/3, 3/4.
        import math
        self.assertAlmostEqual(rows[-1]['cumulative_kd_surprisal_bits'], -math.log2(.5/3*.5*2/3*.75))
        state['turns'][1]['parsed']['impact'] = None
        rows, reason = risk_rows(state)
        self.assertEqual(len(rows), 1)
        self.assertEqual(reason, 'missing_or_invalid_round')

    def test_technical_summary_reports_usage_without_exposing_ids(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            trial = {'model': 'example', 'effort': 'high', 'frame': 'cards', 'game': 'seq'}
            state = {'trial': trial, 'status': 'complete', 'turns': [
                {'ok': True, 'session_id': 'private-id', 'process_pid': 123,
                 'compaction_events': 0}]}
            (p/'state.json').write_text(json.dumps(state))
            event_dir = p/'native'/'private'/'turn-01'
            event_dir.mkdir(parents=True)
            event = {'method': 'thread/tokenUsage/updated', 'params': {'tokenUsage': {
                'modelContextWindow': 1000, 'last': {'totalTokens': 33,
                'inputTokens': 30, 'outputTokens': 3}}}}
            (event_dir/'rpc-received.jsonl').write_text(json.dumps(event)+'\n')
            output = summarize(p)
            self.assertTrue(output['same_session'] and output['same_process'])
            self.assertEqual(output['usage_by_turn'][0]['last_total_tokens'], 33)
            self.assertNotIn('private-id', json.dumps(output))


if __name__ == '__main__':
    unittest.main()
