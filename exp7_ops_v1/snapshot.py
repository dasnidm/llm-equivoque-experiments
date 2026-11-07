"""Private, non-pruning snapshot of one quiescent STOP/blocked job.

This deliberately differs from a completed-job archive: interrupted states
and their pending request checkpoints are retained as-is. No status repair,
request replay, source deletion, CLI-home access, or remote upload occurs.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
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
    _read_json, _regular, _signature, _write_archive,
)
from .control import process_alive

ROOT_FILES = {'budget.json', 'claim.private.json', 'public.jsonl.gz', 'progress.json'}
RAW_FILES = {'prompt.txt', 'schema.json', 'events.jsonl', 'stderr.txt'}
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}')


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise StorageError('Invalid snapshot member')
    parts = value.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise StorageError('Snapshot paths must be relative and canonical')
    if len(parts) == 1 and value in ROOT_FILES:
        return value
    if (len(parts) == 2 and parts[0] == 'states'
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:json|journal\.jsonl)', parts[1])):
        return value
    if len(parts) in (3, 4) and parts[0] == 'native' and re.fullmatch(r'[0-9a-f]{32}', parts[1]):
        if len(parts) == 3 and parts[2] == 'subject-system.txt':
            return value
        if len(parts) == 4 and re.fullmatch(r'turn-(?:0[1-9]|[12][0-9]|3[0-4])', parts[2]) and parts[3] in RAW_FILES:
            return value
    raise StorageError('Snapshot member is outside the explicit job allowlist')


def _lock(stack, path):
    stream, info = stack.enter_context(_regular(path))
    if info.st_size != 0:
        raise StorageError('Lock file contains unexpected bytes')
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise StorageError('Worker or conversation is not quiescent') from exc


def _owned_stopped_job(work, job_id, board):
    if not SAFE_ID.fullmatch(job_id) or board.get('global_stop') is not True:
        raise StorageError('A confirmed global STOP and valid job ID are required')
    remote = board.get('jobs', {}).get(job_id, {})
    if remote.get('status') != 'blocked':
        raise StorageError('Snapshot is restricted to the confirmed blocked job')
    bound = _read_json(work/'identity.private.json')
    claim = _read_json(work/'jobs'/job_id/'claim.private.json')
    if board.get('run_id') != bound.get('run_id'):
        raise StorageError('Stopped board belongs to another run')
    for key in ('model', 'owner', 'model_token'):
        if not bound.get(key) or claim.get(key) != bound[key]:
            raise StorageError('Local job ownership differs from this worker')
    model = board.get('models', {}).get(bound['model'], {})
    if any(model.get(key) != bound[key] for key in ('owner', 'model_token')):
        raise StorageError('Remote model ownership differs')
    if any(remote.get(key) != claim.get(key) for key in ('job_id', 'model', 'owner', 'claim_token', 'trial_ids')):
        raise StorageError('Remote stopped job differs from local claim')
    trials = remote.get('trial_ids', [])
    if not trials or len(set(trials)) != len(trials) or any(not isinstance(t, str) or not SAFE_ID.fullmatch(t) for t in trials):
        raise StorageError('Invalid stopped job assignment')
    return deepcopy(remote)


def _collect(job_dir, remote):
    files = set(ROOT_FILES)
    excluded_locks = {'budget.json.lock'}
    allowed_dirs = {'states', 'native'}
    raw_hashes = {}
    counts = Counter({'complete': 0, 'failed': 0, 'interrupted': 0, 'budget_exhausted': 0, 'unstarted': 0})
    pending = []
    for trial_id in remote['trial_ids']:
        state_path = job_dir/'states'/(trial_id+'.json')
        _no_symlinks(state_path)
        if not state_path.exists():
            counts['unstarted'] += 1
            continue
        state = _read_json(state_path)
        if (state.get('status') not in ('complete', 'failed', 'interrupted', 'budget_exhausted')
                or state.get('trial', {}).get('trial_id') != trial_id
                or state.get('trial', {}).get('model') != remote['model']):
            raise StorageError('Unexpected or still-active conversation state')
        counts[state['status']] += 1
        files.add('states/'+trial_id+'.json')
        excluded_locks.add('states/'+trial_id+'.json.lock')
        journal = 'states/'+trial_id+'.journal.jsonl'
        if (job_dir/journal).exists():
            files.add(journal)
        scratch = state.get('scratch_id', '')
        if not re.fullmatch(r'[0-9a-f]{32}', scratch):
            raise StorageError('Missing native scratch identity')
        native = 'native/'+scratch
        allowed_dirs.add(native)
        if (job_dir/native/'subject-system.txt').exists():
            files.add(native+'/subject-system.txt')
        records = state.get('turns', [])
        turn_numbers = [r.get('turn') for r in records]
        checkpoint = state.get('pending_turn')
        if checkpoint is not None:
            if state['status'] != 'interrupted' or not isinstance(checkpoint, dict):
                raise StorageError('Pending checkpoint must remain an interrupted state')
            turn_numbers.append(checkpoint.get('turn'))
            pending.append(trial_id)
        if any(type(t) is not int or not 1 <= t <= 34 for t in turn_numbers) or len(set(turn_numbers)) != len(turn_numbers):
            raise StorageError('Invalid or duplicate durable turn numbers')
        for turn in turn_numbers:
            directory = f'{native}/turn-{turn:02d}'
            allowed_dirs.add(directory)
            for name in RAW_FILES:
                if (job_dir/directory/name).exists():
                    files.add(directory+'/'+name)
        references = [raw for r in records for raw in r.get('raw_files', [])] + state.get('pending_raw_files', [])
        for raw in references:
            source = Path(raw['path'])
            source = source if source.is_absolute() else job_dir/source
            try:
                relative = source.relative_to(job_dir).as_posix()
            except ValueError as exc:
                raise StorageError('Native reference escapes the owned job') from exc
            _relative(relative)
            if relative not in files or not relative.startswith(native+'/'):
                raise StorageError('Native reference is missing or belongs to another conversation')
            digest = raw.get('sha256', '')
            if not re.fullmatch(r'[0-9a-f]{64}', digest) or raw_hashes.get(relative, digest) != digest:
                raise StorageError('Invalid or conflicting native digest')
            raw_hashes[relative] = digest
    found = set()
    for directory, child_dirs, child_files in os.walk(job_dir, followlinks=False):
        directory = Path(directory)
        for name in child_dirs:
            path = _no_symlinks(directory/name)
            if path.relative_to(job_dir).as_posix() not in allowed_dirs:
                raise StorageError('Unknown source directory must remain untouched')
        for name in child_files:
            path = directory/name
            with _regular(path):
                pass
            found.add(path.relative_to(job_dir).as_posix())
    if found - excluded_locks != files or not excluded_locks <= found:
        raise StorageError('Unknown or missing job files; no snapshot created')
    entries = {}
    for relative in sorted(files):
        _relative(relative)
        info, _ = _file_info(job_dir/relative)
        if relative in raw_hashes and info['sha256'] != raw_hashes[relative]:
            raise StorageError('Durable native evidence digest changed')
        entries[relative] = info
    local_counts = {k: counts[k] for k in ('complete', 'failed', 'interrupted', 'unstarted')}
    local_counts['interrupted'] += counts['budget_exhausted']
    if remote.get('counts') != local_counts:
        raise StorageError('Snapshot state counts differ from confirmed blocked result')
    if entries['public.jsonl.gz']['sha256'] != remote.get('result_sha256') or not remote.get('result_ref'):
        raise StorageError('Public snapshot summary differs from confirmed blocked result')
    return entries, dict(counts), pending


def _verify(archive_path, index):
    if index.get('schema_version') != 1 or index.get('kind') != 'exp7-quiescent-stop-snapshot' or index.get('non_pruning') is not True:
        raise StorageError('Unknown STOP snapshot manifest')
    entries = index.get('files', {})
    if not entries or not isinstance(entries, dict):
        raise StorageError('Missing snapshot file index')
    for relative, info in entries.items():
        _relative(relative)
        if (set(info) != {'sha256','size','mode'} or not re.fullmatch(r'[0-9a-f]{64}', str(info['sha256']))
                or type(info['size']) is not int or info['size'] < 0
                or type(info['mode']) is not int or not 0 <= info['mode'] <= 0o777):
            raise StorageError('Invalid per-file snapshot metadata')
    actual, signature = _file_info(archive_path)
    if actual['sha256'] != index.get('archive_sha256') or actual['size'] != index.get('archive_bytes'):
        raise StorageError('Snapshot compressed digest or size differs')
    seen = set()
    try:
        with _regular(archive_path) as (raw, _):
            with gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
                with tarfile.open(fileobj=compressed, mode='r|') as archive:
                    for member in archive:
                        relative = _relative(member.name)
                        expected = entries.get(relative)
                        if (not member.isfile() or relative in seen or expected is None
                                or member.size != expected['size'] or member.mode != expected['mode']):
                            raise StorageError('Unexpected or nonregular snapshot member')
                        source = archive.extractfile(member)
                        digest, size = _hash_stream(source)
                        if digest != expected['sha256'] or size != expected['size']:
                            raise StorageError('Snapshot member digest differs')
                        seen.add(relative)
                while compressed.read(1024*1024):
                    pass
    except (OSError, EOFError, tarfile.TarError, ValueError) as exc:
        raise StorageError('Snapshot is truncated or corrupt') from exc
    if seen != set(entries):
        raise StorageError('Snapshot omitted indexed evidence')
    if _signature(os.lstat(archive_path)) != signature:
        raise StorageError('Snapshot changed during full verification')
    return index


def verify_snapshot(archive, manifest):
    """Fully reread a downloaded private snapshot without extracting it."""
    return _verify(_no_symlinks(archive), _read_json(manifest))


def snapshot_stopped_job(work_dir, job_id, output_dir, *, stopped_pids, confirmed_board):
    """Copy a quiescent blocked own job; source bytes/statuses never change."""
    work, output = _no_symlinks(work_dir), _no_symlinks(output_dir)
    if len(stopped_pids) < 2 or len(set(stopped_pids)) != len(stopped_pids):
        raise StorageError('Explicit old worker and supervisor PIDs are required')
    if any(process_alive(pid) for pid in stopped_pids):
        raise StorageError('Old worker or supervisor is still alive')
    job_dir = work/'jobs'/job_id
    _no_symlinks(job_dir)
    if output == job_dir or output.is_relative_to(job_dir):
        raise StorageError('Snapshot output must be outside the source job')
    with ExitStack() as stack:
        _lock(stack, work/'worker.lock')
        if (work/'launch-v1').exists():
            _lock(stack, work/'launch-v1'/'launcher.lock')
        remote = _owned_stopped_job(work, job_id, confirmed_board)
        _lock(stack, job_dir/'budget.json.lock')
        for trial_id in remote['trial_ids']:
            if (job_dir/'states'/(trial_id+'.json')).exists():
                _lock(stack, job_dir/'states'/(trial_id+'.json.lock'))
        entries, counts, pending = _collect(job_dir, remote)
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = _no_symlinks(output/'snapshot.lock')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        lock = stack.enter_context(os.fdopen(fd,'a+b'))
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size:
            raise StorageError('Invalid snapshot output lock')
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive = output/(job_id+'.stopped.tar.gz')
        manifest = output/(job_id+'.stopped.manifest.json')
        metadata = {'schema_version':1, 'kind':'exp7-quiescent-stop-snapshot', 'non_pruning':True,
                    'source_job':job_id, 'run_id':confirmed_board['run_id'],
                    'board_identity':{k:confirmed_board[k] for k in ('run_id','manifest_sha256','freeze_sha256','source_commit')},
                    'confirmed_job':remote, 'stopped_pids':list(stopped_pids),
                    'state_counts':counts, 'pending_checkpoint_trials':pending,
                    'locks_excluded':True, 'source_paths':'relative to the owned job directory',
                    'files':entries}
        if manifest.exists():
            old = verify_snapshot(archive,manifest)
            if any(old.get(k) != v for k,v in metadata.items()):
                raise StorageError('Existing snapshot differs; preserve both originals and old snapshot')
        else:
            with tempfile.TemporaryDirectory(prefix='.snapshot-build-',dir=output) as temporary_dir:
                temporary = Path(temporary_dir)/'snapshot.tar.gz'
                _write_archive(job_dir,temporary,entries,6)
                info, _ = _file_info(temporary)
                index = {**metadata,'archive_sha256':info['sha256'],'archive_bytes':info['size']}
                _verify(temporary,index)
                after_entries,after_counts,after_pending = _collect(job_dir,remote)
                if (entries,counts,pending) != (after_entries,after_counts,after_pending):
                    raise StorageError('Source evidence changed while snapshotting')
                if archive.exists():
                    previous,_ = _file_info(archive)
                    if (previous['sha256'],previous['size']) != (info['sha256'],info['size']):
                        raise StorageError('Different orphan snapshot must be preserved')
                else:
                    os.replace(temporary,archive)
                    _fsync_dir(output)
                payload = (json.dumps(index,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
                staged = Path(temporary_dir)/'manifest.json'
                fd = os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(payload);stream.flush();os.fsync(stream.fileno())
                os.replace(staged,manifest)
                _fsync_dir(output)
            verify_snapshot(archive,manifest)
        return {'archive':str(archive),'manifest':str(manifest),'job_id':job_id,
                'file_count':len(entries),'state_counts':counts,'pending_checkpoint_trials':pending,
                'verified':True,'non_pruning':True}
