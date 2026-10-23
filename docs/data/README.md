# Derived explanatory tables

These tables aggregate sequence-condition data from the existing ten-round replication for the documentation update on 2026-10-14. No additional model calls were made, and published tables remain unchanged.

Source: [original trials.csv](../../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/trials.csv), filtered to `kind=seq`. The exact source hash is recorded in [provenance.json](provenance.json).

| File | Unit |
| --- | --- |
| [sequence-response-forms.csv](sequence-response-forms.csv) | 180 conversations per model, pooled over three effort levels and two frames |
| [sequence-uncertainty-by-effort.csv](sequence-uncertainty-by-effort.csv) | 60 conversations per model-effort profile, pooled over two frames |

Each conversation has 12 prediction components. The sum of `match_components + mismatch_components + uncertain_components` equals the conversation count × 12. `uncertain_component_percent` measures uncertainty across components, not the proportion of conversations with 12/12 uncertain answers.

The four conversation categories are mutually exclusive:

1. `all12_match`: all 12 components match the actual generator.
2. `all12_uncertain`: all 12 components express uncertainty.
3. `partial_match_and_uncertain_no_mismatch`: some matches and otherwise uncertainty, with no explicit mismatch.
4. `has_mismatch`: at least one explicit mismatch, possibly alongside uncertainty.

Components are not independent trials. These are descriptive summaries: uncertainty is not combined with explicit errors, and the tables do not establish a general model-capability ranking. Readable versions appear in [Results](../RESULTS.md).

## Retrospective statistical supplement: 2026-10-23

[statistics-2026-10-23/](statistics-2026-10-23) contains the new six-study statistical audit. The original outcomes were already known; these tests are exploratory. [Results and interpretation](../STATISTICS.md) · [한국어 요약](../STATISTICS.ko.md) · [Methods](../STATISTICAL_METHODS.md).

The directory includes all attempted contrasts, raw and adjusted p-values, matched case-block effects and intervals, descriptive summaries, separate McNemar sensitivities, three figures, an offline searchable HTML table, source hashes and byte-reproduction records. Rounds and prediction components are aggregated within conversations before comparison. Study 4's single-case pilot is labeled separately from the principal case-level analyses. Reproduce with `python scripts/statistical_audit.py --check`; no model requests are made.
