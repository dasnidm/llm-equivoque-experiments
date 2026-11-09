"""Offline mathematical checks for the 2026-11-09 design review.

These are generator/precision examples, not LLM observations or model fits.
"""
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, product
import json
from math import ceil, sqrt
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/data/exp7-theory-review-20261109"
OBJECTS = tuple("ABCD")


def retain(objects, chosen, rule):
    return tuple(x for x in objects if (x in chosen) == (rule == "K"))


def trace(first_choice, second_policy, *, target=None, route=None):
    assert (target is None) != (route is None)
    first_rule = route[0] if route else ("K" if target in first_choice else "D")
    survivors = retain(OBJECTS, first_choice, first_rule)
    second_choice = (second_policy[first_rule],)
    second_rule = route[1] if route else ("K" if target in second_choice else "D")
    result = retain(survivors, second_choice, second_rule)
    assert len(result) == 1
    return (first_choice, first_rule, survivors, second_choice, second_rule, result[0])


def main():
    checked = 0
    example = None
    # Six first subsets and 2 x 2 second-choice contingent policies exhaust
    # deterministic valid choice policies within one 4->2->1 round.
    for first in combinations(OBJECTS, 2):
        kept = retain(OBJECTS, first, "K")
        discarded = retain(OBJECTS, first, "D")
        for second_k, second_d in product(kept, discarded):
            policy = {"K": second_k, "D": second_d}
            forced = Counter(trace(first, policy, target=t) for t in OBJECTS)
            variable_rule = Counter(trace(first, policy, route=r)
                                    for r in product("KD", repeat=2))
            assert forced == variable_rule
            assert sum(forced.values()) == 4
            checked += 1
            if example is None:
                example = [{"trace": list(k), "probability": str(Fraction(v, 4))}
                           for k, v in forced.items()]
    assert checked == 24

    # Structural counterfactuals differ despite identical observed laws.
    before = trace(("A", "B"), {"K": "A", "D": "C"}, target="A")[-1]
    after_forced = trace(("C", "D"), {"K": "C", "D": "A"}, target="A")[-1]
    after_rule = trace(("C", "D"), {"K": "C", "D": "A"}, route="KK")[-1]
    assert before == after_forced == "A" and after_rule == "C"

    paths = []
    for s in ("KKKKDDDD", "KDKDKDKD"):
        p = Fraction(s.count("K"), len(s))
        paths.append({"sequence": s, "binary_population_variance": str(p*(1-p)),
                      "adjacent_switches": sum(a != b for a, b in zip(s, s[1:]))})
    assert paths[0]["binary_population_variance"] == paths[1]["binary_population_variance"]

    # Illustrative independent-binomial normal approximation, true difference 0.
    # This is NOT a clustered/factorial/survival power analysis.
    normal = NormalDist()
    z = normal.inv_cdf(.95)  # 90% CI used by a level-.05 TOST.
    margin = .05
    precision = []
    for p in (.1, .25, .5):
        se = sqrt(2*p*(1-p)/120)
        n_ci = ceil(z*z*2*p*(1-p)/margin**2)
        # TOST power at true difference zero: 2 Phi(margin/SE-z)-1.
        n_power = ceil((z+normal.inv_cdf(.9))**2*2*p*(1-p)/margin**2)
        precision.append({"event_probability_per_arm": p, "n_per_arm": 120,
                          "expected_90pct_CI_half_width": z*se,
                          "equivalence_margin_absolute": margin,
                          "n_per_arm_for_expected_CI_half_width": n_ci,
                          "n_per_arm_for_approx_80pct_TOST_power": n_power})

    sources = [ROOT/"exp7_main/analysis_contract.json", ROOT/"exp7_main/schedule.py",
               Path("/workspace/llm-equivoque-experiments/docs/EXP7_HYBRID_COGNITIVE_MODEL.ko.md"),
               Path("/workspace/llm-equivoque-experiments/docs/EXP7_PRE_RESULTS.ko.md"),
               Path("/workspace/llm-equivoque-experiments/docs/EXP7_METHODS_CRITICAL_REVIEW.ko.md")]
    payload = {
        "date": "2026-11-09", "status": "offline_design_review_not_experiment",
        "new_model_calls": 0, "frozen_design_changed": False,
        "source_sha256": {str(p): sha256(p.read_bytes()).hexdigest() if p.exists() else None
                          for p in sources},
        "variance_counterexample": paths,
        "five_round_uniform_outcome_example": {
            "preselected_exact_string_AAAAA_or_ABCDA": str(Fraction(1, 4**5)),
            "any_one_object_repeated_five_times": str(Fraction(1, 4**4)),
            "AAAAA_likelihood_under_uniform_unknown_constant_target": "1/4",
            "constant_target_vs_iid_uniform_Bayes_factor_after_AAAAA": 4**4,
            "assumption": "Uniform independent final outcomes under comparison null; not actual LLM choice probabilities."
        },
        "observational_equivalence_audit": {
            "deterministic_within_round_choice_policies_checked": checked,
            "equal_exact_transcript_distributions": checked,
            "forced_process": "Fresh iid uniform target, chosen before actions; adapt K/D to retain it.",
            "unforced_process": "Two iid fair K/D rules chosen before actions; apply them to free choices.",
            "scope": "4->2->1, noiseless feedback, no generator cues. Fresh iid rounds extend equality; a fixed balanced sequence bank is not covered by this exact equality.",
            "first_policy_example": example,
            "counterfactual_example": {"factual_outcome": before,
                                       "changed_choices_forced_outcome": after_forced,
                                       "changed_choices_fixed_KK_outcome": after_rule},
            "interpretation": "Different causal generators can be indistinguishable from the observed transcript; more repetitions alone do not identify the generator."
        },
        "independent_binomial_precision_examples": precision,
        "power_scope": "Normal approximation, known planning p, independent arms, true difference zero, one comparison. Final sample size needs clustered/factorial/survival and model-recovery simulations."
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/"audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"equivalent_choice_policies": checked,
                      "precision_examples": precision, "new_model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
