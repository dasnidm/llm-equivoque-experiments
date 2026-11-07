"""Non-pruning private backup of a finalized never-started-only continuation.

The prior STOP snapshot and original evidence remain immutable. This operational
helper has no inference path and does not clear STOP, reassign, or prune a job.
Network publication happens only when publish_revision_snapshot() is invoked.
"""
from __future__ import annotations

from contextlib import ExitStack
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile

from exp7_main_v2.storage import (
    StorageError, _file_info, _fsync_dir, _hash_stream, _no_symlinks,
    _read_json, _regular, _signature, _write_archive, _atomic_json,
)
from . import snapshot
from .control import process_alive
from .recovery import verify_reconciliation, verify_prior, check_binding

OP_FILES = ('intent.private.json', 'status.private.json',
            'reconciliation.private.json', 'reconciliation-final.private.json')
KIND = 'exp7-finalized-continuation-snapshot'


def _relative(value, index):
    if not isinstance(value,str) or '\\' in value or '\x00' in value or any(p in ('','.','..') for p in value.split('/')):
        raise StorageError('Invalid revision snapshot path')
    job_prefix='jobs/'+index['job_id']+'/'
    op_prefix=index['operation_relative']+'/'
    if value.startswith(job_prefix):
        snapshot._relative(value[len(job_prefix):])
        return value
    if value.startswith(op_prefix) and value[len(op_prefix):] in OP_FILES:
        return value
    raise StorageError('Revision snapshot member outside its owned job and recovery receipts')


def _verify(archive_path,index):
    if index.get('schema_version')!=1 or index.get('kind')!=KIND or index.get('non_pruning') is not True:
        raise StorageError('Unknown continuation snapshot manifest')
    for key in ('job_id','operation_id','model','run_id'):
        if not isinstance(index.get(key),str) or not snapshot.SAFE_ID.fullmatch(index[key]):
            raise StorageError('Invalid continuation snapshot identity')
    op_parts=str(index.get('operation_relative','')).split('/')
    if len(op_parts)<2 or op_parts[0]!='ops-v1' or op_parts[-1]!=index['operation_id'] or any(not snapshot.SAFE_ID.fullmatch(p) for p in op_parts):
        raise StorageError('Invalid operational receipt location')
    files=index.get('files')
    if not isinstance(files,dict) or not files:
        raise StorageError('Missing revision snapshot file index')
    for relative,info in files.items():
        _relative(relative,index)
        if (not isinstance(info,dict) or set(info)!={'sha256','size','mode'}
                or not re.fullmatch(r'[0-9a-f]{64}',str(info['sha256']))
                or type(info['size']) is not int or info['size']<0
                or type(info['mode']) is not int or not 0<=info['mode']<=0o777):
            raise StorageError('Invalid revision file metadata')
    info,signature=_file_info(archive_path)
    if info['sha256']!=index.get('archive_sha256') or info['size']!=index.get('archive_bytes'):
        raise StorageError('Revision archive checksum differs')
    seen=set()
    try:
        with _regular(archive_path) as (raw,_):
            with gzip.GzipFile(fileobj=raw,mode='rb') as compressed:
                with tarfile.open(fileobj=compressed,mode='r|') as archive:
                    for member in archive:
                        relative=_relative(member.name,index);expected=files.get(relative)
                        if not member.isfile() or relative in seen or expected is None or member.size!=expected['size'] or member.mode!=expected['mode']:
                            raise StorageError('Unexpected revision archive member')
                        digest,size=_hash_stream(archive.extractfile(member))
                        if digest!=expected['sha256'] or size!=expected['size']:
                            raise StorageError('Revision archive member checksum differs')
                        seen.add(relative)
                while compressed.read(1024*1024):pass
    except (OSError,EOFError,tarfile.TarError,ValueError) as exc:
        raise StorageError('Truncated or corrupt revision snapshot') from exc
    if seen!=set(files) or _signature(os.lstat(archive_path))!=signature:
        raise StorageError('Missing revision evidence or archive changed during verification')
    return index


def verify_revision_snapshot(archive,manifest):
    return _verify(_no_symlinks(archive),_read_json(manifest))


def _collect(work,op,remote):
    revision='revisions/'+op.name+'/public.jsonl.gz'
    job_dir=work/'jobs'/remote['job_id']
    job_files,counts,pending=snapshot._collect(job_dir,remote,extra_files=[revision],public_relative=revision)
    entries={'jobs/'+remote['job_id']+'/'+relative:info for relative,info in job_files.items()}
    op_relative=op.relative_to(work).as_posix()
    for name in OP_FILES:
        entries[op_relative+'/'+name]=_file_info(op/name)[0]
    return dict(sorted(entries.items())),counts,pending


