# Branches and result preservation

## Current structure

Use `main` for the current guide and all six completed studies. Historical result branches preserve existing links and the source available at each study's completion. Start new experiments from a separate branch with a new run ID, design, and records; keep result tags fixed.

| Study | Preserved branch | Result tag |
| --- | --- | --- |
| Single round | `integration/equivoque-2026-10-09-v1` | `results/exp1-v1` |
| Three repeated rounds | `integration/equivoque-2026-10-09-exp2-v1` | `results/exp2-v1` |
| Supplied-rule transfer pilot | `integration/equivoque-2026-10-11-exp3-pilot-v1` | `results/exp3-pilot-v1` |
| Thirty-round sequence pilot | `integration/equivoque-2026-10-12-sequence-pilot-v1` | `results/sequence-pilot-v1` |
| Ten-round replication | `integration/equivoque-2026-10-12-sequence-replication-v1` | `results/sequence-replication-v1` |
| Question intervention | `experiment/equivoque-2026-10-13-question-effect-v1` | `results/question-effect-v1` |

For maintenance, create a short-lived branch from current `main`. Do not reuse completed result branches for new collection.

## Cleanup on 2026-10-14

The remote was reduced from 99 branches to **7: main and six result branches**. The 92 retired temporary branches were preserved as follows.

| Temporary branch type | Count | Preservation |
| --- | ---: | --- |
| Worker | 87 | Commits reachable through the latest results and main's merged history |
| Preparation | 3 | Same |
| Planning | 1 | Same |
| Snapshot | 1 | Independent history preserved by `archive/2026-10-14/snapshot-live-01` |

The [branch inventory](archive/branches-2026-10-14.json) records every previous name and exact commit. Six result branches remain available for links in earlier conversations and reports. History, scientific records, local worktrees, and in-progress files were preserved.

Historical review PR [35](https://github.com/dasnidm/llm-equivoque-experiments/pull/35) was merged; draft PRs [56](https://github.com/dasnidm/llm-equivoque-experiments/pull/56), [97](https://github.com/dasnidm/llm-equivoque-experiments/pull/97), and [158](https://github.com/dasnidm/llm-equivoque-experiments/pull/158) were closed after their completed results were present in main. Consult each PR for its final state. Closing a PR is not an additional scientific validation.

## Recovering a historical branch

Create a local branch from the exact SHA in the inventory:

```bash
git switch -c recovered-worker <commit-sha-from-inventory>
```

Inspect the independently preserved snapshot with:

```bash
git show archive/2026-10-14/snapshot-live-01
```

For read-only access, use a [result tag](EXPERIMENTS.md) or the corresponding commit on GitHub.
