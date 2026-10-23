"""Independent small-example checks for the statistical supplement."""
from __future__ import annotations

import itertools
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from statistics_core import (bh, bootstrap_mean, holm, mcnemar_logp,
                             probability_display, rank_omnibus, seed_for, signflip_mean)
from statistical_audit import Audit, did, html_report, normalized, paired_values


class PermutationTests(unittest.TestCase):
    def test_lattice_agrees_with_independent_enumeration(self):
        for d in [[1, 2, -1, 3, -2], [1/3, -2/3, 1, 2/3], [1, 1, -1, -1], [2, 4, -1]]:
            observed = abs(sum(d))
            null = [abs(sum(x*s for x, s in zip(d, signs)))
                    for signs in itertools.product([-1, 1], repeat=len(d))]
            expected = sum(t >= observed - 1e-10 for t in null) / len(null)
            self.assertAlmostEqual(signflip_mean(d)["p_value"], expected, places=12)

    def test_one_direction_and_zeros(self):
        self.assertEqual(signflip_mean([0, 1, 1, 0, 1])["p_value"], .25)
        self.assertEqual(signflip_mean([0, 0, 0])["p_value"], 1)
        self.assertAlmostEqual(signflip_mean([1] * 30)["p_value"], 2 ** -29)

    def test_monte_carlo_never_zero_and_is_reproducible(self):
        d = [1, math.sqrt(2), -math.pi, .718281828, 2]
        a = signflip_mean(d, seed=1234, resamples=9999, max_lattice=0)
        b = signflip_mean(d, seed=1234, resamples=9999, max_lattice=0)
        self.assertEqual(a, b)
        self.assertIn("plus_one", a["method"])
        self.assertGreater(a["p_value"], 0)

    def test_bad_inputs(self):
        for d in [[], [float("nan")], [[1, 2]]]:
            with self.assertRaises(ValueError):
                signflip_mean(d)

    def test_mcnemar_matches_exact_binomial(self):
        for a, b in [(5, 0), (20, 0), (3, 0), (4, 7), (0, 0), (12, 12)]:
            expected = stats.binomtest(a, a+b, .5).pvalue if a+b else 1
            self.assertAlmostEqual(math.exp(mcnemar_logp(a, b)), expected, places=12)

    def test_underflow_is_not_p_zero(self):
        lp = mcnemar_logp(2093, 0)
        self.assertAlmostEqual(lp, (1-2093)*math.log(2), places=9)
        self.assertRegex(probability_display(logp=lp), r"e-\d+")
        with self.assertRaises(ValueError):
            probability_display(0)

    def test_multiplicity_known_example(self):
        p = [.01, .04, .03, np.nan]
        np.testing.assert_allclose(holm(p)[:3], [.03, .06, .06])
        np.testing.assert_allclose(bh(p)[:3], [.03, .04, .04])
        self.assertTrue(np.isnan(holm(p)[3]))
        np.testing.assert_allclose(holm([1, 1, 1]), [1, 1, 1])

    def test_bootstrap_boundary_is_finite_and_reproducible(self):
        self.assertEqual(bootstrap_mean([.5] * 30, seed=7), (.5, .5))
        a = bootstrap_mean([0, 1, 0, 1], seed=seed_for("example"), resamples=1000)
        b = bootstrap_mean([0, 1, 0, 1], seed=seed_for("example"), resamples=1000)
        self.assertEqual(a, b)
        self.assertTrue(0 <= a[0] <= .5 <= a[1] <= 1)

    def test_omnibus_ties_and_order(self):
        self.assertEqual(rank_omnibus(np.ones((8, 3)), seed=2)["p_value"], 1)
        x = np.tile([0, 1, 2], (8, 1))
        result = rank_omnibus(x, seed=2, resamples=9999)
        self.assertLess(result["p_value"], .01)
        self.assertAlmostEqual(result["kendalls_w"], 1)


