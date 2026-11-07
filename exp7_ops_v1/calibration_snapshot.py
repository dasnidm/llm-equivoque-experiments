"""Quiescent technical-attempt snapshot, preserving pending records verbatim.

Only the named attempt and explicitly allowlisted operator evidence are copied.
No inference, status change, replay, pruning, or remote upload is implemented.
"""
from collections import Counter
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import re
import stat
import tempfile

from exp7_main_v2.storage import (
    StorageError, _atomic_json, _file_info, _fsync_dir, _no_symlinks, _read_json, _regular, _write_archive,
)
from . import snapshot
from .control import process_alive

KIND='exp7-quiescent-technical-attempt-snapshot'
OP_NAMES={
    'bounded-probe-status.private.json','bounded-probe-launch.private.json','bounded-probe.log',
    'shared-resume.private.json','shared-resume-intent.private.json','capacity.private.json',
    'access-diagnostic-20261107/intent.json','access-diagnostic-20261107/result.private.json',
}


def _relative(relative,index):
    if not isinstance(relative,str) or '\\' in relative or '\x00' in relative or any(p in ('','.','..') for p in relative.split('/')):
        raise StorageError('Invalid technical snapshot path')
    prefix=index['attempt_relative']+'/'
    if relative.startswith(prefix):
        tail=relative[len(prefix):]
        if tail=='readiness.json':return relative
        snapshot._relative(tail)
        return relative
    op_prefix=index['operation_relative']+'/'
    if relative.startswith(op_prefix) and relative[len(op_prefix):] in OP_NAMES:
        return relative
    raise StorageError('Technical snapshot path outside its allowlist')


def verify_calibration_snapshot(archive,manifest):
    index=_read_json(manifest)
    attempt=index.get('attempt','');op=index.get('operation_relative','')
    if (not isinstance(attempt,str) or not snapshot.SAFE_ID.fullmatch(attempt)
            or index.get('attempt_relative')!='calibration/attempt-'+attempt
            or not isinstance(op,str) or not op.startswith('ops-v1/')
            or any(not snapshot.SAFE_ID.fullmatch(p) for p in op.split('/'))):
        raise StorageError('Invalid technical snapshot scope')
    return snapshot._verify(_no_symlinks(archive),index,expected_kind=KIND,
                            path_validator=lambda p:_relative(p,index))


