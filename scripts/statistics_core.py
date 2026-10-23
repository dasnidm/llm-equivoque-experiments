"""Offline statistical primitives for the explicitly retrospective audit.

No experiment runner or model transport is imported by this module.
"""
from __future__ import annotations

from fractions import Fraction
from functools import reduce
import hashlib
import math

import numpy as np
from scipy import special, stats


def seed_for(label: str, seed: int = 20261023) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{label}".encode()).digest()[:8], "big")


def holm(values):
    """Holm family-wise correction, preserving missing entries and input order."""
    p = np.asarray(values, dtype=float)
    out = np.full(p.shape, np.nan)
    good = np.flatnonzero(np.isfinite(p))
    order = good[np.argsort(p[good], kind="stable")]
    if len(order):
        out[order] = np.minimum(1, np.maximum.accumulate(p[order] * np.arange(len(order), 0, -1)))
    return out


def bh(values):
    p = np.asarray(values, dtype=float)
    out = np.full(p.shape, np.nan)
    good = np.flatnonzero(np.isfinite(p))
    order = good[np.argsort(p[good], kind="stable")]
    if len(order):
        q = p[order] * len(order) / np.arange(1, len(order) + 1)
        out[order] = np.minimum(1, np.minimum.accumulate(q[::-1])[::-1])
    return out


