# Verification record

- Existing `exp7_persistent.test_audit` and `exp7_persistent.test_transport`:
  **35 tests passed**.
- Real CLI, loopback-only 34-turn integration checks passed for 0.159.0-alpha.3,
  0.167.0 and 0.169.0-alpha.3. Latest reviewed warning-filter configuration also
  passed the stable CLI's three integration cases after the final code change.
  These use dummy auth, a child-only home and blocked external HTTP(S).
- A separate loopback server returning HTTP 429/Retry-After 20 exposed a native
  warning in stderr in about 0.30 seconds while the RPC error count was still 0.
  External model requests: 0. This verifies visibility, not disabling of retries.
- Native audit rejects arbitrary 429 substrings such as retry policy fields and
  UUIDs. Retained `codex_core::responses_retry` warnings confirm 16, 10 and 30
  hidden response-429 retry records in the three high-load stages.
- All **60 completed live technical conversations** passed independent original
  RPC/scientific replay audits, with one PID and thread across 34 turns. Actual
  tool events in the successful records: 0. These are excluded from main samples.
- All 12 live technical stages, including local SQLite initialization failure and
  the interrupted pool-10 stage, have private archive/index readback receipts.
  Operator evidence and the post-HALT scope clarification are backed up separately.
- The STOP guard refuses before profile creation, startup or inference. Meter
  records contain **0 new logical turn/start admissions after HALT**. Physical
  HTTP attempts already inside an in-flight CLI request are not directly counted.
- The previous scientific freeze remains unchanged:
  `16f61a400ff1280c54614719efb416df76fb5b696af47ee7b59342474ddbb75a`.
- Python compilation and `git diff --check` passed. New report links were checked.
- Repository-wide documentation validation reaches a pre-existing missing link:
  `docs/EXP7_EXP5_SPEED_COMPARISON.ko.md` links to
  `EXP7_PERFORMANCE_DIAGNOSIS.ko.md`, which exists as unrelated untracked work in
  the original checkout and is absent from this isolated tracked worktree. That
  unrelated user work was not staged or changed.

Original RPC, summaries, scientific responses, failures, pending checkpoints and
older reports were preserved. The corrected operational verdict is a separate
derived analysis; the old RPC-level zero counts were not silently rewritten.
