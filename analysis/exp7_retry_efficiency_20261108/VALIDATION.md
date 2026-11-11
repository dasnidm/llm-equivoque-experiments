# Validation and operational limits

- Final command: `PYTHONPATH=.:scripts python -m unittest scripts.test_exp7_retry_transport scripts.test_exp7_header_probe exp7_persistent.test_audit exp7_persistent.test_transport -v`.
  **49 tests passed in 21.040 seconds.** All model-facing fixtures use loopback,
  dummy auth and blocked external HTTP(S); external model requests: 0.
- The real-CLI fixture completes 34 logical turns after two synthetic capacity
  rejections, with one process/thread and the exact expected user history.
  Compression, no uncertain-response replay, quota/reflection rejection, FIFO,
  STOP cleanup and the post-completion HTTP framing case are covered.
- Live evidence: **126 complete conversations, 4,284 successful logical turns,
  4,294 physical attempts, 10 explicit capacity rejections recovered**.
  All retained science/RPC and retry/FIFO record audits passed; actual tool events: 0.
- Operational stage gates did **not** all pass. The final v4 stage retained its
  STOP/HALT after a last HTTP framing error 82 ms after the final successful RPC.
  This was not replayed or reclassified as an operational pass. See the separate
  [review](TRANSPORT_CLOSE_REVIEW.ko.md).
- The FIFO live check used 10 workers. The recommended 6/FIFO combination itself
  was not directly live-measured, and the final framing fix was verified offline.
  Old readiness does not authorize the revised main profile.
- Six closed live stages, the zero-upstream local failure, and operator/source
  provenance are privately archived with remote SHA256 readback receipts.
  Operator evidence commit: `22416ed2aca1d2d9b91cc69aef6cd1072df05cd6`.
- All **132 recorded native process IDs** (including the local failed startup
  cohort) were no longer alive at closure. Existing main and diagnostic STOPs
  remain present. The common board records the next-run policy separately from
  its unchanged scientific job data and historical concurrency cap.
- The original scientific freeze verifies **78 files**, retains its original
  global CLI check, and keeps SHA256
  `16f61a400ff1280c54614719efb416df76fb5b696af47ee7b59342474ddbb75a`.
  The new technical runtime used its separately pinned CLI 0.167.0.
- Python syntax, regenerated metrics/plots, visual inspection and staged
  `git diff --check` passed. New relative links resolve locally.
- Required repository documentation validation was run after committing the new
  analysis paths. It reaches the pre-existing missing link from
  `docs/EXP7_EXP5_SPEED_COMPARISON.ko.md` to `EXP7_PERFORMANCE_DIAGNOSIS.ko.md`.
  That unrelated file exists as untracked user work in the original checkout;
  it was not staged, modified or copied into this change.

No existing scientific data, failed/pending evidence, manifest or freeze was
deleted, overwritten, or reclassified as a pilot. No main collection was resumed.
