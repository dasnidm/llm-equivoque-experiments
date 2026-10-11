# Experiment 3 pilot worker brief

Run `equivoque-2026-10-11-exp3-pilot-v1`, pilot only. All twenty worker processes
follow the identical plan in EXPERIMENT_3_PILOT_PLAN.md and the frozen
experiment3/protocol files. Only assigned manifests and worker names differ.
Use the separate worker worktree/result branch, 100 or 101 single-turn tasks.
Do not launch any previous experiment or the full Experiment 3 main study.

Verify the common frozen source and assigned manifest. Preflight uses excluded
development cases. No evaluation before matching shared readiness, worker
readiness and coordinator launch record. Subjects have no tools or repository
context; each assigned task starts a fresh native session with the requested
model/effort. Only English prompts and exact card names or cat labels are used.

Preserve prompts, schemas, native raw events/stderr, timestamps, answers, usage,
failures and pending checkpoints. Never replay uncertain requests, replace
failed tasks, correct answers with extra calls, or alter shared source. Halt
new intake on transport failure. Write only the assigned result directory.
Audit the terminal shard, commit and push its branch, and submit its result PR
against integration/equivoque-2026-10-11-exp3-pilot-v1. The coordinator audits
and integrates the union. No model rankings or main-study claims from this pilot.
