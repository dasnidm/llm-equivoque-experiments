# Persistent Codex CLI transport for experiment 7

This profile keeps one `codex app-server` process alive for one independent
conversation. The first request creates a fresh thread; later requests use the
same process and thread. Closing a conversation releases its process. This
reduces repeated CLI startup and model-catalog requests across the conversation's
turns. It does not establish a new server rate limit or guarantee that any chosen
concurrency will succeed.

The transport preserves the experiment's prompts, system instruction, selected
model and reasoning effort, turn-specific schema, parsers, and allocation. A
persistent process is an operational change and must be recorded as a **separate
frozen execution profile**. Preserve existing freezes, original results, failed
attempts, and their transport identifiers; do not rewrite them to appear to have
used this profile. Report the profile alongside results so execution cohorts can
be identified.

## Evidence and independent audit

Each submitted turn retains its exact prompt, optional provider schema, original
outgoing and incoming JSON-RPC records, stderr, and derived exec-compatible event
stream. The conversation retains its exact system instruction. The result carries
file SHA256 values, process PID, provider thread ID, provider turn ID, command,
and token usage. Original RPC records are the evidence; `events.jsonl` is a
reproducible adapter output. Token totals and last-turn token usage are retained
separately and must not be summed interchangeably.

After process shutdown, the final process stderr log and close diagnostics are
hashed and attached to the final response record, or to pending evidence for an
interrupted request. Earlier response hashes refer to immutable per-turn stderr
snapshots and do not hash a process log while it is still changing.

The read-only audit checks file hashes, exact stimulus and schema transmission,
thread/turn identity, terminal status, the mapping from original RPC to derived
events, and one `turn/start` submission per logical turn. For normal completed
conversations the PID and thread stay constant. The audit also reuses the
scientific replay of choices and feedback. Passing these checks establishes the
consistency of retained records; it cannot count undocumented provider-internal
HTTP retries or prove an inference was executed exactly once inside the provider.

## Preflight and activation

1. Pin **`codex-cli 0.159.0-alpha.3`**, transport source, experiment protocol, and
   assignment hashes in the new execution profile. Other CLI versions are rejected
   before the app-server starts. Keep previous profiles and
   their records intact.
2. Check the effective user and project configuration before model calls. The
   app-server must use the intended isolated settings, an empty opaque subject
   directory, the frozen system instruction, and the frozen tool configuration. A
   successful launch alone does not establish subject isolation. Validate the
   original native evidence in a separately labelled technical calibration.
3. Use the environment's existing authenticated Codex home. Do not copy auth
   files, create a shared credential directory, or change the global `HOME` or
   `CODEX_HOME` to hide configuration. Fail preflight if configuration isolation
   cannot be established with the supported CLI.
4. Start each newly assigned conversation with a fresh persistent process and
   thread. After a crash, timeout, interrupted request, or uncertain state, retain
   the pending checkpoint and all raw evidence. Do not restart the process to
   replay that conversation, and do not issue a replacement request implicitly.
5. Release the process on completion, scientific failure, STOP, or an exception.
   Retain raw evidence under the existing storage and backup policy. Deploy only
   under the new profile and perform its readiness checks before collection.

## Concurrency and error handling

Count active requests across every VM sharing the account, as well as per model.
A worker count is not a requests-per-minute limit. Begin from a measured stable
load, stagger starts, and increase in stages while recording successful native
calls per minute, latency percentiles, oldest pending request, catalog errors,
response failures, and cumulative usage. A plateau in successful throughput or
increasing tail latency is a reason to reduce admission even if CPU is idle.

Classify catalog-refresh diagnostics separately from response failures. A catalog
429 can coexist with a successful response; preserve both. A provider response
429 or model-capacity rejection requires its own admission/cooldown policy.
Authentication failure and unknown request completion require inspection before
further intake. Respect `Retry-After` where available, and do not turn backoff
into automatic replay of a scientific turn whose outcome is uncertain.

This implementation and its offline tests do not by themselves authorize or
perform live calibration, alter an existing coordination board, resume a stopped
run, or measure the service's present capacity.

