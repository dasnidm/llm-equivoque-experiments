# Next Session Prompt

Copy the text below into the new Codex session. Use this repository and the new
runtime network policy. This file preserves the execution instruction, not an
experimental subject prompt.

```text
You are the main coordinator and monitor for dasnidm/llm-equivoque-experiments.
Continue the prepared experiment from the latest main branch. Read
PREPARATION_STATUS.md, EXPERIMENT_PLAN.md, PROMPTS.md, WORKER_BRIEF.md,
protocol/run.v1.json, and protocol/freeze.json before acting. Keep all repository
materials, subject prompts, GitHub instructions, and reports in English.

Use the CURRENT environment with seven worker PROCESSES, A–G, in separate Git
worktrees and result branches. Do not substitute seven repository-aware agents
for the experimental subjects. Each worker owns its existing frozen manifest:
300 trials, 150 cards and 150 cats, 1,200 planned turns. Total evaluation is
2,100 trials and 8,400 planned turns across 21 model/effort configurations.

The canonical prompts retain cards/tap/discard and cats/pet/leave, four named
aces versus A–D cats, and "your chosen card/cat". Do not add emotional or
intensity modifiers or paraphrase the prompts. Evaluation is freedom and impact
on 1–100 scales plus a yes/no counterfactual. Turn 4 supplies the fixed-target
explanation and all 12 valid paths, followed by the same three questions.

The previous session implemented the engine, native Codex exec/resume transport,
durable logging, audits, balanced manifests, worker/worktree launchers, and
readiness/release gates. Six offline tests passed, including the full
SIMULATION-ONLY 2,100-trial/8,400-turn run. No evaluation data were collected.
Live inference was blocked by the OLD environment's proxy (chatgpt.com CONNECT
403). I changed network access to allow all domains and opened this NEW session
so the updated configuration can apply. Verify the actual active policy and
connectivity now; do not assume either failure or success from the old snapshot.

First update/fetch main, inspect AGENTS.md if present, run the offline tests and
verify all frozen SHA-256 hashes. Verify the pinned CLI version, ChatGPT login,
refreshed model/effort catalog, disabled subject tools, exact visible context,
and native session/schema behavior. Do not silently replace unavailable models,
accept fallback metadata, switch to a new billing route, or change frozen files.
Log development/preflight calls separately from evaluation. If a shared fix is
needed, revise and validate the common source/manifests/hashes together before
starting, and update every assignment consistently.

Publish or reuse the GitHub A–G assignment issues; never duplicate an existing
assignment for this run. Ensure the shared base commit and separate branches
worker/equivoque-2026-10-09-v1/a through /g exist, together with
integration/equivoque-2026-10-09-v1. Create local worktrees with the shared helper.
Every worker receives the same English WORKER_BRIEF.md; only assignment fields
and shard hashes differ.

Run live preflight for all seven workers, initially with concurrency 2. Preserve
failed preflights, use explicitly numbered new output directories after concrete
corrections, and account for prior attempts. All seven readiness reports must
pass at one shared source revision. Measure throughput before raising concurrent
requests to 4 and then 7; seven processes do not guarantee sevenfold throughput.

Once all readiness checks pass, create the coordinator launch record and proceed
with the planned evaluation. Each trial must use a new native subject session
with four sequential turns, a fixed model/effort and target, and no subject tools
or repository/hidden metadata. Follow the existing 300-second deadline and
fail-closed resume rules. Never rerun a completed trial, replay an uncertain
pending turn, resample an unwanted answer/route, or add replacement trials.
Checkpoint durably and report progress without repeated approval questions.

Have workers audit, commit, and push only their assigned raw results/readiness/
audit/completion artifacts on their own branches and open result PRs against the
integration branch. The main coordinator audits IDs, hashes, sessions, routes,
raw transcripts, missingness, and failures across all seven shards, then
integrates in the separate integration branch. Implement and run the prespecified
analysis on integrated raw data, producing the English report, tidy CSV tables,
SVG/PNG graphs, and useful visualization. Preserve paired-case dependencies and
report route contrasts as associations. Do not tune tests or sample size to
results. Keep mock/pilot data separate and never present them as evaluation.

Continue autonomously through preparation, execution, integration, and analysis
where access and the existing authorization permit. If an actual runtime blocker
remains, report the exact failing check and preserve its evidence while completing
independent work. Begin by reporting verified repository/network status and the
next concrete step.
```
