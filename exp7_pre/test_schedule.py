"""Offline schedule/design tests: no model calls."""
from collections import Counter, defaultdict
import unittest

from .schedule import build, case_partition, fingerprint, FOCUS, KINDS
from .protocol import ARMS, make_probe_policies, validate_trial


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=build('focus');cls.cal=build('focus',calibration=True)

    def test_counts_budgets_and_identifiers(self):
        self.assertEqual((self.plan['planned_sessions'],self.plan['call_cap']),(1200,40800))
        self.assertEqual((self.cal['planned_sessions'],self.cal['call_cap']),(24,816))
        for s in (self.plan,self.cal):
            self.assertEqual(s['planned_sessions'],len(s['trials']))
            self.assertEqual(s['call_cap'],34*len(s['trials']))
            self.assertEqual(len({t['trial_id'] for t in s['trials']}),len(s['trials']))
            self.assertTrue(all(t['run_id']==s['run_id'] for t in s['trials']))
            self.assertTrue(all(validate_trial(t) for t in s['trials']))

    def test_new_families_disjoint_and_balanced(self):
        partition=case_partition(); subsets=[partition[k] for k in ('pre','calibration','main_reserved')]
        all_fps=[fingerprint(x) for group in subsets for x in group]
        self.assertEqual((len(all_fps),len(set(all_fps))),(64,64))
        for group,n in zip(subsets,(12,4,48)):
            self.assertEqual(len(group),n)
            self.assertEqual(set(Counter(c['target_identity'] for c in group).values()),{n//4})
            self.assertEqual(set(Counter(c['target_position'] for c in group).values()),{n//4})
            for c in group:
                counts=Counter(c['positions'])
                self.assertEqual(sorted(counts.values()),[2,2,3,3])
                self.assertEqual(c['positions'][0],c['target_position'])
        # Each pre-study stage rule, identity and starting position must see
        # both paraphrases, rather than p1/p2 being mechanically confounded.
        for key in ('stage_rule','target_identity','target_position'):
            for value in {c[key] for c in partition['pre']}:
                self.assertEqual({c['prompt_variant'] for c in partition['pre'] if c[key]==value},{'p1','p2'})

    def test_exact_arms_and_probe_balance(self):
        prim=[t for t in self.plan['trials'] if t['cohort']=='primary']
        self.assertEqual(len(prim),1152)
        groups=defaultdict(list)
        for t in prim: groups[t['model'],t['effort'],t['arm'],t['kind']].append(t)
        self.assertEqual(len(groups),len(FOCUS)*len(ARMS)*len(KINDS))
        for g in groups.values():
            self.assertEqual(len(g),12)
            self.assertEqual(Counter(t['probe_arm'] for t in g),{'explanation':6,'neutral':6})
            if g[0]['kind']=='unforced': self.assertEqual(Counter(t['stage_rule'] for t in g),{'KK':3,'KD':3,'DK':3,'DD':3})

    def test_probe_policy_ignores_secret_and_actual_choices(self):
        groups=defaultdict(list)
        for t in self.plan['trials']:
            groups[t['case_id']].append(t)
            self.assertEqual(t['probe_policies'],make_probe_policies(t['order'],t['probe_seed']))
        for g in groups.values():
            # Probe policies remain identical even as hidden procedure, target
            # schedule, model, and measurement arm change.
            self.assertTrue(all(t['probe_policies']==g[0]['probe_policies'] for t in g))

    def test_replicates_are_distinct_sessions_not_new_cases(self):
        reps=[t for t in self.plan['trials'] if t['cohort']=='independent_repeat']
        self.assertEqual(len(reps),48)
        self.assertTrue(all(t['arm']=='A' and t['replicate'] in (2,3) for t in reps))
        self.assertEqual(len({t['case_id'] for t in reps}),2)

    def test_schedule_is_deterministic(self):
        self.assertEqual(self.plan,build('focus'))
        self.assertEqual(self.cal,build('focus',calibration=True))


if __name__=='__main__':unittest.main()