The offline real-CLI test compares the model-facing wire instructions and tool
surface with the frozen exec baseline, including WebSocket warmup. The full
34-turn conversation and wire-parity checks have passed against the pinned CLI.
Both transports can expose additional tools already present in that baseline;
matching the baseline does not mean the advertised tool list is empty. Actual
tool-use events are rejected and preserved as failures. The fixture supplies
local responses, so these checks do not measure live-provider capacity.

## New-profile command pattern

Run from the reviewed source checkout with the pinned CLI and parser dependency.
The example uses a new run, manifest directory, work directory, coordination
branch, and results prefix. It creates a **full fresh allocation**: an operator
continuing an older study must reconcile completed and pending assignments first,
and must not use this example to replay them. The interval of one second is an
example per-worker admission setting, not a measured account limit. Every VM's
combined request rate still needs a common budget.

These commands only build and verify local files:

```bash
python -m unittest exp7_persistent.test_audit

python - <<'PY'
from exp7_main_v2.schedule import build, save_bundle
run = 'equivoque-2026-11-07-exp7-persistent-v1'
save_bundle(build(run_id=run), 'manifests/' + run)
PY

python -m exp7_main_v2.worker freeze \
  --bundle manifests/equivoque-2026-11-07-exp7-persistent-v1 \
  --output manifests/equivoque-2026-11-07-exp7-persistent-v1/freeze.json \
  --transport persistent --request-interval 1

python -m exp7_main_v2.worker verify \
  --freeze manifests/equivoque-2026-11-07-exp7-persistent-v1/freeze.json
```

An optional reviewed model catalog can be pinned by adding
`--model-catalog /absolute/path/to/model-catalog.json` to **freeze, prepare, and
run**. Its bytes must have the same SHA256 on every VM; paths may differ. Each
conversation stores its own catalog snapshot in the raw inventory, and the audit
checks its hash and the command's snapshot path.

Prepare the separate coordination board locally, in the stopped state:

```bash
python - <<'PY'
import hashlib
import json
from pathlib import Path
from exp7_main_v2.coordination import new_board

bundle = Path('manifests/equivoque-2026-11-07-exp7-persistent-v1')
freeze = bundle / 'freeze.json'
frozen = json.loads(freeze.read_text())
board = new_board(frozen['run_id'], frozen['manifest_sha256'],
                  frozen['source_commit'], json.loads((bundle / 'jobs.json').read_text()), global_stop=True,
                  global_max_concurrency=4,
                  freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest())
with Path('persistent-board.json').open('x') as output:
    json.dump(board, output, ensure_ascii=False, indent=2)
    output.write('\n')
PY
```

The example board's four slots are an initial reservation policy, not a service
capacity finding. Review the allocation, freeze, CLI version, owner reservations,
and calibration plan before initializing and enabling the new remote board. Do
not point this profile at `exp7/main-v2-coordination` or clear that older board's
STOP. Publishing the new board and enabling intake are deployment actions; none
of the local build commands performs them.

After the new board has been explicitly initialized and enabled, technical
calibration and collection use the same frozen profile and work directory.
**Both commands below make model calls; `run` also publishes research results.**

```bash
python -m exp7_main_v2.worker prepare \
  --freeze manifests/equivoque-2026-11-07-exp7-persistent-v1/freeze.json \
  --coordination-branch exp7/persistent-v1-coordination \
  --results-prefix exp7/persistent-v1-results \
  --work-dir /workspace/work/exp7-persistent-v1-worker \
  --model auto --concurrency 1 \
  --transport persistent --request-interval 1

python -m exp7_main_v2.worker run \
  --freeze manifests/equivoque-2026-11-07-exp7-persistent-v1/freeze.json \
  --coordination-branch exp7/persistent-v1-coordination \
  --results-prefix exp7/persistent-v1-results \
  --work-dir /workspace/work/exp7-persistent-v1-worker \
  --model auto --concurrency 1 \
  --transport persistent --request-interval 1
```

`run` requires successful calibration for the exact model, owner, freeze, and
transport profile. A source edit or a pacing/catalog change needs a new freeze;
the old freeze is never overwritten. An interrupted conversation keeps its
evidence and pending checkpoint and is not resumed through a new app-server.
