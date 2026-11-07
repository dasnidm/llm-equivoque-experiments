"""Scientific allocation and immutable serialization tests; no model calls."""
from collections import Counter, defaultdict
import copy
import tempfile
from pathlib import Path
import unittest

from .schedule import (ARMS, COMMON_SEQUENCE, MODELS, ORDER, audit, build,
                       build_jobs, load_bundle, save_bundle)


class MainScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build()
        cls.jobs = build_jobs(cls.plan)

    def test_counts_unique_sessions_and_budget(self):
        self.assertTrue(audit(self.plan, self.jobs)['passed'])
        self.assertEqual(self.plan['planned_sessions'], 77856)
        self.assertEqual(self.plan['planned_game_rounds'], 778560)
        self.assertEqual(self.plan['call_cap'], 2647104)
        self.assertEqual(Counter(t['model'] for t in self.plan['trials']),
                         {m: 9732 for m in MODELS})

    def test_single_sequence_target_balance_and_no_forcing_in_controls(self):
        groups = defaultdict(list)
        for t in self.plan['trials']:
            self.assertEqual(t['order'], list(ORDER))
            groups[t['cell_id']].append(t)
            if t['game'] == 'seq':
                self.assertEqual(t['targets'], list(COMMON_SEQUENCE))
            if t['kind'] == 'unforced':
                self.assertEqual(t['targets'], [])
                self.assertEqual(t['stage_rule'], t['game'])
        for rows in groups.values():
            if rows[0]['game'] == 'obj':
                expected = 8 if rows[0]['arm'] == 'R_A' else 30
                self.assertEqual(Counter(t['target_identity'] for t in rows),
                                 {x: expected for x in ORDER})

    def test_core_split_fold_and_terminal_balance(self):
        groups = defaultdict(list)
        for t in self.plan['trials']:
            if t['split'] != 'control':
                groups[t['cell_id']].append(t)
        for rows in groups.values():
            for split in ('development', 'holdout'):
                selected = [t for t in rows if t['split'] == split]
                self.assertEqual(len(selected), 60)
                self.assertEqual(Counter(t['probe_arm'] for t in selected),
                                 {'explanation': 30, 'neutral': 30})
                if rows[0]['game'] == 'obj':
                    for target in ORDER:
                        subset = [t for t in selected if t['target_identity'] == target]
                        self.assertEqual(len(subset), 15)
                        self.assertEqual(sorted(Counter(t['probe_arm'] for t in subset).values()), [7, 8])
                        if split == 'development':
                            self.assertEqual(Counter(t['fold'] for t in subset), {i: 3 for i in range(5)})
            if rows[0]['game'] == 'obj':
                for target in ORDER:
                    subset = [t for t in rows if t['target_identity'] == target]
                    self.assertEqual(Counter(t['probe_arm'] for t in subset),
                                     {'explanation': 15, 'neutral': 15})

    def test_r_only_changes_measurement_in_english_schema(self):
        for t in self.plan['trials']:
            self.assertEqual(t['measurement'], 'round10_only' if t['arm'] == 'R_A' else 'each_round')
            self.assertEqual(t['format'], 'en_schema' if t['arm'] == 'R_A' else t['arm'])
            if t['arm'] == 'R_A':
                self.assertEqual(t['split'], 'control')
                self.assertIsNone(t['fold'])

    def test_visible_probe_set_does_not_depend_on_hidden_target(self):
        first = self.plan['trials'][0]['probe_policies']
        self.assertTrue(all(t['probe_policies'] == first for t in self.plan['trials']))
        self.assertEqual(len({(tuple(p['first']), p['second_position']) for p in first}), 4)

    def test_jobs_are_mixed_disjoint_and_model_owned(self):
        lookup = {t['trial_id']: t for t in self.plan['trials']}
        self.assertEqual(len(self.jobs), 2600)
        grouped = defaultdict(list)
        for job in self.jobs:
            grouped[job['model']].append(job)
            rows = [lookup[i] for i in job['trial_ids']]
            self.assertTrue(all(t['model'] == job['model'] for t in rows))
            # Prespecified ordering must genuinely mix condition cells.
            self.assertGreater(len({t['cell_id'] for t in rows}), 1)
        for jobs in grouped.values():
            self.assertEqual(Counter(j['n_trials'] for j in jobs), {30: 324, 12: 1})
            self.assertEqual(sum(j['call_cap'] for j in jobs), 330888)
            first_rows = [lookup[i] for j in jobs[:3] for i in j['trial_ids']]
            self.assertEqual({t['effort'] for t in first_rows}, {'low', 'medium', 'high'})
            self.assertEqual({t['arm'] for t in first_rows}, set(ARMS))

    def test_audit_rejects_duplicate_job_claim_units(self):
        damaged = copy.deepcopy(self.jobs)
        damaged[1]['trial_ids'][0] = damaged[0]['trial_ids'][0]
        with self.assertRaisesRegex(ValueError, 'overlap|omit'):
            audit(self.plan, damaged)

    def test_audit_rejects_wrong_r_measurement(self):
        damaged = dict(self.plan, trials=list(self.plan['trials']))
        index = next(i for i, t in enumerate(damaged['trials']) if t['arm'] == 'R_A')
        damaged['trials'][index] = dict(damaged['trials'][index], measurement='each_round')
        with self.assertRaisesRegex(ValueError, 'Measurement timing'):
            audit(damaged)

    def test_audit_rejects_changed_stimulus_metadata(self):
        damaged = dict(self.plan, common_sequence=['A'] * 10)
        with self.assertRaisesRegex(ValueError, 'Metadata disagrees'):
            audit(damaged)

    def test_deterministic_bundle_roundtrip_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'allocation'
            summary = save_bundle(self.plan, folder)
            self.assertEqual(save_bundle(self.plan, folder), summary)
            self.assertEqual(load_bundle(folder), self.plan)
            changed = dict(self.plan, seed=self.plan['seed'] + 1)
            with self.assertRaisesRegex(ValueError, 'Existing file differs'):
                save_bundle(changed, folder)
            self.assertEqual(load_bundle(folder), self.plan)
            assignment = folder / 'assignments.jsonl.gz'
            assignment.write_bytes(assignment.read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_bundle(folder)

    def test_build_is_reproducible(self):
        self.assertEqual(build(), self.plan)
        self.assertEqual(build_jobs(self.plan), self.jobs)


if __name__ == '__main__':
    unittest.main()
