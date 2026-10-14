# Research status

Last repository organization: **2026-10-14, Europe/Berlin**.

There are [six completed studies and pilots](EXPERIMENTS.md). The latest collection, the question-intervention study on 2026-10-13, contains 180 complete conversations and 5,940 evaluation invocations. Documentation maintenance introduces no new model calls.

## Current guide versus historical records

| Location | Purpose |
| --- | --- |
| Root `README.md` and `docs/` | Current interpretation, navigation, reproduction, and branch policy |
| `analysis/results/<run_id>/` | Published reports, tables, figures, and verification |
| `results/<run_id>/` | Native records, audits, and compressed archives |
| Root `*_PLAN.md`, `PROMPTS.md`, `WORKER_BRIEF.md` | Historical plans, stimuli, and execution instructions; some are frozen inputs |
| `NEXT_SESSION_PROMPT.md`, `PREPARATION_STATUS.md`, `RUN_STATUS.md` | Early-study handoffs, access checks, and completion records |
| Study `runtime/` and `preparation/` folders | Historical launch, interruption, recovery, and publication records |

Historical statements such as “not started,” “authentication needed,” or “next execution” describe their original dates. Use this status page and each run's completion audit for the current interpretation. A new study needs a new run ID and separately documented protocol.

## Completion and exclusions

- **Single round:** 2,100 assigned, 2,093 complete. The 2,096 valid pre-disclosure responses include valid partial observations from incomplete conversations.
- **Three rounds:** 420/420 complete.
- **Supplied-rule transfer pilot:** 2,016/2,016 tasks complete.
- **Thirty-round pilot:** 28/28 conversations complete.
- **Ten-round replication:** 2,520/2,520 complete. User-directed fresh restarts of incomplete attempts were documented; this amendment differs from the original no-replacement plan. Excluded attempts remain archived.
- **Question intervention:** 180/180 complete. Two model-capacity failures, containing 34 invocations, were preserved separately and replaced with fresh conversations under the same settings. Twelve calibration invocations are also excluded from evaluation.

Conversations, rounds, native invocations, internal HTTP retries, and billing are different quantities. Unknown wire-request counts and costs are not inferred from invocation ledgers.
