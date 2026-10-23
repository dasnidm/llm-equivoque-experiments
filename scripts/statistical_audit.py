#!/usr/bin/env python3
"""Reproduce the retrospective six-study supplement, without model calls.

Run from any directory: python scripts/statistical_audit.py
Only this supplement's outputs are written. Historical scientific records are
read, hashed, checked against their audits and otherwise left unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import itertools
import json
import math
from pathlib import Path
import platform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy import stats

from statistics_core import (bh, bootstrap_mean, holm, mcnemar_logp,
                             probability_display, rank_omnibus, seed_for, signflip_mean)

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026-10-23-v1"
DEFAULT_OUTPUT = Path("docs/data/statistics-2026-10-23")
FACTORS = ["case_id", "model", "effort", "frame", "kind", "procedure", "claim", "arm", "phase"]
GAME_METRICS = ["impact", "freedom", "cf_no", "joint"]
CORE_METRICS = ["impact", "joint"]
ITEMS = ["table_lookup_correct", "new_arrangement_correct", "renaming_correct",
         "rule_change_correct", "counterfactual_correct", "changed_counterfactual_correct"]
TRANSFER_METRICS = ["transfer_accuracy", "all_transfer_correct"] + ITEMS
PRED_METRICS = ["prediction_match_fraction", "prediction_uncertain_fraction",
                "prediction_mismatch_fraction", "prediction_all12_match",
                "prediction_all_uncertain", "prediction_any_mismatch"]
RUNS = {
    "s1": ("equivoque-2026-10-09-v1", "attempt-02"),
    "s2": ("equivoque-2026-10-09-exp2-v1", "attempt-01"),
    "s3": ("equivoque-2026-10-11-exp3-pilot-v1", "attempt-01"),
    "s4": ("equivoque-2026-10-12-sequence-pilot-v1", "attempt-01"),
    "s5": ("equivoque-2026-10-12-sequence-replication-v1", "attempt-01"),
    "s6": ("equivoque-2026-10-13-question-effect-v1", "attempt-01"),
}
TITLES = {
    "s1": "Single-round disclosure study", "s2": "Three-round repetition study",
    "s3": "Supplied-rule transfer pilot", "s4": "Thirty-round sequence pilot",
    "s5": "Ten-round sequence replication", "s6": "Question intervention",
}


def finite(value):
    return value is not None and np.isfinite(value)


def is_binary_metric(metric):
    return metric in {"cf_no", "joint", "all_transfer_correct", *ITEMS,
                      "prediction_all12_match", "prediction_all_uncertain", "prediction_any_mismatch",
                      "ever_joint", "early_joint", "early_persistent"}


def percent_metric(metric):
    return is_binary_metric(metric) or metric == "transfer_accuracy" or metric.endswith("_fraction")


def normalized(data, study):
    d = data.copy()
    d["study"] = study
    for column in FACTORS:
        if column not in d:
            d[column] = "-"
    for column in FACTORS:
        d[column] = d[column].fillna("-").astype(str)
    if "configuration_id" not in d:
        d["configuration_id"] = d["model"] + "-" + d["effort"]
    if "counterfactual" in d:
        d["cf_no"] = d.counterfactual.map({"yes": 0.0, "no": 1.0})
    if "impact" in d and "cf_no" in d:
        valid = d.impact.notna() & d.cf_no.notna()
        d["joint"] = np.where(valid, ((d.impact == 1) & (d.cf_no == 1)).astype(float), np.nan)
    return d


def paired_values(data, factor, a, b, metric):
    """Match only unchanged factors; reject accidental many-to-many pairing."""
    keys = [c for c in FACTORS if c != factor]
    # Configuration identity includes model and effort, which are already keys.
    selected = data[keys + [factor, metric]].copy()
    left = selected[selected[factor].astype(str) == str(a)].drop(columns=factor)
    right = selected[selected[factor].astype(str) == str(b)].drop(columns=factor)
    if left.duplicated(keys).any() or right.duplicated(keys).any():
        raise AssertionError(f"Non-unique matching keys: {factor}/{a}/{b}/{metric}")
    left = left.rename(columns={metric: "a"})
    right = right.rename(columns={metric: "b"})
    paired = left.merge(right, on=keys, how="outer", validate="one_to_one", indicator=True)
    valid = paired["a"].notna() & paired["b"].notna()
    result = paired[valid].drop(columns="_merge").copy()
    result["difference"] = result["a"] - result["b"]
    return result, int((~valid).sum()), len(left), len(right)


class Audit:
    def __init__(self, root, output, bootstrap=20000, permutations=99999):
        self.root, self.output = root, output
        self.bootstrap, self.permutations = bootstrap, permutations
        self.sources, self.checks, self.tests, self.blocks, self.sensitivity = [], [], [], [], []
        self.descriptives, self.coding = [], []
        self.ids = set()

    def read(self, path):
        p = self.root / path
        raw = p.read_bytes()
        data = pd.read_csv(p)
        self.sources.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                                 bytes=len(raw), rows=len(data), columns=list(data)))
        return data

    def table(self, study, filename):
        run, attempt = RUNS[study]
        return self.read(Path("analysis/results") / run / attempt / "tables" / filename)

    def json_source(self, path):
        raw = (self.root / path).read_bytes()
        value = json.loads(raw)
        self.sources.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                                 bytes=len(raw), format="json"))
        return value

    def check(self, name, condition, observed=None):
        self.checks.append(dict(check=name, passed=bool(condition), observed=observed))
        if not condition:
            raise AssertionError(f"Source check failed: {name}: {observed}")

    def add_paired(self, data, factor, a, b, metric, *, scope="all", headline=False, note=""):
        study = str(data.study.iloc[0])
        test_id = f"{study}:{factor}:{a}-minus-{b}:{scope}:{metric}"
        pairs, excluded, n_a, n_b = paired_values(data, factor, a, b, metric)
        return self.add_pairs(pairs, test_id=test_id, study=study, metric=metric,
                              contrast=f"{factor}: {a} minus {b}", scope=scope,
                              headline=headline, note=note, excluded=excluded, n_a=n_a, n_b=n_b)

    def add_pairs(self, pairs, *, test_id, study, metric, contrast, scope,
                  headline=False, note="", excluded=0, n_a=None, n_b=None,
                  binary_sensitivity=True):
        if test_id in self.ids:
            raise AssertionError(f"Duplicate test: {test_id}")
        self.ids.add(test_id)
        pilot = study == "s4"
        block_key = "model" if pilot else "case_id"
        row = dict(test_id=test_id, study=study, contrast=contrast, scope=scope, metric=metric,
                   test_type="paired_mean", headline=headline,
                   inference_scope="fixed_model_panel_reference_only" if pilot else "case_block_reference",
                   unit=block_key, n_pairs=len(pairs), n_excluded_unmatched_or_missing=excluded,
                   n_a_available=n_a, n_b_available=n_b,
                   n_cases=pairs.case_id.nunique() if len(pairs) else 0, note=note)
        if not len(pairs):
            row.update(status="not_estimable_no_valid_pairs", p_value=np.nan)
            self.tests.append(row)
            return pairs
        block = pairs.groupby(block_key, sort=True)[["a", "b", "difference"]].mean()
        d = block.difference.to_numpy(float)
        row.update(n_blocks=len(block), mean_a=float(block.a.mean()), mean_b=float(block.b.mean()),
                   estimate=float(d.mean()), pooled_pair_estimate=float(pairs.difference.mean()),
                   median_block_difference=float(np.median(d)),
                   n_positive_blocks=int((d > 1e-12).sum()), n_negative_blocks=int((d < -1e-12).sum()),
                   n_zero_blocks=int((np.abs(d) <= 1e-12).sum()))
        if len(block) < 2:
            row.update(status="not_estimable_fewer_than_two_blocks", p_value=np.nan)
        else:
            result = signflip_mean(d, seed=seed_for(test_id), resamples=self.permutations)
            low, high = bootstrap_mean(d, seed=seed_for(test_id + ":bootstrap"), resamples=self.bootstrap)
            sd = float(np.std(d, ddof=1))
            row.update(**result, ci_low=low, ci_high=high,
                       ci_method="pointwise_case_block_percentile_bootstrap" if not pilot else "selected_model_panel_percentile_reference",
                       ci_degenerate=abs(high - low) < 1e-12,
                       standardized_block_dz=float(d.mean() / sd) if sd > 1e-12 else np.nan,
                       status="no_observed_difference" if np.all(np.abs(d) < 1e-12) else "estimable")
        for key, values in block.iterrows():
            self.blocks.append(dict(test_id=test_id, study=study, block_unit=block_key,
                                    block_id=str(key), mean_a=values.a, mean_b=values.b,
                                    difference=values.difference,
                                    matched_pairs=int((pairs[block_key] == key).sum())))
        if is_binary_metric(metric) and binary_sensitivity:
            if not pairs[["a", "b"]].isin([0, 1]).all().all():
                raise AssertionError(f"Binary endpoint not binary: {test_id}")
            a_only = int(((pairs.a == 1) & (pairs.b == 0)).sum())
            b_only = int(((pairs.a == 0) & (pairs.b == 1)).sum())
            lp = mcnemar_logp(a_only, b_only)
            self.sensitivity.append(dict(test_id=test_id, study=study, metric=metric,
                n_pairs=len(pairs), a_events=int(pairs.a.sum()), b_events=int(pairs.b.sum()),
                a_only=a_only, b_only=b_only, n_discordant=a_only + b_only,
                p_value=math.exp(lp) if lp > -700 else np.nan, log_p_value=lp,
                p_display="p=" + probability_display(logp=lp),
                assumption="Conversation-pair independence conditional on fixed bank; shared-case dependence NOT adjusted"))
        self.tests.append(row)
        return pairs

    def omnibus(self, data, factor, metric, *, scope="all"):
        study = str(data.study.iloc[0])
        test_id = f"{study}:omnibus:{factor}:{scope}:{metric}"
        if test_id in self.ids:
            raise AssertionError(test_id)
        self.ids.add(test_id)
        # Aggregate all non-tested factors over the fixed balanced panel first.
        panel = data.groupby(["case_id", factor], sort=True)[metric].mean().unstack(factor).dropna()
        row = dict(test_id=test_id, study=study, contrast=f"omnibus {factor}", scope=scope,
                   metric=metric, test_type="rank_omnibus", headline=False, unit="case_id",
                   inference_scope="case_block_reference", n_cases=len(panel), n_blocks=len(panel),
                   n_levels=panel.shape[1], n_pairs=np.nan,
                   note="Condition labels exchangeable under reference null; fixed requested models are not a population sample")
        if len(panel) < 2 or panel.shape[1] < 3:
            row.update(status="not_estimable_insufficient_blocks_or_levels", p_value=np.nan)
        else:
            row.update(**rank_omnibus(panel.to_numpy(), seed=seed_for(test_id), resamples=self.permutations), status="estimable")
        self.tests.append(row)

    def summarize(self, data, metrics):
        columns = ["study", "model", "effort", "frame", "kind", "procedure", "claim", "arm", "phase"]
        for level, keys in [("cell", columns), ("overall", ["study", "phase"]),
                            ("model", ["study", "phase", "model"]),
                            ("condition", ["study", "phase", "kind", "arm", "procedure", "claim"])]:
            for key, group in data.groupby(keys, sort=True, dropna=False):
                identity = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
                for metric in metrics:
                    if metric not in group:
                        continue
                    x = group[metric].dropna()
                    self.descriptives.append(dict(**identity, aggregation=level, metric=metric,
                        n_rows=len(group), n_valid=len(x), n_cases=group.loc[x.index, "case_id"].nunique(),
                        mean=float(x.mean()) if len(x) else np.nan,
                        median=float(x.median()) if len(x) else np.nan,
                        sd=float(x.std(ddof=1)) if len(x) > 1 else np.nan,
                        events=int(x.sum()) if len(x) and is_binary_metric(metric) else np.nan))

    def route(self, data, scope):
        data = data.dropna(subset=["pre_impact", "route", "case_id"])
        routes = ["KK", "DD", "KD", "DK"]
        counts = data.route.value_counts().reindex(routes, fill_value=0)
        common = dict(study="s1", scope=scope,
            metric="impact", test_type="observational_route_ols", headline=False,
            inference_scope="case_block_reference", unit="case_id", n_cases=data.case_id.nunique(),
            n_blocks=data.case_id.nunique(), n_pairs=np.nan, n_observations=len(data),
            note="Endogenous route association; cluster t approximation; sparse variation near ceiling",
            **{f"n_{r}":int(counts[r]) for r in routes})
        eligible = bool((counts > 0).all() and data.case_id.nunique() > 1 and len(data) > len(routes))
        if eligible:
            x = np.column_stack([(data.route == r).to_numpy(float) for r in routes])
            y = data.pre_impact.to_numpy(float)
            inverse = np.linalg.inv(x.T @ x)
            beta = inverse @ x.T @ y
            scores = pd.DataFrame(x * (y - x @ beta)[:, None]).groupby(data.case_id.to_numpy(), sort=True).sum().to_numpy()
            n, k = x.shape
            g = len(scores)
            covariance = g / (g - 1) * (n - 1) / (n - k) * inverse @ scores.T @ scores @ inverse
        for name, label, coefficients in [
            ("route_equal_weight", "(KK + DD - KD - DK) / 2", [.5, .5, -.5, -.5]),
            ("route_KK_minus_DD", "KK minus DD", [1, -1, 0, 0]),
            ("route_KD_minus_DK", "KD minus DK", [0, 0, 1, -1]),
        ]:
            test_id = f"s1:{name}:{scope}:pre_impact"
            if test_id in self.ids:
                raise AssertionError(test_id)
            self.ids.add(test_id)
            row = dict(common, test_id=test_id, contrast=label)
            c = np.asarray(coefficients)
            if not eligible or (counts.to_numpy()[c != 0] < 10).any():
                row.update(status="not_estimable_fewer_than_10_per_route_or_two_cases", p_value=np.nan)
                self.tests.append(row)
                continue
            estimate = float(c @ beta)
            se = math.sqrt(max(0, float(c @ covariance @ c)))
            constant = np.ptp(y) < 1e-12
            constant_contrast = abs(estimate) < 1e-12 and se < 1e-12
            if constant or constant_contrast:
                estimate, se = 0.0, 0.0
            statistic = estimate / se if se > 1e-12 else 0.0
            p = 1.0 if constant or constant_contrast else float(2 * stats.t.sf(abs(statistic), g - 1)) if se > 1e-12 else np.nan
            critical = stats.t.ppf(.975, g - 1)
            row.update(estimate=0.0 if constant else estimate, standard_error=se,
                ci_low=estimate - critical * se, ci_high=estimate + critical * se,
                ci_method="case_cluster_robust_t_reference", ci_degenerate=se < 1e-12,
                statistic=statistic, degrees_freedom=g - 1, p_value=p,
                method="case_cluster_robust_route_means_OLS_t",
                status="no_observed_variation" if constant else "no_observed_contrast_variation" if constant_contrast
                       else "estimable" if finite(p) else "not_estimable_zero_contrast_variance")
            self.tests.append(row)


def subsets(data, *, configurations=False):
    yield "all", data
    for model, group in data.groupby("model", sort=True):
        yield f"model={model}", group
    if configurations:
        for configuration, group in data.groupby("configuration_id", sort=True):
            yield f"configuration={configuration}", group


def contrasts(audit, data, factor, a, b, metrics, *, configurations=False,
              prefix="", headline_metric=None, note=""):
    for scope, group in subsets(data, configurations=configurations):
        label = f"{prefix};{scope}" if prefix else scope
        for metric in metrics:
            audit.add_paired(group, factor, a, b, metric, scope=label,
                             headline=scope == "all" and metric == headline_metric, note=note)


def effort_and_model(audit, data, metrics, *, scope):
    for factor in ["model", "effort"]:
        for metric in metrics:
            audit.omnibus(data, factor, metric, scope=scope)
    for high, low in [("medium", "low"), ("high", "low"), ("high", "medium")]:
        contrasts(audit, data, "effort", high, low, metrics, prefix=scope)
    # Retain all pairwise model comparisons at explicitly chosen endpoint scopes.
    for a, b in itertools.combinations(sorted(data.model.unique()), 2):
        for metric in metrics:
            audit.add_paired(data, "model", a, b, metric, scope=scope,
                note="Fixed requested-model contrast, not a general intelligence ranking")


def with_post(trials, measured, study, horizon):
    measured = measured.copy()
    measured["phase"] = "r" + measured["round"].astype(int).astype(str)
    metadata = trials[[c for c in ["trial_id", "case_id", "model", "effort", "frame", "kind", "arm", "configuration_id"] if c in trials]]
    missing = [c for c in metadata if c not in measured or c == "trial_id"]
    measured = measured.merge(metadata[missing], on="trial_id", validate="many_to_one")
    post = metadata.copy()
    for metric in ["freedom", "impact", "counterfactual"]:
        post[metric] = trials[f"post_{metric}"].to_numpy()
    post["phase"] = "disclosed"
    result = normalized(pd.concat([measured, post], ignore_index=True), study)
    counts = result[result.phase != "disclosed"].groupby("trial_id").size()
    assert (counts == horizon).all()
    return result


def predictions_from_components(audit, study, trials):
    raw = audit.table(study, "predictions.csv")
    for column in ["matches_generator", "uncertain"]:
        raw[column] = raw[column].astype(str).str.lower().map({"true": 1, "false": 0, "1": 1, "0": 0})
        assert raw[column].notna().all()
    counts = raw.groupby("trial_id", sort=True).agg(n=("component", "size"),
                matches=("matches_generator", "sum"), uncertain=("uncertain", "sum"))
    audit.check(f"{study}: 12 prediction components per conversation", bool((counts.n == 12).all()))
    out = trials.merge(counts, on="trial_id", validate="one_to_one")
    original_match = "prediction_matches" if study == "s5" else "prediction_generator_matches"
    original_uncertain = "prediction_uncertain" if study == "s5" else "prediction_uncertain_components"
    audit.check(f"{study}: component aggregation matches published trial fields",
        bool((out.matches == out[original_match]).all() and (out.uncertain == out[original_uncertain]).all()))
    return prediction_metrics(out, study)


def prediction_metrics(trials, study):
    d = trials.copy()
    d["mismatches"] = 12 - d.matches - d.uncertain
    assert (d[["matches", "uncertain", "mismatches"]] >= 0).all().all()
    for name, col in [("match", "matches"), ("uncertain", "uncertain"), ("mismatch", "mismatches")]:
        d[f"prediction_{name}_fraction"] = d[col] / 12
    d["prediction_all12_match"] = (d.matches == 12).astype(float)
    d["prediction_all_uncertain"] = (d.uncertain == 12).astype(float)
    d["prediction_any_mismatch"] = (d.mismatches > 0).astype(float)
    d["phase"] = "prediction"
    return normalized(d, study)


def trajectory(measurements, study, horizon):
    games = measurements[measurements.phase.str.match(r"r\d+$")].copy()
    games["round_number"] = games.phase.str[1:].astype(int)
    keys = ["trial_id", "case_id", "configuration_id", "model", "effort", "frame", "kind", "arm"]
    rows = []
    for _, group in games.groupby("trial_id", sort=True):
        group = group.sort_values("round_number")
        assert len(group) == horizon
        row = {key:group.iloc[0][key] for key in keys}
        events = group.loc[group.joint == 1, "round_number"]
        first = int(events.iloc[0]) if len(events) else horizon + 1
        row.update(joint_round_fraction=float(group.joint.mean()),
                   mean_round_impact=float(group.impact.mean()),
                   event_free_rounds=min(first - 1, horizon),
                   ever_joint=float(len(events) > 0), first_joint=first if len(events) else np.nan,
                   early_joint=float(first < horizon),
                   early_persistent=float((group.loc[group.round_number >= first, "joint"] == 1).all()) if first < horizon else np.nan,
                   phase="trajectory")
        rows.append(row)
    return normalized(pd.DataFrame(rows), study)


def did(audit, data, *, inner_factor, inner_a, inner_b, outer_factor, outer_a, outer_b,
        metric, scope="all", headline=False):
    pairs, _, _, _ = paired_values(data, inner_factor, inner_a, inner_b, metric)
    reduced = pairs.rename(columns={"difference": metric}).drop(columns=["a", "b"])
    reduced[inner_factor] = "-"
    reduced["study"] = str(data.study.iloc[0])
    final, excluded, n_a, n_b = paired_values(reduced, outer_factor, outer_a, outer_b, metric)
    audit.add_pairs(final, test_id=f"{data.study.iloc[0]}:interaction:{inner_factor}({inner_a}-{inner_b})x{outer_factor}({outer_a}-{outer_b}):{scope}:{metric}",
        study=str(data.study.iloc[0]), metric=metric,
        contrast=f"({inner_a}-{inner_b}) in {outer_a} minus ({inner_a}-{inner_b}) in {outer_b}",
        scope=scope, headline=headline, excluded=excluded, n_a=n_a, n_b=n_b,
        binary_sensitivity=False,
        note="Difference-in-differences, constructed from distinct matched conversations; values are contrasts, not binary responses")


def load_and_analyze(audit):
    catalog = audit.json_source(Path("docs/experiments.json"))
    audit.check("six distinct completed studies", len(catalog["experiments"]) == 6)
    for experiment in catalog["experiments"]:
        saved_audit = audit.json_source(Path(experiment["audit"]))
        audit.check(f"{experiment['id']}: original native-record audit passed",
                    saved_audit.get("integrity_ok", saved_audit.get("passed")) is True)
    # Study 1. Keep valid partial endpoints; do not restrict everything to completion.
    s1 = audit.table("s1", "trials.csv")
    audit.check("s1 assigned/pre/post denominators", (len(s1), int(s1.pre_impact.notna().sum()), int(s1.post_impact.notna().sum())) == (2100, 2096, 2093),
                [len(s1), int(s1.pre_impact.notna().sum()), int(s1.post_impact.notna().sum())])
    pieces = []
    for phase in ["pre", "post"]:
        d = s1.copy()
        d["phase"] = phase
        for metric in ["impact", "freedom", "counterfactual"]:
            d[metric] = d[f"{phase}_{metric}"]
        pieces.append(d)
    d1 = normalized(pd.concat(pieces, ignore_index=True), "s1")
    audit.summarize(d1, GAME_METRICS)
    contrasts(audit, d1, "phase", "post", "pre", GAME_METRICS, configurations=True, headline_metric="impact",
              note="Descriptive pre/post bundle: information, elapsed time and another measurement change together")
    for phase in ["pre", "post"]:
        contrasts(audit, d1[d1.phase == phase], "frame", "cards", "cats", GAME_METRICS,
                  configurations=True, prefix=phase)
    effort_and_model(audit, d1[d1.phase == "pre"], CORE_METRICS, scope="pre")
    for scope, group in subsets(s1, configurations=True):
        audit.route(group, scope)
    original_estimates = audit.table("s1", "estimates.csv")
    route_results = {row["test_id"]: row for row in audit.tests if row["test_type"] == "observational_route_ols"}
    for original, name in [("primary_route_association", "route_equal_weight"),
                           ("route_KK_minus_DD", "route_KK_minus_DD"),
                           ("route_KD_minus_DK", "route_KD_minus_DK")]:
        selected_routes = original_estimates[original_estimates.metric == original]
        recomputed_routes = [route_results[f"s1:{name}:configuration={row.configuration_id}:pre_impact"]["estimate"]
                             for row in selected_routes.itertuples()]
        audit.check(f"s1 original {original} point estimates reproduced",
                    len(selected_routes) == 21 and bool(np.allclose(recomputed_routes, selected_routes.estimate, atol=1e-10, rtol=0)))
    print("Study 1 complete: endpoint-valid pairs and original route estimand.", flush=True)

    # Study 2. No treating three rounds as 1,260 independent conversations.
    s2 = audit.table("s2", "trials.csv")
    audit.check("s2 complete conversations", len(s2) == 420)
    parts = []
    for i, phase in enumerate(["r1", "r2", "r3", "disclosed"], 1):
        d = s2.copy()
        d["phase"] = phase
        for metric in ["impact", "freedom", "counterfactual"]:
            d[metric] = d[f"m{i}_{metric}"]
        parts.append(d)
    d2 = normalized(pd.concat(parts, ignore_index=True), "s2")
    audit.summarize(d2, GAME_METRICS)
    for a, b in [("r2", "r1"), ("r3", "r1"), ("r3", "r2"), ("disclosed", "r3")]:
        contrasts(audit, d2, "phase", a, b, GAME_METRICS, configurations=True,
                  headline_metric="impact" if (a, b) == ("r3", "r1") else None,
                  note="Repetition, conversation length and repeated measurements are not experimentally separated")
    for phase in ["r1", "r2", "r3", "disclosed"]:
        contrasts(audit, d2[d2.phase == phase], "frame", "cards", "cats", GAME_METRICS,
                  configurations=phase == "r3", prefix=phase)
    effort_and_model(audit, d2[d2.phase == "r3"], CORE_METRICS, scope="r3")
    print("Study 2 complete: conversation-paired trajectories, 10 case blocks.", flush=True)

    # Study 3. Q2-Q4 in one response: use their mean, never 6,048 independent units.
    s3 = audit.table("s3", "tasks.csv")
    audit.check("s3 valid single-response tasks", len(s3) == 2016 and bool((s3.valid == 1).all()))
    recomputed = s3[["new_arrangement_correct", "renaming_correct", "rule_change_correct"]].mean(axis=1)
    audit.check("s3 transfer score is Q2-Q4", bool(np.allclose(recomputed, s3.transfer_accuracy)))
    s3["transfer_accuracy"] = recomputed
    s3["phase"] = "supplied"
    d3 = normalized(s3, "s3")
    audit.summarize(d3, TRANSFER_METRICS)
    for a, b in [("conflicting", "neutral"), ("congruent", "neutral"), ("conflicting", "congruent")]:
        contrasts(audit, d3, "claim", a, b, ["transfer_accuracy"], configurations=True,
                  headline_metric="transfer_accuracy" if (a, b) == ("conflicting", "neutral") else None)
        for procedure, group in d3.groupby("procedure", sort=True):
            contrasts(audit, group, "claim", a, b, ["transfer_accuracy"], prefix=f"procedure={procedure}")
        for metric in TRANSFER_METRICS[1:]:
            audit.add_paired(d3, "claim", a, b, metric)
    for a, b, factor in [("cards", "cats", "frame"), ("fixed_target", "keep_selected", "procedure")]:
        contrasts(audit, d3, factor, a, b, ["transfer_accuracy"], configurations=True)
        for metric in TRANSFER_METRICS[1:]:
            audit.add_paired(d3, factor, a, b, metric)
    audit.omnibus(d3, "claim", "transfer_accuracy")
    effort_and_model(audit, d3, ["transfer_accuracy"], scope="supplied")
    print("Study 3 complete: supplied-rule tasks, 8 case blocks.", flush=True)

    data_by_study = {"s1": d1, "s2": d2, "s3": d3}
    trials_by_study = {"s1": s1, "s2": s2, "s3": s3}
    prediction_data = {}
    trajectories = {}
    for study, horizon, count in [("s4", 30, 28), ("s5", 10, 2520)]:
        trials = audit.table(study, "trials.csv")
        measured = audit.table(study, "measurements.csv")
        if study == "s4":
            trials["case_id"] = "single-shared-pilot-case"
            trials["effort"] = "low"
        audit.check(f"{study}: complete conversations/rounds", len(trials) == count and len(measured) == count * horizon,
                    [len(trials), len(measured)])
        d = with_post(trials, measured, study, horizon)
        audit.summarize(d, GAME_METRICS)
        final = d[d.phase == f"r{horizon}"]
        contrasts(audit, final, "kind", "obj", "seq", GAME_METRICS, configurations=study == "s5",
                  headline_metric="joint", prefix=f"r{horizon}")
        if study == "s5":
            for frame, group in final.groupby("frame", sort=True):
                contrasts(audit, group, "kind", "obj", "seq", CORE_METRICS,
                          configurations=True, prefix=f"r10;frame={frame}")
        for kind, group in final.groupby("kind", sort=True):
            contrasts(audit, group, "frame", "cards", "cats", GAME_METRICS,
                      configurations=study == "s5", prefix=f"r{horizon};kind={kind}",
                      headline_metric="joint" if kind == "obj" else None)
            if study == "s5":
                effort_and_model(audit, group, CORE_METRICS, scope=f"r10;kind={kind}")
        contrasts(audit, d[d.phase.isin(["r1", f"r{horizon}"])], "phase", f"r{horizon}", "r1",
                  GAME_METRICS, configurations=study == "s5", prefix="all_kinds")
        for kind, group in d[d.phase.isin(["r1", f"r{horizon}"])].groupby("kind", sort=True):
            contrasts(audit, group, "phase", f"r{horizon}", "r1", CORE_METRICS, prefix=f"kind={kind}")
        contrasts(audit, d[d.phase.isin([f"r{horizon}", "disclosed"])], "phase", "disclosed", f"r{horizon}",
                  GAME_METRICS, prefix="all_kinds",
                  note="Disclosure bundles explanation, exhaustive table, later time and another report")
        tr = trajectory(d, study, horizon)
        trajectories[study] = tr
        audit.summarize(tr, ["joint_round_fraction", "mean_round_impact", "event_free_rounds", "ever_joint", "early_joint", "early_persistent"])
        contrasts(audit, tr, "kind", "obj", "seq", ["joint_round_fraction", "mean_round_impact", "event_free_rounds"])
        pred = predictions_from_components(audit, study, trials)
        prediction_data[study] = pred
        audit.summarize(pred, PRED_METRICS)
        contrasts(audit, pred, "kind", "obj", "seq", PRED_METRICS, configurations=study == "s5")
        for kind, group in pred.groupby("kind", sort=True):
            contrasts(audit, group, "frame", "cards", "cats", PRED_METRICS, prefix=f"kind={kind}")
        if study == "s5":
            audit.check("s5 final joint counts", [int(final[final.kind == k].joint.sum()) for k in ["obj", "seq"]] == [319, 1])
            audit.check("s5 full prediction matches", [int(pred[pred.kind == k].prediction_all12_match.sum()) for k in ["obj", "seq"]] == [540, 97])
            persistence = [[int((g.early_joint == 1).sum()), int(g.early_persistent.sum())]
                           for _, g in tr.groupby("kind", sort=True)]
            audit.check("s5 early-transition/persistent counts: obj then seq", persistence == [[300, 284], [9, 0]], persistence)
            for metric in GAME_METRICS:
                did(audit, final, inner_factor="frame", inner_a="cards", inner_b="cats", outer_factor="kind",
                    outer_a="obj", outer_b="seq", metric=metric, headline=metric == "joint")
            for scope, group in subsets(final):
                if scope == "all":
                    continue
                for metric in CORE_METRICS:
                    did(audit, group, inner_factor="frame", inner_a="cards", inner_b="cats", outer_factor="kind",
                        outer_a="obj", outer_b="seq", metric=metric, scope=scope)
            for round_number in range(1, 11):
                current = d[d.phase == f"r{round_number}"]
                for metric in GAME_METRICS:
                    audit.add_paired(current, "kind", "obj", "seq", metric, scope=f"trajectory_r{round_number}")
        data_by_study[study] = d
        trials_by_study[study] = trials
        print(f"Study {study[1:]} complete: {count} conversations, prediction components aggregated within conversation.", flush=True)

    # Study 6: independent matched conversations, change-versus-control contrasts.
    s6 = audit.table("s6", "intervention_trials.csv")
    m6 = audit.table("s6", "intervention_measurements.csv")
    audit.check("s6 pre-question baseline", len(s6) == 180 and bool((s6.pre_impact == 100).all() and (s6.pre_joint == 0).all()))
    m6["phase"] = np.where(m6.phase == "game", "r" + m6["round"].astype(int).astype(str), m6.phase)
    m6["frame"], m6["kind"] = "cards", "seq"
    d6 = normalized(m6, "s6")
    audit.summarize(d6, GAME_METRICS)
    pre = d6[d6.phase == "r10"].copy()
    post = d6[d6.phase == "rerating"].copy()
    keys = [c for c in FACTORS if c != "phase"]
    changed = post.merge(pre[keys + GAME_METRICS], on=keys, suffixes=("", "_baseline"), validate="one_to_one")
    for metric in GAME_METRICS:
        changed[metric] = changed[metric] - changed[f"{metric}_baseline"]
    changed["phase"] = "change"
    for a, b in [("explanation", "control"), ("prediction", "control"), ("explanation", "prediction")]:
        for scope, group in subsets(changed):
            for metric in GAME_METRICS:
                audit.add_paired(group, "arm", a, b, metric, scope=scope,
                    headline=metric == "joint" and scope != "all" and b == "control" or
                    metric == "impact" and scope == "model=gpt-6.1-sol" and (a,b) == ("prediction","control"))
        for metric in GAME_METRICS:
            did(audit, changed, inner_factor="arm", inner_a=a, inner_b=b, outer_factor="model",
                outer_a="gpt-5.6-sol", outer_b="gpt-6.1-sol", metric=metric,
                headline=metric == "joint" and (a,b) == ("explanation","control"))
    for arm, group in d6[d6.phase.isin(["r10", "rerating", "disclosed"])].groupby("arm", sort=True):
        for a, b in [("rerating", "r10"), ("disclosed", "rerating")]:
            contrasts(audit, group, "phase", a, b, GAME_METRICS, prefix=f"arm={arm}")
    for metric in GAME_METRICS:
        audit.omnibus(changed, "arm", metric)
    p6 = audit.table("s6", "intervention_predictions.csv")
    summary = p6.groupby("trial_id", sort=True).state.agg(
        matches=lambda x:int((x == "match").sum()), uncertain=lambda x:int((x == "uncertain").sum()), n="size")
    audit.check("s6 prediction components", len(summary) == 60 and bool((summary.n == 12).all()))
    prediction = s6[s6.arm == "prediction"].merge(summary, on="trial_id", validate="one_to_one")
    audit.check("s6 prediction aggregation agrees with saved trial counts",
                bool((prediction.matches == prediction.prediction_matches).all() and
                     (prediction.uncertain == prediction.prediction_uncertain).all()))
    prediction["frame"], prediction["kind"] = "cards", "seq"
    prediction = prediction_metrics(prediction, "s6")
    audit.summarize(prediction, PRED_METRICS)
    for metric in PRED_METRICS:
        audit.add_paired(prediction, "model", "gpt-5.6-sol", "gpt-6.1-sol", metric,
                        note="Prediction-only arm; does not estimate an explanation-order effect")
    data_by_study["s6"] = d6
    trials_by_study["s6"] = s6
    coding = audit.table("s6", "existing_97_account_coding.csv")
    audit.check("selected existing rule accounts", len(coding) == 97 and
                int(coding.target_preserving_mapping_in_account.sum()) == 40)
    audit.coding = coding.groupby("target_preserving_mapping_in_account", dropna=False).size().reset_index(name="count").to_dict("records")
    print("Study 6 complete: matched question interventions and model-by-question contrasts.", flush=True)
    return data_by_study, trials_by_study, prediction_data, trajectories


def corrected_tables(audit):
    tests = pd.DataFrame(audit.tests).sort_values("test_id").reset_index(drop=True)
    audit.check("all computed principal/reference p-values are in (0,1]",
                bool(((tests.p_value.dropna() > 0) & (tests.p_value.dropna() <= 1)).all()))
    audit.check("missing p-values have an explicit non-estimable status",
                bool(tests.loc[tests.p_value.isna(), "status"].str.startswith("not_estimable").all()))
    primary = (tests.inference_scope == "case_block_reference") & tests.p_value.notna()
    tests["p_holm_global"] = np.nan
    tests.loc[primary, "p_holm_global"] = holm(tests.loc[primary, "p_value"])
    for column in ["p_holm_study", "q_bh_study", "p_holm_headline", "p_holm_pilot_reference"]:
        tests[column] = np.nan
    for study in RUNS:
        selected = primary & (tests.study == study)
        tests.loc[selected, "p_holm_study"] = holm(tests.loc[selected, "p_value"])
        tests.loc[selected, "q_bh_study"] = bh(tests.loc[selected, "p_value"])
    headline = primary & tests.headline.fillna(False)
    tests.loc[headline, "p_holm_headline"] = holm(tests.loc[headline, "p_value"])
    pilot = (tests.inference_scope == "fixed_model_panel_reference_only") & tests.p_value.notna()
    tests.loc[pilot, "p_holm_pilot_reference"] = holm(tests.loc[pilot, "p_value"])
    tests["p_display"] = tests.p_value.map(lambda p:probability_display(p) if finite(p) else "not estimable")
    tests["units"] = tests.metric.map(lambda m:"percentage points" if percent_metric(m) else "rounds" if m == "event_free_rounds" else "score points")
    scale = tests.metric.map(lambda m:100.0 if percent_metric(m) else 1.0)
    for column in ["estimate", "ci_low", "ci_high", "pooled_pair_estimate"]:
        tests[column + "_display_units"] = tests[column] * scale
    sensitivity = pd.DataFrame(audit.sensitivity).sort_values("test_id").reset_index(drop=True)
    # Holm in log space, including values too small to represent as IEEE floats.
    if len(sensitivity):
        order = np.argsort(sensitivity.log_p_value.to_numpy(), kind="stable")
        lp = sensitivity.log_p_value.to_numpy()[order]
        adjusted = np.minimum(0, np.maximum.accumulate(lp + np.log(np.arange(len(lp), 0, -1))))
        sensitivity["log_p_holm_sensitivity"] = np.nan
        sensitivity.loc[order, "log_p_holm_sensitivity"] = adjusted
        sensitivity["p_holm_display"] = sensitivity.log_p_holm_sensitivity.map(lambda lp:"p=" + probability_display(logp=lp))
    return tests, sensitivity


def md_table(frame, columns):
    def cell(value):
        if value is None or isinstance(value, float) and not np.isfinite(value):
            return "—"
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines += ["| " + " | ".join(cell(row.get(c)) for c in columns) + " |" for row in frame.to_dict("records")]
    return "\n".join(lines)


def effect_text(row):
    effect = row.get("estimate_display_units", np.nan)
    if not finite(effect):
        return "—"
    lo, hi = row.get("ci_low_display_units", np.nan), row.get("ci_high_display_units", np.nan)
    suffix = "pp" if row.get("units") == "percentage points" else "points"
    return f"{effect:+.3f} {suffix} [{lo:+.3f}, {hi:+.3f}]"


def report(audit, tests, sensitivity, data, trials, trajectories):
    output = audit.output
    principal = tests.inference_scope == "case_block_reference"
    headlines = tests[tests.headline.fillna(False)].copy()
    headlines["effect (95% CI)"] = headlines.apply(effect_text, axis=1)
    headlines["raw p"] = headlines.p_value.map(lambda p:probability_display(p) if finite(p) else "—")
    headlines["global Holm p"] = headlines.p_holm_global.map(lambda p:probability_display(p) if finite(p) else "pilot reference only")
    headlines["headline Holm p"] = headlines.p_holm_headline.map(lambda p:probability_display(p) if finite(p) else "—")
    counts = tests.groupby("study").agg(tests=("test_id", "size"), estimable=("p_value", "count"))
    counts["principal globally adjusted p < .05"] = tests[principal].groupby("study").p_holm_global.apply(lambda x:int((x < .05).sum()))
    counts = counts.fillna(0).reset_index()
    lookup = tests.set_index("test_id")
    key = {
        "disclosure": "s1:phase:post-minus-pre:all:impact",
        "repetition": "s2:phase:r3-minus-r1:all:impact",
        "claim": "s3:claim:conflicting-minus-neutral:all:transfer_accuracy",
        "schedule": "s5:kind:obj-minus-seq:r10;all:joint",
        "frame": "s5:frame:cards-minus-cats:r10;kind=obj;all:joint",
        "interaction": "s5:interaction:frame(cards-cats)xkind(obj-seq):all:joint",
        "explanation": "s6:arm:explanation-minus-control:model=gpt-5.6-sol:joint",
        "prediction": "s6:arm:prediction-minus-control:model=gpt-5.6-sol:joint",
        "impact": "s6:arm:prediction-minus-control:model=gpt-6.1-sol:impact",
    }
    selected = {name: lookup.loc[test_id] for name, test_id in key.items()}
    adj = lambda name: probability_display(selected[name].p_holm_global)
    raw = lambda name: probability_display(selected[name].p_value)
    effect = lambda name: effect_text(selected[name])
    transfer = data["s3"].transfer_accuracy.mean() * 100
    findings_en = [
        f"- **Study 1:** the post-minus-pre impact contrast is {effect('disclosure')}; global Holm p={adj('disclosure')}. "
        "Initial ratings are almost all 100, limiting route comparisons. Disclosure also changes information, time and measurement.",
        f"- **Study 2:** round 3 minus round 1 is {effect('repetition')}; raw p={raw('repetition')}, global Holm p={adj('repetition')}. "
        "The descriptive reduction does not survive the full-audit correction; only ten case families are available.",
        f"- **Study 3:** supplied-rule transfer accuracy is {transfer:.3f}%. Conflicting-minus-neutral is {effect('claim')}; "
        f"global Holm p={adj('claim')}. Eight case families and near-ceiling accuracy do not support an equivalence claim.",
        "- **Study 4:** 5/14 constant-target versus 0/14 sequence conversations end at the joint endpoint. "
        "There is one shared case; the pilot does not supply replicated case-level inference.",
        f"- **Study 5:** constant-minus-sequence joint reports differ by {effect('schedule')} (global Holm p={adj('schedule')}). "
        f"Within constant targets, cards-minus-cats is {effect('frame')} (p={adj('frame')}). "
        f"The schedule-by-frame interaction also survives global correction (p={adj('interaction')}). "
        "Frames bundle nouns, labels, action verbs and feedback, so this does not isolate a noun-only effect.",
        f"- **Study 6:** gpt-5.6-sol's explanation-minus-control joint-report change is {effect('explanation')} "
        f"(global Holm p={adj('explanation')}); its prediction-minus-control difference has raw p={raw('prediction')} "
        f"and global Holm p={adj('prediction')}. For gpt-6.1-sol, prediction reduces impact by 50 points "
        f"(global Holm p={adj('impact')}) while joint reports stay at zero. This intermediate rating change is a distinct endpoint.",
    ]
    findings_ko = [
        f"- **가장 뚜렷한 결과는 고정 오브젝트와 시퀀스의 차이:** 10라운드 반복 실험의 공동 응답 차이는 "
        f"{effect('schedule')}, 전체 Holm 보정 p={adj('schedule')}이다.",
        f"- **카드·캣 차이도 남는다:** 고정 오브젝트 조건에서 {effect('frame')}, 보정 p={adj('frame')}. "
        f"조건×프레이밍 상호작용의 보정 p={adj('interaction')}. 명사·선택 표현·피드백이 함께 달라져 명사만의 효과로 해석할 수는 없다.",
        f"- **질문 효과는 모델과 지표별로 다르다:** gpt-5.6-sol에서 설명 질문은 대조군보다 공동 응답을 "
        f"{effect('explanation')} 늘렸다(보정 p={adj('explanation')}). 예측 질문의 +10pp 차이는 유의하지 않다"
        f"(원 p={raw('prediction')}, 보정 p={adj('prediction')}). gpt-6.1-sol의 예측 질문은 공동 응답을 늘리지 않았지만 "
        f"영향력 점수를 50점 낮췄다(보정 p={adj('impact')}).",
        f"- **나머지 실험:** 1회 실험의 공개 전후 영향력 차이는 유의했다(보정 p={adj('disclosure')}). "
        f"3회 반복의 평균 하락은 원 p={raw('repetition')}이지만 전체 보정 후 p={adj('repetition')}. "
        f"규칙 제공 과제의 정답률은 {transfer:.3f}%이나 주장 프레이밍 차이는 보정 p={adj('claim')}. "
        "30라운드 파일럿은 공유 사례가 하나여서 주 검정 근거에서 분리했다.",
    ]
    title = "# Statistical supplement: six completed studies\n"
    text = [title, f"Retrospective audit **{VERSION}**; all outputs are derived from preserved local records. No new model calls.",
        "[Methods, assumptions and multiplicity](STATISTICAL_METHODS.md) · [한국어 요약](STATISTICS.ko.md) · [Original studies](EXPERIMENTS.md)",
        "## Read this first", "These p-values are exploratory. The original outcomes were already known. "
        "The main analyses match conversations/tasks and then aggregate their differences within shared case families. "
        "The fixed requested-model panel is not a random sample of models. The primary p-values use **50, 10, 8, 30 and 30 case blocks** in Studies 1, 2, 3, 5 and 6. "
        "Study 4 has one shared case and only a separately labeled seven-model fixed-panel reference analysis.",
        "Effects are case-weighted means. Bracketed intervals are nominal **pointwise** 95% intervals, not multiplicity-adjusted simultaneous intervals. "
        "A degenerate interval at a boundary does not establish zero population uncertainty. Global Holm p-values adjust over every estimable principal test, including omnibus and route tests.",
        "## What the results support", "\n".join(findings_en),
        "## Headline contrasts", md_table(headlines, ["study", "contrast", "scope", "metric", "n_pairs", "n_blocks", "effect (95% CI)", "raw p", "global Holm p", "headline Holm p"]),
        "## Complete coverage", md_table(counts, list(counts)),
        "This table counts scripted audit comparisons, not discoveries or independent scientific claims. "
        "Constant/no-difference tests remain in the multiplicity family. See the full tables for all null results and limitations.",
        "## Figures", "![Matched case-block headline effects](data/statistics-2026-10-23/figures/headline_effects.png)",
        "![Frame differences by model in the replication](data/statistics-2026-10-23/figures/frame_by_model.png)",
        "![Question interventions by model and endpoint](data/statistics-2026-10-23/figures/question_effects.png)",
        "## Data and reproducible outputs", "All result files are in [the supplement directory](data/statistics-2026-10-23).",]
    files = [("contrasts.csv", "All paired, route and omnibus tests; raw/adjusted p-values, effects, intervals, units and status"),
             ("case_blocks.csv", "The actual case-block differences used by paired tests"),
             ("sensitivity_mcnemar.csv", "Exact McNemar sensitivities, discordant pairs and stable log p-values"),
             ("descriptives.csv", "All cell, model, condition and overall endpoint summaries"),
             ("source_manifest.json", "Input SHA-256, row counts, columns, versions, analysis seed and code hashes"),
             ("validation.json", "Assertions that the six historical denominators and key aggregates match"),
             ("rule_coding_descriptive.csv", "Selected account coding, descriptive only"),
             ("report.html", "Offline searchable/filterable table; download and open locally"),
             ("reproduction.json", "Deterministic output hashes; use --check to compare a fresh generation")]
    text += ["\n".join(f"- [{name}](data/statistics-2026-10-23/{name}): {description}." for name, description in files)]
    persistence = trajectories["s5"]
    persistence_rows = []
    for kind, group in persistence.groupby("kind", sort=True):
        selected = group[group.early_joint == 1]
        persistence_rows.append(dict(kind=kind, early_joint_conversations=len(selected),
            persistent=int(selected.early_persistent.sum()),
            persistent_rate=float(selected.early_persistent.mean()) if len(selected) else np.nan))
    text += ["## Interpretation boundaries", "- The joint endpoint is an impact-1/counterfactual-no **report**, not private knowledge. "
        "Prediction matches concern the actual generator; other generators can be observationally compatible. Uncertainty is not an explicit mismatch.\n"
        "- Studies 1–2 disclosure/time contrasts do not isolate causal effects of disclosure or repetition. Routes are endogenous associations.\n"
        "- Study 3 has eight case families and near-ceiling supplied-rule accuracy. Non-significant host-claim contrasts are not equivalence findings.\n"
        "- Model and effort contrasts describe requested configurations on these cases, not general intelligence or independently attested internal model versions.\n"
        "- Existing account coding is a single-coordinator, selected review without independent gold-standard validation; no latent-knowledge significance test is attached.\n"
        "- Do not compare the older explanation→prediction cohort with the newer prediction-only arm as a randomized order experiment.",
        "### Persistence: descriptive, conditional on an early transition", md_table(pd.DataFrame(persistence_rows), list(persistence_rows[0])),
        "Conditioning on an observed early transition changes the population and opportunity to reverse. These selected denominators are retained descriptively rather than treated as randomized groups.",
        "## Reproduce", "```bash\npython -m pip install -r analysis/requirements-statistics.txt\npython -m unittest discover -s tests -p 'test_statistics.py' -v\npython scripts/statistical_audit.py --check\npython scripts/validate_repository_docs.py\n```",
        "A plain run regenerates only the new supplement. `--check` regenerates into a temporary directory and verifies every published supplement byte and generated guide. "
        f"Monte Carlo reference distributions use {audit.permutations:,} resamples; bootstrap intervals use {audit.bootstrap:,}. Seeds derive deterministically from each contrast ID. "
        "Byte-for-byte verification requires the recorded Python/library/font environment. "
        "The script imports no runner/transport and depends only on local CSV exports; it does not require a model login."]
    english = "\n\n".join(text) + "\n"
    korean = ["# 여섯 실험의 통계 분석 요약", f"분석 버전: **{VERSION}**. 기존 결과를 이미 알고 수행한 **사후 탐색 분석**이다. 원자료와 기존 보고서는 보존했다.",
        "[전체 결과·그림·재현 방법](STATISTICS.md) · [검정의 가정과 한계](STATISTICAL_METHODS.md)",
        "## 핵심 결과", "\n".join(findings_ko),
        "## 검정 단위", "같은 대화의 라운드·전후 응답·예측 12개 구성요소를 독립 표본으로 세지 않았다. "
        "비교 조건을 같은 사례와 설정끼리 짝지은 뒤, 여러 설정에서 공유하는 **사례군 전체를 한 블록**으로 묶었다. "
        "대규모 반복 실험은 대화 1,260쌍을 비교하지만 주 검정의 사례 블록은 30개다. "
        "30라운드 파일럿은 사례가 하나여서, 고정된 7개 모델 패널에 대한 제한적인 참고 검정만 별도로 제시한다.",
        "`공동 응답`은 영향력 1점이면서 반사실 질문에 no를 답한 경우다. 규칙 이해나 사적 믿음을 직접 측정한 지표는 아니다.",
        "## 주요 비교", md_table(headlines, ["study", "contrast", "scope", "metric", "n_pairs", "n_blocks", "effect (95% CI)", "raw p", "global Holm p"]),
        "`pp`는 퍼센트포인트, `points`는 평정 점수 차이다. 95% 구간은 개별 비교용이며 다중비교 보정 구간이 아니다. "
        "`global Holm p`는 이번 감사의 전체 주 검정을 함께 보정한다. 전체 유의하지 않은 결과도 CSV에 남겼다.",
        "## 해석할 때", "- **유의한 응답 차이가 곧 트릭 이해나 사적 믿음의 증거는 아니다.**\n"
        "- 예측의 불확실 응답과 실제 생성 규칙에 대한 명시적 불일치는 구분했다.\n"
        "- 100점 또는 1점만 반복되어 신뢰구간이 한 점이 될 수 있다. 모집단 불확실성까지 0이라는 뜻은 아니다.\n"
        "- 유의하지 않음은 효과 없음·동등성의 증명이 아니다.\n"
        "- 규칙 공개 전후에는 시간·정보·측정이 함께 달라졌다. p값만으로 공개나 반복의 단독 인과효과를 주장할 수 없다.\n"
        "- 모델·추론량 비교는 요청한 설정과 이번 사례에 한정된다.",
        "모든 검정·효과크기·신뢰구간·보정 p값은 [contrasts.csv](data/statistics-2026-10-23/contrasts.csv)에, "
        "대화 단위 McNemar 참고 검정은 [별도 표](data/statistics-2026-10-23/sensitivity_mcnemar.csv)에 있다. "
        "[HTML 표](data/statistics-2026-10-23/report.html)는 내려받아 열면 연구·지표·검색어로 필터링할 수 있다."]
    return english, "\n\n".join(korean) + "\n"


def plots(audit, tests):
    destination = audit.output / "figures"
    destination.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.hashsalt": VERSION})
    def save(fig, name):
        fig.savefig(destination / f"{name}.png", dpi=180, bbox_inches="tight", metadata={"Software": "equivoque statistical audit"})
        fig.savefig(destination / f"{name}.svg", bbox_inches="tight", metadata={"Date": None})
        plt.close(fig)
    chosen = tests[(tests.headline.fillna(False)) & (tests.metric == "joint") & (tests.study != "s4")]
    fig, ax = plt.subplots(figsize=(10, max(3.5, .48 * len(chosen))))
    for index, (_, row) in enumerate(chosen.iterrows()):
        value, lo, hi = [row[c] for c in ["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]]
        ax.errorbar(value, index, xerr=[[max(0,value-lo)], [max(0,hi-value)]], fmt="o", color="#176787", capsize=3)
    ax.set_yticks(range(len(chosen)), [f"{r.study} | {r.scope}\n{r.contrast}" for r in chosen.itertuples()])
    ax.axvline(0, color="#999", lw=1)
    ax.invert_yaxis()
    ax.set_xlabel("Matched case-block difference in joint reports (percentage points)")
    ax.set_title("Retrospective contrasts; pointwise 95% case-block bootstrap intervals")
    save(fig, "headline_effects")
    frame = tests[(tests.study == "s5") & (tests.contrast == "frame: cards minus cats") & (tests.metric == "joint") & tests.scope.str.startswith("r10;kind=obj;model=")]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for index, (_, row) in enumerate(frame.iterrows()):
        v, lo, hi = [row[c] for c in ["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]]
        ax.errorbar(v, index, xerr=[[max(0,v-lo)], [max(0,hi-v)]], fmt="o", color="#176787", capsize=3)
    ax.set_yticks(range(len(frame)), frame.scope.str.split("model=").str[-1])
    ax.axvline(0, color="#999", lw=1)
    ax.invert_yaxis()
    ax.set_xlabel("Cards minus cats: joint reports (percentage points)")
    ax.set_title("Study 5, constant targets; requested models, effort averaged")
    save(fig, "frame_by_model")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, metric in zip(axes, ["joint", "impact"]):
        current = tests[(tests.study == "s6") & (tests.test_type == "paired_mean") & (tests.metric == metric) & tests.scope.str.startswith("model=") & tests.contrast.isin(["arm: explanation minus control", "arm: prediction minus control"])]
        for index, (_, row) in enumerate(current.iterrows()):
            v, lo, hi = [row[c] for c in ["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]]
            ax.errorbar(v, index, xerr=[[max(0,v-lo)], [max(0,hi-v)]], fmt="o", color="#176787", capsize=3)
        ax.set_yticks(range(len(current)), [f"{r.scope.removeprefix('model=')}\n{r.contrast.removeprefix('arm: ')}" for r in current.itertuples()])
        ax.axvline(0, color="#999", lw=1)
        ax.invert_yaxis()
        ax.set_xlabel("Difference in change (pp)" if metric == "joint" else "Difference in impact change (score points)")
        ax.set_title("Joint report" if metric == "joint" else "Impact rating")
    fig.suptitle("Study 6: matched-case question contrasts, before disclosure")
    fig.tight_layout()
    save(fig, "question_effects")


def html_report(tests):
    columns = ["test_id", "study", "contrast", "scope", "metric", "n_pairs", "n_blocks",
               "estimate_display_units", "ci_low_display_units", "ci_high_display_units", "units",
               "p_value", "p_holm_global", "p_holm_study", "p_holm_headline", "q_bh_study",
               "status", "method", "inference_scope", "ci_degenerate", "note"]
    table = tests.reindex(columns=columns).astype(object)
    rows = table.where(pd.notna(table), None).to_dict("records")
    payload = json.dumps(rows, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    labels = "".join(f'<option value="{s}">{s}: {html.escape(TITLES[s])}</option>' for s in RUNS)
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Equivoque: retrospective statistical audit</title><style>
body{font:15px system-ui,sans-serif;margin:2rem;color:#182936}h1{font-size:1.7rem}p{max-width:1000px;line-height:1.6}
input,select,button{font:inherit;padding:.45rem;margin:.3rem}table{border-collapse:collapse;font-size:12px;white-space:nowrap}
th,td{padding:.5rem;border-bottom:1px solid #d9e0e5;text-align:left}th{position:sticky;top:0;background:#e6f0f5;cursor:pointer}
.scroll{overflow:auto;max-height:75vh}tr:hover{background:#f1f7fa}.note{background:#fff3d9;padding:1rem}#count{font-weight:bold}
</style><h1>Six completed studies: statistical supplement</h1>
<p>Retrospective, exploratory analysis. Principal tests use paired case-family blocks; rounds and prediction components are not independent samples.
P-values are two-sided reference tests under the assumptions in STATISTICAL_METHODS.md. Raw, global Holm and study Holm p-values are distinct.
Intervals are pointwise, and constant boundary data can produce degenerate intervals. Pilot model-panel tests are separately labeled.</p>
<p class="note">A joint impact-1/counterfactual-no report is not private mechanism knowledge. An uncertain prediction is not an explicit mismatch.
Read the generated Markdown guide for source hashes, caveats and reproduction commands. Click a column heading to sort.</p>
<label>Study <select id="study"><option value="">All</option>""" + labels + """</select></label>
<label>Search <input id="query" placeholder="metric, model, frame, contrast..."></label>
<label><input type="checkbox" id="sig">Global Holm p &lt; .05</label><button id="reset">Reset</button>
<p id="count"></p><div class="scroll"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script id="data" type="application/json">""" + payload + """</script><script>
const data=JSON.parse(document.getElementById('data').textContent), cols=Object.keys(data[0]);let sort=null,up=true;
const esc=x=>String(x??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=x=>typeof x==='number'?(Math.abs(x)>0&&Math.abs(x)<.001?x.toExponential(4):Number(x.toPrecision(7))):esc(x);
document.getElementById('head').innerHTML='<tr>'+cols.map(c=>'<th data-col="'+c+'">'+esc(c)+'</th>').join('')+'</tr>';
function render(){const s=document.getElementById('study').value,q=document.getElementById('query').value.toLowerCase(),sig=document.getElementById('sig').checked;
let rows=data.filter(r=>(!s||r.study===s)&&(!q||JSON.stringify(r).toLowerCase().includes(q))&&(!sig||(r.p_holm_global!==null&&r.p_holm_global<.05)));
if(sort)rows.sort((a,b)=>{let x=a[sort],y=b[sort];if(x===null)return 1;if(y===null)return -1;return (typeof x==='number'?x-y:String(x).localeCompare(String(y)))*(up?1:-1)});
document.getElementById('count').textContent=rows.length+' of '+data.length+' retained tests';
document.getElementById('body').innerHTML=rows.map(r=>'<tr>'+cols.map(c=>'<td>'+fmt(r[c])+'</td>').join('')+'</tr>').join('');}
document.getElementById('head').onclick=e=>{const c=e.target.dataset.col;if(c){up=sort===c?!up:true;sort=c;render()}};
for(const id of ['study','query','sig'])document.getElementById(id).addEventListener('input',render);
document.getElementById('reset').onclick=()=>{document.getElementById('study').value='';document.getElementById('query').value='';document.getElementById('sig').checked=false;sort=null;render()};render();
</script></html>"""


