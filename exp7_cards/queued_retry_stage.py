"""Run a fresh, bounded technical stage with the queued-retry prototype.

No calls occur on import. This is separate from the frozen scientific study.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from exp7_pre.runner import CallBudget, atomic_json
from scripts.exp7_native_retry_audit import audit_native_retries
from .coordination import GitCoordinator
from .protocol import CardProtocol
from .queued_retry_audit import audit_queued_trial
from .queued_retry_runner import run_trial
from .queued_retry_transport import QueuedRetryTransport
from .schedule import MODELS
from .supervise import BOARD, REMOTE
from .technical_sweep import TechnicalGate, initialize_sqlite, sqlite_wrapper, technical_trials
from .tool_surface_probe import probe as probe_tool_surface
from .worker import StorageMonitor


def run(root,catalog,*,sessions=7,label='queue-check',binary='/opt/codex/bin/codex',on_hold=None):
    if type(sessions) is not int or not 7<=sessions<=70:
        raise ValueError('Expected 7 to 70 distinct technical sessions')
    catalog=Path(catalog).resolve()
    slugs={m.get('slug') for m in json.loads(catalog.read_text()).get('models',[])}
    if not set(MODELS)<=slugs:raise ValueError('Catalog does not contain seven requested models')
    if not probe_tool_surface(binary,catalog)['no_tool_isolation_passed']:
        raise RuntimeError('Tool-free isolation check failed before live calls')
    trials=technical_trials(label,sessions)
    root=Path(root).resolve()
    root.mkdir(parents=True,mode=0o700,exist_ok=False)
    gate=TechnicalGate(GitCoordinator(REMOTE,BOARD,root/'guard.git'))
    gate.check()
    # Unlimited retries can create files quickly; refresh capacity without
    # imposing a transmission interval.
    storage=StorageMonitor([root],gate,ttl=1)
    storage.check(force=True)
    wrapper,_=sqlite_wrapper(root,binary)
    transport=QueuedRetryTransport(timeout=180,codex_binary=str(wrapper),catalog_path=catalog)
    initialize_sqlite(root,transport)
    def before_send():
        gate.check()
        storage.check()
    transport.before_send=before_send
    source=('queued_retry_stage.py','queued_retry_transport.py','queued_retry_runner.py',
            'queued_retry_audit.py','technical_sweep.py','tool_surface_probe.py','protocol.py','runner.py')
    profile={'scope':'independent technical sessions only','label':label,'target_rpm':None,
             'concurrency':sessions,'sessions':sessions,'pacing':'none','max_attempts_per_turn':None,
             'catalog_sha256':hashlib.sha256(catalog.read_bytes()).hexdigest(),
             'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in source},
             'trials':trials}
    data=(json.dumps(profile,sort_keys=True,separators=(',',':'))+'\n').encode()
    freeze=hashlib.sha256(data).hexdigest()
    (root/'profile.json').write_bytes(data)
    budget=CallBudget(root/'budget.json','technical-'+label,sessions*34)
    start=time.monotonic();states=[];exceptions=[]
    try:
        with ThreadPoolExecutor(max_workers=sessions) as pool:
            futures={pool.submit(run_trial,t,CardProtocol(),transport,root/'states'/(t['trial_id']+'.json'),
                                 root/'native',budget,freeze):t for t in trials}
            for f in as_completed(futures):
                try:states.append(f.result())
                except Exception as exc:
                    exceptions.append({'trial':futures[f]['trial_id'],'type':type(exc).__name__})
                atomic_json(root/'progress.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
                    'finished':len(states),'exceptions':len(exceptions),'planned':sessions,
                    'statuses':dict(Counter(s['status'] for s in states))})
        # Held live sessions must stay open. A caller/monitor can inspect the
        # durable files; there is intentionally no automatic replay or kill.
        while transport.held_processes:
            if on_hold is not None:on_hold(transport,root)
            try:
                atomic_json(root/'held.json',{'trials':sorted(transport.held_processes),
                             'watcher_errors':dict(transport.watcher_errors),'updated_at':datetime.now(timezone.utc).isoformat()})
            except OSError:
                # A storage failure must not terminate the controller and
                # close the pipe to a subject held for reconciliation.
                pass
            time.sleep(1)
        # Re-read states after any background held-process reconciliation.
        states=[json.loads((root/'states'/(t['trial_id']+'.json')).read_text())
                for t in trials if (root/'states'/(t['trial_id']+'.json')).exists()]
    finally:
        if not transport.held_processes:transport.close()
    reports=[]
    for state in states:
        if state['status']=='complete':
            a=audit_queued_trial(state['trial'],CardProtocol(),root/'states'/(state['trial']['trial_id']+'.json'),freeze)
            reports.append({'trial':state['trial']['trial_id'],'integrity_ok':a['integrity_ok'],'errors':a['errors']})
    native=audit_native_retries(root)
    elapsed=time.monotonic()-start
    calls=sum(sum(bool(t.get('ok')) for t in s.get('turns',[])) for s in states)
    attempts=dict(transport.attempt_counts)
    summary={'scope':'independent technical only','planned_sessions':sessions,'target_rpm':None,
             'concurrency':sessions,'pacing':'none','max_attempts_per_turn':None,
             'session_statuses':dict(Counter(s['status'] for s in states)),
             'successful_calls':calls,'actual_turn_starts':transport.total_sent,
             'retryable_error_attempts':attempts.get('requeued',0),'rpc_429_error_attempts':attempts.get('rpc_429',0),
             'elapsed_seconds':elapsed,'observed_successes_per_minute':60*calls/elapsed if elapsed else 0,
             'uncertain_sessions':sum(s['status']=='held' or bool(s.get('pending_turn')) for s in states),
             'noncomplete_sessions':sum(s['status']!='complete' for s in states)+len(exceptions),
             'forbidden_tool_events':sum(int(t.get('tool_events',0)) for s in states for t in s.get('turns',[])),
             'compaction_events':sum(int(t.get('compaction_events',0)) for s in states for t in s.get('turns',[])),
             'native_429_retry_log_records':native.get('native_429_retry_log_records'),
             'audits_passed':sum(a['integrity_ok'] for a in reports),'audits':reports,'exceptions':exceptions}
    atomic_json(root/'summary.json',summary)
    return summary


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--catalog',required=True)
    p.add_argument('--sessions',type=int,default=7);p.add_argument('--label',default='queue-check')
    a=p.parse_args()
    print(json.dumps(run(a.root,a.catalog,sessions=a.sessions,label=a.label),ensure_ascii=False,indent=2))
