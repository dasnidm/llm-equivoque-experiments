# Current execution status

Run: `equivoque-2026-10-09-v1`. All seven workers passed live preflight at shared source `c7651db`. ChatGPT device authentication was restored by the owner; the current runtime permits unrestricted HTTP routing, with actual model responses verified.

Collection began at 20:07:56 UTC on October 9, 2026 (22:07:56 Europe/Berlin), initially with two active workers. The coordinator measured concurrency at two and four before expanding to seven. The user subsequently requested ten additional executors and explicitly requested immediate concurrency 17. All seventeen A–Q executors began collection at 21:13:08 UTC, with 877 trials already complete. See `preparation/current-runtime/EXECUTION_AMENDMENT.md`, `executor-assignments-01.json`, and `coordinator-launch-03.json` for that authorization, exclusive execution schedules, and readiness gate.

The frozen preparation documents describe the earlier preparation state. They remain unchanged during evaluation; current readiness, launch, calibration, and collection evidence are in `preparation/current-runtime/` and each worker result directory.

The original A–G logical manifests each retain 300 trials, 150 per frame, and the total evaluation remains 2,100 trials with 8,400 planned turns. Only remaining execution ownership was subdivided across additional processes. Frozen source, prompts, models, efforts, targets, seeds and deadlines remain unchanged. Failed/partial/interrupted trials remain in the assigned denominator and are never replaced.

Current operational state is in the local `preparation/current-runtime/collection-progress.json`; historical progress is appended to `expanded-progress-history.jsonl`. Terminal-record checkpoints are pushed on seventeen separate result branches. All ten helpers passed new native four-turn session checks and all-configuration offline isolation checks, with 40 separately retained calibration invocations. Current network policy is unrestricted and enforced; a read-only account quota check confirmed ordinary usage remains allowed.

The coordinator postprocessor waits for all seventeen executors, audits and publishes exclusive helper shares, reunites canonical A–G ownership, audits the full raw-data union before integrating on the separate integration branch, runs the prespecified analysis and export validation, and creates a draft review PR without merging main. English report, tidy tables, SVG/PNG figures and a portable HTML figure browser will be copied to the user-facing output directory after completion.

Before resuming work, follow `preparation/current-runtime/ACTIVE_COLLECTION_HANDOFF.md`. Do not restart the original whole-manifest runners while helpers own disjoint IDs. Final outcome analysis and figures are pending collection completion.
