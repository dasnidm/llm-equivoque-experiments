# User-authorized executor expansion

On 2026-10-09 the user requested approximately ten additional worker processes,
then explicitly requested immediate concurrency 17 because of time constraints.
This supersedes the previous instruction to limit execution to seven processes
and the proposed intermediate 10-process calibration stage.

The original A–G logical manifests each still own 300 trials (150 cards and
150 cats). Their hashes, the 2,100-trial roster, all targets and starting cases,
the 21 model/effort configurations, the canonical English prompts, the deadline,
and four sequential native turns remain unchanged. No evaluation IDs, replacement
trials or replay calls were added. The approved frozen source remains
`c7651dbc5ff3fa2e0e40b9eb63715f3b0f40e372`, with freeze SHA-256
`4d19cee4c0ecb44029c66d054f86d02bda8c81598667af2aa491cb1298dc66e4`.

Executors H–Q have separate worktrees and result branches. They execute disjoint
subsets of unstarted original-manifest IDs. Existing partial trials stay with
their original executors; terminal trials are excluded. Unstarted paired frames
stay together when both remain on the same original shard. Each executor follows
a subsequence of the original manifest order. A durable assignment hash,
coordinator launch record, process locks and exclusive per-trial claim records
prevent concurrent or repeated execution.

The execution adapter imports the unchanged frozen `run_trial` and native
transport from each original logical worker's worktree. Subject scratch paths
also remain under that original worktree, so helpers introduce no new executor
metadata or different repository context into experimental subject inputs.
Only results are written in the helper's own branch. The coordinator will audit
each exclusive share and reunite the results under the original seven manifests
before the prespecified full-union analysis.

All ten helpers verified frozen source hashes, pinned CLI and ChatGPT login,
inherited their original worker's all-21-configuration live readiness, inspected
the actual serialized requests for all 21 configurations offline, and completed
a new four-turn native live session. These 40 new calibration invocations are
preserved separately and excluded from evaluation. No billing route changed.

Before subdivision, original worker parents were paused in subprocess waits.
Their seven existing CLI requests completed normally. Child exit status 0 was
observed from Linux `/proc` zombie status. Raw event streams, exact schemas and
system text were retained and reconciled into their existing checkpoints
without any new inference request. All seven responses arrived within the
unchanged 300-second deadlines. Original monotonic durations for those seven
turns are unavailable and remain missing. This handoff is distinct from the
earlier runtime reattachment recovery, whose seven original exit codes and
durations are both unavailable.

Seventeen processes began collection at 2026-10-09 21:13:08 UTC, with 877 trials
already complete. Throughput and failures are observed operationally; this is
not a randomized comparison of concurrency levels. The original seven-process
calibration and all failed readiness evidence are retained. Analysis will retain
executor provenance and describe the scheduling amendment as a technical limit.
