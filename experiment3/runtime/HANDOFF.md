# Experiment 3 pilot in-progress handoff

Run equivoque-2026-10-11-exp3-pilot-v1 is collecting its authorized 2,016 single-turn pilot tasks. Do not launch another coordinator, preflight, replacement trial or main experiment. Read collection-progress.json, detached-supervisor-01.json, processes-01.json and coordinator-launch-01.json before any action. Twenty OS worker processes use the verified frozen source 46126a6e4d4fe28806bbc26695d6caff7fe53544 with measured concurrency 2→5→10→20.

All 21 model/effort access checks and 20 worker checks passed following owner device reauthentication. Calibration: 43 native invocations (41 valid, two preserved auth failures), excluded. Earlier failures remain preserved. Existing experiments and main are unchanged.

Monitor the detached supervisor and durable task states. Never replay an uncertain task, replace a failure, tune prompts or change sample size. Only previously unrequested tasks can be considered after diagnosing an actual interruption; preserve all original pending/native records and authorizations. Do not interpret partial pilot outcomes as final estimates.

When all workers exit, audit each terminal shard, push its result branch, create/reuse its result PR, integrate on integration/equivoque-2026-10-11-exp3-pilot-v1, audit the union and run the frozen experiment3.analyze. Write the English report, CSVs and SVG/PNG/HTML deliverables; complete hashes/publication verification. End after the pilot. No Experiment 3 main or Experiment 4–7 collection.
