"""Fast admission wrapper; no production launch entry point.

This file intentionally does not change the already frozen worker. A new
operational freeze and passing no-tool isolation are prerequisites for use.
"""
from .worker import GatedTransport


class FastGatedTransport(GatedTransport):
    def __init__(self, transport, gate):
        super().__init__(transport, gate)
        self.transport.stop_requested = self.gate.stopped.is_set

    def request(self, *args, **kwargs):
        self.gate.check()
        try:
            response = self.transport.request(*args, **kwargs)
        except Exception as exc:
            self._observe_exception(exc)
            raise
        self.gate.observe(response)
        if response.get('compaction_events') or not response.get('ok'):
            self.gate.stopped.set()
            try:
                self.gate.coordinator.set_stop(True, 'Fast card-study response failed or compacted; inspect')
            except Exception:
                pass
        return response
