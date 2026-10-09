# Experimental Plan: Model and Reasoning-Effort Comparisons in Equivoque

**Version:** Revised working draft, October 9, 2026.
**Status:** Original tap/pet framing retained without emotional or intensity modifiers. Shared English prompts and worker
instructions drafted. Runner implementation and offline validation are complete. Live access
calibration and evaluation remain pending; preparation files are hashed. The owner reports seven cloud environments provisioned and selected one current
environment with seven worker processes/worktrees. Actual inference access
remains a separate readiness check.

## 1. Objective and interpretation

Study how language models distinguish freedom to choose objects from influence
on the final outcome in a four-object equivoque task. Compare reported judgments
before and after disclosure of the fixed-target procedure and all possible paths.

The engine follows one invariant hidden rule. Its participant-facing mapping
from selecting to keeping/removing can either repeat or switch between stages.
Research questions are:

1. Does pre-disclosure impact differ between consistent routes (KK, DD) and
   switching routes (KD, DK)?
2. Do the matched card/tap and cat/pet scenarios change choices or reported
   judgments?
3. How do these responses vary across model and reasoning-effort settings?
4. How do judgments change after exhaustive evidence is disclosed?

These are model-generated responses in one task family, not measures of human
subjective agency or a general reasoning benchmark. Observed routes arise from
model choices and are not randomized treatments. Disclosure combines a procedure
explanation, an exhaustive table, and a later measurement turn; this design does
not isolate the causal contribution of each component or rule out repetition.

## 2. Model matrix and evaluation budget

| Model | Effort settings | Trials per setting |
| --- | --- | ---: |
| `gpt-5.6-luna` | low, medium, high | 100 |
| `gpt-5.6-terra` | low, medium, high | 100 |
| `gpt-5.6-sol` | low, medium, high | 100 |
| `gpt-6-luna` | low, medium, high | 100 |
| `gpt-6-sol` | low, medium, high | 100 |
| `gpt-6-astra` | low, medium, high | 100 |
| `gpt-6.1-sol` | low, medium, high | 100 |

The initial plan reports these names/settings in local account metadata on
October 9, 2026. Actual access in each execution environment must be verified.
Do not equate account inventory with API availability, silently substitute a
model, or assume equal effort labels mean equal computation. Log actual provider
model identifiers/versions and use a fixed model/effort across a trial.

**Budget confirmed for preparation:**

| Quantity | Calculation | Total |
| --- | --- | ---: |
| Configurations | 7 models × 3 effort settings | 21 |
| Paired starting cases | Shared by all configurations | 50 |
| Trials per configuration | 50 cards + 50 cats | 100 |
| Evaluation trials | 21 × 100 | 2,100 |
| Planned successful responses | 2,100 × 4 | 8,400 |
| Workers | A–G in one current environment | 7 |
| Trials per worker | 150 cards + 150 cats | 300 |
| Planned responses per worker | 300 × 4 | 1,200 |

If 100 trials **per frame** are intended, use 100 paired cases, 4,200 trials,
and 16,800 planned responses. That is a different budget, not another phase.
The prepared schedule uses 50 paired cases and this 2,100-trial budget. Development, access
checks, and throughput calibration are separate from evaluation, with their own
call counts and artifacts. Failures can leave fewer than 8,400 valid responses;
transport retries can produce more requests. Report both quantities.

## 3. Matched scenarios and canonical prompts

Retain the owner's original scenarios: four named aces with **tap** instructions
and **discard** feedback, versus four labeled cats with **pet** instructions and
**leave** feedback. Remove emotional or intensity modifiers such as happily.
Cards and cats share starting-case assignments, informational sequence,
judgment questions, scales, and response structure. Card subjects see and return
card names; cat subjects see and return A/B/C/D labels.

Research codes map A = ace of spades, B = ace of clubs, C = ace of diamonds,
D = ace of hearts. The card prompts, remaining lists, tables, and response schemas
use only the full card names, without A/B/C/D prefixes. Cats display A/B/C/D only,
without individual traits or names. The engine normalizes exact card-name answers
to internal research codes after preserving raw responses. Preserve this pairing
mapping across cases; never show the code mapping to card subjects.

