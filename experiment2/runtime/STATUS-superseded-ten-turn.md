# Experiment 2 status

Run: `equivoque-2026-10-09-exp2-v1`.

Preparation source: `1b397809ed98ce20521a3e4903a0a4c93800c816`.
Freeze SHA-256: `e704ca265a351cddf2431cae2ae7c5eedc530365a938952fc6c18c1432d53c81`.

420 trials, 21 model/effort configurations, 10 cards and 10 cats per configuration.
Each trial contains three rounds and four measurements in one ten-turn native session.
Twenty isolated worker processes/worktrees A–T own 21 disjoint trial IDs each.

53 frozen preparation files verified in all 20 worktrees. Existing tests: 9 passed.
Experiment 2 protocol/concurrency/integrity/numerical checks: 11 passed.
The 420-trial/4,200-turn simulation and nine figure families passed offline validation;
these are not evaluation observations. Experiment 1 frozen files and results are unchanged.

Shared live access preflight is running. Worker ten-turn live preflight and the
coordinator release remain required before evaluation. Preserve failed attempts.
See shared-preflight-01/readiness.json and the prospective EXPERIMENT_2_PLAN.md.
