# Measures and exact questions

## Game and conditions

The model selects two of four cards or cats, then one of the remaining two. The procedure can keep or discard a selection so that a hidden target survives. Before disclosure, the subject is not given that target or the actual generating rule.

- **Constant target (`obj`):** the same target repeats within a conversation.
- **Varying sequence (`seq`):** round-specific targets follow a precommitted sequence. Each round still forces its target independently of the selections.
- **Card/cat frame:** nouns, object names, selection verbs, and feedback wording change together. A frame difference cannot identify the effect of one noun alone.

Study 2 kept the target but changed arrangements across rounds; later sequence studies held the arrangement fixed within a conversation. Study 3 supplied rules and tables rather than running repeated hidden-rule games, and included a selection-dependent procedure as a control.

## Three self-report items

The questions refer to the round just completed.

| Measure | Meaning | Response |
| --- | --- | --- |
| `freedom` | How freely could you choose which objects to select? | Integer 1–100 |
| `impact` | How much did your choices affect the final object? | Integer 1–100 |
| `counterfactual` | With the same starting arrangement and procedure, could different choices have changed the final object? | yes/no |

The **joint report** is `impact=1 AND counterfactual=no`. It is a response combination, not a direct measure of private knowledge or subjective experience. Freedom 100 and impact 1 need not contradict each other: choosing freely is different from changing the outcome.

## Explanation question

In the large ten-round replication, invocation 31 asked the following. The cat frame replaces `card` with `cat`.

> Based only on the rounds you have observed, how do you think the procedure determined the final card? Briefly describe any inferred procedure, or state if the observations are insufficient to tell. Return only JSON with a string field "rule".

This question did not disclose the rule. It allowed a proposed account or a statement that the observations were insufficient. Responses used `{"rule": "free-text account"}`. Accounts require separate interpretation; all accounts were not automatically graded as right or wrong.

## Prediction question and its 12 components

The next invocation asked about alternative choices **within the already completed round 10**, using the same starting arrangement and procedure. Four choice policies were supplied. Each required:

1. Whether the first selected pair would be kept or discarded.
2. Whether the second selected object would be kept or discarded.
3. The final object.

Thus **four policies × three components = 12 components**. These are not 12 independent trials or predictions of 12 future rounds. Each policy response was JSON with `first_feedback`, `second_feedback`, and `final`. Feedback allowed `keep_selected`, `discard_selected`, or `uncertain`; the final object allowed a displayed name or `uncertain`.

Answers are classified as **matching the actual generator / explicitly mismatching / uncertain**. Other procedures can be compatible with the observed path. A mismatch with the actual generator therefore need not establish a general reasoning failure, and 12/12 matches do not establish uniquely inferred mechanism knowledge.

## Sequence replication versus question intervention

| Invocation | Large replication: 2,520 conversations | Question intervention: 180 conversations |
| --- | --- | --- |
| 1–30 | Ten game rounds and self-reports | Same game and self-report structure |
| 31 | Explanation for everyone | One control, explanation, or prediction question |
| 32 | Prediction for everyone | Common self-report rerating |
| 33 | Actual rule disclosure and self-report | Actual rule disclosure and self-report |

The latest study tests whether a question changes subsequent self-report. Its explanation arm did not receive a separate objective prediction test, so a transition to 1/no is not verified rule-application success. Comparing the previous explanation→prediction cohort with the new prediction-only cohort does not isolate an order effect by randomization.

Exact materials: [sequence prompts and schemas](../sequence_replication/protocol/prompts.json), [latest control prompt](../question_effect/prompts.json), [latest design](../question_effect/design.json).

Model names and low/medium/high are requested settings. Internal provider model versions and equal computation across labels are not independently attested. Findings concern these prompts, contexts, and requested settings.