Retain **your chosen card/cat** as requested, including when the selected object
was removed. This is the scenario's outcome-attribution wording, not a factual
claim that the subject caused the final label. It may affect reported agency;
keep it parallel and fixed across frames and do not interpret the absolute
rating as independent of that wording.

The frame contrast is the difference between these matched scenarios. Object
nouns, natural action verbs, removal descriptions, and ace descriptions differ;
therefore an observed difference cannot be attributed solely to object category.
The corrected preference retains those original elements while removing added
emotional/intensity modifiers. A pure noun-only or richer emotional condition
would require a separate protocol, not a worker-specific wording change.

`protocol/prompts.v1.json` is the single machine-readable source for system text,
all four turns, both feedback branches, evaluation wording, and response schemas.
`PROMPTS.md` documents exact examples and rendering. All written materials and
subject prompts are English. Workers use identical files from one base commit;
no worker authors its own stimulus or makes a frame-specific paraphrase.

The choice prompts do not mention equivoque, a hidden target, forcing, route
frequency, future evidence, or evaluation questions. The phase is text only.
Use the same output-format mode across configurations when feasible and document
unavoidable provider differences before freeze. Supported schema restrictions
must be verified rather than assumed. Do not vary prompts to increase effects,
add selective thinking instructions, or tune prompts against evaluation outcomes.

## 4. Fixed-target engine

Start with four objects in a predetermined displayed order. The subject selects
two distinct card names or cat labels, then one of the remaining two. Internally
use paired research codes for the invariant engine. Before Turn 1, assign
one target, independent of every model output. Apply the same rule at both steps:

```text
if the target is in the selected set:
    keep the selected set             # K
else:
    remove the selected set           # D
```

The target never changes between turns or counterfactual branches. A remaining
set retains the initial displayed order. K/D records the operation on the
selected set; the observed route is KK, KD, DK, or DD. Do not change the target
to balance routes or resample repeated choices. Route frequencies are outcomes.

Validate 48 branches for one arrangement: four targets × six first pairs × two
second choices. Also validate all 24 initial-order permutations (1,152 branches).
Every branch must terminate at the assigned target. Turn 4 shows exactly the
12 valid paths for that trial's one target and arrangement, generated by the
engine, with no additional model call.

## 5. Randomization, pairing, and worker allocation

For the working 50-case schedule, cross target label (4) with target display
position (4), using three cases per cell: 48 cases. Add two cases in distinct
rows and columns, chosen by the schedule RNG. Each target label and position
then occurs 12 or 13 times. Within a cell, sample distinct arrangements of the
other labels, and choose unused arrangements for the two additions. Avoid exact
(target, displayed-order) duplicates. Log the resulting balance.

Use the same case IDs, target labels, and displayed orders in cards and cats
and across all 21 configurations. Pairing is at the **starting-case** level;
the two frames may yield different choices and routes. Do not force matching
choices or filter pairs according to observed routes.

For each configuration, shuffle its 50 paired cases among seven workers. Give
each worker seven pairs and give one worker an eighth pair. Rotate the extra
pair across A–G over 21 configurations so every worker gets three extras. Both frames of a pair use the same
worker but separate subject sessions. Across configurations, independently
shuffle this allocation so a case is not permanently tied to one worker.
Shuffle each worker's 300 trial execution order to mix configuration and frame.
This distributes every configuration/frame over workers and execution time.

Use separately recorded seeds for case generation, worker assignment, execution
order, and analysis bootstrap. Seeds, full schedule, worker manifests, and their
SHA-256 hashes are frozen before evaluation. Each trial ID uniquely names its
run, configuration, frame, and paired case. The seven manifests must be disjoint
and their union must equal the complete schedule. The algorithm above is a
proposed concrete default; freeze its implementation and actual seeds together.

## 6. Four turns and outcome definitions