def snapshot_finalized_revision(work_dir,operation_dir,output_dir,*,stopped_pids,confirmed_board,
                                prior_snapshot_archive,prior_snapshot_manifest):
    """Snapshot after recovery exits and before the main worker reacquires its lock."""
    work,op,output=map(_no_symlinks,(work_dir,operation_dir,output_dir))
    if not op.is_relative_to(work/'ops-v1') or not snapshot.SAFE_ID.fullmatch(op.name):
        raise StorageError('Recovery receipts must belong to this worker ops-v1 directory')
    if len(stopped_pids)<2 or len(set(stopped_pids))!=len(stopped_pids) or any(process_alive(pid) for pid in stopped_pids):
        raise StorageError('Previous worker and supervisor must be stopped')
    with ExitStack() as stack:
        snapshot._lock(stack,work/'worker.lock')
        if (work/'launch-v1').exists():snapshot._lock(stack,work/'launch-v1'/'launcher.lock')
        snapshot._lock(stack,op/'recovery.lock')
        intent=_read_json(op/'intent.private.json');receipt=_read_json(op/'reconciliation-final.private.json')
        status=_read_json(op/'status.private.json')
        intent_digest=_file_info(op/'intent.private.json')[0]['sha256']
        if (receipt.get('phase')!='finalized' or status.get('status')!='finalized'
                or receipt.get('intent_sha256')!=intent_digest or status.get('intent_sha256')!=intent_digest
                or _no_symlinks(receipt.get('intent_path',''))!=op/'intent.private.json'):
            raise StorageError('A hash-bound finalized recovery receipt is required')
        verify_reconciliation(work,op/'reconciliation-final.private.json')
        job_id=intent['original_job']['job_id'];remote=confirmed_board.get('jobs',{}).get(job_id)
        if remote!=receipt.get('completed_job') or remote.get('status')!='partial_failed' or remote['counts']['unstarted']:
            raise StorageError('Current remote job must exactly match finalized partial completion')
        check_binding(confirmed_board,intent['bound'],intent['board_identity'],remote)
        bound=_read_json(work/'identity.private.json')
        for key in ('run_id','model','owner','model_token'):
            if bound.get(key)!=intent['bound'].get(key):raise StorageError('Local worker ownership changed')
        selected=intent.get('selected_ids',[])
        if len(selected)!=4 or len(set(selected))!=4 or set(selected)&set(intent['excluded_interrupted_ids']):
            raise StorageError('Revision must contain exactly four distinct originally unstarted IDs')
        job_dir=work/'jobs'/job_id
        if output==job_dir or output.is_relative_to(job_dir):raise StorageError('Snapshot output cannot be inside source job')
        snapshot._lock(stack,job_dir/'budget.json.lock')
        for tid in remote['trial_ids']:snapshot._lock(stack,job_dir/'states'/(tid+'.json.lock'))
        prior=snapshot.verify_snapshot(prior_snapshot_archive,prior_snapshot_manifest)
        old=intent['original_job']
        if any(prior['confirmed_job'].get(k)!=old.get(k) for k in ('job_id','model','owner','claim_token','trial_ids','counts','calls','result_ref','result_sha256')):
            raise StorageError('Prior STOP snapshot belongs to another job revision')
        if any(intent['prior_files'].get(relative)!=info['sha256'] for relative,info in prior['files'].items()):
            raise StorageError('Prior snapshot evidence differs from the recovery intent')
        if any('states/'+tid+'.json' in intent['prior_files'] for tid in selected):
            raise StorageError('Continued IDs were not originally unstarted')
        entries,counts,pending=_collect(work,op,remote)
        metadata={'schema_version':1,'kind':KIND,'non_pruning':True,'run_id':confirmed_board['run_id'],
                  'model':remote['model'],'job_id':job_id,'operation_id':op.name,
                  'operation_relative':op.relative_to(work).as_posix(),'confirmed_job':remote,
                  'board_identity':intent['board_identity'],'continued_ids':selected,
                  'excluded_interrupted_ids':intent['excluded_interrupted_ids'],
                  'state_counts':counts,'pending_checkpoint_trials':pending,'files':entries,
                  'prior_snapshot_archive_sha256':prior['archive_sha256'],
                  'prior_snapshot_manifest_sha256':_file_info(prior_snapshot_manifest)[0]['sha256'],
                  'source_paths':'relative to the worker directory','locks_excluded':True}
        output.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock_path=_no_symlinks(output/'snapshot.lock')
        fd=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        lock=stack.enter_context(os.fdopen(fd,'a+b'));lock_info=os.fstat(lock.fileno())
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink!=1 or lock_info.st_size:
            raise StorageError('Invalid revision snapshot output lock')
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=output/(job_id+'.'+op.name+'.tar.gz');manifest=output/(job_id+'.'+op.name+'.manifest.json')
        if manifest.exists():
            existing=verify_revision_snapshot(archive,manifest)
            if any(existing.get(k)!=v for k,v in metadata.items()):raise StorageError('Existing revision snapshot differs')
        else:
            with tempfile.TemporaryDirectory(prefix='.revision-build-',dir=output) as tempdir:
                candidate=Path(tempdir)/'archive.tar.gz';_write_archive(work,candidate,entries,6)
                info,_=_file_info(candidate);index={**metadata,'archive_sha256':info['sha256'],'archive_bytes':info['size']}
                _verify(candidate,index)
                verify_prior(work,intent,allow_budget_change=True)
                if _collect(work,op,remote)!=(entries,counts,pending):raise StorageError('Source changed while snapshotting')
                if archive.exists():
                    previous,_=_file_info(archive)
                    if (previous['sha256'],previous['size'])!=(info['sha256'],info['size']):raise StorageError('Different orphan revision archive')
                else:os.replace(candidate,archive);_fsync_dir(output)
                _atomic_json(manifest,index)
            verify_revision_snapshot(archive,manifest)
        return {'archive':str(archive),'manifest':str(manifest),'job_id':job_id,'operation_id':op.name,
                'verified':True,'non_pruning':True,'file_count':len(entries),'state_counts':counts}


