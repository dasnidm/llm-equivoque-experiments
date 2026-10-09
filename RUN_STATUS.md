# Completed evaluation

Run: `equivoque-2026-10-09-v1`.

2100 assigned trials attempted; 2093 complete; 8392 evaluation subject invocations.

All seven workers passed live readiness at the common frozen source. Concurrency was measured at two and four before expansion to seven. The user subsequently authorized ten additional executors and immediate concurrency 17; the original A–G manifests and total 2,100-trial roster remained unchanged. Seven actual 300-second timeouts remain terminal failures. After draining already-requested responses without replay and passing 21 shared service checks, all 17 executors resumed with measured whole-trial concurrency and delay-sensitive intake. A second runtime reattachment was reconciled from 17 final native responses without replay, followed by another 21 shared service checks and a separately gated resumption. All raw records, prior preflight failures, session IDs, hashes, and errors are retained. The coordinator audited the seven-shard union before integrating results on the separate integration branch.

See `analysis/results/equivoque-2026-10-09-v1/attempt-02/REPORT.md` for the English report and endpoint denominators, `index.html` for the portable figure browser, `tables/` for CSVs, `figures/` for SVG/PNG exports, and `provenance.json` for the exact integrated-data revision and analysis source hash.

The final portable report package is `analysis/results/equivoque-2026-10-09-v1/equivoque-analysis.zip`. Current presentation is `attempt-02`; the original `attempt-01` remains preserved and all 18 CSV tables are byte-identical. The second presentation adds an observed-results interpretation and readable interval axes. Final audit covers 2,100 unique trials/sessions and 27,276 exact native files; 430 calibration/development invocations are excluded. Review PR: https://github.com/dasnidm/llm-equivoque-experiments/pull/35. Main remains unchanged.
