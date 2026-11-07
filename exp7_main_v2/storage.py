"""Verified, private terminal-job archives; never touch CLI or historical data.

The caller holds its worker lock and passes the remotely confirmed completion
record. Only that job's allowlisted ``states/`` and ``native/`` files can be
pruned. The archive and independent per-file index are durable and fully read
back before deletion. No network or inference occurs in this module.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

DEFAULT_STORAGE_POLICY = {
    'schema_version': 1,
    'min_free_bytes': 5 * 1024**3,
    'min_free_inodes': 100_000,
    'compression_level': 6,
}
CHUNK = 1024 * 1024
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}')


class StorageError(RuntimeError):
    pass


class InsufficientStorage(StorageError):
    def __init__(self, metrics):
        self.metrics = metrics
        super().__init__('Insufficient free storage or inodes: ' + json.dumps(metrics, sort_keys=True))


def _policy(value=None):
    value = dict(DEFAULT_STORAGE_POLICY if value is None else value)
    if set(value) != set(DEFAULT_STORAGE_POLICY) or value['schema_version'] != 1:
        raise StorageError('Unknown storage policy; use the frozen complete policy')
    if any(type(value[k]) is not int for k in value):
        raise StorageError('Storage policy values must be integers')
    if value['min_free_bytes'] < 5 * 1024**3 or value['min_free_inodes'] < 100_000:
        raise StorageError('Storage guard thresholds cannot be relaxed below the frozen safety floor')
    if not 1 <= value['compression_level'] <= 9:
        raise StorageError('Invalid archive compression level')
    return value


def storage_metrics(path):
    """Read filesystem availability without creating, deleting, or reserving."""
    path = Path(path).absolute()
    while not path.exists():
        if path == path.parent:
            raise StorageError('No existing filesystem ancestor')
        path = path.parent
    values = os.statvfs(path)
    return {'path': str(path), 'free_bytes': values.f_bavail * values.f_frsize,
            'free_inodes': values.f_favail, 'total_bytes': values.f_blocks * values.f_frsize,
            'total_inodes': values.f_files}


def disk_guard(path, policy=None):
    policy = _policy(policy)
    metrics = {**storage_metrics(path), 'min_free_bytes': policy['min_free_bytes'],
               'min_free_inodes': policy['min_free_inodes']}
    metrics['ok'] = (metrics['free_bytes'] >= policy['min_free_bytes']
                     and metrics['free_inodes'] >= policy['min_free_inodes'])
    if not metrics['ok']:
        raise InsufficientStorage(metrics)
    return metrics


def _safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise StorageError('Invalid archive path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise StorageError('Archive paths must be canonical and relative')
    if path.parts[0] not in ('states', 'native') or len(path.parts) < 2:
        raise StorageError('Archive path outside states/native')
    return value


def _no_symlinks(path):
    path = Path(path).absolute()
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise StorageError('Symlinks are forbidden: ' + str(component))
    return path.resolve(strict=False)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _regular(path):
    path = _no_symlinks(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise StorageError('Cannot open verified regular file: ' + str(path)) from exc
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise StorageError('Only unlinked-to-other-paths regular files are allowed: ' + str(path))
        yield stream, info


def _hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(CHUNK)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _file_info(path):
    with _regular(path) as (stream, before):
        digest, size = _hash_stream(stream)
        if _signature(before) != _signature(os.fstat(stream.fileno())):
            raise StorageError('File changed while hashing: ' + str(path))
        return {'sha256': digest, 'size': size, 'mode': stat.S_IMODE(before.st_mode)}, _signature(before)


def _fsync_dir(path):
    fd = os.open(_no_symlinks(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path):
    with _regular(path) as (stream, _):
        try:
            return json.load(stream)
        except (ValueError, UnicodeError) as exc:
            raise StorageError('Invalid storage metadata: ' + str(path)) from exc


def _atomic_json(path, value):
    path = _no_symlinks(path)
    temporary = path.with_name(path.name + '.pending')
    _no_symlinks(temporary)
    if temporary.exists():
        with _regular(temporary):
            pass
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _inventory(job_dir):
    """Do not traverse a symlink or special file, including in empty trees."""
    files, directories = set(), set()
    for name in ('states', 'native'):
        root = job_dir / name
        _no_symlinks(root)
        if not root.exists():
            continue
        if not root.is_dir():
            raise StorageError('Loose root is not a directory')
        for current, child_dirs, child_files in os.walk(root, followlinks=False):
            current = Path(current)
            directories.add(current.relative_to(job_dir).as_posix())
            for child in child_dirs:
                _no_symlinks(current / child)
            for child in child_files:
                path = current / child
                with _regular(path):
                    pass
                files.add(_safe_relative(path.relative_to(job_dir).as_posix()))
    return files, directories


def _receipt(job_dir, completion, trial_ids):
    if not isinstance(completion, dict) or completion.get('status') not in ('complete', 'partial_failed'):
        raise StorageError('A remotely confirmed completed job is required')
    if not trial_ids or len(set(trial_ids)) != len(trial_ids) or any(not isinstance(t, str) or not SAFE_ID.fullmatch(t) for t in trial_ids):
        raise StorageError('Invalid expected trial IDs')
    claim = _read_json(job_dir / 'claim.private.json')
    keys = ('job_id', 'claim_token', 'owner', 'model')
    if any(not completion.get(k) or completion[k] != claim.get(k) for k in keys):
        raise StorageError('Completion does not match this local job claim')
    if not SAFE_ID.fullmatch(completion['job_id']) or completion['job_id'] != job_dir.name:
        raise StorageError('Job directory identity mismatch')
    if completion.get('trial_ids') != list(trial_ids) or claim.get('trial_ids') != list(trial_ids):
        raise StorageError('Completed job trial set differs from local claim')
    counts = completion.get('counts', {})
    if (not isinstance(counts, dict) or not set(counts) <= {'complete', 'failed', 'interrupted', 'unstarted'}
            or counts.get('interrupted', 0) or counts.get('unstarted', 0)
            or any(type(v) is not int or v < 0 for v in counts.values())
            or counts.get('complete', 0) + counts.get('failed', 0) != len(trial_ids)):
        raise StorageError('All assigned conversations must be complete or failed, with none uncertain')
    if not completion.get('result_ref') or not re.fullmatch(r'[0-9a-f]{64}', str(completion.get('result_sha256', ''))):
        raise StorageError('Confirmed public result reference and SHA are required')
    public = job_dir / 'public.jsonl.gz'
    if _file_info(public)[0]['sha256'] != completion['result_sha256']:
        raise StorageError('Local public result differs from confirmed publication')
    return {**{k: completion[k] for k in keys}, 'trial_ids': list(trial_ids),
            'status': completion['status'], 'counts': counts,
            'result_ref': completion['result_ref'], 'result_sha256': completion['result_sha256']}


def _terminal_state(state, trial_id):
    if (not isinstance(state, dict) or state.get('status') not in ('complete', 'failed')
            or state.get('pending_turn') is not None or state.get('pending_raw_files')
            or state.get('trial', {}).get('trial_id') != trial_id):
        raise StorageError('Active, interrupted, pending, or mismatched state cannot be archived')
    scratch = state.get('scratch_id', '')
    if not re.fullmatch(r'[0-9a-f]{32}', scratch):
        raise StorageError('Invalid native scratch identity')
    return scratch


def _collect(job_dir, trial_ids):
    allowed, raw_digests = set(), {}
    statuses = {'complete': 0, 'failed': 0}
    for trial_id in trial_ids:
        state_relative = 'states/' + trial_id + '.json'
        state = _read_json(job_dir / state_relative)
        scratch = _terminal_state(state, trial_id)
        statuses[state['status']] += 1
        allowed.add(state_relative)
        for suffix in ('.json.lock', '.journal.jsonl'):
            relative = 'states/' + trial_id + suffix
            if (job_dir / relative).exists():
                allowed.add(relative)
        if 'states/' + trial_id + '.json.lock' not in allowed:
            raise StorageError('State has no quiescence lock')
        for record in state.get('turns', []):
            for raw in record.get('raw_files', []):
                path = Path(raw['path'])
                path = path if path.is_absolute() else job_dir / path
                try:
                    relative = _safe_relative(path.relative_to(job_dir).as_posix())
                except ValueError as exc:
                    raise StorageError('Native evidence escapes the owned job') from exc
                if not relative.startswith('native/' + scratch + '/'):
                    raise StorageError('Native evidence belongs to another session')
                digest = raw.get('sha256')
                if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    raise StorageError('Missing native evidence SHA')
                if relative in raw_digests and raw_digests[relative] != digest:
                    raise StorageError('Inconsistent native evidence references')
                raw_digests[relative] = digest
                allowed.add(relative)
    actual, dirs = _inventory(job_dir)
    if actual != allowed:
        raise StorageError('Unknown or missing loose files; preserve all data: ' + repr(sorted(actual ^ allowed)))
    _check_dirs(dirs, allowed)
    entries = {}
    for relative in sorted(allowed):
        info, _ = _file_info(job_dir / relative)
        if relative.endswith('.json.lock') and info['size'] != 0:
            raise StorageError('State lock contains unknown data')
        if relative in raw_digests and info['sha256'] != raw_digests[relative]:
            raise StorageError('Native evidence hash differs from the durable response')
        entries[relative] = info
    return entries, statuses


def _check_dirs(directories, files):
    known = {'states', 'native'}
    for relative in files:
        known.update(str(p) for p in PurePosixPath(relative).parents if str(p) != '.')
    if not directories <= known:
        raise StorageError('Unknown loose directories must be preserved')


@contextmanager
def _state_locks(job_dir, trial_ids):
    with ExitStack() as stack:
        for trial_id in trial_ids:
            path = job_dir / 'states' / (trial_id + '.json.lock')
            _no_symlinks(path)
            if not path.exists():
                continue  # A verified previous prune may already have removed it.
            stream, info = stack.enter_context(_regular(path))
            if info.st_size:
                raise StorageError('Nonempty state lock')
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StorageError('A conversation is still locked by a runner') from exc
        yield


class _HashingReader:
    def __init__(self, stream):
        self.stream, self.digest = stream, hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def _write_archive(job_dir, temporary, entries, level):
    _no_symlinks(temporary)
    if temporary.exists():
        with _regular(temporary):
            pass
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0, compresslevel=level) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for relative, expected in entries.items():
                    with _regular(job_dir / relative) as (source, before):
                        if before.st_size != expected['size']:
                            raise StorageError('File size changed before archiving')
                        header = tarfile.TarInfo(relative)
                        header.size, header.mode, header.mtime = before.st_size, expected['mode'], 0
                        reader = _HashingReader(source)
                        archive.addfile(header, reader)
                        if reader.digest.hexdigest() != expected['sha256'] or _signature(before) != _signature(os.fstat(source.fileno())):
                            raise StorageError('File changed while archiving')
        out.flush()
        os.fsync(out.fileno())


def _validated_index(value):
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('kind') != 'exp7-private-terminal-job':
        raise StorageError('Unknown archive index')
    if not re.fullmatch(r'[0-9a-f]{64}', str(value.get('archive_sha256', ''))):
        raise StorageError('Missing archive SHA')
    if type(value.get('archive_bytes')) is not int or value['archive_bytes'] < 1:
        raise StorageError('Missing archive byte count')
    files = value.get('files')
    if not isinstance(files, dict) or not files:
        raise StorageError('Empty or invalid archive file manifest')
    for relative, info in files.items():
        _safe_relative(relative)
        if (not isinstance(info, dict) or set(info) != {'sha256', 'size', 'mode'}
                or not re.fullmatch(r'[0-9a-f]{64}', str(info['sha256']))
                or type(info['size']) is not int or info['size'] < 0
                or type(info['mode']) is not int or not 0 <= info['mode'] <= 0o777):
            raise StorageError('Invalid per-file archive metadata')
    return value


def _read_archive(archive_path, index, consume=None):
    """Check every compressed byte and every member; no extractall calls."""
    info, signature = _file_info(archive_path)
    if info['sha256'] != index['archive_sha256'] or info['size'] != index['archive_bytes']:
        raise StorageError('Archive SHA/size mismatch; no loose files may be deleted')
    seen = set()
    try:
        with _regular(archive_path) as (raw, _):
            with gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
                with tarfile.open(fileobj=compressed, mode='r|') as archive:
                    for member in archive:
                        relative = _safe_relative(member.name)
                        if not member.isfile() or member.issym() or member.islnk() or relative in seen:
                            raise StorageError('Nonregular or duplicate archive member')
                        expected = index['files'].get(relative)
                        if expected is None or member.size != expected['size'] or member.mode != expected['mode']:
                            raise StorageError('Unexpected archive member or size')
                        source = archive.extractfile(member)
                        if source is None:
                            raise StorageError('Unreadable archive member')
                        if consume is None:
                            digest, size = _hash_stream(source)
                        else:
                            digest, size = consume(relative, expected, source)
                        if digest != expected['sha256'] or size != expected['size']:
                            raise StorageError('Archive member digest mismatch')
                        seen.add(relative)
                # Force gzip trailer/CRC validation, even after tar end blocks.
                while compressed.read(CHUNK):
                    pass
    except (OSError, EOFError, tarfile.TarError, ValueError) as exc:
        raise StorageError('Corrupt or truncated archive; preserve loose files') from exc
    if seen != set(index['files']):
        raise StorageError('Archive omits indexed files')
    if _signature(os.lstat(archive_path)) != signature:
        raise StorageError('Archive changed during full verification')
    return signature


def verify_archive(archive, manifest):
    """Read all archive members and validate each byte against its own SHA."""
    index = _validated_index(_read_json(manifest))
    _read_archive(_no_symlinks(archive), index)
    return index


def _verify_remaining(job_dir, index):
    present, directories = _inventory(job_dir)
    if not present <= set(index['files']):
        raise StorageError('Unknown files appeared after archiving; preserve them')
    _check_dirs(directories, index['files'])
    signatures = {}
    for relative in present:
        actual, signature = _file_info(job_dir / relative)
        if actual != index['files'][relative]:
            raise StorageError('Loose file changed since archive: ' + relative)
        signatures[relative] = signature
    return signatures, directories


def _prune(job_dir, archive_path, index, archive_signature):
    signatures, directories = _verify_remaining(job_dir, index)
    removed = 0
    for relative in sorted(signatures):
        path = job_dir / relative
        if _signature(os.lstat(archive_path)) != archive_signature:
            raise StorageError('Verified archive changed before prune')
        actual, current = _file_info(path)
        if actual != index['files'][relative] or current != signatures[relative]:
            raise StorageError('Loose file changed before deletion')
        if _signature(os.lstat(path)) != current:
            raise StorageError('Loose file was replaced before deletion')
        path.unlink()
        removed += 1
    # Remove only known empty directories. A newly arrived unknown file is
    # never removed and makes rmdir fail closed.
    for relative in sorted(directories, key=lambda p: len(PurePosixPath(p).parts), reverse=True):
        path = job_dir / relative
        _no_symlinks(path)
        try:
            path.rmdir()
        except OSError as exc:
            raise StorageError('Loose directory not empty after verified prune') from exc
        _fsync_dir(path.parent)
    return removed


def archive_completed_job(job_dir, archive_dir, *, completion, expected_trial_ids, prune=True, policy=None):
    """Archive this own, remotely completed job, then optionally prune it.

    Hold the VM worker lock throughout. Pass the confirmed remote job returned
    by complete_job(), not an unacknowledged local completion proposal. Partial
    pruning is idempotent: an existing valid index is the authority; any changed
    loose file or unknown file blocks further pruning.
    """
    job_dir, archive_dir = _no_symlinks(job_dir), _no_symlinks(archive_dir)
    policy = _policy(policy)
    if any(archive_dir == job_dir / name or archive_dir.is_relative_to(job_dir / name) for name in ('states', 'native')):
        raise StorageError('Archives must be outside loose evidence directories')
    receipt = _receipt(job_dir, completion, list(expected_trial_ids))
    archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    job_id = receipt['job_id']
    archive = archive_dir / (job_id + '.tar.gz')
    manifest = archive_dir / (job_id + '.manifest.json')
    lock_path = _no_symlinks(archive_dir / (job_id + '.archive.lock'))
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise StorageError('Invalid archive lock')
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StorageError('Another archive operation is active') from exc
        with _state_locks(job_dir, expected_trial_ids):
            _no_symlinks(archive)
            _no_symlinks(manifest)
            if manifest.exists():
                index = _validated_index(_read_json(manifest))
                if index.get('completion') != receipt:
                    raise StorageError('Existing archive belongs to a different claim or result')
                archive_signature = _read_archive(archive, index)
                _verify_remaining(job_dir, index)
            else:
                entries, statuses = _collect(job_dir, expected_trial_ids)
                if any(statuses[k] != receipt['counts'].get(k, 0) for k in statuses):
                    raise StorageError('State status counts differ from remote completion')
                temporary = archive.with_name(archive.name + '.pending')
                _write_archive(job_dir, temporary, entries, policy['compression_level'])
                info, _ = _file_info(temporary)
                index = {'schema_version': 1, 'kind': 'exp7-private-terminal-job',
                         'created_at': datetime.now(timezone.utc).isoformat(),
                         'completion': receipt, 'storage_policy': policy,
                         'archive_sha256': info['sha256'], 'archive_bytes': info['size'],
                         'files': entries}
                # Verify the entire candidate before committing either artifact.
                _read_archive(temporary, index)
                if archive.exists():
                    # A crash between archive and index commit is recoverable
                    # only when the orphan is exactly the deterministic archive
                    # reconstructed from all still-present original files.
                    orphan, _ = _file_info(archive)
                    if orphan['sha256'] != info['sha256'] or orphan['size'] != info['size']:
                        raise StorageError('Different orphan archive must be preserved; no prune')
                    temporary.unlink()
                else:
                    os.replace(temporary, archive)
                _fsync_dir(archive_dir)
                _atomic_json(manifest, index)
                archive_signature = _read_archive(archive, index)
            # Durable tombstone blocks accidental local replay even if the
            # process dies partway through removing loose state files.
            marker_path = job_dir / 'archive-receipt.private.json'
            marker = {'schema_version': 1, 'job_id': job_id,
                      'claim_token': receipt['claim_token'], 'result_ref': receipt['result_ref'],
                      'result_sha256': receipt['result_sha256'], 'archive': str(archive),
                      'manifest': str(manifest), 'archive_sha256': index['archive_sha256'],
                      'manifest_sha256': _file_info(manifest)[0]['sha256']}
            if marker_path.exists():
                if _read_json(marker_path) != marker:
                    raise StorageError('Archive tombstone differs; preserve loose files')
            else:
                _atomic_json(marker_path, marker)
            removed = _prune(job_dir, archive, index, archive_signature) if prune else 0
            remaining, _ = _inventory(job_dir)
            return {'archive': str(archive), 'manifest': str(manifest),
                    'file_count': len(index['files']), 'archive_bytes': index['archive_bytes'],
                    'pruned_files': removed, 'remaining_loose_files': len(remaining),
                    'verified': True, 'job_id': job_id}


def restore_archive(archive, manifest, destination):
    """Restore original file bytes into an empty directory with no overwrites."""
    index = verify_archive(archive, manifest)
    destination = _no_symlinks(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise StorageError('Restore destination must be empty')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)

    def consume(relative, expected, source):
        target = _no_symlinks(destination / _safe_relative(relative))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest, size = hashlib.sha256(), 0
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), expected['mode'])
            os.fsync(out.fileno())
        _fsync_dir(target.parent)
        return digest.hexdigest(), size

    _read_archive(archive, index, consume)
    # Verify on-disk bytes after writing, not just bytes passed to write().
    for relative, expected in index['files'].items():
        if _file_info(destination / relative)[0] != expected:
            raise StorageError('Restored bytes differ from archive index')
    _fsync_dir(destination)
    return index
