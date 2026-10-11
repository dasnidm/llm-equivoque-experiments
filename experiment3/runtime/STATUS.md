# Experiment 3 pilot status

Run `equivoque-2026-10-11-exp3-pilot-v1`: pilot only, 2,016 single-turn tasks, 20 worker processes.

Normal ChatGPT device reauthentication succeeded. Fresh shared-preflight-02 passed all 21 model/effort access/schema checks and all 21 offline zero-tool request inspections. All twenty worker preflight-01 reports passed at the same frozen preparation commit 46126a6e4d4fe28806bbc26695d6caff7fe53544. The two earlier failed authentication probes are preserved. Calibration audit: 43 native invocations, 41 valid responses and two authentication failures, excluded from evaluation.

The coordinator launch record releases only the frozen pilot. Collection starts with two active workers and follows the measured 2→5→10→20 ramp. Each task has one new session; no replay or replacement. The full main study and Experiments 4–7 are outside scope. Existing data and main are unchanged.
