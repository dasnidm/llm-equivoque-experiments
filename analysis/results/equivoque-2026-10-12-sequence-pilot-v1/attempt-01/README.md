# Thirty round forcing sequence pilot

Seven exact model/low combinations, four conditions, 28 assigned conversations, 840 planned game rounds and 2,604 planned evaluation invocations. The precommitted sequence and frozen prompts are in EXPERIMENT_7_PLAN.md and experiment7/protocol.

Analysis is under analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01: REPORT.md, seven CSV tables, five PNG/SVG figures, a standalone explorer and an artifact hash manifest.

Raw records are losslessly preserved in results/equivoque-2026-10-12-sequence-pilot-v1/raw-archives. Each worker archive contains its native events, effective schemas, journals, trial states, calibration attempts, audit and provenance. The coordinator archive retains shared checks, failed diagnostics, gate records, process logs and concurrency observations. Each archive manifest lists SHA-256 hashes of every original file.

The remote branch stores compressed raw archives plus audit/provenance summaries; the local integration additionally retains every unpacked raw file. Frozen source files are identical between local and published source commits, whose commit metadata differ. This is a representation difference, not a loss of raw bytes.

To reproduce tables and figures, use the integration branch with the pinned environment and run python -m experiment7.analyze --root . --output analysis/results/equivoque-2026-10-12-sequence-pilot-v1/reproduction-01. The analyzer safely extracts worker archives when unpacked trial states are absent and reconstructs all prompts and force paths before analysis. No inference is needed for reproduction.

Calibration is excluded from all evaluation tables. The invocation ledger counts runner invocations across every physical attempt once, including failed calibration; it does not estimate hidden HTTP retries or billing cost. No failed or completed evaluation trial is replayed or replaced. One conversation per cell supports descriptive comparisons, not population discovery-time estimates.
