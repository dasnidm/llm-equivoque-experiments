# Experimental Plan: Model and Reasoning-Effort Comparisons in Equivoque

**Version:** Working draft, October 9, 2026  
**Status:** Documentation prepared; implementation, protocol freeze, and the multi-model run are pending.

## 1. Objective

Compare how language models interpret a choice activity in which the experiment engine changes whether a selected set is kept or discarded to preserve a predetermined outcome. Examine judgments before and after exhaustive counterfactual evidence is disclosed.

The engine uses one consistent hidden rule. The participant nevertheless observes a potentially changing mapping from **selecting** an object to **keeping or removing** it. This ambiguity in the participant-facing mapping is the phenomenon of interest.

Research questions:

1. Do model-generated judgments differ between consistent mappings (`KK`, `DD`) and switching mappings (`KD`, `DK`)?
2. Do matched card and cat descriptions produce different choices, explanations, or impact judgments?
3. How do these responses vary across models and reasoning-effort settings?
4. How do judgments change after all possible choice branches are revealed?

This first run measures direct choice behavior and reported judgments. It does not, by itself, establish a general reasoning benchmark or measure human subjective agency.

## 2. Model matrix

Use the following seven model identifiers with three effort settings each:

| Model | Reasoning effort | Planned trials |
|---|---|---:|
| `gpt-5.6-luna` | `low`, `medium`, `high` | 100 per setting |
| `gpt-5.6-terra` | `low`, `medium`, `high` | 100 per setting |
| `gpt-5.6-sol` | `low`, `medium`, `high` | 100 per setting |
| `gpt-6-luna` | `low`, `medium`, `high` | 100 per setting |
| `gpt-6-sol` | `low`, `medium`, `high` | 100 per setting |
| `gpt-6-astra` | `low`, `medium`, `high` | 100 per setting |
| `gpt-6.1-sol` | `low`, `medium`, `high` | 100 per setting |

This gives **21 configurations**. These identifiers and effort options were present in the local account's model metadata on October 9, 2026. Successful inference has not been verified for every configuration or in the intended cloud environment. Verify access before collection; do not silently replace unavailable models.

Keep the selected model and effort fixed across all four turns of a trial. Equal effort labels across models do not necessarily imply equal token budgets or computation.

## 3. Scope and trial budget

The current budget is **100 total trials per configuration**, yielding:

| Quantity | Calculation | Total |
|---|---|---:|
| Configurations | 7 models × 3 effort settings | 21 |
| Trials | 21 × 100 | 2,100 |
| Calls | 2,100 × 4 | 8,400 |
| Workers | Proposed concurrency | 5 |

**Working frame allocation, pending confirmation:** 50 card trials and 50 cat trials per configuration. For a paired comparison, generate 50 initial worlds and present each once as cards and once as cats in separate subject sessions. Use the same planned cases across model/effort configurations, while randomizing execution order.

If the intended allocation is instead **100 card trials plus 100 cat trials per configuration**, the budget becomes **4,200 trials and 16,800 calls**. That larger allocation is an alternative, not an additional phase in this plan.

Development and access/throughput calibration calls must be logged separately from the planned evaluation budget. Their count has not yet been fixed.

## 4. Four-object engine and randomization

Each trial begins with four labeled objects, `A`, `B`, `C`, and `D`. The participant sees their order and chooses two distinct labels. The engine reduces the set to two objects. The participant then chooses one remaining label, and the engine reduces the set to one object.

Before the first choice, randomly assign a hidden target and the initial object order. The engine applies the same rule at both steps:

```text
if the target belongs to the selected set:
    keep the selected set
else:
    discard the selected set
```

The target is fixed throughout that trial, including all branches disclosed in Turn 4. Never redraw it between turns or counterfactual branches. Generate assignments independently of model outputs and record the randomization seed. For paired card/cat cases, preserve the same hidden target and arrangement across the pair.

Randomize and, where feasible, balance target identities and positions across the case schedule. Log any remaining imbalance. Do not assign a target to obtain a particular route after observing a choice. Final seed and balancing details must be frozen before evaluation.

