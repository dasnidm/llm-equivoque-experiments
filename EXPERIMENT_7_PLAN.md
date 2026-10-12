# Experiment 7 Thirty round forcing sequence comparison

Recommended pilot design, October 12, 2026. Compare constant and varying hidden
forcing targets with fixed object positions. The question is whether reported
agency changes without an articulated account of the host's procedure, and
whether repeated identical outcomes change that relationship. Agency is
operationalized as two separate reported dimensions: selection freedom and
perceived causal influence on the outcome. Retain the canonical counterfactual
judgment. The owner authorized the initial four-condition, 28-session pilot and its analysis
on October 12, 2026. Additional stopping groups are not included. Collection
requires the matching new freeze, readiness reports and coordinator gate. Completed experiments
and their frozen English materials remain unchanged.

## Evidence and hypotheses

Experiment 2 has 420 complete sessions, ten shared families and three rounds
before disclosure. All impact ratings were 100 or 1. Impact-1 counts were 0,
16 and 73 after rounds 1, 2 and 3; mean impact was 100, 96.229 and 82.793.
Round 3 counterfactual no counts were 72, so the judgments remain distinct.
Freedom stayed near 100. All post-disclosure impact scores were 1. One
counterfactual trajectory returned from no to yes before disclosure.

Pailhes, Kumari and Gustav Kuhn found declining freedom ratings over three
human equivoque rounds without a significant impact-rating trial effect
(Friedman p = .466). They suggested participants might feel something outside
their control without explicitly understanding the force. That interpretation
does not establish individual discovery times or an implicit-awareness
mechanism. Their participants did not see card faces before ratings; this pilot
displays outcomes every round and is not a direct human replication.

Prospective hypotheses:

- Constant outcomes may change perceived causal influence earlier than varying
  outcomes.
- Either sequence may produce lower impact while selection freedom remains high.
- Changed agency reports may coexist with no articulated procedure; articulated
  procedure knowledge may coexist with high freedom. Do not assume one obligatory
  sequence of psychological stages.

The owner's reference to something feeling wrong concerns the causal-influence
judgment. Do not add a separate unusualness or suspicion scale. Analyze freedom
and impact separately, rather than silently summing them. LLM answers measure
task reports, not evidence of human-like subjective feelings.

Sources:

