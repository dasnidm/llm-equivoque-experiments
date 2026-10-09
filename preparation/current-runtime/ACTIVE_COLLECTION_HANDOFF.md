# Active collection handoff

The frozen preparation documents are historical. Actual evaluation began on
2026-10-09; do not reset result branches or restart a fresh 2,100-trial run.
The current integration branch is `integration/equivoque-2026-10-09-v1`.

The user explicitly authorized ten additional worker processes and immediate
concurrency 17. All original A–G logical manifests, canonical stimuli,
model/effort configurations, targets, seeds, cases and the 2,100-trial roster
remain unchanged. Exclusive execution IDs and readiness paths for A–Q are in
`executor-assignments-01.json`; gate `coordinator-launch-03.json` binds its hash.
Read `EXECUTION_AMENDMENT.md` before interpreting the old seven-process wording.

Before launching any process, inspect the active process list and
`collection-progress.json`. The active external collection controller is
`work/coordinator/expanded_collect.py`, which launches
`work/coordinator/expanded_executor.py`. The checkpoint monitor is
`work/coordinator/monitor_expanded.py`; the completion/analysis controller is
`work/coordinator/postprocess.py`. Each executor has its own worktree and branch
`worker/equivoque-2026-10-09-v1/{a..q}`.

Do not invoke the original frozen whole-manifest `equivoque run` during this
execution epoch: helpers own exclusive future IDs, and the original whole-shard
runner does not coordinate those claims. The external adapter calls the
unchanged frozen `run_trial` and native transport from each original logical
worker's tree, retains original subject paths, and writes only its exclusive
results in its own tree. Existing terminal IDs are omitted from all schedules.
Existing partial states stayed with A–G. Durable claims and process locks block
repeated or concurrent execution. Additional repository agents are not subjects.

If runtime reattachment stops processes, preserve all pending states and existing
native CLI children. Never replay an uncertain request. Compare durable raw
event streams, exact system/prompt/schema, session continuity, deadline evidence,
response counts and available exit status before any offline checkpoint
reconciliation. Recovery scripts for epochs 01 and 02 already ran and their
reports are immutable; do not rerun or overwrite them. An executor provenance
file or durable claim prevents unreviewed relaunch. Recovery/resumption requires
an explicitly numbered new execution epoch and a new fail-closed gate.

The postprocessor automatically waits for successful completion of all seventeen
executors. It publishes helper result PRs and merges their disjoint data into
their original logical owner's branch, then publishes complete 300-trial A–G
audits/result PRs, audits all IDs, hashes, sessions and full raw checkpoints,
merges only on the separate integration branch, runs the prespecified analysis,
verifies export/denominator integrity, creates a draft main review PR, and copies
the report/browser/tables/figures to the output directory. It halts on actual
collection failure. Main is not automatically merged.

All preflight failures, calibration calls, original recovery logs and unknown
timing/exit metadata remain separate from evaluation. Ten helper session checks
added 40 calibration invocations; all retained worker/helper preflights total
383 calls, plus two development calls. Neither simulation nor the earlier pilot
is evaluation. Do not inspect or tune outcomes while collection is ongoing.

## Actual systemic failure update

Seventeen-executor collection is now paused after seven actual native 300-second timeouts. Current accounting: 1,034 complete, 7 failed, 8 safe partial, 1,051 unattempted. All ten calls active at global pause drained normally inside the deadline; exits were observed and raw streams reconciled without new calls. No uncertain pending evaluation turn remains. The old expanded controller, checkpoint monitor and postprocessor have stopped; do not assume those jobs are still running. A shared 21-configuration live service recheck is running at concurrency 2 in `work/coordinator/recheck_service.py`. Follow `service-preflight-01/readiness.json` and the paused union audit. New collection requires an explicitly numbered gate/epoch and must omit all complete/failed IDs. The eight partial native sessions may resume only their next unanswered turn. A simple access diagnostic took 212.58 seconds; subsequent low-concurrency probes took 87.40 and 3.73 seconds. Frozen source, network policy and account route remain unchanged. No final analysis has run.
