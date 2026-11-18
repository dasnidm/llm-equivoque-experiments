"""Single-controller experiment 7 launch. Never resumes an uncertain run."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
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
from exp7_pre.transport import subject_directory
from .main_backup import archive_conversation, PrivateGitBackup, sha
from .main_schedule import RUN_ID, load
from .main_status import Dashboard, RemoteControl, StatusDB, render
from .protocol import ZeroCardProtocol
from .rolling_dispatch import dispatch

REMOTE='https://github.com/dasnidm/llm-equivoque-experiments.git'
BOARD='exp7/cards-0to100-main-100x2-20261118'
RAW='dasnidm/llm-equivoque-exp7-raw'
RAW_BRANCH='raw/equivoque-exp7-cards-0to100-100x2-20261118'
REPO=Path(__file__).resolve().parents[1]
ASSIGNMENTS=REPO/'exp7_cards_zero'/'main_run'/'assignments.jsonl.gz'
ASSIGNMENTS_SHA='a98f26b601254c7bf8af4b60c41cd170bc5125d63e62165b519e5fa98bf7fc82'


def make_wrapper(root, binary):
    wrapper=root/'codex-main'
    sqlite_root=root/'cli-sqlite'
    sqlite_root.mkdir(mode=0o700)
    code='''#!/usr/bin/env python3
import hashlib, os, pathlib, sys
env = os.environ.copy()
if 'app-server' in sys.argv[1:]:
    key = hashlib.sha256(os.getcwd().encode()).hexdigest()[:24]
    path = pathlib.Path(%r) / key
    path.mkdir(mode=0o700, exist_ok=True)
    env['CODEX_SQLITE_HOME'] = str(path)
    env['RUST_LOG'] = 'codex_core::responses_retry=warn,error'
os.execve(%r, [%r] + sys.argv[1:], env)
''' % (str(sqlite_root),str(binary),str(binary))
    wrapper.write_text(code);wrapper.chmod(0o700)
    return wrapper


def sqlite_for(root,native):
    cwd=str(subject_directory(native).resolve())
    return root/'cli-sqlite'/hashlib.sha256(cwd.encode()).hexdigest()[:24]


class BackupThread(threading.Thread):
    def __init__(self, root, db, store, repository_id):
        super().__init__(daemon=True,name='private-backup')
        self.root,self.db,self.store=root,db,store
        self.repository_id=repository_id
        self.error=None;self.stopping=threading.Event();self.wake=threading.Event()

    def run(self):
        while not self.stopping.is_set():
            items=self.db.pending(20)
            if not items:
                self.wake.wait(10);self.wake.clear();continue
            if len(items)<20 and not self.stopping.is_set():
                # Accumulate a small batch while sessions continue at full speed.
                self.stopping.wait(8)
                items=self.db.pending(20)
            try:
                if verify_private_repository(RAW)['id'] != self.repository_id:
                    raise ValueError('Private backup repository identity changed')
                commit=self.store.upload(items)
                for item in items:
                    terminal='complete' if item['status']=='complete_pending_backup' else 'failed'
                    self.db.update(item['trial_id'],terminal,backup_commit=commit)
                    native=self.root/'native'/item['scratch']
                    # Raw content was independently read back from the private
                    # remote; only this terminal sample's local scratch is pruned.
                    sqlite=sqlite_for(self.root,native)
                    shutil.rmtree(native)
                    if sqlite.exists():shutil.rmtree(sqlite)
                    Path(item['archive']).unlink()
                self.error=None
            except Exception as exc:
                self.error=type(exc).__name__
                # Push acknowledgement can be ambiguous: never retry blindly.
                return


def controller(root, dashboard_repo, catalog, binary='/opt/codex/bin/codex', concurrency=42):
    root=Path(root).resolve();dashboard_repo=Path(dashboard_repo).resolve();catalog=Path(catalog).resolve()
    if root.exists():raise FileExistsError('Run directory exists; explicit recovery is required')
    if concurrency != 42:raise ValueError('The initial main profile uses 42 independent sessions')
    trials=load(ASSIGNMENTS,ASSIGNMENTS_SHA)
    slugs={m.get('slug') for m in json.loads(catalog.read_text()).get('models',[])}
    if not {t['model'] for t in trials}<=slugs:raise ValueError('Model catalog incomplete')
    metadata=verify_private_repository(RAW)
    if not probe(binary,catalog)['no_tool_isolation_passed']:
        raise RuntimeError('CLI tool-isolation preflight failed')
    disk_guard(root.parent)
    root.mkdir(parents=True,mode=0o700)
    for name in ('states','native'): (root/name).mkdir(mode=0o700)
    frozen_catalog=root/'catalog.json';shutil.copyfile(catalog,frozen_catalog);frozen_catalog.chmod(0o600)
    version=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(REPO),'status','--porcelain','--untracked-files=no'],text=True)
    if dirty:raise RuntimeError('Tracked source changed after freeze')
    profile={'run_id':RUN_ID,'source_commit':version,'assignments_sha256':ASSIGNMENTS_SHA,
             'catalog_sha256':sha(frozen_catalog),'private_repository_id':metadata['id'],
             'raw_branch':RAW_BRANCH,'concurrency':concurrency,'waves':[4200,4200],
             'rate_limit':None,'max_retries':None,'protocol':ZeroCardProtocol.protocol_id}
    profile_bytes=(json.dumps(profile,sort_keys=True,separators=(',',':'))+'\n').encode()
    freeze=hashlib.sha256(profile_bytes).hexdigest()
    (root/'profile.json').write_bytes(profile_bytes)
    db=StatusDB(root/'status.sqlite',trials)
    backup=PrivateGitBackup(root/'backup.git','https://github.com/'+RAW+'.git',RAW_BRANCH)
    wrapper=make_wrapper(root,binary)
    transport=QueuedRetryTransport(timeout=180,codex_binary=str(wrapper),catalog_path=frozen_catalog)
    dashboard=Dashboard(dashboard_repo)
    control=RemoteControl(REMOTE,BOARD,root/'control.git',RUN_ID)
    backup_worker=BackupThread(root,db,backup,metadata['id'])
    state={'text':'준비 완료','done':False,'dashboard_error':None}
    # Publish a runnable control only after every read-only preflight succeeds.
    dashboard.sync()
    (dashboard_repo/'control.json').write_text(json.dumps({'run_id':RUN_ID,'stop':False,'reason':'user authorized main run'})+'\n')
    dashboard.git('add','control.json');dashboard.git('commit','-q','-m','Enable experiment 7 main run');dashboard.git('push','-q')
    if not control.check_once():raise RuntimeError('Remote board has STOP set')

    def before_send():
        while True:
            try:
                okay=control.check_once()
                disk_guard(root)
                if backup_worker.error:okay=False
                if dashboard.last_success and time.monotonic()-dashboard.last_success>180:okay=False
                if okay:return
            except Exception:
                pass
            time.sleep(2)
    transport.before_send=before_send
    budget=CallBudget(root/'budget.json',RUN_ID,8400*34)
    backup_worker.start()
    def publish_loop():
        while not state['done']:
            try:dashboard.publish(render(db,transport,state['text'],backup_worker.error))
            except Exception as exc:state['dashboard_error']=type(exc).__name__
            time.sleep(30)
        try:dashboard.publish(render(db,transport,state['text'],backup_worker.error))
        except Exception as exc:state['dashboard_error']=type(exc).__name__
    publisher=threading.Thread(target=publish_loop,daemon=True,name='public-dashboard')
    # Require first confirmed public snapshot before opening the model queue.
    dashboard.publish(render(db,transport,'실행 준비',None))
    publisher.start()

    def finish_terminal(trial,state_one):
        ident=trial['trial_id'];path=root/'states'/(ident+'.json')
        status=state_one.get('status')
        if status=='complete':
            audit=audit_queued_trial(trial,ZeroCardProtocol(),path,freeze)
            if not audit['integrity_ok']:
                db.update(ident,'held',turns=len(state_one.get('turns',[])),error='integrity_audit_failed')
                return {'status':'held','trial':trial}
        elif status!='failed' or state_one.get('failure_kind')!='process_exited':
            db.update(ident,'held',turns=len(state_one.get('turns',[])),error='session_not_terminal')
            return {'status':'held','trial':trial}
        item=archive_conversation(root,ident,state_one['scratch_id'])
        db.update(ident,('complete' if status=='complete' else 'failed')+'_pending_backup',
                  turns=len(state_one.get('turns',[])),archive=item['archive'],archive_sha=item['sha256'],
                  archive_bytes=item['bytes'],scratch=state_one['scratch_id'])
        backup_worker.wake.set()
        # Do not retain thousands of full raw conversation objects in memory.
        return {'status':status,'trial_id':ident}

    def run_one(trial):
        ident=trial['trial_id'];path=root/'states'/(ident+'.json')
        db.update(ident,'active')
        try:
            state_one=run_trial(trial,ZeroCardProtocol(),transport,path,root/'native',budget,freeze)
            return finish_terminal(trial,state_one)
        except Exception as exc:
            db.update(ident,'held',error=type(exc).__name__)
            raise

    def reconcile(trial):
        path=root/'states'/(trial['trial_id']+'.json')
        try:record=json.loads(path.read_text())
        except (OSError,ValueError):return None
        # A held process keeps its slot. The watcher's confirmed process exit
        # is archived as a failure; the original trial is never restarted.
        if (record.get('status')=='failed' and record.get('failure_kind')=='process_exited'
                and trial['trial_id'] not in transport.held_processes):
            return finish_terminal(trial,record)
        return None

    def progress(done,held,active,errors):
        atomic_json(root/'progress.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
                    'state':state['text'],'finished':len(done),'held':len(held),'active':len(active),
                    'exceptions':len(errors),'backup_error':backup_worker.error,
                    'dashboard_error':state['dashboard_error']})

    try:
        for wave in ('wave-1','wave-2'):
            state['text']='1차 수집 중' if wave=='wave-1' else '2차 수집 중'
            rows=[t for t in trials if t['stage']==wave]
            done,errors=dispatch(rows,concurrency,run_one,reconcile,progress)
            if errors:raise RuntimeError('Controller errors require reconciliation')
            # Every first-wave session must be terminal and remotely backed up
            # before a single second-wave session starts.
            while db.pending():
                if backup_worker.error:raise RuntimeError('Private backup requires reconciliation')
                backup_worker.wake.set();time.sleep(3)
            if len(done)!=4200 or any(x.get('status') not in ('complete','failed') for x in done):
                raise RuntimeError('Wave has unresolved trials')
        state['text']='수집 완료'
    except Exception as exc:
        state['text']='중단 — 기록 확인 필요'
        atomic_json(root/'controller-error.json',{'type':type(exc).__name__,'at':datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        state['done']=True;backup_worker.stopping.set();backup_worker.wake.set()
        if not transport.held_processes:transport.close()
        publisher.join(timeout=40)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--dashboard',required=True)
    p.add_argument('--catalog',required=True)
    a=p.parse_args();controller(a.root,a.dashboard,a.catalog)
