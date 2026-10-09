# Incomplete live data snapshot

Run: `equivoque-2026-10-09-v1`. Captured between 2026-10-09T21:30:20.116663+00:00 and 2026-10-09T21:30:21.124500+00:00.

Statuses captured: {"active": 17, "complete": 1026} across 1043 unique attempted evaluation IDs. The full planned roster remains 2,100 trials. Seventeen executors continue collection.

All current terminal records, preflight/recovery evidence and coherent live-state/native-raw snapshots are retained under `results/equivoque-2026-10-09-v1/worker-*/`. Pending streams can be incomplete. `snapshot-live-01-executor-*/` files are historical snapshot evidence, excluded from evaluation-file discovery and never an instruction to replay. No result analysis was run on this incomplete snapshot.

The original result branches were also updated. See `LIVE_SNAPSHOT.json` for capture accounting, per-executor commit links and raw-file inventories. Main is unchanged, and full integration/analysis waits for collection completion.
