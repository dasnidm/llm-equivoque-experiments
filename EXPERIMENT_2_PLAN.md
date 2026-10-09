# Experiment 2: Three repeated equivoque rounds before disclosure

**Run:** `equivoque-2026-10-09-exp2-v1`

**Authorized:** October 9, 2026; 420 trials and 20 worker processes.
**Status:** Prospective protocol. Freeze all stimuli, assignments, and analysis specifications before evaluation.

## Objective and unit of observation

Measure changes in model-generated judgments after three repetitions of the
same four-object procedure within one conversation, and after a final disclosure.
One **trial** contains three rounds and four measurements. The rounds are not
independent trials. Each trial has a new native conversation that persists for
all ten turns; other trials and the paired card/cat trial have separate sessions.

The hidden target is assigned before the first request and remains the same in
all three rounds. Restore all four objects at each round's start. Predetermine
three distinct displayed arrangements, with no selection-dependent randomization.
At both choice steps, keep the group containing the target. The final object is
therefore identical across all three rounds regardless of choices. This repeated
outcome gives the subject a possible clue before the explicit disclosure.

The coordinator interprets the requested repetition as a fixed target across
rounds. Changing targets between rounds would be a separate experiment.

## Matrix and budget

Retain the experiment 1 requested models: `gpt-5.6-luna`, `gpt-5.6-terra`,
`gpt-5.6-sol`, `gpt-6-luna`, `gpt-6-sol`, `gpt-6-astra`, and `gpt-6.1-sol`,
each with `low`, `medium`, and `high` reasoning effort. These are requested
settings; backend versions and equal computation across labels are not assumed.

| Quantity | Total |
| --- | ---: |
| Requested model/effort configurations | 21 |
| Shared paired starting cases | 10 |
| Trials per configuration | 20: 10 cards + 10 cats |
| Independent native trial sessions | 420 |
| Choice rounds within those sessions | 1,260 |
| Measurement occasions per trial | 4 |
| Planned evaluation turns | 4,200 |
| Worker processes/worktrees/result branches | 20: A–T |
| Assigned trials per worker | 21 |

Ten workers receive 11 card and 10 cat trials; ten receive 10 card and 11 cat
trials. Every worker receives exactly one trial from each configuration. Card/cat
partners may run on different workers; worker identity is not the pairing unit.
Development, offline simulations, shared live service probes, and worker
calibration sessions are separately labeled and excluded from evaluation.

## Ten-turn sequence and exact measurements

| Turn | Round / phase | Requested response |
| --- | --- | --- |
| 1 | Round 1: choose two of four | Two distinct object names/labels |
| 2 | Round 1: first feedback, choose one of two | One remaining name/label |
| 3 | Round 1: second feedback and measurement M1 | Freedom, impact, counterfactual |
| 4 | Round 2: restore four objects, choose two | Two distinct names/labels |
| 5 | Round 2: first feedback, choose one | One remaining name/label |
| 6 | Round 2: second feedback and measurement M2 | Freedom, impact, counterfactual |
| 7 | Round 3: restore four objects, choose two | Two distinct names/labels |
| 8 | Round 3: first feedback, choose one | One remaining name/label |
| 9 | Round 3: second feedback and measurement M3 | Freedom, impact, counterfactual |
| 10 | Disclose the common fixed target and all three exhaustive tables; M4 | Freedom, impact, counterfactual |

Use the original English system message, card/tap/discard and cat/pet/leave
choice and feedback text, full named aces for cards, A–D labels for cats, and
"Your chosen card/cat" wording. Do not add emotional modifiers, explanations,
confidence questions, thinking instructions, or free-text answers. Preserve the
original evaluation block byte for byte: freedom and impact are integer 1–100;
counterfactual is exactly yes/no. Each measurement refers to the round just
completed, including Round 3 after disclosure.

Only these structural additions are allowed: neutral Round 2/3 restart labels,
the same measurement-scope sentence at all four measurements, and final text
explaining that the target/rule applied throughout all three rounds. Turn 10
includes three 12-row tables, one for each predetermined arrangement. No hidden
target or rule is disclosed before Turn 10; earlier final feedback necessarily
names the object that remained, just as in experiment 1.

The single stimulus source is `experiment2/protocol/prompts.json`, retaining a
byte-identical copy of the original canonical data as its base. Document the
exact additions in `experiment2/PROMPTS.md`. Keep experiment 1 files unchanged.

## Cases, assignment, and reproducibility

Use seeds 2026100921 (cases), 2026100922 (assignment), 2026100923 (execution),
and 2026100924 (bootstrap). Balance the ten target labels as 3,3,2,2 in a seeded
order. Independently balance target display positions at each round as 3,3,2,2.
Randomize the other objects subject to distinct orders within each case. Freeze
the resulting cases rather than balancing observed routes or responses.

