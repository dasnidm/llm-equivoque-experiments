# LLM Equivoque Experiments

A four-object experiment on model-generated judgments of choice freedom and
influence on a fixed outcome, before and after exhaustive evidence. The frames
retain **card/tap** and **cat/pet**, **discard/leave**, and parallel **your chosen
card/cat** wording. Emotional/intensity modifiers are omitted. All materials
and subject prompts are English. Cards are displayed and selected by their full
names, without A/B/C/D prefixes; cats retain A/B/C/D labels.

## Prepared run

`equivoque-2026-10-09-v1` has 21 model/effort configurations, 50 shared paired
cases, and **2,100 trials / 8,400 planned subject turns**. Workers **A–G** each
receive **300 trials / 1,200 turns**, including **150 cards and 150 cats**.
For every configuration a worker receives 14 or 16 trials; each receives the
16-trial allocation for exactly three configurations.

The selected execution is **one current environment, seven worker processes,
seven Git worktrees/result branches**. The owner also provisioned seven cloud
environments, which remain an alternative. Concurrency is calibrated before
increasing from two active workers to four/seven.

## Source and instructions

- [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md): protocol, pairing, failures, analysis,
  planned graphs, and launch requirements.
- [PROMPTS.md](PROMPTS.md) and [protocol/prompts.v1.json](protocol/prompts.v1.json):
  exact English subject prompts and schemas. Ratings are 1–100; counterfactual
  is yes/no; four turns remain in one isolated native subject conversation.
- [WORKER_BRIEF.md](WORKER_BRIEF.md): identical instructions, commands, GitHub
  branch assignments, and separate integration.
- [PREPARATION_STATUS.md](PREPARATION_STATUS.md): verified preparation and the
  remaining live-access gate.
- [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md): complete English handoff
  instruction for the new session with updated network access.
- `preparation/`: offline validation summary and preserved developmental
  access-failure evidence, separate from evaluation data.
- `manifests/equivoque-2026-10-09-v1/`: full schedule and seven disjoint shards.
- `equivoque/`: deterministic engine, Codex native-session transport, durable
  collection, preflight, and raw-log audit.
- `protocol/freeze.json`: SHA-256 hashes of prepared source/protocol/manifests.

## Offline verification

```bash
python3 -m unittest discover -s tests -v
```

The tests validate all 1,152 logical paths and 2,304 frame-specific prompt paths,
allocation/pairing, invalid responses, uncertain resume, log tampering, and a
complete **simulation-only** 2,100-trial/8,400-turn dry run. Simulated records are
rejected by the ordinary experimental audit and are not evaluation evidence.
Python 3.12 and the pinned Codex CLI are used; collection needs no Python packages
beyond the standard library.

## Live status

The first supervisor probe received no model response because the active proxy
policy denied chatgpt.com. The owner reports relaxing domain restrictions; the
last observed active policy still showed restricted access. Recheck the applied
policy and live inference before launch. A local ChatGPT login or model catalog
alone does not prove inference access. No planned evaluation has started.

All seven live readiness reports and a coordinator launch record are required.
The prior 16-trial pilot used different session/measurement methods; its raw data
are not included and are kept separate from this run.