class MatchingTests(unittest.TestCase):
    def data(self):
        rows = []
        for case, model, frame in itertools.product(["case1", "case2"], ["m1", "m2"], ["cards", "cats"]):
            rows.append(dict(case_id=case, model=model, effort="high", frame=frame,
                             trial_id=f"{case}-{model}-{frame}", phase="r10",
                             joint=int(frame == "cards"), impact=1 if frame == "cards" else 100))
        return normalized(pd.DataFrame(rows), "s5")

    def test_shared_cases_not_inflated_by_model_repetitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp), Path(tmp), bootstrap=100, permutations=999)
            audit.add_paired(self.data(), "frame", "cards", "cats", "joint")
            row = audit.tests[0]
            self.assertEqual(row["n_pairs"], 4)
            self.assertEqual(row["n_blocks"], 2)
            self.assertEqual(row["p_value"], .5)
            self.assertEqual(row["estimate"], 1)

    def test_missing_is_excluded_not_zero_imputed(self):
        d = self.data()
        d.loc[(d.case_id == "case1") & (d.model == "m1") & (d.frame == "cats"), "joint"] = np.nan
        pairs, missing, _, _ = paired_values(d, "frame", "cards", "cats", "joint")
        self.assertEqual(len(pairs), 3)
        self.assertEqual(missing, 1)
        self.assertTrue((pairs.difference == 1).all())

    def test_duplicate_matching_keys_fail(self):
        d = self.data()
        d = pd.concat([d, d.iloc[:1]], ignore_index=True)
        with self.assertRaises(AssertionError):
            paired_values(d, "frame", "cards", "cats", "joint")

    def test_interactions_are_contrasts_not_binary_observations(self):
        rows = []
        for case, model, arm in itertools.product(["c1", "c2", "c3"], ["m1", "m2"], ["a", "b", "c"]):
            rows.append(dict(case_id=case, model=model, effort="high", arm=arm,
                             phase="change", joint=int((model == "m1") == (arm == "a"))))
        d = normalized(pd.DataFrame(rows), "s6")
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp), Path(tmp), bootstrap=100, permutations=999)
            for a, b in [("a", "b"), ("a", "c"), ("b", "c")]:
                did(audit, d, inner_factor="arm", inner_a=a, inner_b=b,
                    outer_factor="model", outer_a="m1", outer_b="m2", metric="joint")
            self.assertEqual(len(audit.tests), 3)
            self.assertEqual(len(audit.sensitivity), 0)
            self.assertEqual(audit.tests[0]["estimate"], 2)

    def test_original_and_secondary_route_weights(self):
        rows = []
        routes = ["KK", "DD", "KD", "DK"]
        for case, (r, route) in itertools.product(range(12), enumerate(routes)):
            for repeat in range(2 if route == "KK" else 1):
                rows.append(dict(case_id=f"c{case}", route=route,
                                 pre_impact=70 + case*.2 + [3, 1, 4, 2][r] + case*r*.1))
        d = pd.DataFrame(rows)
        means = d.groupby("route").pre_impact.mean()
        expected = [(means.KK + means.DD - means.KD - means.DK)/2,
                    means.KK - means.DD, means.KD - means.DK]
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp), Path(tmp))
            audit.route(d, "all")
            self.assertEqual(len(audit.tests), 3)
            for row, estimate in zip(audit.tests, expected):
                self.assertAlmostEqual(row["estimate"], estimate, places=12)
                self.assertEqual(row["n_blocks"], 12)
                self.assertGreater(row["p_value"], 0)
                self.assertLessEqual(row["p_value"], 1)

    def test_html_preserves_small_nonzero_probabilities(self):
        import json
        source = pd.DataFrame([dict(test_id="tiny", p_value=2**-49, p_holm_global=1e-12)])
        page = html_report(source)
        payload = page.split('<script id="data" type="application/json">')[1].split('</script>')[0]
        row = json.loads(payload)[0]
        self.assertEqual(row["p_value"], 2**-49)
        self.assertIsNone(row["n_blocks"])

    def test_zero_variance_route_pair_with_variation_elsewhere(self):
        rows = [dict(case_id=f"c{case}", route=route,
                     pre_impact=100 if route in ["KK", "DD"] else 100-case%4)
                for case, route in itertools.product(range(12), ["KK", "DD", "KD", "DK"])]
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp), Path(tmp))
            audit.route(pd.DataFrame(rows), "all")
            comparison = audit.tests[1]
            self.assertEqual(comparison["estimate"], 0)
            self.assertEqual(comparison["p_value"], 1)
            self.assertEqual(comparison["status"], "no_observed_contrast_variation")


if __name__ == "__main__":
    unittest.main()
