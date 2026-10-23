# Retrospective statistical audit: methods

Analysis date: **2026-10-23**. This is a new, explicitly retrospective supplement
to six completed studies. Their results were already known when this analysis
was requested. These p-values are **exploratory**, not newly preregistered or
confirmatory results. Original data, protocols, archives and published reports
are not edited. No new model calls are made.

## Questions and coverage

- Study 1: the original equal-weight route association and secondary KK–DD and
  KD–DK associations, disclosure changes,
  card/cat contrasts, and model/effort differences.
- Study 2: round 2 versus 1, round 3 versus 1 and 2, disclosure versus round 3,
  frame contrasts and model/effort differences at round 3.
- Study 3: all three host-claim pairings, procedure and frame contrasts,
  model/effort differences, transfer accuracy and its constituent items.
- Study 4: final and trajectory outcomes, frame/schedule/disclosure contrasts
  as **limited fixed-panel sensitivity analyses**. There is only one shared
  case/schedule, so population case-level inference is unavailable.
- Study 5: schedule, frame, schedule-by-frame contrasts, model/effort
  differences, first-report timing, trajectories, predictions and uncertainty.
- Study 6: all question-arm pairings by model and over the fixed two-model
  panel; changes in impact, freedom, counterfactual-no and the joint endpoint;
  model-by-question interactions; disclosure changes and prediction forms.

This is a coverage-oriented analysis, not a search for whichever test gives the
smallest p-value. Technical failures, selected persistence subsets and manual
rule-account coding remain descriptive: they do not provide randomized
comparisons or an independent gold standard for private mechanism knowledge.
Cross-study order comparisons are not randomized question-order experiments.

## Units, matching and estimands

The observation unit is a **conversation** (Studies 1, 2, 4, 5, 6), or a single
response task (Study 3). Repeated rounds, pre/post responses and the 12 prediction
components are not independent observations. The fixed requested model/effort
panel is not a random sample of all possible models.

Case families are shared across conditions and configurations: **50, 10, 8,
1, 30, 30** in Studies 1–6 respectively. Matched differences first use the same
case/configuration and all applicable unchanged factors. Those differences are
then averaged **within case family** before inferential calculations. Thus a
large pooled schedule contrast in Study 5 has 1,260 matched conversation pairs
but **30 case blocks**, not 1,260 independent case replicates. Prediction
components are summarized within conversation first.

The primary effect is the equally weighted mean of these case-block
differences, conditional on the tested fixed configuration panel. Binary or
fractional differences are displayed in **percentage points**; ratings in score
points. Missing endpoints are not imputed. A contrast uses only endpoint-valid
matched pairs. With Study 1's missing values, an equal-case effect can differ
slightly from a pooled conversation-weighted mean; both are exported.

## Paired tests and intervals

The main reference test independently flips the sign of each entire case-block
difference and compares the absolute mean to its null distribution. It is exact
when the distribution can be evaluated by an integer-lattice dynamic program
(or its one-direction/zero special cases). Otherwise it uses **99,999**
Monte Carlo sign flips, a `(exceedances + 1)/(replicates + 1)` correction and an
exported Monte Carlo standard error. No p-value is rounded down to zero.

The test assumes independent case blocks and exchangeability/sign symmetry of
the paired contrast under its reference null. Calling it exact describes
calculation of that reference distribution; it does **not** establish that
historical labels, time, frame wording or model identities were randomized.
Case banks were generated for these studies and are finite; the analysis does
not establish performance on every possible task or on future model versions.

Nominal pointwise **95% percentile intervals** resample whole case differences
**20,000** times. They are not simultaneous intervals. Boundary/constant data
can produce degenerate intervals; these are explicitly flagged and do not prove
zero population uncertainty or general equivalence. Standardized paired
effects are undefined when the block standard deviation is zero; they are left
missing rather than reported as infinity.

