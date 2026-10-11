# Experiment 3: objective rule-transfer pilot

Prospective protocol, October 11, 2026. The owner authorized **pilot only**.
Run: `equivoque-2026-10-11-exp3-pilot-v1`. No Experiment 3 main collection or
Experiment 4–7 collection is authorized by this launch. Experiments 1 and 2 are
complete and remain byte-for-byte unchanged.

## Design and scope

21 existing model/effort configurations × cards/cats × two actual procedures ×
three host claims × eight shared case families = **2,016 single-turn tasks**.
Each task is a fresh native ChatGPT session. Twenty OS worker processes A–T use
separate Git worktrees and result branches (100 or 101 tasks each). These are
processes, not repository-aware subject agents. The model matrix stays unchanged:
gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol, gpt-6-luna, gpt-6-sol, gpt-6-astra,
gpt-6.1-sol, each at low/medium/high effort. English prompts are versioned under
experiment3/protocol; existing canonical prompts are not edited.

The two procedures are fixed-target equivoque and always retaining selections.
For each of six first pairs there are two legal second selections. An exhaustive
verified 12-row table shows the actual procedure. All fixed-target rows end at
the designated object; retaining selections ends at each of four objects three
times. The prompt describes both candidate rules without naming which generated
the table. The host supplies a neutral opinion, a correct outcome-influence
claim, or an incorrect claim. The table and all questions are identical across
the three claims within each procedure. There is no instruction to distrust or
ignore the host. This is a vignette reasoning test, not a subjective agency task.

## Items and oracle

One JSON response contains four exact object names and two yes/no answers:

1. Table lookup: a path already shown, treated only as a control.
2. New arrangement: same inferred procedure and designated identity, new order.
3. Simultaneous explicit renaming: all labels, choices, and designated identity
   covary under a bijection; answer using the new name.
4. Explicit rule change: switch to the other procedure with a fully specified
   new scenario and, when needed, a different named designated object.
5. Could different legal choices change the final object in the original rule?
6. The same counterfactual for the changed rule.

The deterministic oracle validates choices, exhaustive tables, arrangements,
renaming, and changed rules. No explanation or private reasoning is requested.
Cards display full ace names; cats use A–D. Engine codes do not appear as card
names. The eight cases balance target identity and initial target position,
two occurrences each. The development cases have disjoint (order, target) pairs
and distinct IDs and are excluded from evaluation. Trials and worker allocation
use frozen seeds. Scheduling mixes configurations/frames/procedures/claims.

The arrangement/renaming query pairs include the designated identity to keep
their second choices legal under either candidate procedure. Half select that
identity at stage two and half select the other object. This small pilot does
not test transfer paths where stage-one selection omits the target; those paths
are represented in the original exhaustive table. This limits claims about
transfer coverage and is a criterion for developing harder disjoint main cases.

## Frozen descriptive analysis

Primary task score: mean accuracy over Questions 2–4, values 0, 1/3, 2/3, 1.
Primary pilot contrast: conflicting minus neutral, matched within configuration,
frame, procedure, and case, then equal weight across the 84 configuration × frame
× procedure cells with at least one valid pair. Report available/missing cells
and paired cases. Congruent minus neutral is secondary. Control lookup, individual
transfer items, original/changed counterfactuals, all-three-transfer-correct,
case-family summaries, configuration heatmaps, errors, failures, and latency are
descriptive. Always-no scores 50% on balanced original counterfactuals.

Report assigned and valid denominators, raw answers, missingness and matched
pair exclusions. Do not replace failures or impute missing answers as incorrect.
Do not count six answers as six independent trials. Eight shared case families
are the relevant independent case sampling units; no confirmatory p values,
model ranking, or power guarantee. Pilot outcomes may guide a separately frozen
main protocol with disjoint new cases, but may not change this run midcollection.
Generate tidy CSVs, five SVG/PNG figure families, English report, offline HTML,
provenance and hash manifest from audited integrated raw records.

## Readiness, collection, and publication

Verify both previous freezes and all existing tests. Freeze new code, prompts,
manifests, protocol, tests and analysis before any pilot task. Pin the existing
codex-cli 0.159.0-alpha.3, ChatGPT auth route, native transport, zero offered tools
and exact system/empty-directory context; preserve proxy and CA settings.
Live check every one of 21 combinations and all 20 worker processes, using the
new schema and excluded development cases. Record all calibration calls and
failures. All readiness checks must share one frozen preparation commit.
Only the coordinator's matching all-worker launch record releases collection.

Use one native request per task, 300-second deadline, durable pending checkpoint,
full prompts, canonical/effective schema, native events/stderr, usage and raw
hashes. No uncertain replay, corrected-response call, best-of-repeat selection,
additional replacement or change of model. Internal HTTP retries are not assumed
observable. Requested model/effort, catalog and native request inspection are
recorded; internal served model versions may not be independently attested.

Start bounded concurrency at 2; after at least 30 seconds and four completed
tasks with median recent native latency ≤60 seconds and no pending task >120
seconds, increase to 5, 10, then 20. At high pending ages reduce intake; a transport
failure halts new intake for diagnosis. Active requests finish and remain logged.
These operational measurements are not randomized scaling experiments.

Reuse assignments with this run ID; do not duplicate issues. Publish worker data
on their result branches and integrate only into the new pilot integration
branch. Keep main and both earlier integrations unchanged. Preserve every raw
failure. Audit disjoint assigned IDs, sessions, exact stimuli, schemas, scores,
native hashes and journals before reporting. Stop after the pilot report.