def verify_stopped_calibration_receipt(work_dir,receipt_path):
    """Return only the ten immutable c10-01 terminal pending-state exclusions.

    This grants no execution permission. The caller retains its strict default
    quiescence rule for every other state and must explicitly opt into this
    precise historical exclusion. No source/receipt bytes are written.
    """
    work,receipt=map(_no_symlinks,(work_dir,receipt_path))
    if not receipt.is_relative_to(work) or receipt.name!='calibration-c10-01.stopped.manifest.json':
        raise StorageError('An owned exact c10-01 snapshot receipt is required')
    archive=receipt.with_name('calibration-c10-01.stopped.tar.gz')
    index=verify_calibration_snapshot(archive,receipt)
    if index.get('attempt')!='c10-01' or index.get('global_stop_confirmed') is not True:
        raise StorageError('Receipt is not the stopped c10-01 attempt')
    expected_counts={'complete':0,'failed':0,'interrupted':10,'budget_exhausted':0,'unstarted':8}
    if (index.get('state_counts')!=expected_counts or index.get('assigned')!=18
            or index.get('recorded_calls')!=100 or index.get('successful_calls')!=100
            or index.get('reserved_calls')!=110 or index.get('call_limit')!=612):
        raise StorageError('Receipt differs from the exact ten interrupted / one hundred successful-call incident')
    bound=_read_json(work/'identity.private.json')
    if any(index.get(k)!=bound.get(k) for k in ('run_id','model','owner')):
        raise StorageError('Stopped technical receipt belongs to another worker')
    directory=work/index['attempt_relative'];op=work/index['operation_relative']
    ids=index['expected_trial_ids']
    expected={f'cal-c10-01-{bound["model"]}-{effort}-{i:02d}' for effort in ('low','medium','high') for i in range(1,7)}
    if len(ids)!=18 or set(ids)!=expected:raise StorageError('Stopped technical panel changed')
    op_prefix=index['operation_relative']+'/'
    operator_receipts=[p[len(op_prefix):] for p in index['files'] if p.startswith(op_prefix)]
    entries,metrics=_collect(work,directory,op,ids,bound,index['board_identity']['freeze_sha256'],operator_receipts)
    if entries!=index['files'] or any(index.get(k)!=v for k,v in metrics.items()):
        raise StorageError('Stopped technical source differs from the archived receipt')
    pending_ids=index['pending_checkpoint_trials']
    if len(pending_ids)!=10 or len(set(pending_ids))!=10:
        raise StorageError('Exactly ten terminal uncertainty exclusions are required')
    paths=set();recorded_tickets=[];pending_tickets=[]
    for tid in pending_ids:
        path=directory/'states'/(tid+'.json');state=_read_json(path)
        pending=state.get('pending_turn')
        if state.get('status')!='interrupted' or not isinstance(pending,dict):
            raise StorageError('Only unchanged terminal interrupted checkpoints may be excluded')
        records=state.get('turns',[])
        if not all(r.get('ok') is True and r.get('raw_files') for r in records):
            raise StorageError('Earlier successful responses require their native evidence references')
        recorded_tickets.extend(r.get('budget_ticket') for r in records)
        pending_tickets.append(pending.get('budget_ticket'))
        pending_directory=directory/'native'/state['scratch_id']/f'turn-{pending["turn"]:02d}'
        _no_symlinks(pending_directory)
        if pending_directory.exists():raise StorageError('A terminal pending request now has native attempt evidence')
        paths.add(path.resolve())
    if any(type(t) is not int for t in recorded_tickets+pending_tickets):
        raise StorageError('Missing exact incident budget tickets')
    if sorted(recorded_tickets)!=list(range(1,101)) or sorted(pending_tickets)!=list(range(101,111)):
        raise StorageError('Technical incident request tickets do not reconcile to 100 responses and 10 terminal pending reservations')
    return paths


