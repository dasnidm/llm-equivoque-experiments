"""Bounded, independent technical load test with immediate retry and no rate cap.

No model calls occur on import. This is not the scientific collection worker.
Each trial is fresh; a confirmed 429/selected 5xx is retried at most five times
in the same CLI session after verified history rollback. Other sessions continue.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from exp7_pre.audit import audit_trial
from exp7_pre.runner import CallBudget, atomic_json
from scripts.exp7_native_retry_audit import audit_native_retries
from .coordination import GitCoordinator
from .max_retry_transport import MaxRetryTransport
from .protocol import CardProtocol
from .runner import run_trial
from .schedule import MODELS
from .supervise import BOARD, REMOTE
from .technical_sweep import TechnicalGate, initialize_sqlite, sqlite_wrapper, technical_trials
from .tool_surface_probe import probe as probe_tool_surface


def audit_retry_evidence(state):
    """Check all saved retry hashes and the recorded rollback history."""
    errors, expected = [], []
    session = state.get('session_id')
    pids = set()
    for turn in state.get('turns', []):
        pids.add(turn.get('process_pid'))
        if turn.get('session_id') != session:
            errors.append('Thread changed')
        for retry in turn.get('retry_records', []):
            paths = {}
            for item in retry.get('raw_files', []):
                path = Path(item['path']); paths[path.name] = path
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                    errors.append('Retry artifact hash mismatch')
            try:
                sent = [json.loads(x) for x in paths['revert-sent.jsonl'].read_text().splitlines()]
                received = [json.loads(x) for x in paths['revert-received.jsonl'].read_text().splitlines()]
                if [x.get('method') for x in sent] != ['thread/revert','thread/turns/list']:
                    errors.append('Missing rollback or history check')
                if (sent[0]['params']['threadId'] != session or
                        sent[0]['params']['beforeTurnId'] != retry['turn_id']):
                    errors.append('Rollback target mismatch')
                lists = [x.get('result') for x in received if x.get('id') == sent[1].get('id')]
                if len(lists) != 1 or [x.get('id') for x in lists[0].get('data',[])] != expected:
                    errors.append('Recorded rollback history mismatch')
            except (KeyError,ValueError,IndexError,TypeError):
                errors.append('Malformed rollback evidence')
        expected.append(turn.get('app_server_turn_id'))
    if state.get('status') == 'complete' and (len(state.get('turns', [])) != 34 or len(pids) != 1):
        errors.append('Incomplete or changed process')
    return {'integrity_ok':not errors,'errors':errors}


def run(root, catalog, *, concurrency=28, sessions=56, max_attempts=5, binary='/opt/codex/bin/codex'):
    if type(concurrency) is not int or type(sessions) is not int or not 7 <= concurrency <= sessions <= 70:
        raise ValueError('Expected 7 <= concurrency <= sessions <= 70')
    catalog = Path(catalog).resolve()
    slugs = {x.get('slug') for x in json.loads(catalog.read_text()).get('models', [])}
    if not set(MODELS) <= slugs:
        raise ValueError('Missing requested models')
    if not probe_tool_surface(binary, catalog)['no_tool_isolation_passed']:
        raise RuntimeError('Tool-free isolation check failed')
    trials = technical_trials('maxretry', sessions)
    root = Path(root).resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    gate = TechnicalGate(GitCoordinator(REMOTE, BOARD, root/'guard.git'))
    gate.check()
    wrapper,_ = sqlite_wrapper(root,binary)
    transport = MaxRetryTransport(timeout=180,codex_binary=str(wrapper),catalog_path=catalog,max_attempts=max_attempts)
    initialize_sqlite(root, transport)
    transport.before_send = gate.check
    metadata = {'scope':'independent technical test only', 'target_rpm':None, 'concurrency':concurrency,
                'sessions':sessions,'max_attempts_per_turn':max_attempts,'pacing':'none',
                'catalog_sha256':hashlib.sha256(catalog.read_bytes()).hexdigest(),
                'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                 for name in ('max_retry_stage.py','max_retry_transport.py','technical_sweep.py',
                                              'tool_surface_probe.py','protocol.py','runner.py')},
                'trials':trials}
    payload = (json.dumps(metadata,sort_keys=True,separators=(',',':'))+'\n').encode()
    freeze = hashlib.sha256(payload).hexdigest()
    (root/'profile.json').write_bytes(payload)
    budget = CallBudget(root/'budget.json','technical-max-retry',sessions*34)
    started = time.monotonic()
    states, errors = [], []
    def execute(t):
        return run_trial(t,CardProtocol(),transport,root/'states'/(t['trial_id']+'.json'),root/'native',budget,freeze)
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            iterator = iter(trials)
            pending = {pool.submit(execute,t):t for t in (next(iterator) for _ in range(concurrency))}
            while pending:
                done,_ = wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    trial = pending.pop(future)
                    try: states.append(future.result())
                    except Exception as exc: errors.append({'trial':trial['trial_id'],'error_type':type(exc).__name__})
                    next_trial = next(iterator,None)
                    if next_trial is not None:
                        pending[pool.submit(execute,next_trial)] = next_trial
                atomic_json(root/'progress.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
                    'finished':len(states),'exceptions':len(errors),'planned':sessions,
                    'statuses':dict(Counter(s['status'] for s in states))})
    finally:
        transport.close()
    audits = []
    for s in states:
        if s['status'] == 'complete':
            a = audit_trial(s['trial'],CardProtocol(),root/'states'/(s['trial']['trial_id']+'.json'),freeze)
            b = audit_retry_evidence(s)
            audits.append({'trial':s['trial']['trial_id'],'integrity_ok':a['integrity_ok'] and b['integrity_ok'],
                           'errors':a['errors']+b['errors']})
    native = audit_native_retries(root)
    elapsed = time.monotonic()-started
    successful = sum(sum(bool(t.get('ok')) for t in s.get('turns',[])) for s in states)
    retry_attempts = sum(bool(x['retryable']) for x in transport.attempt_statuses)
    summary = {'scope':'independent technical only', 'planned_sessions':sessions,'target_rpm':None,
               'concurrency':concurrency,'max_attempts_per_turn':max_attempts,'pacing':'none',
               'session_statuses':dict(Counter(s['status'] for s in states)),
               'exceptions':len(errors),'errors':errors,'successful_calls':successful,
               'actual_turn_starts':len(transport.sent_stamps),'retryable_error_attempts':retry_attempts,
               'rpc_429_error_attempts':sum(x['http_status'] == 429 for x in transport.attempt_statuses),
               'elapsed_seconds':elapsed,'observed_successes_per_minute':60*successful/elapsed if elapsed else 0,
               'complete_sessions_per_hour':3600*sum(s['status']=='complete' for s in states)/elapsed if elapsed else 0,
               'uncertain_sessions':sum(s['status'] in ('interrupted','budget_exhausted') or bool(s.get('pending_turn'))
                                        for s in states)+len(errors),
               'noncomplete_sessions':sum(s['status'] != 'complete' for s in states)+len(errors),
               'forbidden_tool_events':sum(int(t.get('tool_events',0)) for s in states for t in s.get('turns',[])),
               'compaction_events':sum(int(t.get('compaction_events',0)) for s in states for t in s.get('turns',[])),
               'native_429_retry_log_records':native.get('native_429_retry_log_records'),
               'audits_passed':sum(a['integrity_ok'] for a in audits),'audits':audits}
    atomic_json(root/'summary.json',summary)
    return summary


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--catalog',required=True)
    p.add_argument('--concurrency',type=int,default=28);p.add_argument('--sessions',type=int,default=56)
    p.add_argument('--max-attempts',type=int,default=5)
    a=p.parse_args()
    print(json.dumps(run(a.root,a.catalog,concurrency=a.concurrency,sessions=a.sessions,max_attempts=a.max_attempts),ensure_ascii=False,indent=2))