def signflip_mean(differences, *, seed=20261023, resamples=99999, max_lattice=200000):
    """Two-sided paired block sign-flip reference test on the mean contrast.

    Exact on a small rational lattice; otherwise Monte Carlo with a plus-one
    correction. Exchangeability/sign symmetry of *blocks* is an assumption,
    not a claim that the historical studies randomized every manipulation.
    """
    d = np.asarray(differences, dtype=float)
    if d.ndim != 1 or not len(d) or not np.all(np.isfinite(d)):
        raise ValueError("Expected a nonempty finite vector of block differences")
    d = d[np.abs(d) > 1e-12]
    if not len(d):
        return dict(p_value=1.0, method="exact_signflip_no_observed_difference", permutations=1, mc_se=0.0)
    if np.all(d > 0) or np.all(d < 0):
        p = math.ldexp(1.0, 1 - len(d))
        return dict(p_value=p, method="exact_signflip_one_direction", permutations=2 ** len(d), mc_se=0.0)
    observed = abs(float(d.sum()))
    if observed < 1e-12:
        return dict(p_value=1.0, method="exact_signflip_zero_mean", permutations=2 ** len(d), mc_se=0.0)
    # Rational reconstruction is verified before calling a result exact.
    fractions = [Fraction(float(x)).limit_denominator(100000) for x in d]
    scale = 1
    for f in fractions:
        scale = math.lcm(scale, f.denominator)
        if scale > 10 ** 10:
            break
    if scale <= 10 ** 10:
        integer = [f.numerator * (scale // f.denominator) for f in fractions]
        divisor = reduce(math.gcd, (abs(x) for x in integer))
        integer = np.array([x // divisor for x in integer], dtype=np.int64)
        weights = np.abs(integer)
        total = int(weights.sum())
        if total <= max_lattice and np.allclose(integer * divisor / scale, d, atol=1e-10, rtol=0):
            dp = np.array([1.0])
            for w in weights:
                w = int(w)
                new = np.zeros(len(dp) + w)
                new[:len(dp)] += dp * .5
                new[w:] += dp * .5
                dp = new
            assert abs(dp.sum() - 1) < 1e-12
            tail = np.abs(2 * np.arange(total + 1) - total) >= abs(int(integer.sum()))
            p = float(dp[tail].sum())
            return dict(p_value=min(1.0, p), method="exact_signflip_integer_lattice", permutations=2 ** len(d), mc_se=0.0)
    rng = np.random.default_rng(seed)
    exceed = 0
    for start in range(0, resamples, 4096):
        count = min(4096, resamples - start)
        signs = 2 * rng.integers(0, 2, size=(count, len(d)), dtype=np.int8) - 1
        exceed += int(np.count_nonzero(np.abs(signs @ d) >= observed - 1e-10))
    p = (exceed + 1) / (resamples + 1)
    return dict(p_value=p, method="monte_carlo_signflip_plus_one", permutations=resamples,
                mc_se=math.sqrt(p * (1 - p) / (resamples + 1)))


def bootstrap_mean(differences, *, seed, resamples=20000):
    d = np.asarray(differences, dtype=float)
    if d.ndim != 1 or not len(d) or not np.all(np.isfinite(d)):
        raise ValueError("Expected nonempty finite block differences")
    if np.ptp(d) < 1e-12:
        return float(d.mean()), float(d.mean())
    rng = np.random.default_rng(seed)
    values = np.empty(resamples)
    for start in range(0, resamples, 4096):
        count = min(4096, resamples - start)
        values[start:start + count] = d[rng.integers(0, len(d), size=(count, len(d)))].mean(axis=1)
    return tuple(float(x) for x in np.quantile(values, [.025, .975]))


def mcnemar_logp(a_only: int, b_only: int) -> float:
    """Log exact two-sided McNemar p; remains finite for >1,000 discordances."""
    n = int(a_only + b_only)
    if not n:
        return 0.0
    k = np.arange(min(a_only, b_only) + 1)
    log_mass = special.gammaln(n + 1) - special.gammaln(k + 1) - special.gammaln(n - k + 1) - n * math.log(2)
    return min(0.0, float(math.log(2) + special.logsumexp(log_mass)))


def probability_display(p=None, *, logp=None):
    if logp is not None and math.isfinite(logp):
        if logp < -700:
            exponent = math.floor(logp / math.log(10))
            coefficient = math.exp(logp - exponent * math.log(10))
            return f"{coefficient:.3f}e{exponent}"
        p = math.exp(logp)
    if p is None or not math.isfinite(float(p)):
        return "not estimable"
    if p == 0:
        raise ValueError("Do not publish a numerical underflow as p = 0")
    return f"{p:.3e}" if p < .001 else f"{p:.4f}"


def rank_omnibus(matrix, *, seed, resamples=99999):
    """Within-case condition-label permutation test of Friedman rank sums.

    Each row is a *case-averaged* vector, not a conversation/round/component.
    Monte Carlo is used instead of the small-sample chi-square approximation.
    """
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or len(x) < 2 or x.shape[1] < 3 or not np.all(np.isfinite(x)):
        raise ValueError("Need >=2 complete blocks and >=3 levels")
    n, k = x.shape
    ranked = stats.rankdata(x, axis=1) - (k + 1) / 2
    observed = float(np.sum(ranked.sum(axis=0) ** 2))
    if observed < 1e-12:
        return dict(p_value=1.0, method="exact_rank_permutation_zero_statistic", permutations=1,
                    mc_se=0.0, statistic=0.0, kendalls_w=0.0)
    ties = sum(sum(c ** 3 - c for c in np.unique(row, return_counts=True)[1]) for row in x)
    correction = 1 - ties / (n * (k ** 3 - k))
    q = 12 * observed / (n * k * (k + 1) * correction) if correction > 0 else 0.0
    rng = np.random.default_rng(seed)
    exceed = 0
    for start in range(0, resamples, 1024):
        count = min(1024, resamples - start)
        order = np.argsort(rng.random((count, n, k)), axis=2)
        shuffled = np.take_along_axis(np.broadcast_to(ranked, (count, n, k)), order, axis=2)
        null = np.sum(shuffled.sum(axis=1) ** 2, axis=1)
        exceed += int(np.count_nonzero(null >= observed - 1e-10))
    p = (exceed + 1) / (resamples + 1)
    return dict(p_value=p, method="monte_carlo_within_case_rank_permutation_plus_one",
                permutations=resamples, mc_se=math.sqrt(p * (1 - p) / (resamples + 1)),
                statistic=q, kendalls_w=q / (n * (k - 1)))