def _collect(work,directory,op,ids,bound,freeze_digest,operator_receipts):
    relative_root=directory.relative_to(work).as_posix()
    allowed={'budget.json','progress.json'}
    excluded={'budget.json.lock'}
    directories={'states','native'}
    referenced={}
    counts=Counter({'complete':0,'failed':0,'interrupted':0,'budget_exhausted':0,'unstarted':0})
    pending=[];recorded=0;successful=0
    for tid in ids:
        path=directory/'states'/(tid+'.json');_no_symlinks(path)
        if not path.exists():counts['unstarted']+=1;continue
        state=_read_json(path);trial=state.get('trial',{})
        if (state.get('status') not in ('complete','failed','interrupted','budget_exhausted')
                or trial.get('trial_id')!=tid or trial.get('model')!=bound['model']
                or trial.get('cohort')!='technical_calibration' or state.get('freeze_sha256')!=freeze_digest):
            raise StorageError('Technical state has wrong ownership, scope, freeze, or active status')
        counts[state['status']]+=1
        allowed.add('states/'+tid+'.json');excluded.add('states/'+tid+'.json.lock')
        journal='states/'+tid+'.journal.jsonl'
        if (directory/journal).exists():allowed.add(journal)
        scratch=state.get('scratch_id','')
        if not re.fullmatch(r'[0-9a-f]{32}',scratch):raise StorageError('Invalid technical scratch identity')
        native='native/'+scratch;directories.add(native)
        if (directory/native/'subject-system.txt').exists():allowed.add(native+'/subject-system.txt')
        records=state.get('turns',[]);recorded+=len(records);successful+=sum(r.get('ok') is True for r in records)
        turns=[r.get('turn') for r in records]
        checkpoint=state.get('pending_turn')
        if checkpoint is not None:
            if state['status']!='interrupted' or not isinstance(checkpoint,dict):raise StorageError('Pending technical request must remain interrupted')
            turns.append(checkpoint.get('turn'));pending.append(tid)
        if any(type(t) is not int or not 1<=t<=34 for t in turns) or len(turns)!=len(set(turns)):
            raise StorageError('Invalid technical turn checkpoints')
        for t in turns:
            turn_dir=f'{native}/turn-{t:02d}';directories.add(turn_dir)
            for name in snapshot.RAW_FILES:
                if (directory/turn_dir/name).exists():allowed.add(turn_dir+'/'+name)
        refs=[raw for r in records for raw in r.get('raw_files',[])]+state.get('pending_raw_files',[])
        for raw in refs:
            p=Path(raw['path']);p=p if p.is_absolute() else directory/p
            try:relative=p.relative_to(directory).as_posix()
            except ValueError as exc:raise StorageError('Native file escapes technical attempt') from exc
            if relative not in allowed or not relative.startswith(native+'/'):raise StorageError('Unknown native technical reference')
            digest=raw.get('sha256','')
            if not re.fullmatch(r'[0-9a-f]{64}',digest) or referenced.get(relative,digest)!=digest:
                raise StorageError('Conflicting technical evidence digest')
            referenced[relative]=digest
    if (directory/'readiness.json').exists():allowed.add('readiness.json')
    actual=set()
    for current,dirs,files in os.walk(directory,followlinks=False):
        for name in dirs:
            path=_no_symlinks(Path(current)/name)
            if path.relative_to(directory).as_posix() not in directories:raise StorageError('Unknown technical source directory')
        for name in files:
            path=Path(current)/name
            with _regular(path):pass
            actual.add(path.relative_to(directory).as_posix())
    if actual-excluded!=allowed or not excluded<=actual:raise StorageError('Unknown or missing technical source files')
    entries={}
    for relative in sorted(allowed):
        info,_=_file_info(directory/relative)
        if relative in referenced and info['sha256']!=referenced[relative]:raise StorageError('Technical native digest changed')
        entries[relative_root+'/'+relative]=info
    for name in operator_receipts:
        if name not in OP_NAMES:raise StorageError('Operator evidence path is not allowlisted')
        path=op/name
        entries[path.relative_to(work).as_posix()]=_file_info(path)[0]
    budget=_read_json(directory/'budget.json')
    metrics={'assigned':len(ids),'state_counts':dict(counts),'pending_checkpoint_trials':pending,
             'recorded_calls':recorded,'successful_calls':successful,'reserved_calls':budget.get('used'),
             'call_limit':budget.get('limit')}
    return dict(sorted(entries.items())),metrics


