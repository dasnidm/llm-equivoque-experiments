# LLM Equivoque Experiments

An experimental study of how language models interpret choices and their effect on an outcome in a four-object equivoque task, using matched card and cat descriptions.

The current working plan is **21 model/effort configurations × 100 trials × 4 model calls**, or **2,100 trials and 8,400 calls**. Five workers are proposed for parallel execution.

Read [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the protocol, model matrix, randomization, measurements, analysis, and runtime assumptions.

## Status

- English working plan prepared on October 9, 2026.
- This repository currently contains documentation; the experiment runner has not been implemented here.
- The planned multi-model experiment has not been run.
- Model access in the intended cloud execution environment still needs verification.
- The working allocation is 50 card trials and 50 cat trials per configuration. This allocation is a documented assumption pending confirmation; 100 trials per frame would double the experiment size.

An earlier local pilot used `gpt-6.1-sol` with `low` effort for 16 trials and 64 calls. Its scope and limitations are described in the plan; the original raw data are not included in this initial repository.

## Next implementation steps

1. Implement and validate the deterministic four-object engine and exhaustive branch disclosure.
2. Freeze prompts, schemas, randomization, analysis contrasts, and technical failure policies.
3. Implement one subject session per trial, with four sequential turns and independent sessions across trials.
4. Verify model access and measure throughput with five workers before launching the planned run.

Creating this repository does not launch inference jobs or configure a cloud environment.
