# Experiment 3 pilot handoff

Scope: pilot only. Do not rerun Experiment 1 or 2; do not start Experiment 3 main or Experiments 4–7.

Read EXPERIMENT_3_PILOT_PLAN.md and experiment3/runtime/STATUS.md. The frozen 2,016-task preparation and 20 worker worktrees are complete. Authenticate through normal Codex ChatGPT login, verify a genuinely refreshed catalog and actual access, then run `python -m experiment3 shared --output experiment3/runtime/shared-preflight-02`. Preserve failed preflight-01 and access-probes-01. Both failed model access probes count as calibration; no evaluation data exist.

Once shared readiness passes, run `python -m experiment3.coordinate --phase preflight --shared <absolute shared-preflight-02/readiness.json> --attempt 01 --preflight-concurrency 2`. Release only when all twenty worker checks pass at source fdf738ba0d574021c30c0854b2f5ef60230f0e85: `python -m experiment3 release --readiness <twenty worker readiness paths> --shared <shared report> --output <coordinator launch path>`.

Launch the collection with a detached coordinator `python -m experiment3.coordinate --phase run --launch <absolute launch path> --attempt 01`. Use the frozen measured ramp 2→5→10→20. Monitor and checkpoint/push raw results. Never replay an uncertain request or replace failures. Integrate worker result branches into integration/equivoque-2026-10-11-exp3-pilot-v1, audit, then execute `python -m experiment3.analyze`. End after the pilot report. All prior raw data and freezes must remain unchanged.