def snapshot_stopped_calibration(work_dir,attempt,operation_dir,output_dir,*,expected_trial_ids,
                                 stopped_pids,confirmed_board,operator_receipts):
    """Copy only after worker/supervisor exits; source files are never written."""
    work,op,output=map(_no_symlinks,(work_dir,operation_dir,output_dir))
    if not snapshot.SAFE_ID.fullmatch(attempt) or not op.is_relative_to(work/'ops-v1'):
        raise StorageError('Invalid technical attempt or operation scope')
    directory=work/'calibration'/('attempt-'+attempt);_no_symlinks(directory)
    if output==directory or output.is_relative_to(directory):raise StorageError('Output must be outside technical source')
    if len(stopped_pids)<2 or len(set(stopped_pids))!=len(stopped_pids) or any(process_alive(pid) for pid in stopped_pids):
        raise StorageError('Explicit previous worker and supervisor must be stopped')
    if confirmed_board.get('global_stop') is not True:raise StorageError('Technical snapshot requires confirmed global STOP')
    bound=_read_json(work/'identity.private.json');model=confirmed_board.get('models',{}).get(bound['model'],{})
    if confirmed_board.get('run_id')!=bound['run_id'] or any(model.get(k)!=bound.get(k) for k in ('owner','model_token')):
        raise StorageError('Stopped board or model ownership differs')
    ids=list(expected_trial_ids)
    if len(ids)!=18 or len(set(ids))!=18 or any(not isinstance(t,str) or not snapshot.SAFE_ID.fullmatch(t) for t in ids):
        raise StorageError('Exactly the eighteen frozen technical trial IDs are required')
    expected={f'cal-{attempt}-{bound["model"]}-{effort}-{i:02d}' for effort in ('low','medium','high') for i in range(1,7)}
    if set(ids)!=expected:raise StorageError('Technical IDs do not match this model/attempt panel')
    with ExitStack() as stack:
        snapshot._lock(stack,work/'worker.lock')
        if (work/'launch-v1').exists():snapshot._lock(stack,work/'launch-v1'/'launcher.lock')
        snapshot._lock(stack,directory/'budget.json.lock')
        for tid in ids:
            if (directory/'states'/(tid+'.json')).exists():snapshot._lock(stack,directory/'states'/(tid+'.json.lock'))
        entries,metrics=_collect(work,directory,op,ids,bound,confirmed_board['freeze_sha256'],operator_receipts)
        metadata={'schema_version':1,'kind':KIND,'non_pruning':True,'run_id':bound['run_id'],'model':bound['model'],
                  'owner':bound['owner'],'attempt':attempt,'attempt_relative':directory.relative_to(work).as_posix(),
                  'operation_relative':op.relative_to(work).as_posix(),'expected_trial_ids':ids,
                  'global_stop_confirmed':True,'stopped_pids':list(stopped_pids),
                  'board_identity':{k:confirmed_board[k] for k in ('run_id','manifest_sha256','freeze_sha256','source_commit')},
                  'source_paths':'relative to the worker directory','locks_excluded':True,'files':entries,**metrics}
        output.mkdir(parents=True,exist_ok=True,mode=0o700)
        lockpath=_no_symlinks(output/'snapshot.lock');fd=os.open(lockpath,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        lock=stack.enter_context(os.fdopen(fd,'a+b'));info=os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size:raise StorageError('Invalid snapshot output lock')
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=output/('calibration-'+attempt+'.stopped.tar.gz');manifest=output/('calibration-'+attempt+'.stopped.manifest.json')
        if manifest.exists():
            existing=verify_calibration_snapshot(archive,manifest)
            if any(existing.get(k)!=v for k,v in metadata.items()):raise StorageError('Existing technical snapshot differs')
        else:
            with tempfile.TemporaryDirectory(prefix='.technical-build-',dir=output) as tempdir:
                candidate=Path(tempdir)/'archive.tar.gz';_write_archive(work,candidate,entries,6)
                info,_=_file_info(candidate);index={**metadata,'archive_sha256':info['sha256'],'archive_bytes':info['size']}
                snapshot._verify(candidate,index,expected_kind=KIND,path_validator=lambda p:_relative(p,index))
                if _collect(work,directory,op,ids,bound,confirmed_board['freeze_sha256'],operator_receipts)!=(entries,metrics):
                    raise StorageError('Technical source changed during snapshot')
                if archive.exists():
                    old,_=_file_info(archive)
                    if (old['sha256'],old['size'])!=(info['sha256'],info['size']):raise StorageError('Different orphan technical archive')
                else:os.replace(candidate,archive);_fsync_dir(output)
                _atomic_json(manifest,index)
            verify_calibration_snapshot(archive,manifest)
        return {'archive':str(archive),'manifest':str(manifest),'verified':True,'non_pruning':True,
                'file_count':len(entries),**metrics}
