# Preparation Status

**Run:** equivoque-2026-10-09-v1  
**Prepared on:** October 9, 2026  
**Execution choice:** One current cloud environment with worker processes A–G
and one Git worktree/result branch per worker.

## Prepared and verified offline

- Common English prompts: cards/tap/discard, cats/pet/leave, chosen-card/cat
  attribution, no emotional/intensity modifiers, three evaluation fields. Cards
  display and accept full names only; cats use A/B/C/D. No card subject sees the
  engine codes, including in response schemas or counterfactual tables.
- Fixed target and all 1,152 target/order/choice paths; 2,304 frame-specific
  four-turn prompt paths; deterministic 12-row disclosure tables.
- Native exec/resume transport with canonical system text and disabled subject
  tools, a 300-second deadline, durable raw logs, and no uncertain-turn replay.
- A–G disjoint manifests: 300 trials each, 150 per frame, 1,200 planned turns.
  Shared cases remain paired. Each worker has 14 trials in 18 configurations and
  16 trials in three configurations. Total: 2,100 trials and 8,400 planned turns.
- Seven meaningful offline checks, including the full simulation-only dry run,
  failure preservation, session uniqueness, and raw-log tampering detection.
- Common worker brief, worktree/launcher scripts, hash freeze, readiness and
  coordinator-release gates, separate result and integration branches.

## Live blocker observed

The supervisor is logged in to Codex with ChatGPT and has
`codex-cli 0.159.0-alpha.3`. Its first developmental probe attempted gpt-6.1-sol/low
but received **zero model responses**: the proxy rejected chatgpt.com with CONNECT
403. Retained diagnostics also reported fallback metadata for that model because
its refreshed catalog was unavailable. Do not substitute a model or accept
fallback metadata as verified access.

The owner reports allowing all domains. The last active runtime observation
still showed restricted policy, no chatgpt.com grant, and CONNECT 403. Runtime
application/recheck is required. No proxy bypass, alternate identity, new API
key, or silent transport replacement has been used.

## Gate to evaluation

After the applied network policy permits the intended ChatGPT inference endpoint,
run live preflight for A–G and retain all reports. Each has a maximum of 24
requested subject turns, separately counted as calibration. All seven must be
ready for the same frozen source, manifests, model matrix, and native-session
behavior before the main coordinator generates a launch record.

**No evaluation data have been collected.** Code/manifests/assignments can be
prepared and published while this live gate remains pending; execution readiness
must not be reported as complete before it passes.

## Current-session corrections

The current runtime's startup HTTP policy is unrestricted. Preserved probes
reached github.com and chatgpt.com with HTTP 200; the unauthenticated Codex model
endpoint returned HTTP 401. No proxy bypass or TLS verification change was used.
The status service reports policy state `unknown`, so that field alone does not
establish enforcement; the connectivity/inference evidence is recorded separately.

The inherited ChatGPT login initially could not refresh its token. The owner
completed the normal device-login flow in this session, using the same ChatGPT
route. The refreshed catalog then included all seven specified models and all
three required effort settings. A separate gpt-6-sol/low developmental request
returned valid JSON with no metadata fallback or tool events. This is not an
evaluation trial.

The original A–G preflights and their post-login `preflight-02` attempts are
preserved. They exposed residual structured CLI role/mode hints and an inert
`unified_exec` capability flag. The common transport now explicitly suppresses
the role/mode hints; common preflight additionally inspects actual native request
bodies for every configuration, without credentials or inference, and requires
zero offered tools plus exact visible context. Frozen prompts, schedules, seeds,
model/effort matrix, deadlines, and sample size are unchanged. A coordinated new
source/hash freeze and seven matching live preflight reports are still required
before the launch gate opens.