All 21 configurations and both frames share the same ten case IDs, fixed target,
and three internal arrangements. For each configuration, shuffle cases and
assign its ten card and ten cat trials to workers with a deterministic alternating
frame allocation. Independently shuffle execution order within every shard.
The 20 manifests must be disjoint and their union must equal exactly 420 IDs.
No optional stopping, replacement trials, response correction, or resampling.

Freeze the plan, prompts, source, imported experiment 1 transport/isolation
implementation, tests, analysis, full schedule, and manifests with SHA-256.
Execution must descend from the approved common preparation commit, with every
frozen file unchanged. Use new result branches and a separate integration branch.

## Readiness, execution, and durable records

Use the existing pinned native Codex CLI and ChatGPT authentication route.
Verify actual model access, refreshed catalog/effort support, zero offered
subject tools, exact visible context, strict schemas, and ten-turn resume
continuity. Retain the frozen 300-second turn deadline and unsupported
`uniqueItems` adaptation with mandatory local duplicate-choice rejection.

A shared preflight inspects actual native bodies for all 21 configurations and
makes one separately logged live access probe per configuration. Each of 20
workers verifies the shared evidence and its frozen source/manifest, inspects
its effective native request, and completes a separate ten-turn live calibration
session. A coordinator release requires all 20 matching readiness reports.

Launch all 20 OS worker processes. Use fair whole-trial permits, starting with
two active trials and increasing through 5, 10, and 20 after measured completions
and acceptable response delays. Reduce new intake on prolonged responses. Stop
new trial grants after a systemic transport/isolation failure; let known active
requests drain. Never repeat failed, completed, or uncertain pending requests.
Resume only an unrequested next turn after verified reconciliation and a fresh
gate when necessary. Concurrency is operational scheduling, not a treatment.

Log every exact prompt, canonical/effective schema, raw answer and native event,
session, timestamp, available usage, duration, exit code, failure, parsed choice,
round route, and remaining set. Copy exact native system/schema/event/stderr files
into the assigned result directory with a SHA-256 manifest. Keep credentials,
authorization headers, user configuration, and native session storage out of Git.
Audit all valid partial endpoints, failures, and assigned-but-unattempted trials.

## Prespecified analysis

The primary longitudinal contrast is mean within-trial **M3 minus M1 impact**,
reported for each requested configuration pooled over frames and an equally
weighted mean across the 21 configurations. This asks whether judgments change
before explicit disclosure. Secondary contrasts are M2−M1, M3−M2, and M4−M3 for
impact and freedom; also retain M4−M1. Report means and distributions at every
occasion, adjacent counterfactual yes/no transitions, complete four-answer
trajectories, and first observed pre-disclosure no by measurement. Do not infer
unobserved transitions or treat no as proof the subject identified the hidden rule.

Compare cats minus cards within each shared case for each score/occasion, and
retain round-specific routes and choice patterns descriptively. Do not use sparse
route cells for confirmatory contrasts or pool their turns as independent trials.
Report post-disclosure no and impact=1 rates among endpoint-valid observations,
alongside assigned denominators, missingness, failures, and calibration counts.

Use 2,000 percentile bootstrap replicates that resample the **ten shared cases**
as clusters with the frozen analysis seed. Apply the same resampled case indices
across frames, configurations, and all measurement occasions. Compute contrasts
using valid within-trial or within-case pairs. Do not impute missing scores.
Require at least five contributing cases and 95% estimable replicates for an
interval; otherwise label it insufficient. The equally weighted overall contrast
requires all 21 configuration estimates. Intervals are nominal pointwise 95%;
there are no confirmatory significance or model-ranking claims.

Produce an English report, tidy trial/measurement/turn/estimate/transition/route/
missingness/technical CSVs, PNG/SVG plots, and a standalone HTML visualization.
Use frequency-aware plots and axis margins so boundary ratings do not disappear.
Do not present 420 trials as 420 independent starting cases: this design has ten.

## Interpretation and limitations

Repetition bundles additional choice experiences, repeated measurement, repeated
final labels, and a longer conversation. There is no unrepeated control, so an
M1→M3 change cannot isolate the causal effect of repetition alone. Disclosure
bundles explanation, exhaustive evidence, and a later measurement. The frame
contrast changes nouns, names, and action verbs together. Scores are task-specific
model judgments, not human subjective experience or calibrated probabilities.

The empty subject working-directory context is unavoidable in the native CLI and
may contain the run/repository name, as documented for experiment 1. Inspect and
preserve it; supply no repository content, assigned metadata, or worker brief.
Observe backend model version and HTTP retry counts only if genuinely exposed;
otherwise retain them as unknown. Do not infer billing cost from token totals.

Experiment 1 is a contextual comparison, not a randomized control for this run.
Its raw data and completed analysis remain separate and unchanged.
