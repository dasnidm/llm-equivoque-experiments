# LLM Equivoque Experiments

Six completed studies/pilots examine model-reported choice freedom, influence on
an outcome, counterfactual judgments, prediction uncertainty, and question effects
in four-object equivoque procedures. Subject prompts are English; the current
research notes are mainly Korean.

| Study | Completed units | Main observation |
| --- | ---: | --- |
| Single round | 2,093/2,100 conversations | 2,092/2,096 valid pre-disclosure impact ratings were 100; all 2,093 valid post-disclosure reports were impact 1/counterfactual no |
| Three repeated rounds | 420 conversations | Mean impact 100→96.2→82.8 before disclosure |
| Supplied-rule transfer pilot | 2,016 single-response tasks | Transfer accuracy 98.45%; conflicting-minus-neutral host-claim contrast +0.05 percentage points |
| Thirty-round sequence pilot | 28 conversations | Final joint report 5/14 constant-target vs 0/14 varying-sequence |
| Ten-round replication | 2,520 conversations | Final joint report 319/1,260 constant-target vs 1/1,260 varying-sequence |
| Question intervention | 180 conversations | Explanation prompted 20/30 joint-report changes in gpt-5.6-sol-high; 0/30 in control |

The **joint report** is impact=1 AND counterfactual=no. It is not a direct score of
privately inferred mechanism knowledge. Prediction components matching the hidden
generator, explicit mismatches, and uncertainty are separate categories. Only 97
of 1,260 sequence conversations matched all 12 components, but 76% of the 1,163
remaining conversations contained no explicit mismatch: they wholly abstained or
combined matches with uncertainty.

The latest question intervention independently crossed two models with control,
explanation, or prediction questions after 10 rounds and before disclosure. All 180
pre-question reports were impact 100/yes. gpt-6.1-sol-high had no joint-report
transition, but all 30 prediction-arm impact ratings changed 100→50 while retaining
yes. The strict joint endpoint therefore misses intermediate rating changes.
The explanation arm had no separate objective prediction test. Changes in reported
judgments do not establish whether the model already knew, deduced a rule at the
question, or changed its response policy.

[Study index and downloads](EXPERIMENTS.md) · [Detailed interpretation](RESULTS.md)
· [Measurement definitions](METHODS.md) · [Archive-only reproduction](REPRODUCIBILITY.md)
· [Branch preservation](BRANCHES.md) · [Korean home](../README.md)

`main` contains the current guide and cumulative completed results. Six result
branches and six result tags preserve historical snapshots; obsolete worker and
preparation branches are retired after ancestry checks. The one independent live
snapshot is retained under an archive tag. Original protocols, data, and published
analyses remain unchanged. Use historical tags or frozen-source packages for
reproduction because the living root README has been updated.