`K` denotes keeping the selected set; `D` denotes discarding it. The possible two-step routes remain **KK, KD, DK, and DD**. The observed route depends on the hidden target and the model's choices. Randomizing targets can change route frequencies but does not impose exact route quotas. If routes are equally frequent, 100 trials gives about 25 trials per route, or about 12.5 per frame under the 50/50 allocation.

Random targets alone do not remove every route/label confound. A model that repeatedly chooses particular labels can still induce associations between routes and final labels. Record label and position preferences and inspect these associations before interpreting route differences.

Validate all **48 branches**: four targets × six first-choice pairs × two second choices. Every branch must end at its trial's target. Turn 4 shows the 12 valid branches for that target and initial arrangement.

## 5. Four calls within one trial

| Turn | Information supplied | Model response |
|---|---|---|
| 1 | Frame, initial arrangement, instruction to select two labels | Two distinct valid labels |
| 2 | Actual keep/discard feedback and the two remaining labels | One valid remaining label |
| 3 | Final object and evaluation questions | Pre-disclosure judgments and explanation |
| 4 | Exhaustive table of all 12 branches under the same procedure | Post-disclosure judgments and explanation |

The experiment code performs each keep/discard operation. These operations are not model calls. Four calls refer to four requested model responses in a technically valid trial; retries would add requests and must be reported separately.

In each evaluation collect:

- **Impact:** How much did the participant's choices affect the final object? Integer from 0 to 100.
- **Freedom:** How free was the participant to choose the objects selected? Integer from 0 to 100.
- **Counterfactual judgment:** Could different valid choices change the final label? `yes`, `no`, or `uncertain`.
- **Confidence:** Integer from 0 to 100.
- **Possible final labels:** A nonempty subset of the four labels.
- **Procedure explanation:** A concise explanation based on the available evidence.

Use the same evaluation wording before and after disclosure. The exact wording, question order, and JSON schemas are not yet frozen. In particular, decide during development whether ratings precede the explanation; explaining first may influence subsequent ratings.

## 6. Sessions and prompts

Create a **new subject session for every trial**, and preserve that session across its four sequential turns. Card and cat versions use separate sessions. Do not retain prior trials, explanations, or exhaustive disclosures in the next trial's context.

The previous pilot used a fresh CLI session at every stage and replayed the trial transcript as user text. That is not established as equivalent to native multi-turn continuity. The new runner should use native conversation continuity and document its transport and history behavior. Keep old and new protocol results distinguishable.

Choice instructions should be neutral and minimal. Do not mention equivoque, forcing, deception, hidden targets, desired route frequencies, or later evaluation questions before the choices. Use matched card/cat wording and information, changing the object noun for the minimal frame comparison. This phase uses text descriptions, not photographs, animations, or GUI interaction.

Freeze prompts and schemas before evaluation. Do not select a prompt because it produces larger effects, or add selective "think harder" instructions to particular effort conditions. Temperature is not a planned experimental factor; verify supported parameters for the actual provider and do not assume all reasoning configurations support temperature control. Repeated identical choices are valid observations and are not grounds for resampling.

Record model/harness instructions and tool availability. The subject should receive only its own trial information, without repository access, browsing, shell tools, or hidden engine metadata. Model-written explanations are observable outputs, not faithful access to the full internal reasoning process.

## 7. Five-worker execution

Parallelize **across independent trials**, keeping the four turns of each trial sequential. Mix model/effort/frame assignments across workers and time so that a single worker or time window is not synonymous with a particular model.

Each worker receives a nonoverlapping manifest and writes to its own output location. Use stable trial IDs, immutable protocol hashes, and a shared code revision. Merge results after checking for missing or duplicate trial IDs.

Codex Cloud is a proposed host for the runner. Its coordinating agent should execute code; experimental subjects should be separate model requests with restricted trial context. Do not have one repository-aware coding conversation answer all trials itself.

Before launch, verify that the cloud runner can authenticate to the intended target models and that its network access and limits support the experiment. The local account's model inventory is not proof of cloud or API-project availability. If API inference is used, confirm its model identifiers, access, and billing separately. No cloud environment has been configured as part of this repository creation.

