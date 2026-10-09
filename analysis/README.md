# Prespecified analysis implementation

This code follows the frozen `EXPERIMENT_PLAN.md`. It does not make model calls.
Run only in the integration worktree after auditing/integrating all worker data:

```bash
python3 -m unittest discover -s analysis -p 'test_*.py' -v
python3 analysis/analyze.py --output analysis/results/equivoque-2026-10-09-v1/attempt-01
```

Dependencies are NumPy, pandas, and matplotlib. The analysis records installed
versions and its source hash. Use a new output directory for each analysis.

The loader audits every shard, manifest union, provenance, and cross-worker
session uniqueness. It rejects simulation records and excludes all preflight,
development, and pilot data. Final analysis requires finished collection. An
explicit `--allow-incomplete` option labels aborted collection as partial; it
still refuses to generate outcome reports/graphs without valid evaluation data.

The 2,000 shared bootstrap draws resample the 50 starting cases, retaining both
frames and all configurations. Route associations use equal route weights and
the prespecified ten-per-route and 95% valid-replicate thresholds. Missing
endpoints are retained without imputation; endpoint-specific paired estimates
exclude only invalid members of that endpoint pair. No hypothesis tests or
additional trials are introduced.

Outputs include an English report, tidy trial/turn and estimate CSVs, endpoint
denominators, route counts (including zeros), transitions, evidence consistency,
target/position, choice, worker/time and technical descriptions, SVG/PNG figures,
captions, audit, and provenance. Actual HTTP attempts, billing costs, and
independently observed backend model versions remain unavailable unless the
transport exposes evidence for them. Requested model/effort and native usage
remain in raw logs. Synthetic numerical tests are never experimental data.
