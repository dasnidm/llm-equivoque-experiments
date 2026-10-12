# Ten-round sequence replication

Run: `equivoque-2026-10-12-sequence-replication-v1`.
Authorized October 12, 2026: the original seven exact models at low, medium and
high effort; cards and cats; constant target and precommitted varying targets;
30 fresh sessions per cell, ten rounds per session; the three terminal calls;
start with ten worker processes. Base: completed sequence pilot integration
commit `6bde9e140c650b4e0738e27d46963168cdceff79`. No completed experiment,
canonical wording or frozen old source is changed. This run has 84 cells,
2,520 independent native conversations, 25,200 game rounds and 83,160 planned
evaluation invocations. Calibration is additional and excluded.

## Matched families and counterbalancing

Generate thirty case families prospectively. Each family has a fixed displayed
layout, constant target and a ten-round varying position sequence. The layout
stays fixed within its conversation. Thirty cases balance the constant target's
displayed identity and position to 7 or 8 occurrences each. Identity by position
has two cases per cell except two preselected cells with one case. Each distinct
layout/target pair is drawn before collection. Identity and position still covary
within a conversation but vary across families.

Cards' homologous displayed identities are spades, clubs, hearts, diamonds;
cats' are A, B, C, D. Research-internal card codes remain A, B, D, C in that
display mapping. They never appear in card subject prompts or schemas.

For each family, draw a balanced ten-position sequence: each position occurs
twice or three times; randomly select the two extra positions and shuffle the
tail after setting the first position to the constant target's position.
Consecutive repeats are allowed. All 21 settings and both frames share the same
thirty families. No sequence is selected for its observed behavior. At every
step keep the group containing that round's hidden target. Labels, sequence,
precommitment and balancing are concealed until the terminal disclosure.

## Session and endpoints

Every trial starts a fresh native Codex ChatGPT session in a neutral empty UUID
directory with zero offered tools. Pin codex-cli 0.159.0-alpha.3. No alternate
provider, billing route, missing-model substitution or metadata fallback.
Canonical English choice and feedback prompts stay unchanged. Each round asks
selection freedom and causal influence on 1–100 scales and the yes/no
counterfactual, about the round just completed. All ten rounds continue even
after low ratings. There are thirty game-phase calls per session.

After round ten: (1) elicit a rule account without supplied candidate rules,
(2) predict four alternative choice policies in the completed final round,
each with two feedback components and a final object, permitting uncertainty,
(3) disclose the rule, all ten targets and all twelve legal final-round paths,
then repeat the three ratings. These are three calls, not three extra rounds.
Rules and predictions precede disclosure. Their questions may prompt new
deductions and do not identify an earlier private discovery time.

## Prospective analysis

Primary endpoint: proportion with both impact=1 and counterfactual=no at round
ten. Name it an observed joint judgment, not proof of mechanism discovery.
Include a valid round-ten response even if a later terminal call fails. Keep
impact and counterfactual separately in all exports. Scores between 1 and 100
are valid. An initial joint report in round one is not a demonstrated transition.

Secondary endpoints: first observed joint report within ten rounds, subsequent
reversals, persistence to round ten, freedom and impact trajectories, twelve
terminal prediction components (matching and uncertain counted separately),
raw rule accounts, and post-disclosure judgments. No joint report by ten is
right-censored at >10, not evidence of permanent inability. Missing reports are
not imputed. Terminal rule coding remains separate from numeric endpoints;
uncoded accounts stay uncoded and raw text is retained. A blinded coding export
supports a later disclosed descriptive rubric assessment.

Estimate constant-minus-varying differences within configuration and frame,
cats-minus-cards differences within configuration and schedule, and medium/high
minus low effort within model, frame and schedule. Use matched valid case pairs.
Resample the thirty case-family IDs together across all configurations, frames,
conditions and occasions, using 2,000 seed-fixed replicates. Report nominal
pointwise percentile 95% intervals only when five paired cases contribute and
95% of bootstrap replicates are estimable. These are estimation intervals, not
confirmatory model rankings or corrected significance tests. There is no power
guarantee from choosing thirty sessions. Routes are adaptive outcomes, not
randomized factors. Changing target sequences also changes possible feedback
routes; the condition comparison covers the whole schedule policy.

## Execution, failures and provenance

Workers A–J each receive 252 sessions: exactly three sessions from every one of
the 84 cells. Within-worker order is seed-shuffled. One active native session
per worker; ten evaluation workers and up to ten evaluation calls in flight.
Start intake at ten. If pending calls age excessively, reduce new trial intake
to five or two, then recover to ten only after measured successful throughput.
Do not silently add workers or alter assignments mid-run. Any later increase
needs an explicit scheduling amendment with exclusive unstarted IDs.

Before evaluation, verify all old freezes and new source tests, every one of
the 21 exact catalog settings, zero tools and exact visible context, 21 excluded
one-round native sessions, four excluded ten-round continuity sessions covering
both frames and schedules, and ten worker-specific one-round checks. Nominal
calibration: 35 sessions and 318 invocations, plus retained failed diagnostics.
All ten readiness records at one shared source revision and a coordinator
launch record are required. No partial model-matrix launch.

Keep the 300-second per-call deadline, durable request and response journals,
exact prompts and schemas, native event and stderr bytes, session IDs and file
hashes. Completed or failed trials are never rerun or replaced. A pending turn
is not replayed; safe recovery may reconcile one already-requested final native
response with matching stimulus, schema and session, then request only the next
unrequested turn. Halt intake on transport failures; do not resample answers.

Keep results on new worker and integration branches derived from the completed
pilot. Main and older experiment data remain unchanged. Prefer CLI Git push
for publication and lossless archives on disk; do not embed large binary/base64
payloads into the coordinator chat. Audit every native byte and cross-worker
ID before analysis. Publish English reports, tidy CSVs, PNG/SVG figures, a
portable explorer and source/provenance/archive hashes. Usage is not a billing
estimate and requested model names do not attest private backend versions.
