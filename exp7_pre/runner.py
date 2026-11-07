"""Durable one-trial runner. Calling run_trial is an explicit external action.

No replay after a pending or uncertain request; no implicit repair calls. A
shared locked budget reserves each attempt before the native request is sent.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode()
    fd, tmp = tempfile.mkstemp(prefix='.atomic-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def append_event(path, value):
    with Path(path).open('a', encoding='utf8') as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')
        f.flush(); os.fsync(f.fileno())


class CallBudget:
    """A process-safe, durable cap; reservations count even on process crash."""
    def __init__(self, path, run_id, limit):
        self.path = Path(path)
        if not isinstance(run_id, str) or not run_id or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError('A run ID and positive integer call limit are required')
        self.run_id, self.limit = run_id, limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix+'.lock')

    def reserve(self, trial_id, turn):
        with self.lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if data['run_id'] != self.run_id or data['limit'] != self.limit:
                    raise ValueError('Existing budget run ID or immutable limit differs')
            else:
                data = {'run_id':self.run_id,'limit':self.limit,'used':0}
            if data['used'] >= self.limit:
                return None
            ticket = data['used']+1
            data['used'] = ticket
            atomic_json(self.path, data)
            return ticket


TERMINAL = {'complete','failed','interrupted','budget_exhausted'}


def run_trial(trial, protocol, transport, state_path, scratch, budget, freeze_sha256):
    """Run one preassigned conversation; no model call occurs until invoked.

    freeze_sha256 must be computed over the immutable study configuration by
    the launcher, which is also responsible for approval and manifest gating.
    """
    if not re.fullmatch(r'[0-9a-f]{64}', freeze_sha256):
        raise ValueError('Valid frozen configuration SHA-256 required')
    from .protocol import phase, operate_step
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            state = json.loads(path.read_text())
            if state['trial'] != trial or state['freeze_sha256'] != freeze_sha256 or state['transport'] != transport.name:
                raise ValueError('Resume trial, frozen inputs, or transport mismatch')
            if state['status'] in TERMINAL:
                return state
            if state.get('pending_turn') is not None:
                state.update(status='interrupted', ended_at=now(), error='Uncertain pending request; no replay')
                atomic_json(path, state)
                return state
        else:
            n = int(trial['n_rounds'])
            if n < 1: raise ValueError('n_rounds must be positive')
            state = {'trial':trial, 'status':'active', 'started_at':now(), 'ended_at':None,
                     'session_id':None, 'turns':[], 'pending_turn':None,
                     'scratch_id':uuid.uuid4().hex, 'transport':transport.name,
                     'freeze_sha256':freeze_sha256,
                     'system_sha256':hashlib.sha256(protocol.system(trial).encode()).hexdigest(),
                     'rounds':[{'round':i,'order':list(trial['order']),'remaining':list(trial['order']),
                                'route':'','selections':[],'final':None} for i in range(1,n+1)]}
            atomic_json(path,state)
        system = protocol.system(trial)
        if hashlib.sha256(system.encode()).hexdigest() != state['system_sha256']:
            raise ValueError('System instruction changed while resuming')
        native = Path(scratch)/state['scratch_id']
        journal = path.with_suffix('.journal.jsonl')
        for turn in range(len(state['turns'])+1,3*trial['n_rounds']+5):
            r, local = phase(trial,turn)
            current = state['rounds'][r-1]
            feedback = current['route'][-1] if current['route'] else None
            prompt = protocol.prompt(trial,turn,feedback,current['remaining'],rounds=state['rounds'])
            schema = protocol.schema(turn,current['remaining'],trial['frame'],trial)
            ticket = budget.reserve(trial['trial_id'],turn)
            if ticket is None:
                state.update(status='budget_exhausted',ended_at=now(),error='Frozen global call cap reached')
                atomic_json(path,state)
                return state
            req = {'turn':turn,'round':r,'local_turn':local,'prompt':prompt,'schema':schema,
                   'requested_at':now(),'session_id_before':state['session_id'],'budget_ticket':ticket}
            state['pending_turn'] = req
            atomic_json(path,state)
            append_event(journal,{'type':'request_checkpoint',**req})
            try:
                result = transport.request(trial,prompt,schema,system,state['session_id'],native,turn)
            except Exception as exc:
                # Preserve references to whatever bytes were durably emitted;
                # the pending request remains present and is never replayed.
                paths = []
                if native.exists():
                    for p in sorted(native.rglob('*')):
                        if p.is_file():
                            paths.append({'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
                state.update(status='interrupted',ended_at=now(),error=f'Transport exception: {type(exc).__name__}: {exc}')
                state['pending_raw_files']=paths
                atomic_json(path,state)
                return state
            # Full native events and stderr are immutable raw files. Keeping
            # them again in every state rewrite would make long runs quadratic.
            record = {**req, **{k:v for k,v in result.items() if k not in ('events','stderr')},
                      'event_count':len(result.get('events',[])), 'received_at':now()}
            append_event(journal,{'type':'response_checkpoint',**record})
            state['pending_turn'] = None
            state['turns'].append(record)
            if not result.get('ok'):
                state.update(status='failed',ended_at=now(),error='Transport/session/tool-isolation failure')
                atomic_json(path,state)
                return state
            next_id=result.get('session_id')
            if not next_id or (state['session_id'] is not None and next_id != state['session_id']):
                state.update(status='failed',ended_at=now(),error='Missing or changed session ID')
                atomic_json(path,state)
                return state
            state['session_id'] = next_id
            try:
                parsed = protocol.parse_response(result['text'],turn,current['remaining'],trial['frame'],trial)
                if not isinstance(parsed,dict): raise ValueError('Parsed result must be a dictionary')
                if local in (1,2):
                    selection=parsed['selection']
                    selection=selection if local==1 else [selection]
                    remaining,operation=operate_step(trial,r,local,current['remaining'],selection)
                    if operation not in ('K','D'): raise ValueError('Invalid K/D operation')
                    current['remaining']=list(remaining)
                    current['route']+=operation
                    current['selections'].append(selection)
                    if local==2:
                        if len(remaining)!=1: raise ValueError('Final outcome must contain exactly one object')
                        current['final']=remaining[0]
                record['parsed']=parsed
            except (ValueError,TypeError,KeyError) as exc:
                if local in (1,2):
                    state.update(status='failed',ended_at=now(),error=f'Invalid selection: {exc}')
                    record['parse_error']=str(exc)
                    atomic_json(path,state)
                    return state
                record['parsed']={'_parse':'unparseable','error':str(exc)}
            atomic_json(path,state)
        state.update(status='complete',ended_at=now())
        atomic_json(path,state)
        return state
