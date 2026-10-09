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
