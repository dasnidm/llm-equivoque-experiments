"""User-authorized continuation without calibration or diagnostic model calls."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from exp7_main_v2.coordination import GitCoordinator, Conflict
from exp7_main_v2.worker import ROOT, ResultPublisher, verify_freeze, sha
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.storage import _write_archive, _file_info
from exp7_pre.runner import atomic_json, now
from exp7_backup_v1.sidecar import verify_private_repository
from .control import read
from .recovery import recovery_lock, prepare_recovery, execute_recovery, inventory


def backup(directory, operation, phase, bound):
    """Non-pruning copy and private remote byte verification; no model calls."""
    folder=operation/('backup-'+phase);folder.mkdir()
    files={name:_file_info(directory/name)[0] for name in inventory(directory)}
    archive=folder/'archive.tar.gz';manifest=folder/'manifest.json'
    _write_archive(directory,archive,files,6)
    with tarfile.open(archive,'r:gz') as stream:
        assert set(stream.getnames())==set(files)
        for member in stream:
            assert hashlib.sha256(stream.extractfile(member).read()).hexdigest()==files[member.name]['sha256']
    assert files=={name:_file_info(directory/name)[0] for name in files}
    atomic_json(manifest,dict(non_pruning=True,phase=phase,files=files,archive_sha256=sha(archive)))
    repo='dasnidm/llm-equivoque-exp7-raw'
    metadata=verify_private_repository(repo)
    publisher=ResultPublisher('https://github.com/'+repo+'.git',f"raw/{bound['run_id']}/{bound['model']}",folder/'publication.git')
    receipts=[]
    for path in (archive,manifest):
        target=f"snapshots/{bound['run_id']}/{bound['model']}/{directory.name}/{operation.name}/{phase}/{path.name}"
        ref=publisher.publish(path,target)
        with (publisher.cache/'publisher.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            assert hashlib.sha256(publisher._existing(publisher._head(),target)).hexdigest()==sha(path)
        receipts.append(dict(ref=ref,sha256=sha(path)))
    assert verify_private_repository(repo)['id']==metadata['id']
    atomic_json(folder/'receipt.private.json',dict(verified=True,files=receipts))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir',required=True);parser.add_argument('--operation-dir',required=True)
    parser.add_argument('--job-id',required=True);parser.add_argument('--expected-unstarted',type=int,required=True)
    parser.add_argument('--old-worker-pid',type=int,required=True);parser.add_argument('--old-supervisor-pid',type=int,required=True)
    args=parser.parse_args()
    work=Path(args.work_dir).resolve();op=Path(args.operation_dir).resolve();op.mkdir(parents=True,exist_ok=True)
    if shutil.which('codex')!='/opt/codex/bin/codex':raise Conflict('Original CLI required')
    freeze=ROOT/'manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json'
    frozen,digest=verify_freeze(freeze)
    trials={t['trial_id']:t for t in load_bundle(ROOT/frozen['bundle'])['trials']}
    remote='https://github.com/dasnidm/llm-equivoque-experiments.git'
    coordinator=GitCoordinator(remote,'exp7/main-v2-coordination',op/'coordination.git')
    bound=read(work/'identity.private.json')
    if bound['concurrency'] not in (1,2,3):raise Conflict('A pool of one to three is required')
    publisher=ResultPublisher(remote,'exp7/main-v2-results/'+bound['model'],op/'results.git')
    started=now()
    def status(stage,**extra):
        record=dict(stage=stage,started_at=started,updated_at=now(),pid=os.getpid(),concurrency=bound['concurrency'],
                    calibration_calls=0,diagnostic_calls=0,**extra)
        atomic_json(op/'supervisor-status.private.json',record)
        atomic_json(work/'supervisor-status.json',record)
    with recovery_lock(work,op,args.old_worker_pid,args.old_supervisor_pid):
        board=coordinator.status();job=board['jobs'][args.job_id]
        if board['global_stop']:raise Conflict('A newer global STOP remains set')
        selected=[tid for tid in job['trial_ids'] if not (work/'jobs'/args.job_id/'states'/(tid+'.json')).exists()]
        prepare_recovery(coordinator,publisher,work,op,trials,digest,args.job_id,selected,expected_count=args.expected_unstarted)
        status('preserving_previous_result',job_id=args.job_id)
        backup(work/'jobs'/args.job_id,op,'before',bound)
        status('continuing_unstarted',job_id=args.job_id,assigned=len(selected))
        receipt=execute_recovery(coordinator,publisher,work,op,trials)
        completed=receipt['completed_job']
        status('continued_result_published',counts=completed['counts'])
        backup(work/'jobs'/args.job_id,op,'after',bound)
    if completed['status']!='partial_failed' or completed['counts']['unstarted']:
        status('stopped_preserved',counts=completed['counts']);return
    status('run',continued_job=args.job_id)
    command=[sys.executable,'-m','exp7_main_v2.worker','run','--freeze',str(freeze),'--work-dir',str(work),
             '--model',bound['model'],'--owner',bound['owner'],'--concurrency',str(bound['concurrency']),'--calibration-attempt','01']
    child=subprocess.Popen(command,stdin=subprocess.DEVNULL)
    status('run',continued_job=args.job_id,worker_pid=child.pid)
    code=child.wait();status('run_returned',exit_code=code,worker_pid=child.pid)
    raise SystemExit(code)


if __name__=='__main__':main()
