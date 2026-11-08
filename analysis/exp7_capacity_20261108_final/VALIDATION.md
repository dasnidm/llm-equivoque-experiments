# Verification record

- The original experiment freeze remained valid: `16f61a400ff1280c54614719efb416df76fb5b696af47ee7b59342474ddbb75a`.
- All 54 completed technical conversations (1,836 turns) passed original RPC/scientific integrity audits. This verifies retained evidence, not equivalence of response distributions or a permanent rate limit.
- Every live stage, including the interrupted 110/min stage, has a private archive, member hashes, and a verified remote readback receipt. The pre-model local launch error and operator logs were also retained separately.
- Offline checks covered completed-state no-replay behavior, halted-send behavior, transport lifecycle, technical-trial validation, and per-model transport routing. No inference was performed by those checks.
- The main scientific run remained STOP; no failed or uncertain scientific request was retried or replaced.
- `python scripts/validate_repository_docs.py` failed on an existing link in `docs/EXP7_EXP5_SPEED_COMPARISON.ko.md` to missing `EXP7_PERFORMANCE_DIAGNOSIS.ko.md`. The reference and missing target also exist in pinned baseline commit `9171e0612ad50fa8e2d999ba0af212cf37291a60`; this capacity study did not introduce it.

Raw backup repository: private `dasnidm/llm-equivoque-exp7-raw`, branch `capacity/equivoque-2026-11-08-exp7-capacity-v1`.
The 110/min stage and subsequent operator-evidence readbacks were confirmed at commits `3cef05d0e8a128b1f9a6f2363cf834766b949f57` and `9a34c22dd3c8edba057ad058bb38f4ff0a602c48` respectively.