| Turn | Subject receives | Subject returns |
| --- | --- | --- |
| 1 | Four displayed objects, select-two instruction | Two distinct card names or cat labels |
| 2 | Actual first K/D feedback, two remaining objects, select-one instruction | One remaining card name or cat label |
| 3 | Actual second K/D feedback, final object, three questions | Pre-disclosure JSON |
| 4 | Fixed-target explanation, exhaustive 12-row table, same three questions | Post-disclosure JSON |

The program's keeping/removing actions are not model calls. A completed trial
has four sequential model responses. Each evaluation requests only:

- **Freedom:** integer 1–100; 1 = no freedom, 100 = complete freedom to select.
- **Impact:** integer 1–100; 1 = no effect, 100 = complete control of the final object.
- **Counterfactual:** yes/no on whether different valid choices, with the same
  initial arrangement and procedure, could change the final object.

Question order is freedom, impact, counterfactual at both measurements. Do not
request subject explanations, confidence, or possible-final-label sets in this
version. The earlier six-field measurement is superseded. The disclosure is
supplied by the engine, not invented by a worker or the subject.

The forced binary answer cannot express uncertainty. A single pre-disclosure
path is compatible with several procedures, so do not grade pre-disclosure
answers unconditionally against the unseen engine. After disclosure, `no` is
the evidence-consistent counterfactual answer and 1 is the no-impact endpoint.
Report their rates; do not require either response during collection. High
freedom after disclosure can be coherent and is not an error.

## 7. Subject sessions and environment access

Create one new native subject conversation for every trial; preserve it across
its four turns. Card/cat partners and all other trials have separate conversations.
Do not reuse subject memory, replay prior disclosures in later trials, or have
one repository-aware worker answer its own trials. The coordinator executes
code; subjects are separate model requests with only their own trial context.

Subjects have no tools, browsing, shell, repository access, worker instructions,
or hidden metadata. The final label appears at Turn 3; its prior assignment and
the invariant procedure are disclosed only at Turn 4. Log exact request history,
system/harness text, session and response IDs, and provider options. Disable
cross-trial state and optional shared memory. Record supported token limits and
sampling settings; temperature is not a factor and may not be supported.

The owner reports seven provisioned cloud environments but selected **one current
cloud environment with seven worker processes**. Each process uses a separate
Git worktree/result branch, one active trial at a time, and unique native subject
sessions. Share the frozen code and inherited authentication, not subject history.
Use two active workers initially and calibrate four/seven before increasing the
active-request limit. Provisioned environments remain available for future
failure isolation; they are not used in this first execution configuration.

The implemented transport is Codex CLI exec/resume with ChatGPT login. It
replaces built-in model instructions with the canonical system text, ignores
user configuration and repository instructions, disables subject tool features,
and logs exact commands, responses, and unavoidable empty-directory environment
context. CLI version is pinned in protocol/run.v1.json. Log observed tool events
as contamination and stop affected collection. Verify the effective feature flags
and visible context before live requests. Code/setup tests are not proof of model
access or of model-internal reasoning behavior.

Live preflight checks the refreshed model/effort catalog, one full four-turn
native session, and one single-turn schema/access probe for each of the other
20 configurations: at most 24 requested subject turns per worker, separate from
evaluation. All seven live reports must pass at one frozen source revision before
the coordinator creates a launch record. A missing catalog entry or fallback
metadata blocks readiness; models are never silently replaced.

The current supervisor's first attempted probe failed before a model response
because the proxy denied chatgpt.com. The owner reports changing domain access;
the last observed active policy still reported restricted, with no chatgpt.com
grant. Recheck applied policy and actual connectivity before live preflight.
Configuration drafts and active runtime policy can differ. No proxy bypass is
part of the transport or launch instructions.

## 8. Failure, retry, and resume rules

Proposed uniform defaults to validate and freeze during development:

- One 300-second deadline per turn, including backoff and retries.
- Zero additional harness requests after a failed or ambiguous CLI turn. The
  native CLI may retry its HTTP transport internally; retain its error/event
  stream, distinguish subject invocations from HTTP attempts, and report actual
  HTTP counts as unavailable when they are not exposed.