def generate(root, output, *, bootstrap=20000, permutations=99999, write_guides=True):
    output.mkdir(parents=True, exist_ok=True)
    audit = Audit(root, output, bootstrap, permutations)
    data, trials, predictions, trajectories = load_and_analyze(audit)
    tests, sensitivity = corrected_tables(audit)
    def csv(frame, name):
        frame.to_csv(output / name, index=False, float_format="%.17g", lineterminator="\n")
    csv(tests, "contrasts.csv")
    csv(pd.DataFrame(audit.blocks).sort_values(["test_id", "block_id"]), "case_blocks.csv")
    csv(sensitivity, "sensitivity_mcnemar.csv")
    csv(pd.DataFrame(audit.descriptives), "descriptives.csv")
    csv(pd.DataFrame(audit.coding), "rule_coding_descriptive.csv")
    for study, frame in trajectories.items():
        csv(frame, f"{study}_conversation_trajectories.csv")
    manifest = dict(analysis_version=VERSION, seed=20261023, bootstrap_resamples=bootstrap,
        monte_carlo_resamples=permutations,
        source_basis_commit="d36fdfa8abbb2ed5e569d7a6ea5f930f6d8af51b",
        scope="Retrospective case-block reference inference conditional on fixed requested-model panel",
        versions=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                      pandas=pd.__version__, matplotlib=matplotlib.__version__),
        inputs=sorted(audit.sources, key=lambda x:x["path"]),
        code_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                     for name in ["scripts/statistical_audit.py", "scripts/statistics_core.py", "docs/STATISTICAL_METHODS.md"]},
        test_counts=dict(retained=len(tests), principal=int(((tests.inference_scope == "case_block_reference") & tests.p_value.notna()).sum()),
                         pilot_references=int((tests.inference_scope == "fixed_model_panel_reference_only").sum()),
                         mcnemar_sensitivities=len(sensitivity)))
    (output / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (output / "validation.json").write_text(json.dumps(dict(passed=True, checks=audit.checks), indent=2, ensure_ascii=False) + "\n")
    plots(audit, tests)
    (output / "report.html").write_text(html_report(tests))
    english, korean = report(audit, tests, sensitivity, data, trials, trajectories)
    if write_guides:
        (root / "docs/STATISTICS.md").write_text(english)
        (root / "docs/STATISTICS.ko.md").write_text(korean)
    hashes = {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.rglob("*")) if p.is_file() and p.name != "reproduction.json"}
    reproduction = dict(analysis_version=VERSION, deterministic_output_sha256=hashes,
        generated_guides_sha256={"docs/STATISTICS.md":hashlib.sha256(english.encode()).hexdigest(),
                                "docs/STATISTICS.ko.md":hashlib.sha256(korean.encode()).hexdigest()})
    (output / "reproduction.json").write_text(json.dumps(reproduction, indent=2) + "\n")
    return tests, reproduction, english, korean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Regenerate in a temporary directory and compare all published outputs")
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument("--permutations", type=int, default=99999)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.bootstrap < 100 or args.permutations < 999:
        parser.error("Use >=100 bootstrap draws and >=999 Monte Carlo permutations")
    destination = ROOT / args.output
    if args.check:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="equivoque-statistics-") as temporary:
            _, reproduced, english, korean = generate(ROOT, Path(temporary), bootstrap=args.bootstrap,
                                                     permutations=args.permutations, write_guides=False)
            expected = json.loads((destination / "reproduction.json").read_text())
            if reproduced != expected:
                differing = [name for name, digest in expected["deterministic_output_sha256"].items()
                             if reproduced["deterministic_output_sha256"].get(name) != digest]
                raise AssertionError(f"Supplement reproduction mismatch: {differing}")
            for name, text in [("docs/STATISTICS.md", english), ("docs/STATISTICS.ko.md", korean)]:
                assert (ROOT / name).read_text() == text, f"Generated guide mismatch: {name}"
        print("PASS: all supplement tables, figures, HTML, manifests and both generated guides reproduce byte for byte; no model calls.")
    else:
        tests, _, _, _ = generate(ROOT, destination, bootstrap=args.bootstrap, permutations=args.permutations)
        print(f"Generated {len(tests)} retained tests in {destination.relative_to(ROOT)}; no model calls.")
        print(tests[tests.headline.fillna(False)][["test_id", "estimate_display_units", "p_value", "p_holm_global"]].to_string(index=False))


if __name__ == "__main__":
    main()
