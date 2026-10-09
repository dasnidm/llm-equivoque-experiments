# Experiment 2 shared worker brief

Read `EXPERIMENT_2_PLAN.md` and `experiment2/PROMPTS.md`. The run is
`equivoque-2026-10-09-exp2-v1`: 20 worker **processes** A–T, 21 assigned trials
each. Every trial uses one new native subject session across ten sequential
turns: three choose-two/choose-one/measurement rounds, then disclosure/measurement.
Subjects receive only frozen English stimuli and the inspected empty-directory
native context. They have no tools or repository/assignment instructions.

Use your own `worker/<run_id>/<letter>` result branch and worktree at the common
approved preparation commit. Verify `experiment2/protocol/freeze.json` and
`manifests/<run_id>/worker-<letter>.json`. Run live ten-turn calibration separately
from evaluation. Shared 21-configuration service checks and all 20 worker
readiness reports must match before the coordinator releases collection.

Execute only the 21 assigned IDs in your manifest, one active trial per worker.
The target, three arrangements, model, effort, and exact prompts are fixed.
Never replace or repeat a failed/completed/uncertain request, resample choices,
add corrective messages, inspect scores to alter stimuli, or patch common source.
Retain any valid earlier endpoints in failed trials. A systemic transport or
isolation failure closes new intake globally while existing requests drain.

Preserve exact prompts, schemas, answers, native event streams/stderr, sessions,
timestamps, usage, failures, and all three engine traces. The runner archives
native files with SHA-256 checks. Write only your assigned result directory.
Audit, commit, and push your results on your branch; integrate only through the
separate experiment 2 integration branch. Keep written repository materials
and reports in English. Never merge to main or include credentials/session storage.

Commands are available as `python -m equivoque2`: `service-preflight` is shared;
`preflight --manifest ... --output ... --shared ...` is per worker;
`release --readiness <20 paths> --shared ... --output ...` is coordinator-only;
`run --manifest ... --readiness ... --launch ... --controls ...` requires release;
`audit --manifest ... --output ...` independently reconstructs all three rounds.

The coordinator runs 20 processes with fair trial permits, calibrating limits
2, 5, 10, then 20. Readiness uses no evaluation IDs or reused subject sessions.
Failed preflights remain recorded; corrections use numbered new output paths.
