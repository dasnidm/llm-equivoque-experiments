"""Resume unstarted Exp7 trials while preserving old live sessions as held."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time

from exp7_backup_v1.sidecar import verify_private_repository
from exp7_cards.queued_retry_audit import audit_queued_trial
from exp7_cards.queued_retry_runner import run_trial
from exp7_cards.queued_retry_transport import QueuedRetryTransport
from exp7_cards.tool_surface_probe import probe
from exp7_main_v2.storage import disk_guard
from exp7_pre.runner import CallBudget, atomic_json
from .main_backup import PrivateGitBackup, archive_conversation, sha
from .main_controller import (ASSIGNMENTS, ASSIGNMENTS_SHA, BOARD, RAW, RAW_BRANCH,
                              REMOTE, REPO, RUN_ID, BackupThread)
from .main_schedule import load
from .main_status import Dashboard, RemoteControl, StatusDB, render
from .protocol import ZeroCardProtocol
from .rolling_dispatch import dispatch


def pause_and_hold(pid, db, active_ids):
    """Suspend without killing any session; roll back suspension if lock fails."""
    os.kill(pid,signal.SIGSTOP)
    try:
        for _ in range(30):
            status=Path(f'/proc/{pid}/status').read_text()
            if '\nState:\tT' in status or '\nState:\tt' in status:break
            time.sleep(.1)
        else:raise RuntimeError('Original controller did not pause')
        db.hold_active(active_ids)
    except Exception:
        os.kill(pid,signal.SIGCONT)
        raise


def resume(root,dashboard_repo,old_pid,binary='/opt/codex/bin/codex',concurrency=42):
    root=Path(root).resolve();dashboard_repo=Path(dashboard_repo).resolve()
    if concurrency!=42:raise ValueError('Expected 42 rolling slots')
    cmd=Path(f'/proc/{old_pid}/cmdline').read_bytes()
    if b'exp7_cards_zero.main_controller' not in cmd or str(root).encode() not in cmd:
        raise ValueError('Original controller identity does not match the run')
    progress=json.loads((root/'progress.json').read_text())
    if not progress.get('backup_error'):raise ValueError('Expected a paused backup failure')
    if (root/'recovery-profile.json').exists():raise FileExistsError('Recovery already attempted')
    source=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(REPO),'status','--porcelain','--untracked-files=no'],text=True)
    if dirty:raise RuntimeError('Tracked recovery source is not frozen')
    trials=load(ASSIGNMENTS,ASSIGNMENTS_SHA)
    db=StatusDB.attach(root/'status.sqlite',trials);snapshot=db.resume_snapshot()
    active={ident for ident,status in snapshot.items() if status=='active'}
    if len(active)!=42 or any(status not in ('active','complete','unstarted') for status in snapshot.values()):
        raise ValueError('Unexpected status; reconcile manually')
    for ident in active:
        record=json.loads((root/'states'/(ident+'.json')).read_text())
        if record.get('status')!='active' or not record.get('pending_turn'):
            raise ValueError('Original live-session state is not safely classifiable')
    metadata=verify_private_repository(RAW)
    old_profile=json.loads((root/'profile.json').read_text())
    if old_profile['private_repository_id'] != metadata['id'] or old_profile['run_id'] != RUN_ID:
        raise ValueError('Private repository or original run changed')
    catalog=root/'catalog.json'
    if sha(catalog)!=old_profile['catalog_sha256']:raise ValueError('Frozen catalog changed')
    if not probe(binary,catalog)['no_tool_isolation_passed']:raise RuntimeError('CLI tool-isolation check failed')
    disk_guard(root)
    store=PrivateGitBackup.reopen(root/'backup.git','https://github.com/'+RAW+'.git',RAW_BRANCH)
    # The 97 previously verified archives must still be in the remote tree.
    listed=set(store.git('ls-tree','-r','--name-only',store.parent).splitlines())
    complete={ident for ident,status in snapshot.items() if status=='complete'}
    if not all('archives/'+ident+'.tar.gz' in listed for ident in complete):
        raise ValueError('Completed sample missing from private backup')
    wrapper=root/'codex-main'
    if not wrapper.is_file():raise ValueError('Original runtime wrapper missing')
    dashboard=Dashboard(dashboard_repo)
    # The previous publisher may have stopped after committing an update;
    # reconcile only its dashboard branch before takeover.
    dashboard.sync()
    old_board=(dashboard_repo/'README.md').read_text()
    old_429=re.search(r'\| RPC 429 / 재대기 \| ([\d,]+) / ([\d,]+) \|',old_board)
    old_success=re.search(r'\| 성공 턴 \| ([\d,]+) \|',old_board)
    if not old_429 or not old_success:raise ValueError('Previous dashboard counters unavailable')
    baseline={'rpc_429':int(old_429.group(1).replace(',','')),
              'requeued':int(old_429.group(2).replace(',','')),
              'success':int(old_success.group(1).replace(',',''))}
    # Earlier dashboard refreshes can lag; require consistency with durable
    # successful-turn state to avoid silently resetting the cumulative count.
    recorded_success=0
    for ident,status in snapshot.items():
        if status in ('active','complete'):
            record=json.loads((root/'states'/(ident+'.json')).read_text())
            recorded_success+=sum(bool(x.get('ok')) for x in record.get('turns',[]))
    baseline['success']=recorded_success
    baseline['retryable']=max(baseline['rpc_429'],baseline['requeued'])
    control=RemoteControl(REMOTE,BOARD,root/'recovery-control.git',RUN_ID)
    if not control.check_once():raise RuntimeError('Remote board has STOP set')
    profile={'run_id':RUN_ID,'original_profile_sha256':sha(root/'profile.json'),
             'recovery_source_commit':source,'assignments_sha256':ASSIGNMENTS_SHA,
             'catalog_sha256':sha(catalog),'previous_controller_pid':old_pid,
             'held_trial_ids_sha256':hashlib.sha256('\n'.join(sorted(active)).encode()).hexdigest(),
             'private_backup_parent':store.parent,'concurrency':concurrency,
             'counter_baseline':baseline,'policy':'hold_old_live_sessions; start_only_previously_unstarted_samples'}
    payload=(json.dumps(profile,sort_keys=True,separators=(',',':'))+'\n').encode()
    freeze=hashlib.sha256(payload).hexdigest()
    with (root/'recovery-profile.json').open('xb') as f:
        f.write(payload);f.flush();os.fsync(f.fileno())
    transport=QueuedRetryTransport(timeout=180,codex_binary=str(wrapper),catalog_path=catalog)
    transport.attempt_counts.update(baseline)
    backup=BackupThread(root,db,store,metadata['id'])
    state={'text':'복구 준비','done':False,'dashboard_error':None}
    def before_send():
        while True:
            try:
                okay=control.check_once();disk_guard(root)
                if backup.error:okay=False
                if dashboard.last_success and time.monotonic()-dashboard.last_success>180:okay=False
                if okay:return
            except Exception:pass
            time.sleep(2)
    transport.before_send=before_send
    budget=CallBudget(root/'budget.json',RUN_ID,8400*34)
    pause_and_hold(old_pid,db,active)
    # From this point the old Python controller remains suspended, not killed;
    # its 42 original CLI processes are untouched and their trial IDs are excluded.
    atomic_json(root/'recovery-takeover.json',{'at':datetime.now(timezone.utc).isoformat(),
                'previous_controller_pid':old_pid,'held_count':len(active),
                'recovery_profile_sha256':freeze,'old_controller_signal':'SIGSTOP'})
    backup.start()
    def publisher_loop():
        while not state['done']:
            try:
                dashboard.publish(render(db,transport,state['text'],backup.error));state['dashboard_error']=None
            except Exception as exc:state['dashboard_error']=type(exc).__name__
            time.sleep(30)
        try:dashboard.publish(render(db,transport,state['text'],backup.error))
        except Exception as exc:state['dashboard_error']=type(exc).__name__
    while True:
        try:
            dashboard.publish(render(db,transport,'1차 재개 — 기존 42개 세션 보류',None))
            break
        except Exception as exc:
            state['dashboard_error']=type(exc).__name__
            time.sleep(10)
    publisher=threading.Thread(target=publisher_loop,daemon=True);publisher.start()

    def finish(trial,record):
        ident=trial['trial_id'];path=root/'states'/(ident+'.json');status=record.get('status')
        if status=='complete':
            audit=audit_queued_trial(trial,ZeroCardProtocol(),path,freeze)
            if not audit['integrity_ok']:
                db.update(ident,'held',turns=len(record.get('turns',[])),error='integrity_audit_failed')
                return {'status':'held','trial':trial}
        elif status!='failed' or record.get('failure_kind')!='process_exited':
            db.update(ident,'held',turns=len(record.get('turns',[])),error='session_not_terminal')
            return {'status':'held','trial':trial}
        item=archive_conversation(root,ident,record['scratch_id'])
        db.update(ident,('complete' if status=='complete' else 'failed')+'_pending_backup',
                  turns=len(record.get('turns',[])),archive=item['archive'],archive_sha=item['sha256'],
                  archive_bytes=item['bytes'],scratch=record['scratch_id'])
        backup.wake.set();return {'status':status,'trial_id':ident}

    def run_one(trial):
        ident=trial['trial_id'];path=root/'states'/(ident+'.json');db.update(ident,'active')
        try:return finish(trial,run_trial(trial,ZeroCardProtocol(),transport,path,root/'native',budget,freeze))
        except Exception as exc:db.update(ident,'held',error=type(exc).__name__);raise

    def reconcile(trial):
        try:record=json.loads((root/'states'/(trial['trial_id']+'.json')).read_text())
        except (OSError,ValueError):return None
        if (record.get('status')=='failed' and record.get('failure_kind')=='process_exited'
                and trial['trial_id'] not in transport.held_processes):return finish(trial,record)
        return None

    def progress(done,held,active_now,errors):
        atomic_json(root/'recovery-progress.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
                    'state':state['text'],'finished':len(done),'held_new':len(held),
                    'held_original':len(active),'active_new':len(active_now),'exceptions':len(errors),
                    'backup_error':backup.error,'dashboard_error':state['dashboard_error']})

    try:
        for wave in ('wave-1','wave-2'):
            if wave=='wave-2':
                # Never advance while any first-wave sample is active, held,
                # unstarted, or awaiting verified backup.
                while True:
                    wave1=[(w,s,n) for _,_,_,w,s,n in db.counts() if w=='wave-1']
                    unresolved=sum(n for _,s,n in wave1 if s not in ('complete','failed'))
                    if not unresolved:break
                    state['text']=f'1차 대기 — 미정리 {unresolved}개'
                    time.sleep(10)
            state['text']='1차 재개 — 기존 42개 세션 보류' if wave=='wave-1' else '2차 수집 중'
            current=db.resume_snapshot()
            selected=[t for t in trials if t['stage']==wave and current[t['trial_id']]=='unstarted']
            done,errors=dispatch(selected,concurrency,run_one,reconcile,progress)
            if errors:raise RuntimeError('New controller errors require reconciliation')
            while db.pending():
                backup.wake.set();time.sleep(3)
            if len(done)!=len(selected) or any(x.get('status') not in ('complete','failed') for x in done):
                raise RuntimeError('Wave has unresolved new trials')
        state['text']='수집 완료'
    except Exception as exc:
        state['text']='중단 — 기록 확인 필요'
        atomic_json(root/'recovery-error.json',{'type':type(exc).__name__,'at':datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        state['done']=True;backup.stopping.set();backup.wake.set()
        if not transport.held_processes:transport.close()
        publisher.join(timeout=40)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--dashboard',required=True);p.add_argument('--old-pid',type=int,required=True)
    a=p.parse_args();resume(a.root,a.dashboard,a.old_pid)
