# Experiment 2 continuation handoff

Owner-confirmed sequence: Round 1 / M1, Round 2 / M2, Round 3 / M3,
then final disclosure / M4. Ten turns per trial, 420 sessions, 4,200 planned
invocations. Twenty OS workers A–T; active permit limit 20 at owner request.

Run: `equivoque-2026-10-09-exp2-v1`.
Integration branch: `integration/equivoque-2026-10-09-exp2-v1`.
Approved frozen source: `1b397809ed98ce20521a3e4903a0a4c93800c816`.
Freeze SHA-256: `e704ca265a351cddf2431cae2ae7c5eedc530365a938952fc6c18c1432d53c81`.
The temporary nine-turn preparation draft collected no data; the final files
exactly match the original validated ten-turn preparation. Keep frozen files unchanged.

Current progress is authoritative in collection-progress.json. The detached
supervisor/worker PIDs and controls are in processes-resume-01.json. Check actual
process state, not only PID existence: zombies are terminated. Do not launch
another supervisor or shard while current processes are live.

Original runtime reconnection terminated foreground workers. Twenty unique
completed pending responses were reconciled from native completion events with
zero new model calls. Original exit statuses and durations remain null. See
runtime-recovery-01.json and resume-authorization-01.json. Fresh continuation
gate: coordinator-launch-resume-01.json. Resume retains original native sessions;
only an unrequested next turn may be called. Never replay a pending/failed/completed
request. Never silently replace failed trials, models, efforts, targets, or prompts.

All twenty complete ten-turn readiness sessions and 21 shared access probes
remain valid: 221 calibration invocations in 41 sessions, excluded from evaluation.
Readiness lives under worker-*/preflight-01 and shared-preflight-01. GitHub issues
36–55 already assign A–T; integration review is draft PR 56. Reuse without duplication.

Immutable terminal data checkpoints use `python -m experiment2.publish --phase
checkpoint` with fresh tool credentials. Do not capture active changing trial
files as complete records. Recovery snapshots and gate histories are immutable.
Do not include credentials, authorization headers, or native session storage.

After every assigned ID is terminal and all workers stop, run publish --phase
finalize. Open/reuse twenty audited result PRs with `python -m
experiment2.result_prs` before merging. Commit coordinator evidence so root is
clean, then run publish --phase integrate. Integrate only the separate experiment
2 branch, preserving experiment 1 and main.

Run frozen analysis: `python -m experiment2.analyze --output
analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01` (new directory required).
Then `python -m experiment2.deliver --output` with the same directory adds
calibration accounting, descriptive choice exports, offline explorer, artifact
hashes, and ZIP without changing frozen estimators. Primary: R3 minus R1 impact.
Ten shared case clusters, 2,000 frozen-seed bootstrap replicates, no imputation,
no causal repetition/control or model-ranking claim. Preserve valid partials.

Push integrated raw results and English report/tables/PNG/SVG/HTML/ZIP to the
integration branch, refresh PR 56 via REST with concrete audited counts, and
verify remote heads. Do not merge main. Update this handoff/status upon completion.