New intervals can differ from the historical reports because this supplement
uses its own explicitly recorded resampling counts, seeds and case-weighted
estimands. Historical intervals remain preserved alongside their original
methods; the supplement does not silently replace them.

For binary matched endpoints, a separate exact McNemar sensitivity analysis
conditions on discordant conversation pairs. This assumes independent pairs
conditional on the tested bank and does **not** adjust pooled comparisons for
shared case families. It therefore complements rather than replaces the
case-block analysis. Very small sensitivity p-values are retained in log space
to prevent numerical underflow from being published as `p=0`.
The sensitivity CSV's `p_display` and `p_holm_display` fields carry a literal
`p=` prefix so spreadsheet/CSV readers retain extremely small values as text.
Their numeric logarithms remain available for calculation; the ordinary float
field is left missing below its reliable display range.

## Omnibus and observational route tests

Model/effort/claim omnibus comparisons use case-averaged outcomes and a
within-case condition-label permutation distribution of the Friedman rank-sum
statistic, with 99,999 Monte Carlo permutations and plus-one correction.
Kendall's W is descriptive. The conditional exchangeability assumption is
explicit; model identity is not a randomized treatment or an intelligence rank.

Study 1's original route estimand is
`(mean(KK) + mean(DD) - mean(KD) - mean(DK))/2`, not a frequency-weighted
consistent-versus-switching contrast. It uses saturated route-means OLS with
case-cluster sandwich variance, a finite-cluster correction, and a t reference
with `case_count - 1` degrees of freedom. Each involved route must have >=10 valid
observations. The original secondary contrasts KK–DD and
KD–DK use the same route-means model and variance calculation. Sparse variation and near-ceiling outcomes limit these
asymptotic p-values. Routes arose from model choices; their contrasts are
**associations**, not causal route effects.
When a route contrast and its observed cluster variance are both zero, the
table retains it with reference p=1 and a no-observed-variation status. A
nonzero contrast with zero estimated variance is instead non-estimable.

Study 4 lacks replicated case families. Its optional exact sign-flip reference
groups the two frames within each of seven fixed model blocks. These values
describe a selected panel on a single schedule; they are not evidence for a
population of cases or models. They are excluded from the principal
case-inference multiplicity families and reported separately.

## Multiplicity, endpoints and interpretation

Every estimable principal paired, route and omnibus p-value receives:

1. Holm adjustment over **all principal tests in this audit**;
2. Holm adjustment within its study;
3. Benjamini–Hochberg adjustment within its study, as a secondary FDR view.

A small explicitly marked headline family also receives its own Holm
adjustment. It is still retrospective. All attempted contrasts, including
non-significant and constant outcomes, remain in the exported tables. Pilot
panel reference tests and conversation-level McNemar sensitivities have
separate labels/families; they are not substituted into principal conclusions.
BH is a secondary exploratory view and does not guarantee FDR control under
arbitrary dependence among the many overlapping comparisons; Holm is the main
reported multiplicity correction.

The joint endpoint is exactly `impact=1 AND counterfactual=no`. It is a response
combination, not a measure of private awareness. Freedom, influence magnitude,
counterfactual judgments and epistemic confidence are different constructs.
Matching the actual generator is not uniquely identifying that generator from
observations. Uncertainty and explicit prediction mismatches remain distinct.
The card/cat manipulation bundles nouns, names, action verbs and feedback;
its contrast is not a noun-only treatment effect.
Failure to reject a null is not an equivalence or absence-of-effect finding.
Before/after disclosure comparisons also change time, supplied information and
measurement; their p-values do not isolate disclosure as a randomized cause.

## Reproduction

See [the statistical results](STATISTICS.md) for generated tables, source
hashes, versions, test counts and commands. The deterministic code is
`scripts/statistical_audit.py` and `scripts/statistics_core.py`; the supplement
depends only on local archived exports, NumPy, SciPy, pandas and matplotlib.
