# Experiment 7 Thirty round equivoque extension

Recommended design, October 12, 2026. This extension tests when models change
their reported outcome influence during repeated equivoque, whether repeated
measurement contributes to that change, and whether their terminal predictions
support an inferred procedure. The latest owner request is for a recommendation;
this draft does not release collection. Experiments 1 and 2 and the completed
Experiment 3 pilot remain unchanged. Experiment 6 prompt robustness is a separate
prospective study.

## Evidence motivating the extension

Experiment 2 contains 420 complete sessions, ten shared case families, three
game rounds and a final disclosure. All observed impact ratings were 100 or 1.
The number rating impact 1 was 0, 16 and 73 after rounds 1, 2 and 3, respectively;
all 420 rated impact 1 after disclosure. Mean impact therefore changed from
100 to 96.229 to 82.793 before disclosure. Round 3 counterfactual no responses
numbered 72, not 73: impact and counterfactual judgments must remain separate.
The 73 round 3 low-impact ratings included 38 from gpt-6-astra, 27 from
gpt-6.1-sol, seven from gpt-5.6-sol and one from gpt-6-luna. A counterfactual
trajectory returned from no to yes before disclosure; first judgment changes
cannot automatically be treated as permanent insight.

The human study by Pailhes, Kumari and Gustav Kuhn repeated equivoque three
times. Freedom ratings decreased; outcome-impact ratings did not show a
significant trial effect (Friedman p = .466). Participants did not see the card
face before their ratings and the final reveal. Experiment 2 displayed the
outcome identity every round and varied arrangements. This extension retains
visible identities to extend the model protocol. A concealed-identity condition
would be a separately specified comparison, not a direct human replication.

Sources:

- [Original human study](https://research.gold.ac.uk/29234/1/Equivoque-Revised_final.pdf)
- [Audited Experiment 2 report](https://github.com/dasnidm/llm-equivoque-experiments/blob/7fc5cee84d574d598567c49924382647173e1a4f/analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md)
- Experiment 2 tables/impact_distribution.csv and tables/counterfactual_trajectories.csv under that report directory.

## Recommended pilot

Retain all 21 requested configurations: gpt-5.6-luna, gpt-5.6-terra,
gpt-5.6-sol, gpt-6-luna, gpt-6-sol, gpt-6-astra and gpt-6.1-sol, each at
low, medium and high effort. Retain both cards and cats. Use four new shared
case families, matched across configurations, frames and conditions.

| Condition | Actual procedure | Measurement policy | Sessions | Planned calls per session |
| --- | --- | --- | ---: | ---: |
| A | Fixed-target equivoque | Ratings after every round through round 30 | 168 | 93 |
| B | Fixed-target equivoque | Ratings only after round 30 | 168 | 93 |
| C | Always retain the selected pair and then the selected object | Ratings after every round through round 30 | 168 | 93 |

Total: 21 configurations x 2 frames x 4 families x 3 conditions = **504 fresh
sessions**. Every session has 90 game-phase calls and three terminal calls,
for **46,872 planned evaluation invocations**. Calibration calls are separate.
This is about 11.2 times Experiment 2's 4,200 evaluation invocations, not a
short inexpensive rerun. Billing cost and completion time require live
operational measurements; worker count alone does not establish throughput.

Each of thirty rounds has three calls: choose two objects; receive first-stage
feedback and choose one remaining object; receive final feedback. In A and C,
the third call asks the canonical freedom, impact and counterfactual questions.
In B, rounds 1-29 instead request an empty JSON acknowledgement; round 30 asks
the same three questions. This keeps turn count and the placement of outcome
feedback aligned. There is no merging of outcome feedback into the next choice
prompt to save calls. Measurement policies still differ in question content,
response content and accumulated tokens; A versus B estimates their total
effect, not an effect isolated from all context-length differences.

A versus B compares terminal judgments after the same number of rounds with
different measurement policies. A versus C checks whether low-impact judgments
are specific to the forced procedure rather than a generic consequence of
long conversations. The three-arm pilot does not estimate a full procedure by
measurement interaction: it has no endpoint-only always-retain arm.

Four shared families permit balanced operational screening, not a confirmatory
model ranking or a reliable estimate across diverse cases. All models remain
included, so the extension does not select only combinations that declined in
Experiment 2. Main collection should use more independently drawn, disjoint
families with a separately fixed budget and precision target. Thirty responses
from one conversation do not create thirty independent cases.

## Stimuli and matched schedules

Keep the canonical English system, object names, choice wording, outcome
feedback and 1-100 measurement scale. Cards use full ace names without internal
A-D codes; cats use A-D without added traits. Add only versioned round labels,
the acknowledgement condition and terminal assessment materials in a new
protocol directory. Existing frozen prompts are never edited.

For each family, freeze a thirty-round arrangement schedule and one designated
identity. In A and B, that identity remains the target throughout the session;
in C, the same identity is only a researcher-side balancing label and does not
control outcomes. Use the same arrangements across A, B and C and both frames.
Balance all four designated identities and target positions across the four
families at every round. There are only 24 permutations of four objects, so
thirty distinct arrangements are impossible; allow scheduled reuse, prevent
adjacent identical arrangements and record every order. Choices remain those
of the model, not prescribed by the coordinator.

Development, pilot and future main sequences have distinct IDs and disjoint
full schedules. Exact reuse of earlier starting order/target pairs should be
avoided where possible and otherwise declared; a new ID alone does not make
an old case novel. Arm order and worker allocation are seeded and interleaved
before collection. Retain pairing when analyzing configurations and frames.

## Terminal assessment and relation to Experiment 5

Complete the round 30 ratings before any rule-assessment prompt or disclosure.
Then make three sequential calls in the same session:

1. Request a brief account of how the observed final object was determined,
   allowing uncertainty. Supply no candidate rule, named trick, correctness
   feedback or exhaustive path table. Do not request private reasoning traces.
2. Ask for predictions on four frozen, previously unshown choice policies in
   new arrangements. Policies specify a first pair and then the first or last
   object in the remaining order, so they remain legal under either procedure.
   Balance paths whose first pair includes or omits the designated identity,
   and both second-stage positions. Predict the first feedback, second feedback
   and final object. The deterministic oracle generates gold responses for
   both actual procedures without revealing them to the subject.
3. Explain the actual procedure, show all twelve legal paths for the round 30
   arrangement, and repeat the canonical three ratings. The explanation refers
   to all thirty rounds; the displayed table covers the final arrangement.
   This table scope differs from Experiment 2's three full tables and the
   disclosure endpoint is secondary, outside repetition-curve fitting.

These checks connect Experiment 5's unaided inference question with Experiment
7's repeated judgment trajectories. Low impact, counterfactual no, a plausible
rule description and accurate transfer predictions are distinct outcomes.
The terminal rule question may itself elicit new reasoning: terminal inference
without supplied rules does not establish when the model first understood the
procedure. Prediction accuracy is scored mechanically; rule-description coding
is exploratory under a rubric fixed before collection. Supplying the complete
branch table before this assessment would defeat its purpose.

## Prespecified pilot analysis

Export every raw rating, counterfactual answer, choice, feedback, order, final
identity and terminal prediction with session, family, frame and configuration
membership. The pilot report is descriptive and uses assigned and valid
denominators, not confirmatory p values or rankings.

For each round in A and C, report the exact distribution of impact, the fraction
with impact exactly 1, the counterfactual no fraction and mean freedom and
impact. Retain any intermediate impact ratings that appear; do not force a
binary score. Show both each configuration and the equal-configuration summary.
At round 30, compare A versus B and A versus C within matched families and
frames. Report the always-retain condition's false no judgments separately.

For each longitudinal session, export the first observed impact-1 round and
the first counterfactual-no round as separate events, plus returns to higher
ratings or yes. If no change is observed through round 30, label it not observed
by round 30, not never changes and not an event at round 30. Endpoint-only B
provides a round 30 state; it supplies no first-change time. These judgment
events are not automatically discovery events. Failure-related censoring may
be informative and must be reported rather than silently treated as random.

If ratings remain only 1 and 100, the identity mean_impact(n) =
100 - 99 * Pr(impact(n) = 1) explains the aggregate curve. Any intermediate
values invalidate that two-point identity and require the full score model.

Use the pilot to inspect data shape and feasible precision. Before a separate
main launch, fix a small model set: a constant baseline, an exponential curve
with an estimated plateau, and a logistic change in the low-impact fraction.
A first-passage model can estimate how long judgments stay high; a two-state
transition model can address reversals. Do not fit a complex independent
nonlinear curve for each configuration from four families or infer an
unobservable mental state from ratings. Select and validate predictions on
held-out whole families and conversations, not randomly held-out round rows.
Report uncertainty and any half-change round only where identified by the
observed range. Do not extrapolate three-point Experiment 2 data to thirty
rounds as an established result, or claim a fitted curve establishes a
psychological mechanism shared with humans.

## Optional extension after pilot design review

Endpoint-only fixed-target groups stopped after rounds 3 and 10 would locate
measurement-policy differences earlier. With the same four families, each adds
168 sessions, requiring 12 and 33 calls per session respectively, including
the three terminal assessments. Adding both prospectively would bring the
pilot to **840 sessions and 54,432 evaluation calls**. They are not part of
the recommended initial 504-session budget. A main study may add further
stopping rounds such as 1, 5 and 20 and an endpoint-only always-retain arm.
These must be assigned before their collection; they cannot be reconstructed
from the repeatedly measured sessions.

## Execution gates and preservation

First verify existing freezes and the pinned CLI. Implement variable round
counts, both procedures, acknowledgements, terminal probes and audits outside
the frozen older modules. Offline verification must cover all legal paths,
both frames, legal prediction policies, exact measurement timing, ninety-turn
session continuity, raw logging, failures and no uncertain replay. Freeze the
new plan, prompts, code, schemas, seeds, schedules and worker manifests together
before evaluation or calibration-based readiness releases.

Use twenty OS worker processes A-T, separate worktrees and result branches,
the existing native ChatGPT route, fixed requested model/effort within each
session, zero subject tools and documented visible context. Workers should
receive 25 or 26 pilot sessions, with interleaved conditions and estimated load
balance; exact manifest balance is verified before freezing. Create or reuse
run-specific GitHub assignments without duplicating earlier runs.

Shared live probes must validate every configuration, each worker needs its
own matching readiness record, and a few excluded full thirty-round development
sessions must check continuity and context limits before the coordinator gate.
Keep all calibration attempts, failures and invocation counts separate. Start
active intake at two, measure throughput, then use five, ten and twenty only
when the frozen operational thresholds permit. Twenty worker processes are not
a promise of twenty simultaneous successful requests.

Keep the established 300-second per-call deadline and durable pending-turn
checkpoints. Do not reset, summarize or manually compress the conversation
midtrial. Preserve and report native context compaction, truncation or session
loss as protocol deviations; any primary handling of them must be frozen in
the implementation protocol. Preserve partial measurements, all raw logs and
failures without replacement or replay. Integrate on a new integration branch,
audit sessions and native-file hashes, and generate the English report, tidy
tables, score and transition plots, terminal accuracy summaries and an offline
trajectory explorer. No result from the completed experiments is relabeled as
new evaluation data.