- Retry only if the original request is known not to have advanced the session,
  or provider idempotency/response recovery guarantees no duplicate turn.
  Ambiguous session state ends that trial as interrupted; do not restart it under
  the same ID or manufacture continuity.
- Invalid JSON, out-of-range ratings, duplicate/invalid first selections, invalid
  second selections, or refusal are logged response failures. Do not add a corrective
  turn or rerun the trial. Valid repeated choices and undesired ratings are data.
- Resume unstarted trials or a uniquely recoverable native session from its last
  durable checkpoint. Never rerun a completed trial. Preserve every attempt.

Checkpoint requests and responses durably. Distinguish unattempted, active,
complete, partial, failed, and interrupted records, including failure turn/type.
Trials without four valid responses are not counted as complete. A valid Turn 3
may contribute to explicitly defined pre-disclosure analyses even if Turn 4
fails; only valid pre/post pairs contribute to change estimates. Do not replace
failed trials to restore the nominal sample size. A shared-code/protocol defect
requires a coordinated version decision, not an individual worker patch.

## 9. GitHub orchestration and integration

First complete shared runner development and validation. Freeze one protocol,
runner revision, schedule, analysis specification, and provider configuration.
Publish seven GitHub preparation assignments using the **same** English instruction
in `WORKER_BRIEF.md`, with different structured shard/branch fields.

Each worker starts from the same reviewed base commit, uses its own branch
`worker/<run_id>/<worker_id>`, and writes only under
`results/<run_id>/worker-<worker_id>/`. No worker changes shared source during
evaluation. Return raw logs, an audit, a completion report, and a result PR.
Manifests and canonical prompt files are coordinator-owned.

The main coordinator reviews and integrates results in a separate branch
`integration/<run_id>`. Validate provenance, matching hashes, expected IDs,
transcript/route correctness, failures, and absence of duplicate/colliding records
before merging. Preserve raw artifacts and error records. Run final analysis and
figures on that integrated data and record the exact integration commit.
GitHub assignments deliver the prepared shards and common worker instructions.
They authorize preparation/preflight. Evaluation starts only with the coordinator
launch record after all seven live readiness checks pass.

## 10. Prespecified analysis

The trial is one interaction; its pre/post measures are paired. Card/cat trials
and configurations share 50 starting cases. Resample by paired-case ID, retaining
all frames/configurations belonging to each sampled case; individual calls or
label permutations are not independent structural reasoning tasks.

Define the following estimates before evaluation:

1. **Primary route association:** for each configuration, pool frames and compute
   `(mean_KK + mean_DD) / 2 - (mean_KD + mean_DK) / 2` on valid Turn 3 impact.
   Use equal route weights, not the route frequencies. Call it an association.
2. **Disclosure change:** mean within-trial post-minus-pre impact and freedom,
   plus counterfactual transition counts, using valid pre/post pairs.
3. **Object-frame difference:** cats-minus-cards impact/freedom within each
   starting case and configuration, separately pre and post. Use only pairs valid
   for the requested endpoint. Routes may differ within a pair; the frame estimate
   includes any frame-related choice changes.
4. **Secondary/descriptive estimates:** KK−DD, KD−DK, route-specific frame
   distributions, label/position preferences, post-disclosure counterfactual-no
   and minimum-impact rates, failure rates, latency, and available usage.

For means and differences, use 2,000 paired-case cluster bootstrap replicates
and percentile 95% intervals with a fixed analysis seed. Mark these as nominal
pointwise intervals, not simultaneous evidence for all comparisons. Report the
number of cases, trials, and valid resamples supporting every estimate.

A pooled primary route contrast requires at least ten valid trials in **each**
route per configuration. If that threshold fails, or fewer than 95% of bootstrap
replicates can estimate all required route means, mark the contrast insufficient;
show route counts/distributions rather than substituting zero or collecting more
trials. Frame-by-route comparisons are descriptive and may be sparse.

