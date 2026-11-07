"""Main-study adapter around the unchanged durable pre-study runner.

The distributed worker must first obtain a remotely acknowledged claim and
verify the frozen assignment. This module owns the per-conversation protocol
contract; GitHub model/job ownership is the worker's responsibility.
"""
from exp7_pre.runner import (
    CallBudget, TERMINAL, atomic_json, append_event, now, run_trial as _run_trial,
)
from exp7_pre.transport import NativeTransport

from .protocol import MainProtocol, validate_trial


def run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256):
    """Validate before reserving any call, then preserve every original row.

Fresh rows get a fresh native session. Pending/uncertain calls are never
replayed; completed and failed rows are never replaced. Schema is selected
per turn by MainProtocol. NativeTransport retains strict tool-event rejection.
"""
    validate_trial(trial)
    return _run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256)
