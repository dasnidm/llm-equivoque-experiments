"""Run queued-retry trials and retain unresolved live processes.

This isolated prototype is not connected to the frozen scientific worker.
"""
import fcntl
import json
from pathlib import Path
import threading

from exp7_pre.runner import run_trial as durable_trial, atomic_json, append_event, now
from .protocol import adapt
from .runner import _record_transport_close


def _watch_held(trial, transport, path, freeze_sha256):
    """Observe the original child; never spawn or replay a held sample."""
    key = trial['trial_id']
    with transport._map_lock:
        conversation = transport._conversations.get(key)
    if conversation is None:
        return  # Controller identity unknown: do not infer process death.
    with transport.watcher_lock:
        if key in transport.watchers:
            return
        transport.watchers.add(key)
    def watch():
        try:
            conversation.process.wait()
            with path.with_suffix(path.suffix+'.queued.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                state=json.loads(path.read_text())
                if (state.get('status')!='held' or state.get('trial')!=trial
                        or state.get('freeze_sha256')!=freeze_sha256
                        or transport.process_state(key)!='exited'):
                    return
                state.update(status='failed',ended_at=now(),failure_kind='process_exited')
                append_event(path.with_suffix('.journal.jsonl'),
                             {'type':'held_process_exited','at':now(),'pending':bool(state.get('pending_turn'))})
                atomic_json(path,state)
                files=transport.close_trial(key)
                _record_transport_close(trial,transport,path,state,files,freeze_sha256)
                transport.held_processes.pop(key,None)
        except Exception as exc:
            transport.watcher_errors[key]=type(exc).__name__
        finally:
            with transport.watcher_lock:
                transport.watchers.discard(key)
    threading.Thread(target=watch,daemon=True,name='queued-held-'+key).start()


def run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256):
    """Keep a live ambiguous session held; classify dead processes as failures."""
    adapt(trial)
    path=Path(state_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Separate wrapper lock serializes held-state reconciliation and the
    # durable runner's own inner checkpoint lock, across controller processes.
    with path.with_suffix(path.suffix+'.queued.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_guarded(trial,protocol,transport,path,scratch,budget,freeze_sha256)


def _run_guarded(trial, protocol, transport, path, scratch, budget, freeze_sha256):
    key = trial['trial_id']
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior is not None and (prior.get('trial') != trial or prior.get('freeze_sha256') != freeze_sha256
                              or prior.get('transport') != transport.name):
        raise ValueError('Existing trial, frozen inputs, or transport mismatch')
    state = None
    try:
        if prior is not None:
            if prior.get('status') in ('complete','failed','budget_exhausted','unstarted'):
                return prior
            if prior.get('status') == 'held':
                if transport.process_state(key) != 'exited':
                    state = prior
                    _watch_held(trial,transport,path,freeze_sha256)
                    return state
                prior.update(status='failed',ended_at=now(),failure_kind='process_exited')
                append_event(path.with_suffix('.journal.jsonl'),
                             {'type':'held_process_exited','at':now(),'pending':bool(prior.get('pending_turn'))})
                atomic_json(path,prior)
                state = prior
                transport.held_processes.pop(key,None)
                return state
        state = durable_trial(trial, protocol, transport, path, scratch, budget, freeze_sha256)
        if state.get('status') in ('interrupted', 'failed'):
            process = transport.process_state(key)
            if process == 'not_started':
                state.update(status='unstarted', ended_at=now(), failure_kind='process_not_started')
                append_event(path.with_suffix('.journal.jsonl'),
                             {'type':'sample_not_started','at':now(),'pending':bool(state.get('pending_turn'))})
                atomic_json(path,state)
            elif process != 'exited':
                transport.held_processes.setdefault(key, {'reason':'live_session_requires_reconciliation'})
                reason = 'live_session_requires_reconciliation' if process == 'alive' else 'process_identity_unknown'
                state.update(status='held', ended_at=None, hold_reason=reason)
                append_event(path.with_suffix('.journal.jsonl'),
                             {'type':'live_session_held','at':now(),'pending':bool(state.get('pending_turn'))})
                atomic_json(path,state)
                _watch_held(trial,transport,path,freeze_sha256)
            else:
                state.update(status='failed',ended_at=now(),failure_kind='process_exited')
                append_event(path.with_suffix('.journal.jsonl'),
                             {'type':'sample_failed_process_exited','at':now(),
                              'pending':bool(state.get('pending_turn'))})
                atomic_json(path,state)
        return state
    except Exception as exc:
        # A checkpoint/journal failure can occur outside transport.request.
        # Never let a controller error silently close a still-live subject.
        if transport.process_state(key) == 'alive':
            transport.held_processes.setdefault(key,{'reason':'controller_exception','type':type(exc).__name__})
            if path.exists():
                try:
                    state=json.loads(path.read_text())
                    state.update(status='held',ended_at=None,hold_reason='controller_exception')
                    append_event(path.with_suffix('.journal.jsonl'),
                                 {'type':'live_session_held','at':now(),'reason':'controller_exception'})
                    atomic_json(path,state)
                    _watch_held(trial,transport,path,freeze_sha256)
                except (OSError,ValueError,KeyError) as checkpoint_error:
                    transport.watcher_errors[key]='checkpoint_'+type(checkpoint_error).__name__
                    # Still suppress cleanup: the process is live and the
                    # on-disk snapshot may require manual reconciliation.
                    state={'status':'held'}
        raise
    finally:
        if state is not None and state.get('status') != 'held':
            files=transport.close_trial(key)
            _record_transport_close(trial,transport,path,state,files,freeze_sha256)
