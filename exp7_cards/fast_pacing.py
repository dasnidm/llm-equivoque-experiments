"""Offline-tested building blocks for high-throughput, single-VM admission.

Admission is placed immediately around the actual turn/start send, not around
GitHub reads or session startup. No live collection is started by this module.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import time


@contextmanager
def shared_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class SharedTurnPacer:
    """One VM-local pace across processes, with permission checked outside lock.

    ``send`` must only durably write the already-formed request to the local
    app-server pipe; it must not perform Git/network operations while locked.
    """
    def __init__(self, path, rpm):
        if isinstance(rpm, bool) or not isinstance(rpm, (int, float)) or not 0 < rpm <= 1000:
            raise ValueError('rpm must be in (0, 1000]')
        self.path = Path(path)
        self.interval = 60.0 / rpm

    def send(self, permission, write_request):
        permission()
        last_check = time.monotonic()
        while True:
            # Refresh while queued, without repeatedly performing a slow
            # permission lookup for every short wait iteration. The remote
            # check is never inside the pacing lock.
            if time.monotonic() - last_check >= 1.0:
                permission()
                last_check = time.monotonic()
            with shared_lock(self.path) as stream:
                stream.seek(0)
                raw = stream.read().strip()
                last = float(raw) if raw else None
                now = time.monotonic()
                if last is not None and last > now + 1:
                    raise RuntimeError('Pace clock changed; inspect before continuing')
                delay = 0.0 if last is None else max(0.0, last + self.interval - now)
                if delay <= 0:
                    # Reserve even if the local write raises: an uncertain send
                    # must not release the slot or be replayed implicitly.
                    stream.seek(0); stream.truncate(); stream.write(str(now))
                    stream.flush(); os.fsync(stream.fileno())
                    return write_request()
            time.sleep(min(delay, 0.2))


@dataclass(frozen=True)
class StageResult:
    target_rpm: float
    successful_calls: int
    duration_seconds: float
    concurrency: int = 7
    response_429: int = 0
    native_429: int = 0
    uncertain_requests: int = 0
    forbidden_tool_events: int = 0
    telemetry_complete: bool = True

    def __post_init__(self):
        if (isinstance(self.target_rpm, bool) or not isinstance(self.target_rpm, (int, float))
                or not math.isfinite(self.target_rpm) or not 0 < self.target_rpm <= 1000
                or isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, (int, float))
                or not math.isfinite(self.duration_seconds) or self.duration_seconds < 0):
            raise ValueError('Invalid technical-stage rate or duration')
        for value in (self.successful_calls, self.response_429, self.native_429,
                      self.uncertain_requests, self.forbidden_tool_events):
            if type(value) is not int or value < 0:
                raise ValueError('Technical-stage counts must be nonnegative integers')
        if type(self.telemetry_complete) is not bool:
            raise ValueError('Telemetry state must be explicit')
        if type(self.concurrency) is not int or self.concurrency <= 0:
            raise ValueError('Concurrency must be a positive integer')

    @property
    def completed_rpm(self):
        return 60.0 * self.successful_calls / self.duration_seconds if self.duration_seconds > 0 else 0.0


def next_stage(current, previous=None, *, minimum_calls=150, minimum_seconds=90,
               step_rpm=10, plateau_fraction=1.03, concurrency_step=7, max_concurrency=70):
    """Choose the next *technical* load stage, never retrying uncertain turns.

    A real overload stops the sweep. Two finite clean stages with less than 3%
    improvement indicate an observed plateau, not a universal provider limit.
    """
    if (minimum_calls < 1 or minimum_seconds <= 0 or step_rpm <= 0 or plateau_fraction <= 1
            or concurrency_step < 1 or max_concurrency < current.concurrency):
        raise ValueError('Invalid technical-sweep policy')
    if (current.response_429 or current.native_429 or current.uncertain_requests
            or current.forbidden_tool_events or not current.telemetry_complete):
        return {'action': 'stop', 'reason': 'overload, uncertain request, tool event, or incomplete telemetry'}
    if current.successful_calls < minimum_calls or current.duration_seconds < minimum_seconds:
        return {'action': 'measure_more', 'target_rpm': current.target_rpm}
    if previous is not None:
        if (previous.target_rpm > current.target_rpm or
                (previous.target_rpm == current.target_rpm and previous.concurrency >= current.concurrency)):
            raise ValueError('Technical sweep must increase rate or concurrency')
        if (previous.response_429 or previous.native_429 or previous.uncertain_requests
                or previous.forbidden_tool_events or not previous.telemetry_complete
                or previous.successful_calls < minimum_calls or previous.duration_seconds < minimum_seconds):
            raise ValueError('Previous stage is not a valid clean measurement')
        if current.completed_rpm < previous.completed_rpm * plateau_fraction:
            best = max((previous, current), key=lambda s: s.completed_rpm)
            return {'action': 'plateau', 'target_rpm': best.target_rpm,
                    'concurrency': best.concurrency, 'observed_rpm': best.completed_rpm}
    if current.completed_rpm < .85 * current.target_rpm and current.concurrency < max_concurrency:
        return {'action': 'increase_concurrency', 'target_rpm': current.target_rpm,
                'concurrency': min(current.concurrency + concurrency_step, max_concurrency)}
    if current.target_rpm + step_rpm > 1000:
        return {'action': 'stop', 'reason': 'configured technical sweep bound reached'}
    return {'action': 'increase', 'target_rpm': current.target_rpm + step_rpm,
            'concurrency': current.concurrency}