def publish_revision_snapshot(archive,manifest,repository,publication_dir,*,repository_check=None,publisher_factory=None):
    """Explicit private upload plus remote readback; retain every local artifact."""
    from exp7_backup_v1.sidecar import (
        _repository_metadata,verify_private_repository,_remote_readback,MAX_GIT_BLOB,
    )
    from exp7_main_v2.worker import ResultPublisher
    index=verify_revision_snapshot(archive,manifest)
    archive,manifest,folder=map(_no_symlinks,(archive,manifest,publication_dir))
    checker=repository_check or (lambda:verify_private_repository(repository))
    repo=_repository_metadata(checker(),repository)
    for source in (archive,manifest):
        if source.stat().st_size>MAX_GIT_BLOB:raise StorageError('Snapshot exceeds private Git blob limit')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    branch=f"raw/{index['run_id']}/{index['model']}"
    base=f"snapshots/{index['run_id']}/{index['model']}/{index['job_id']}/{index['operation_id']}"
    binding={'schema_version':1,'repository':repo['full_name'],'repository_id':repo['id'],'branch':branch,
             'run_id':index['run_id'],'model':index['model'],'job_id':index['job_id'],
             'operation_id':index['operation_id'],'archive_sha256':index['archive_sha256'],
             'manifest_sha256':_file_info(manifest)[0]['sha256']}
    destination=folder/'destination.private.json'
    if destination.exists():
        if _read_json(destination)!=binding:raise StorageError('Private revision destination or bytes changed')
    else:_atomic_json(destination,binding)
    factory=publisher_factory or ResultPublisher
    publisher=factory('https://github.com/'+repo['full_name']+'.git',branch,folder/'publication.git')
    expected={}
    signatures={source:_file_info(source)[1] for source in (archive,manifest)}
    for name,source in [('archive.tar.gz',archive),('manifest.json',manifest)]:
        current=_repository_metadata(checker(),repository)
        if current['id']!=repo['id']:raise StorageError('Private repository identity changed')
        info,_=_file_info(source);target=base+'/'+name
        expected[target]={'bytes':info['size'],'sha256':info['sha256']}
        publisher.publish(source,target)
    final=_repository_metadata(checker(),repository)
    if final['id']!=repo['id']:raise StorageError('Private repository identity changed before readback')
    head=_remote_readback(publisher,expected)
    if any(_file_info(path)[1]!=signature for path,signature in signatures.items()):
        raise StorageError('Local revision snapshot changed during publication')
    receipt={**binding,'status':'verified','remote_commit':head,'files':expected,
             'scope':'Non-pruning finalized continuation snapshot; original pending states preserved',
             'local_archive_retained':True}
    _atomic_json(folder/'receipt.private.json',receipt)
    return receipt