## 8. Runtime budget

The **20-second estimate is for one complete four-call trial**, not one call:

```text
2,100 trials × 20 seconds = 42,000 seconds = 700 minutes
700 minutes / 5 workers = 140 minutes = 2 hours 20 minutes
```

The earlier `gpt-6.1-sol`/`low` pilot averaged approximately **25.42 seconds per complete trial**, including orchestration gaps. At that reference speed, 2,100 trials across five workers would take approximately **178 minutes**, assuming ideal throughput scaling.

Neither estimate establishes the speed of other models, higher effort settings, native sessions, or cloud execution. Measure completed trials per minute and latency by configuration during a small calibration run. Update the estimate from observed throughput. Setup time, retries, queueing, rate-limit pauses, and worker interruptions are additional. Five workers do not necessarily produce five times the throughput.

## 9. Analysis and interpretation

The trial, not an individual call, is the unit of a complete interaction. Pre/post judgments within a trial are paired. Card/cat versions and model configurations share planned cases; preserve those dependencies in analysis. Label permutations and repeated versions of one four-object structure are not independent structural reasoning problems.

Prespecify the following analyses before evaluation:

- Pre-disclosure Impact distributions by model, effort, frame, and observed route.
- The consistent-versus-switching contrast: `(KK + DD) / 2 - (KD + DK) / 2`, using equal route weights where estimable rather than allowing route frequency to determine the contrast.
- Secondary route contrasts `KK - DD` and `KD - DK`, with a declared approach to multiple comparisons.
- Paired pre/post changes and card/cat differences.
- Choice frequencies by label and position, route frequencies, and technical failure rates.
- Actual latency and available token usage by configuration.

Natural routes are not randomized treatment groups. Inspect target, label, position, template, and choice-policy confounds. Report route comparisons as associations unless a design justifies stronger inference. A later controlled-transcript experiment can test route effects while balancing these factors; it is not included in this 8,400-call budget.

A single observed branch may be compatible with both forcing and a legitimate fixed-stage keep/discard procedure. Do not assign unconditional pre-disclosure accuracy scores from the hidden engine alone. The exhaustive disclosure provides an evidence-understanding check: every valid choice sequence has the same final label.

Report effect sizes and uncertainty, not only significance. Do not add trials until a desired p-value appears. One hundred trials per configuration is a practical initial budget, not a guarantee of power for every route, frame, or interaction. Use prespecified handling for sparse route cells.

## 10. Logging and technical failures

For each trial retain the configuration, frame, paired-case ID, target, initial order, seed, actual prompts and schemas, selections, engine feedback, route, raw responses, parsed judgments, session/turn IDs, timestamps, durations, available token usage, and technical errors.

Store the hidden target in experiment logs but exclude it from subject inputs until information disclosure makes it inferable. Preserve original failures. Freeze timeout and bounded technical-retry rules during development; do not retry because of an undesired choice, route, score, or explanation. A partially completed trial must not be silently counted as a complete four-turn trial.

## 11. Earlier pilot and remaining work

The completed local pilot comprised **16 trials and 64 calls** with `gpt-6.1-sol`/`low`: eight card and eight cat trials. It used four objects, text-only choices, and a fixed initial label order. Mean pre-disclosure Impact was approximately 76.9 for cards and 78.1 for cats; post-disclosure Impact was zero in all 16 trials. Repeated choices induced associations between routes and final labels. These are exploratory observations, not results from the planned 21-configuration run.

Remaining work:

1. Confirm the frame allocation and freeze the trial count, exact prompts, schemas, randomization, analysis, and failure rules.
2. Implement the engine, native-session runner, worker manifests, and raw-log validation.
3. Validate all branches and verify that hidden information does not enter subject prompts.
4. Verify actual model/effort access in the execution environment and measure five-worker throughput.
5. Freeze the protocol and code, run the planned experiment, audit completeness, and analyze the results.

The repository currently provides the working plan. No new model calls, benchmark results, or scientific approvals are implied by its creation.