- [Original human study](https://research.gold.ac.uk/29234/1/Equivoque-Revised_final.pdf)
- [Audited Experiment 2 report](https://github.com/dasnidm/llm-equivoque-experiments/blob/7fc5cee84d574d598567c49924382647173e1a4f/analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md)
- Experiment 2 tables/impact_distribution.csv and tables/counterfactual_trajectories.csv under that report directory.

## Four pilot labels and model matrix

Use seven low-effort configurations: gpt-5.6-luna, gpt-5.6-terra,
gpt-5.6-sol, gpt-6-luna, gpt-6-sol, gpt-6-astra and gpt-6.1-sol.
The four owner-specified pilot labels form a frame by sequence comparison:

| Pilot label | Frame | Hidden target schedule | Sessions |
| --- | --- | --- | ---: |
| exp3-pilot-card-obj | Cards | Same card in all 30 rounds | 7 |
| exp3-pilot-card-seq | Cards | Precommitted varying thirty-round sequence | 7 |
| exp3-pilot-cat-seq | Cats | The matched precommitted varying sequence | 7 |
| exp3-pilot-cat-obj | Cats | Same cat in all 30 rounds | 7 |

All four ask the canonical freedom, impact and counterfactual questions after
every round. The cat-obj label is the cat frame. These are condition labels for
a new collection run, not a reuse or renaming of the completed Experiment 3
objective-rule-transfer pilot. Use a distinct run ID and results location.

Fix displayed positions throughout all initial pilot conversations:

- Cards: ace of spades, ace of clubs, ace of hearts, ace of diamonds.
- Cats: A, B, C, D.

The shared forcing sequence is specified by position numbers 1-4, not by
reassigning the existing internal card codes. Position 3 therefore denotes
ace of hearts for cards and C for cats. Existing internal card identities remain
A=spades, B=clubs, C=diamonds, D=hearts; the displayed card order is internally
A,B,D,C. These internal codes are never shown to card subjects.

At each stage, keep the group containing that round's hidden target. Generate
all targets before any subject call. Balance the varying sequence's four
positions to 7 or 8 occurrences, select which receive 8 using the frozen seed,
and shuffle without choosing an interesting-looking sequence. Consecutive
repeats are allowed. Use the varying sequence's first target position as the
constant condition's target position, matching round 1 in both conditions.

Freeze one initial position sequence and share it across all seven models and
both frames. Conceal the sequence, precommitment, balancing scheme, condition
label and engine until primary measurements end. Cards use full ace names
without internal A-D prefixes; cats retain the canonical A-D labels.

Keeping arrangements fixed is appropriate for this initial comparison: it
aligns the presented layouts while testing the sequence policies. Identity and
position covary, however, so the pilot cannot distinguish identity-based from
position-based hypotheses. A later replication can counterbalance different
fixed arrangements and constant targets across fresh conversations.

Sequence changes can also change realized keep/discard routes through adaptive
subject choices. The condition comparison estimates the total sequence-policy
effect, not outcome repetition with all intermediate feedback held constant.
Record routes without treating them as randomized factors or baseline covariates.

## Scope and optional timing assessments

Initial screen: 7 configurations x 2 frames x 2 conditions = **28 fresh
sessions**, containing **840 game rounds**. Each has 90 game-phase calls and
three terminal calls, or 93 invocations. Total: **2,604 evaluation invocations**,
excluding calibration. Across both conditions, each model plays 60 card rounds
and 60 cat rounds.

One conversation per model, frame and condition can show when that conversation
changes judgment. It cannot estimate a model's usual change time. The shared
sequence does not create 28 independent stimulus families. Treat results as
descriptive screening, not confirmatory rankings. A separately frozen replication
should draw multiple sequences, counterbalance constant targets and arrangements,
and repeat fresh conversations. Thirty round rows are not thirty independent cases.

Repeatedly asking about rules can itself invite rule search. To assess expressed
rule knowledge at earlier times, prospectively add fresh conversations stopped
after rounds 3 and 10, with identical sequence prefixes and no disclosed stopping
length. Ask the rule assessment only at the assigned endpoint. Each stop adds
28 sessions. Stops at 3, 10 and 30 together yield **84 sessions, 1,204 game rounds
and 3,864 evaluation invocations**:
28 x [(3 x 3 + 3) + (3 x 10 + 3) + (3 x 30 + 3)].
These groups compare reports and elicited articulation at sampled times; they
do not reveal a private internal discovery instant.

## Measurements and terminal assessment

Version new materials without editing older frozen files. Retain the English
system, choice wording, outcome feedback and canonical three-question block.
Each round is choose two; receive feedback and choose one; receive final feedback
and answer freedom, impact and counterfactual. Allow every integer score from
1 to 100, including intermediate values. Do not instruct subjects to seek tricks.

After the last pre-disclosure rating at the assigned stop, make three calls:

1. Request a brief account of how the host determines outcomes, allowing several
   plausible hypotheses or insufficient information. Supply no candidate rule,
   table or correctness feedback. This is elicited inference without supplied
   rules, not an unprompted record of earlier discovery.
2. Request counterfactual predictions for four frozen, unobserved choice policies
   in an already completed round with its original arrangement. Each policy
   chooses a first pair and then the first or last remaining object, making it
   legal under either feedback. Include pairs containing or omitting the actual
   round-specific target and both second-stage positions. Predict first feedback,
   second feedback and final object; allow insufficient information. Do not
   reveal target precommitment before answers.
3. Reveal the actual rule and target schedule up to the stop, show all twelve
   legal paths for the final observed round, and repeat the canonical ratings.
   This endpoint is excluded from pre-disclosure trends.

Prediction of a future unseen random target is not a rule-understanding test.
Observed traces can also fit alternative random keep/discard policies, so
precommitment need not be uniquely inferable. Predictions matching the actual
generator measure consistency with that mechanism, not necessarily deduction
from sufficient evidence. Keep uncertainty distinct. Merely saying outcomes
repeat is different from articulating conditional keep/discard mapping.
Use a descriptive rubric fixed before collection and preserve raw descriptions.
With positions fixed, do not reject an identity or position hypothesis merely
because an unobserved implementation parameter was not identifiable.

## Analysis and later mathematical modeling

Export all prompts, choices, orders, targets, feedback, scores, counterfactuals
and terminal answers with session, configuration, frame, condition and stop.
Use assigned and valid denominators and retain failures and partial measurements.
Plot individual freedom and impact trajectories and their joint patterns,
score distributions, impact-1 fractions and counterfactual-no fractions.
Compare conditions within configurations and frames while retaining case pairing.

Record the first impact-1 round and first counterfactual-no round separately,
plus reversals and full scores. If no event occurs by 30, report not observed
by 30, not never understands and not an event at 30. Continue after the first
low rating through the assigned length to assess persistence. High freedom with
low impact is a substantive dissociation, not automatically an inconsistent answer.

For stopping groups, tabulate low impact with no articulated rule, low impact
with a mechanism-consistent account, and high impact with an articulated rule.
These are expressed reports: a missing explanation does not prove absent
internal understanding, and the terminal question may elicit reasoning only then.

If impact remains only 1 and 100, mean_impact(n) =
100 - 99 * Pr(impact(n) = 1). Otherwise use the full score distribution.
The small screen describes curve shape and feasibility. Before a larger
replication, fix a limited set of constant, exponential-with-plateau and logistic
models, and consider first-passage and reversible transition models. Validate on
held-out whole sequences and conversations rather than random round rows.
Treat failure-related censoring as potentially informative. Similar curves alone
do not establish shared psychological mechanisms with humans.

## Preparation and execution

Verify previous freezes and implement the new target-per-round engine,
fixed arrangements, stopping lengths, terminal assessments and audits outside
older frozen modules. Offline checks must cover all legal paths for every target,
both frames and sequences, timing, continuity, native integrity and no uncertain
replay. Freeze new code, English prompts, schemas, schedules, seeds, rubric and
manifests together. This draft alone is neither an execution freeze nor a launch.

Retain twenty OS workers in separate worktrees and result branches with seeded
assignments and measured intake limits. For 28 sessions, workers receive one or
two sessions each; they are processes, not repository-aware assistant subjects.
Use the pinned native CLI and ChatGPT route, low effort fixed within sessions,
zero subject tools and documented visible context. Verify all seven requested
settings and every worker at one source revision, including excluded full-length
development sessions for context feasibility and continuity.

Increase concurrency only from measured throughput and pending ages. Keep
calibration calls and failures separate. Preserve the 300-second per-call deadline,
durable pending checkpoints, raw logs and failures without replay or replacement.
Do not reset or manually summarize sessions; freeze handling of detected
compaction or truncation. Reuse run-specific assignments without duplication,
integrate on a new branch, audit raw files and session identities, and produce
the English report, tables, graphs and trajectory explorer. Genuine-selection
and measurement-frequency controls may be prospectively added later; they are
not included in this initial two-sequence comparison.

## Authorized collection specification

The initial four labels and all 28 thirty-round sessions are authorized. The
three- and ten-round stopping groups remain prospective and are not collected.
Native subjects run in a neutral empty directory under /workspace/work/native-study
so repository and condition names are absent from the visible path. All seven
low configurations and all twenty workers must pass, including four excluded
full-length development sessions. Staged intake requires thirty seconds and
eight completed native calls, median latency at most sixty seconds and pending
age below 120 seconds; pending ages over 150 or 240 seconds reduce new intake.
The English report is descriptive and preserves partial outcomes and uncertainty.
