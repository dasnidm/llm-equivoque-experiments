"""Keep the durable protocol runner and release trial-scoped transports."""
from exp7_main.runner import *  # noqa: F401,F403
from exp7_main.runner import run_trial as _run_trial
import json
from pathlib import Path


def _record_transport_close(trial, transport, state_path, state, files, freeze_sha256):
    """Bind final process diagnostics only after their writer has exited."""
    if not files:
        return
    path = Path(state_path)
    if state is None:
        state = json.loads(path.read_text())
    if (state.get("trial") != trial or state.get("transport") != transport.name
            or state.get("freeze_sha256") != freeze_sha256):
        raise ValueError("Cannot attach cleanup evidence to a different trial")
    if state.get("pending_turn") is not None or not state.get("turns"):
        target, field = state, "pending_raw_files"
    else:
        target, field = state["turns"][-1], "raw_files"
    # A pending snapshot may have captured the still-growing process log.
    # Replace that reference with the final, post-exit digest explicitly.
    merged = {entry["path"]: entry for entry in target.get(field, [])}
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("Invalid transport-close evidence")
        merged[entry["path"]] = entry
    target[field] = list(merged.values())
    append_event(path.with_suffix(".journal.jsonl"),
                 {"type": "transport_closed", "closed_at": now(), "raw_files": files})
    atomic_json(path, state)


def run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256):
    """A persistent CLI belongs to one full trial, including follow-up turns.

    The durable runner still handles checkpoints and forbids uncertain replay.
    Cleanup happens after success, scientific failure, STOP, or an exception.
    Legacy one-shot transports have no lifecycle callback and are unchanged.
    """
    state = None
    try:
        state = _run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256)
        return state
    finally:
        close_trial = getattr(transport, "close_trial", None)
        if close_trial is not None:
            files = close_trial(trial["trial_id"])
            _record_transport_close(trial, transport, state_path, state, files, freeze_sha256)
