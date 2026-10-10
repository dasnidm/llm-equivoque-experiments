# Experiment 2 status

Run: `equivoque-2026-10-09-exp2-v1`.

The owner explicitly confirmed a measurement after Round 3 before disclosure.
Final sequence: Round 1/questions, Round 2/questions, Round 3/questions,
then final disclosure/last questions. Four measurements, ten native turns per
trial: 420 sessions and 4,200 planned evaluation invocations.

The confirmed sequence exactly matches the validated preparation source
`1b397809ed98ce20521a3e4903a0a4c93800c816` and its original freeze. All 53 source,
prompt, plan, analysis, and manifest files are restored byte for byte. Twenty
workers completed ten-turn native calibration, and all 21 shared live model/effort
checks passed. Those 221 invocations are calibration only. All 620 worker native
calibration files passed integrity audit. The temporary nine-turn draft produced
no evaluation observations or additional model calls.

All 420 trial IDs, ten shared paired cases, three round arrangements, targets,
worker ownership, requested models/efforts, and canonical English base prompts
are unchanged. Preserve original readiness evidence and require the coordinator
release before evaluation. See confirmed-measurement-sequence.json and the
prospective EXPERIMENT_2_PLAN.md. Experiment 1 remains unchanged.

The owner requested immediate concurrency 20. Twenty active workers were verified.
Runtime reconnection then terminated the foreground coordinator and workers;
20 uniquely completed pending responses were recovered without inference calls.
All worker audits passed. Parent-observed exit codes and durations for recovered
turns remain null. A fresh coordinator release and recorded provenance history
authorize only unrequested next turns. The twenty-worker continuation now uses
a detached supervisor; see runtime-recovery-01.json, resume-authorization-01.json,
and processes-resume-01.json.

Collection finished: all 420 assigned sessions completed, 4,200 evaluation
invocations, zero failed/interrupted/unattempted trials. All twenty worker audits
passed, verifying 13,020 evaluation native files and 420 unique sessions. Four
measurement occasions each have 420 valid endpoints. Final worker commits are
pushed and match explicitly fetched remote refs. Result PRs 57–76 target the
separate experiment 2 integration branch. Both freezes are unchanged: 53 new
protocol files and 32 original experiment 1 files. Integration and frozen analysis
are the remaining steps.