Effect sizes and uncertainty are the main reporting format. The initial report
makes no confirmatory significance claims from the 21 contrasts or many secondary
comparisons. If hypothesis tests are added before freeze, specify their complete
family, null-resampling/test method, and multiplicity correction in advance.
Do not add tests or trials because a desired significance threshold was missed.
One hundred trials per configuration is a practical budget, not a power guarantee.

Inspect associations with target label/position, choices, worker, and time.
Present counts and conditional descriptions without treating observational route
conditioning as a causal adjustment. Summarize missingness by configuration/frame
and report endpoint-specific denominators. Retain all failures in the assigned
trial denominator; do not impute missing ratings as zero or the scale minimum.

## 11. Figures and reproducible outputs

Generate all figures from the integrated raw records using a versioned analysis
script, not manually entered summaries. Planned outputs are:

- Route counts by model/effort/frame, with sparse cells visible.
- Pre-disclosure impact distributions and the primary route contrasts with
  intervals and contributing counts.
- Paired disclosure changes and pre/post freedom-versus-impact plots, to show
  that choice freedom and outcome influence are separate measures.
- Paired cats-minus-cards frame differences with intervals.
- Counterfactual yes/no transitions and post-disclosure evidence-consistency rates.
- Technical failure, request latency, and available token/cost summaries; show
  a cost only when billing information supports it.

Use consistent colors and 1–100 rating axes. Explain error bars, endpoints,
denominators, insufficient cells, and observational contrasts in captions.
Export SVG and PNG figures, tidy CSV summaries, and an English report. An optional
interactive dashboard can accompany the static figures after the data audit;
it is not an added experimental condition. Deliver actual data visualizations
only after collection, with the run ID, protocol hash, and integration revision.

## 12. Logging and runtime expectations

Retain run/trial/configuration/frame/case/worker IDs, assigned target and order,
seeds and hashes, exact system/user messages and schemas, provider options,
selections and operation routes, raw/parsed responses, session/response IDs,
attempt counters, timestamps/durations, available usage, and all errors.
Research logs include the hidden target; subject input does not disclose its
assignment before Turn 4. Exclude credentials and environment dumps.

The 20-second reference is for a complete four-turn trial: 2,100 × 20 / 7 =
6,000 seconds, or 100 minutes under ideal scaling. The earlier low-effort pilot's
25.42 seconds/trial gives approximately 127 minutes. Neither establishes speed
for this protocol, other configurations, or native cloud sessions. Measure trial
throughput by worker/configuration and update estimates from calibration;
queueing, retries, setup, rate limits, and interruptions add time.

## 13. Pilot provenance and launch checklist

The earlier local pilot had 16 trials/64 calls using `gpt-6.1-sol`/low, eight
cards and eight cats, fixed label order, and fresh CLI sessions with transcript
replay at each stage. Reported pre-impact means were approximately 76.9 and 78.1;
post-impact was zero throughout. Raw pilot data are not in this repository.
Treat it as exploratory and separate from the revised native-session, three-item,
1–100 protocol. Do not mix its ratings or conclusions into new evaluation data.

Before evaluation, complete and record:

1. Frame allocation, final prompt review, output-format mode, and analysis freeze.
2. Shared engine/runner implementation, including all 1,152 branch validations,
   complete 12-row disclosures, matched-frame/schema consistency, isolation, and
   interrupted-session/idempotency handling.
3. Access/effort/schema/session checks for every configuration and environment,
   plus the bounded preflight/throughput calibration with separately reported requests.
4. Actual seeds, balanced schedule, seven disjoint manifests, hashes, common base
   commit, durable logging, retry/deadline settings, and audit implementation.
5. Seven GitHub assignments, worker result branches, separate integration,
   completeness audit, reproducible analysis, and the planned English figures/report.

The subject templates, source, schedule, and analysis specification are hashed
in protocol/freeze.json after offline tests. This preparation freeze does not
assert live access readiness or authorize evaluation before the launch gate.
