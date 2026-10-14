# Completed studies and downloads

These six studies use different observation units. Study 3 consists of single-response tasks; the other studies use multi-turn game conversations. Early unpreserved prototypes and access/calibration probes are not pooled into evaluation results. Study 1 links to its final `attempt-02` presentation; the original analysis is also preserved.

| Study | Run ID | Complete / assigned | Evaluation native invocations | Result tag |
| --- | --- | ---: | ---: | --- |
| 1 | `equivoque-2026-10-09-v1` | 2,093/2,100 | 8,392 | `results/exp1-v1` |
| 2 | `equivoque-2026-10-09-exp2-v1` | 420/420 | 4,200 | `results/exp2-v1` |
| 3 | `equivoque-2026-10-11-exp3-pilot-v1` | 2,016/2,016 | 2,016 | `results/exp3-pilot-v1` |
| 4 | `equivoque-2026-10-12-sequence-pilot-v1` | 28/28 | 2,604 | `results/sequence-pilot-v1` |
| 5 | `equivoque-2026-10-12-sequence-replication-v1` | 2,520/2,520 | 83,160 | `results/sequence-replication-v1` |
| 6 | `equivoque-2026-10-13-question-effect-v1` | 180/180 | 5,940 | `results/question-effect-v1` |

Invocation counts describe evaluation runner calls. They exclude separately recorded calibration, development, and discarded attempts, and are not counts of internal HTTP retries or billable requests. Failure policies differed by run; consult [Status](STATUS.md) and the original reports.

<a id="exp1"></a>
## 1. Single-round study

Seven models × three reasoning-effort settings × two frames × 50 shared cases yielded 2,100 assigned conversations. A forced-outcome game was followed by self-report, then disclosure of the rule and exhaustive evidence, and a second self-report.

Of 2,096 valid pre-disclosure impact ratings, 2,092 were 100. All 2,093 valid post-disclosure reports were impact 1/counterfactual no. Near-ceiling initial ratings limited route contrasts. Routes arose from model choices and were not randomized interventions. Valid partial observations from the seven incomplete conversations remained in the relevant endpoint denominators.

[Original report](../analysis/results/equivoque-2026-10-09-v1/attempt-02/REPORT.md) · [Analysis ZIP](../analysis/results/equivoque-2026-10-09-v1/equivoque-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-09-v1/attempt-02/tables) · [Native records](../results/equivoque-2026-10-09-v1) · [Audit](../analysis/results/equivoque-2026-10-09-v1/attempt-02/union_audit.json)

<a id="exp2"></a>
## 2. Three repeated rounds

Twenty-one model/effort configurations × two frames × ten cases yielded 420 independent conversations. The target stayed constant while arrangements changed across rounds. Disclosure followed all three rounds.

Mean impact was 100 → 96.229 → 82.793; counterfactual-no counts were 0 → 16 → 72. All 420 post-disclosure reports were 1/no. Additional experience, repeated measurement, and conversation length changed together; repetition alone was not isolated by a randomized control.

[Original report](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md) · [Analysis ZIP](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/tables) · [Native records](../results/equivoque-2026-10-09-exp2-v1) · [Audit](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/union_audit.json)

<a id="exp3"></a>
## 3. Supplied-rule transfer pilot

Twenty-one configurations × two frames × two procedures × three host claims × eight case families yielded 2,016 single-response tasks. Rules, exhaustive tables, and a host opinion were supplied. Both fixed-target and selection-retaining procedures were included.

Mean transfer accuracy on questions 2–4 was 98.446%. The conflicting-minus-neutral host-claim contrast was +0.050 percentage points. This tests applying supplied information, not discovering a hidden rule. Near-ceiling accuracy may limit sensitivity to the opinion manipulation.

[Original report](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/REPORT.md) · [Analysis ZIP](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/tables) · [Native records](../results/equivoque-2026-10-11-exp3-pilot-v1) · [Audit](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/union_audit.json)

<a id="sequence-pilot"></a>
## 4. Thirty-round sequence pilot

Seven models at low effort × two frames × constant/sequence targets yielded 28 conversations and 840 game rounds. The historical code folder `experiment7/` refers to this same run; it is not a separate seventh completed study.

At round 30, the joint report appeared in 5/14 constant-target and 0/14 sequence conversations. The five constant-condition impact drops first appeared in rounds 3–7 and persisted. All freedom ratings were 100, and all 28 post-disclosure reports were 1/no. One conversation per cell and one shared sequence support a descriptive screen, not model rankings or typical discovery times.

[Original report](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/REPORT.md) · [Analysis ZIP](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/sequence-pilot-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/tables) · [Native records](../results/equivoque-2026-10-12-sequence-pilot-v1) · [Audit](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/union_audit.json)

<a id="sequence-replication"></a>
## 5. Ten-round replication

Seven models × three efforts × two frames × two schedules yielded 84 cells, with 30 conversations per cell: 2,520 conversations and 25,200 game rounds. Layouts stayed fixed within conversations, and 30 case families were shared across cells. Rule accounts and predictions followed the round-10 self-report and preceded actual rule disclosure.

Round-10 joint reports occurred in 319/1,260 constant-target conversations (25.3%) and 1/1,260 sequence conversations (0.08%). Among 300 constant conversations with an earlier first joint report, 284 (94.7%) maintained it at every later round. Frame differences depended on the model. All-12 prediction matches occurred in 540/1,260 constant and 97/1,260 sequence conversations. Incomplete predictions must not all be classified as explicit errors.

[Original report](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/REPORT.md) · [Analysis ZIP](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/sequence-replication-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables) · [Native records](../results/equivoque-2026-10-12-sequence-replication-v1) · [Audit](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/union_audit.json)

<a id="question-effect"></a>
## 6. Question intervention: 180 conversations

Only gpt-5.6-sol and gpt-6.1-sol at high effort, cards, and sequence targets were tested. Two models × control/explanation/prediction × 30 shared cases yielded 180 fresh conversations. After round 10, each received one question, followed by a common self-report before disclosure.

All 180 pre-question reports were impact 100/yes. gpt-5.6-sol changed to 1/no in 0/30 control, 20/30 explanation, and 3/30 prediction conversations. gpt-6.1-sol had no joint transition, but all 30 prediction-arm impact ratings changed 100 → 50. The study separates question effects on subsequent reports; it does not distinguish prior knowledge from newly elicited inference or a change in response policy.

[Original report](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/REPORT.html) · [Analysis ZIP](../analysis/results/equivoque-2026-10-13-question-effect-v1/question-effect-analysis.zip) · [Tables](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/tables) · [Native records](../results/equivoque-2026-10-13-question-effect-v1) · [Audit](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/audit.json)

[English interpretation](RESULTS.md#question-effects) · [Archive-only reproduction check](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/reproduction.json)

GitHub displays repository HTML as source rather than executing it as a report. Use the English guide for reading online, or download and extract a study ZIP and open its HTML locally. Published original reports retain their original wording and language.
