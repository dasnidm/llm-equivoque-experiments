"""Persistent CLI adapter with shared pacing at the actual turn/start send.

Prototype only: the old experimental profile and its freeze are untouched.
The CLI still advertises collaboration tools; this adapter does not solve that
scientific isolation problem and must not be used for main collection yet.
"""
import threading

import exp7_persistent.transport as native
from .fast_pacing import SharedTurnPacer


_conversation_patch_lock = threading.RLock()
_thread_profile = threading.local()
_original_conversation = native._Conversation
_active_requests = 0


class _PacedConversation(_original_conversation):
    def __init__(self, *args, **kwargs):
        self._fast_profile = getattr(_thread_profile, 'value', None)
        super().__init__(*args, **kwargs)

    def send(self, message, sent):
        if message.get('method') != 'turn/start' or self._fast_profile is None:
            return super().send(message, sent)
        pacer, permission, stop_requested = self._fast_profile
        def write_request():
            # Local only: never perform remote Git I/O in the admission lock.
            if stop_requested():
                raise RuntimeError('Local stop set before turn/start')
            return super(_PacedConversation, self).send(message, sent)
        return pacer.send(permission, write_request)


class FastPersistentTransport(native.PersistentTransport):
    # Keep the actual RPC/evidence identity for the existing audit, but use a
    # separately frozen execution profile to distinguish the admission policy.
    name = native.PersistentTransport.name

    def __init__(self, *, pace_path, target_rpm, **kwargs):
        if kwargs.get('min_start_interval', 0) != 0:
            raise ValueError('Old per-worker pacing must be disabled in the fast profile')
        super().__init__(**kwargs)
        self.pacer = SharedTurnPacer(pace_path, target_rpm)
        self.stop_requested = None

    def request(self, *args, **kwargs):
        global _active_requests
        if self.before_send is None or self.stop_requested is None:
            raise RuntimeError('A fail-closed remote gate and local stop check are required')
        if getattr(_thread_profile, 'value', None) is not None:
            raise RuntimeError('Nested fast transport calls are unsupported')
        _thread_profile.value = (self.pacer, self.before_send, self.stop_requested)
        # The module's factory is installed only while fast requests are
        # active. Thread-local profiles allow concurrent conversations without
        # serializing the requests themselves.
        with _conversation_patch_lock:
            if _active_requests == 0:
                if native._Conversation is not _original_conversation:
                    del _thread_profile.value
                    raise RuntimeError('Unexpected native conversation factory')
                native._Conversation = _PacedConversation
            elif native._Conversation is not _PacedConversation:
                del _thread_profile.value
                raise RuntimeError('Native factory changed during active requests')
            _active_requests += 1
        try:
            return super().request(*args, **kwargs)
        finally:
            del _thread_profile.value
            with _conversation_patch_lock:
                _active_requests -= 1
                if _active_requests == 0:
                    native._Conversation = _original_conversation
