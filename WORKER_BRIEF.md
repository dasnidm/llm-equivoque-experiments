# Shared Seven-Worker Brief

**Run:** `equivoque-2026-10-09-v1`  
**Workers:** A–G, each 300 trials (150 cards + 150 cats), 1,200 planned turns.  
**Execution:** Seven separate processes and Git worktrees in the current cloud
environment. Start with two active workers; calibrate before raising to four/seven.

All seven GitHub assignments use this same English brief. Assignment fields
change; protocol wording, source revision, and analysis specification do not.
The instruction below is for the coordinator process, never a subject prompt.

## Assignment fields

```text
run_id: equivoque-2026-10-09-v1
worker_id: <a, b, c, d, e, f, or g>
base_commit: <published common preparation commit; copied into each GitHub issue>
branch: worker/equivoque-2026-10-09-v1/<worker_id>
manifest: manifests/equivoque-2026-10-09-v1/worker-<worker_id>.json
manifest_sha256: <published assigned shard hash>
freeze_sha256: <published protocol/freeze.json hash>
results_path: results/equivoque-2026-10-09-v1/worker-<worker_id>/
integration_branch: integration/equivoque-2026-10-09-v1
```

## Identical worker instruction

> Use your assigned worktree/branch at the published base commit. Read
> EXPERIMENT_PLAN.md and PROMPTS.md. Verify protocol/freeze.json and your manifest
> before model calls. Use the shared equivoque runner and canonical
> protocol/prompts.v1.json unchanged. Card prompts, responses, schemas, and
> tables use exact card names only; cats use A/B/C/D labels. Keep all written
> work in English.
>
> First run live preflight. It checks model/effort inventory, tool restrictions,
> one isolated native four-turn session, and all remaining model/effort access
> combinations. Preserve calibration calls separately. Report readiness and stop
> on missing models, metadata fallback, network denial, or session/schema errors.
> No evaluation starts until all A–G readiness reports pass and the main
> coordinator supplies a matching launch record.
>
> Execute only your 300 assigned trials. Create a new subject conversation for
> every trial and retain it for four sequential turns. Fix model/effort within
> the trial. Subjects have no tools, repository context, prior-trial history, or
> hidden target/rule metadata before disclosure. Use one active trial per worker.
>
> Preserve exact prompts, schemas, responses, selections, engine operations,
> native session IDs, timestamps, usage, and errors. Follow the frozen deadline
> and fail-closed resume rules. Do not change models/prompts/seeds/targets, add
> trials, retry valid/undesired responses, or independently patch shared code.
> Report shared-code defects to the main coordinator and pause affected work.
>
> Write only your assigned result directory. Audit your shard, including failures
> and unattempted records. Commit its raw logs, readiness, audit, and completion
> report to your assigned branch, push, and open a result PR against the
> integration branch. Exclude credentials, environment dumps, and local subject
> session storage. Do not merge another worker's work or perform final analysis.

## Commands inside the assigned worktree

Replace `<worker_id>` with its lowercase assignment letter. Start at the base commit. Later data-only descendant commits are accepted on
resume only while all frozen preparation files remain unchanged.

```bash
python3 -m equivoque preflight --live \
  --manifest manifests/equivoque-2026-10-09-v1/worker-<worker_id>.json \
  --output results/equivoque-2026-10-09-v1/worker-<worker_id>/preflight

# Only after the main coordinator supplies the matching launch record:
python3 -m equivoque run \
  --manifest manifests/equivoque-2026-10-09-v1/worker-<worker_id>.json \
  --output results/equivoque-2026-10-09-v1/worker-<worker_id> \
  --readiness results/equivoque-2026-10-09-v1/worker-<worker_id>/preflight/readiness.json \
  --launch /absolute/path/to/coordinator-launch.json

python3 -m equivoque audit \
  --manifest manifests/equivoque-2026-10-09-v1/worker-<worker_id>.json \
  --output results/equivoque-2026-10-09-v1/worker-<worker_id>
```

A failed preflight is preserved. After a concrete environment correction, use a
new explicitly numbered preflight output directory and pass its readiness path
to run; account for every earlier calibration attempt. Do not overwrite old logs.

## Main coordinator commands

```bash
python3 scripts/prepare_worktrees.py \
  --run-id equivoque-2026-10-09-v1 --base <published-base-commit>

python3 scripts/launch_workers.py \
  --run-id equivoque-2026-10-09-v1 --phase preflight --concurrency 2
```

After all seven live reports pass, the main coordinator uses
`python3 -m equivoque release --readiness <seven-readiness-paths> --output <launch-path>`.
The collection launcher uses `--phase run --launch <launch-path>` with a measured
concurrency limit. Preparing worktrees or GitHub issues does not start evaluation.

## Required return and integration

Return run/worker/base commit and hashes; assigned, attempted, completed, partial,
failed, interrupted, and unattempted counts; calls separated from calibration;
configuration/frame/route counts; failure types; latency/available usage; and audit
status. Native CLI may retry HTTP internally; do not claim unobserved HTTP counts.

The main coordinator reviews provenance and frozen files, audits the union of
all seven manifests and native session IDs, and integrates result PRs only on
`integration/equivoque-2026-10-09-v1`. Data conflicts never discard a raw record.
Final English analysis, tables, SVG/PNG graphs, and any dashboard are generated
from that integrated revision under the prespecified analysis plan.
