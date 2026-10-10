# Experiment 2: Three repeated equivoque rounds

Run `equivoque-2026-10-09-exp2-v1`. Collection finished and raw integrity checks passed.
420 assigned native trial sessions, ten shared starting cases, three rounds per
trial, four measurements, and 4200 evaluation invocations.
Terminal statuses: {"complete": 420}.

## Observed longitudinal results

The equally weighted 21-configuration mean within-trial Round 3 minus Round 1
impact was -17.207 points (nominal pointwise 95% case-cluster
interval -21.214 to -13.436; estimable). This
describes change before explicit disclosure, rather than an isolated causal
effect of repetition. Endpoint means and answer counts are below.

| measurement | valid | mean_impact | mean_freedom | yes | no |
| --- | --- | --- | --- | --- | --- |
| 1 | 420 | 100.000 | 99.881 | 420 | 0 |
| 2 | 420 | 96.229 | 100.000 | 404 | 16 |
| 3 | 420 | 82.793 | 100.000 | 348 | 72 |
| 4 | 420 | 1.000 | 99.764 | 0 | 420 |

Among 420 valid post-disclosure endpoints, 420
counterfactual answers were no and 420 impact ratings were 1.
Freedom to choose and influence on the final object are distinct judgments;
high post-disclosure freedom is not an error.

## Primary configuration estimates

| configuration_id | estimate | ci_low | ci_high | n_cases | n_observations | status |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna-low | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-luna-medium | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-luna-high | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-terra-low | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-terra-medium | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-terra-high | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-sol-low | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-sol-medium | -4.950 | -14.850 | 0.000 | 10 | 20 | estimable |
| gpt-5.6-sol-high | -29.700 | -44.550 | -14.850 | 10 | 20 | estimable |
| gpt-6-luna-low | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-6-luna-medium | -4.950 | -14.850 | 0.000 | 10 | 20 | estimable |
| gpt-6-luna-high | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-6-sol-low | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-6-sol-medium | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-6-sol-high | 0.000 | 0.000 | 0.000 | 10 | 20 | estimable |
| gpt-6-astra-low | -64.350 | -84.150 | -39.600 | 10 | 20 | estimable |
| gpt-6-astra-medium | -69.300 | -89.100 | -44.550 | 10 | 20 | estimable |
| gpt-6-astra-high | -54.450 | -84.150 | -29.700 | 10 | 20 | estimable |
| gpt-6.1-sol-low | -34.650 | -54.450 | -14.850 | 10 | 20 | estimable |
| gpt-6.1-sol-medium | -29.700 | -44.550 | -14.850 | 10 | 20 | estimable |
| gpt-6.1-sol-high | -69.300 | -94.050 | -44.550 | 10 | 20 | estimable |
| ALL_EQUAL_CONFIGURATIONS | -17.207 | -21.214 | -13.436 | 10 | 420 | estimable |

## Analysis and interpretation

Every interval resamples the same ten shared cases across frames, configurations,
and occasions, with 2,000 replicates and the frozen seed. Contrasts use only valid
pairs; missing endpoints are not imputed. Require five contributing cases and
95% estimable replicates; overall estimates require all 21 configurations.
Intervals are nominal pointwise 95%, without confirmatory multiple-comparison or
model-ranking claims. Boundary ratings can make bootstrap intervals degenerate;
this does not prove exact equality outside the recorded task.

Three repetitions bundle additional choices, repeated final labels, repeated
questions, and a longer conversation; there is no unrepeated randomized control.
The disclosure combines explanation, exhaustive evidence, and later measurement.
Card/cat wording changes nouns, names, and verbs together. Routes arise from model
choices. Pre-disclosure no responses are observed judgments, not proof the subject
identified the hidden procedure. Results concern these frozen English prompts and
native context, not human subjective experience or general reasoning accuracy.

The native empty working-directory context can contain the run/repository name.
Subjects receive no repository files, worker brief, hidden assignments, or tools.
Requested model/effort settings are retained; backend versions, actual HTTP attempt
counts, and billing cost are unknown. Operational latency excludes failed trials
and trials with unknown durations; changing concurrency is not a controlled
model speed comparison. Earlier valid endpoints in failures remain included.

Experiment 1 remains separate and is not a randomized control. See the prospective
EXPERIMENT_2_PLAN.md, provenance.json, union_audit.json, tidy tables, and figure
captions for exact definitions, denominators, records, and technical limitations.

## Calibration accounting and descriptive choice exports

The 21 shared access probes and 20 separate ten-turn worker sessions contributed
221 calibration invocations in 41 sessions, excluded from every evaluation estimate.
Calibration archives were reverified, and their session IDs are disjoint from
evaluation. The temporary nine-turn preparation draft collected no observations;
the owner-confirmed sequence retains Round 3 questions before final disclosure.

calibration_invocations.csv provides the call ledger. choices.csv,
choice_patterns.csv, and round_traces.csv export recorded choices and partial
round routes descriptively, including rounds without a valid score. They retain
trial/case/round membership and do not add inferential contrasts. The packaging
utility leaves the frozen analysis source, estimates, plots, and raw data unchanged.

explorer.html provides an offline configuration/frame selector for recorded
endpoint means and trial answers, with visible valid counts. It performs no
new inferential analysis; use estimates.csv for paired contrasts and intervals.

Runtime reconnection interrupted the original coordinator and workers.
20 pending responses were recovered from unique, schema-valid
final native completion events with matching sessions, prompts, systems, and
schemas, within the frozen deadline. No requests were replayed. Original
parent-observed exit statuses and monotonic durations for these turns remain
unknown. Their trial observations are retained, while the affected complete
trials are excluded from latency summaries requiring all ten durations.

Technical token columns sum the native-reported usage counters across
invocations. Counter semantics after native session resumption are not established
as marginal billable usage; these sums are not billing estimates. Native WebSocket
reconnection diagnostics remain in the raw logs even when a final turn completes.
