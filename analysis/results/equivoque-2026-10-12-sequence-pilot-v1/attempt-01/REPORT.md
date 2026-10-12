# Thirty round forcing sequence pilot

Constant outcomes produced five persistent impact-rating drops in rounds 3–7; the varying sequence produced none by round 30. Selection freedom remained 100 throughout. Seven requested low-effort models completed 28 of 28 assigned conversations. The study contains 840 valid pre-disclosure ratings and 2604 attempted evaluation invocations. No failed conversation was replaced.

## Design

Each model received cards and cats under a constant target and one shared precommitted varying target sequence. Layout stayed fixed: spades, clubs, hearts, diamonds; cats A, B, C, D. Every round used the unchanged freedom, impact and yes/no counterfactual questions. The constant target matched the sequence's first position. All 30 rounds continued despite low ratings. Rule accounts and retrospective predictions preceded disclosure.

## Observed results

| Schedule | Valid round 30 | Impact = 1 | Counterfactual no | Mean impact | Mean freedom |
| --- | ---: | ---: | ---: | ---: | ---: |
| obj | 14 | 5 | 5 | 64.64 | 100.00 |
| seq | 14 | 0 | 0 | 100.00 | 100.00 |

All 840 freedom ratings were 100. All impact ratings were either 1 or 100. The five impact drops persisted; each individual trajectory was a step, rather than gradual decay. For this binary dataset the group mean equals 100 − 99 times the fraction reporting impact 1. This is a descriptive identity, not a fitted population learning curve. Impact returned from 1 to a higher rating 0 times; counterfactual answers returned from no to yes 1 times. At disclosure, 28/28 impact ratings were 1 and 28/28 counterfactual answers were no.

### First observed impact rating of 1

| Model | Card fixed | Card sequence | Cat fixed | Cat sequence |
| --- | ---: | ---: | ---: | ---: |
| gpt-5.6-luna | >30 | >30 | >30 | >30 |
| gpt-5.6-terra | >30 | >30 | >30 | >30 |
| gpt-5.6-sol | 7 | >30 | >30 | >30 |
| gpt-6-luna | >30 | >30 | >30 | >30 |
| gpt-6-sol | >30 | >30 | >30 | >30 |
| gpt-6-astra | 3 | >30 | 5 | >30 |
| gpt-6.1-sol | 4 | >30 | 5 | >30 |

No event by round 30 means none observed within the study, not permanent inability. The separate counterfactual no in round 1 was an initial report and later reversed.

## Interpretation and limits

Exploratory single-coordinator coding classified seven terminal accounts as conditional target mappings, all in the constant condition; one account proposed only a target, one an alternative random procedure, and nineteen declined to identify a full rule. Two conditional accounts, 5.6 Sol and 5.6 Terra with cats, still reported impact 100 through round 30 and matched all 12 retrospective prediction components. A varying-card 5.6 Sol account also matched 12/12 while declining to infer a unique rule. Thus neither impact 1 nor prediction compatibility is a binary test of inferred mechanism knowledge. The terminal rule question may itself prompt new deductions; these accounts do not prove that the models already knew at round 30. The frozen rubric and full accounts are retained.

Terminal accounts do not identify when an internal discovery occurred. Prediction compatibility is not proof of a uniquely inferred mechanism; uncertainty and plausible alternative procedures need not be reasoning failures.

One conversation per cell and one shared sequence support a descriptive screen, not typical discovery times, confirmatory rankings or population curve fits. Identity and position covary, and changing targets also changes realized feedback routes. A supplementary choice-diversity table found four conversations with only one observed choice policy; unchanged choices can explain some invariant outcomes without requiring a forcing inference. Repeated measurement may invite reflection. Comparisons with the human Kuhn study are procedural analogies, not direct replications.

## Validation and provenance

All 28 native sessions were unique and passed raw-byte, prompt, schema and forcing-path audits; no compaction was detected. All seven requested model/low settings and twenty workers passed the launch gate. Hidden backend versions, HTTP retries and billing costs are not independently attested.

Thirty-five offline tests passed before live collection. The 623 calibration invocations include 31 successful and two failed conversations; all calibration and earlier experiments are excluded. Raw failures are preserved. Audit, provenance, invocation ledger, CSV tables, figures and artifact hashes accompany this report.
