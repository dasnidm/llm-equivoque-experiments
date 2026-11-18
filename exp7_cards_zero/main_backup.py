"""Private, checksummed backups of terminal conversations for the new run."""
from pathlib import Path
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def archive_conversation(root, trial_id, scratch_id):
    """Archive and individually verify state, journal, native and retry files.

    As in the original private backup contract, never include Codex auth files,
    shared or per-conversation CLI SQLite databases, or other conversations.
    No input is deleted by this function.
    """
    root = Path(root)
    state = root/'states'/(trial_id+'.json')
    journal = root/'states'/(trial_id+'.journal.jsonl')
    native = root/'native'/scratch_id
    sources = [(state, Path('states')/state.name), (journal, Path('states')/journal.name),
               (native, Path('native')/scratch_id)]
    if not all(p.exists() for p, _ in sources):
        raise ValueError('Missing terminal-conversation evidence')
    for suffix in ('.json.lock', '.json.queued.lock'):
        lock = root/'states'/(trial_id+suffix)
        if lock.exists(): sources.append((lock, Path('states')/lock.name))
    expected={}
    for path, _ in sources:
        paths = [path] if path.is_file() else list(path.rglob('*'))
        if any(p.is_symlink() or (not p.is_file() and not p.is_dir()) for p in paths):
            raise ValueError('Unexpected link or special file in archive inputs')
    for source, name in sources:
        paths=[source] if source.is_file() else sorted(p for p in source.rglob('*') if p.is_file())
        for path in paths:
            if path.stat().st_nlink != 1:
                raise ValueError('Hard-linked files are not permitted')
            relative=name if source.is_file() else name/path.relative_to(source)
            expected[relative.as_posix()]={'sha256':sha(path),'size':path.stat().st_size}
    spool = root/'archive-spool'
    spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = spool/(trial_id+'.tar.gz')
    if target.exists():
        raise FileExistsError('Refusing to overwrite archive')
    temporary = spool/(trial_id+'.pending')
    with temporary.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz', compresslevel=4) as archive:
            for source, name in sources:
                archive.add(source, arcname=name.as_posix(), recursive=True)
            manifest=json.dumps({'version':1,'trial_id':trial_id,'files':expected},
                                sort_keys=True,separators=(',',':')).encode()
            info=tarfile.TarInfo('MANIFEST.json');info.size=len(manifest);info.mode=0o600
            archive.addfile(info,io.BytesIO(manifest))
        raw.flush()
        os.fsync(raw.fileno())
    # Full decompression and per-file checks verify the archived original bytes.
    with tarfile.open(temporary, 'r:gz') as archive:
        seen=set()
        for member in archive:
            if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe archive member')
            if member.isfile() and member.name != 'MANIFEST.json':
                if member.name in seen or member.name not in expected:
                    raise ValueError('Unexpected or duplicate archive member')
                digest=hashlib.sha256();size=0;stream=archive.extractfile(member)
                for block in iter(lambda:stream.read(1024*1024),b''):
                    digest.update(block);size+=len(block)
                if expected[member.name] != {'sha256':digest.hexdigest(),'size':size}:
                    raise ValueError('Archived file mismatch')
                seen.add(member.name)
        if seen != set(expected):raise ValueError('Missing archive members')
        if json.load(archive.extractfile('MANIFEST.json'))['files'] != expected:
            raise ValueError('Archive manifest mismatch')
    os.replace(temporary, target)
    return {'trial_id': trial_id, 'archive': str(target), 'sha256': sha(target),
            'bytes': target.stat().st_size}


def restore_archive(archive_path, destination, expected_sha256):
    """Restore exact archived files into a new empty directory, never replay."""
    archive_path=Path(archive_path);destination=Path(destination)
    if sha(archive_path)!=expected_sha256:raise ValueError('Archive checksum mismatch')
    if destination.exists():raise FileExistsError('Restore destination must not exist')
    destination.mkdir(parents=True,mode=0o700)
    with tarfile.open(archive_path,'r:gz') as archive:
        members=archive.getmembers()
        manifests=[m for m in members if m.name=='MANIFEST.json' and m.isfile()]
        if len(manifests)!=1:raise ValueError('Invalid archive manifest')
        manifest=json.load(archive.extractfile(manifests[0]))
        expected=manifest['files']
        seen=set()
        for member in members:
            if member.name=='MANIFEST.json' or member.isdir():continue
            name=Path(member.name)
            if (not member.isfile() or name.is_absolute() or '..' in name.parts
                    or member.name in seen or member.name not in expected):
                raise ValueError('Unsafe or unexpected archive member')
            target=destination/name
            target.parent.mkdir(parents=True,exist_ok=True)
            digest=hashlib.sha256();size=0
            with target.open('xb') as output:
                stream=archive.extractfile(member)
                for block in iter(lambda:stream.read(1024*1024),b''):
                    output.write(block);digest.update(block);size+=len(block)
                output.flush();os.fsync(output.fileno())
            if expected[member.name]!={'sha256':digest.hexdigest(),'size':size}:
                raise ValueError('Restored file mismatch')
            seen.add(member.name)
        if seen!=set(expected):raise ValueError('Archive does not match manifest')
    return {'files':len(seen),'trial_id':manifest['trial_id']}


class PrivateGitBackup:
    """Single-writer, fast-forward-only bare Git archive, no worktree copies."""
    def __init__(self, cache, remote, branch):
        self.cache, self.remote, self.branch = Path(cache), remote, branch
        if self.cache.exists():
            raise FileExistsError('Backup cache already exists')
        self.cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.run(['git', 'init', '--bare', '-q', str(self.cache)], check=True)
        self.verify_cache = self.cache.parent/(self.cache.name+'-readback')
        if self.verify_cache.exists():
            raise FileExistsError('Backup readback cache already exists')
        subprocess.run(['git', 'init', '--bare', '-q', str(self.verify_cache)], check=True)
        self.parent = None
        remote_heads = subprocess.run(['git', 'ls-remote', '--heads', remote, 'refs/heads/'+branch],
                                      check=True, capture_output=True, text=True, timeout=45)
        if remote_heads.stdout.strip():
            raise FileExistsError('Private backup branch already exists')

    def git(self, *args, env=None, input_bytes=None):
        variables = {**os.environ, 'GIT_TERMINAL_PROMPT':'0', 'GIT_AUTHOR_NAME':'Exp7 backup',
                     'GIT_AUTHOR_EMAIL':'exp7-backup@localhost', 'GIT_COMMITTER_NAME':'Exp7 backup',
                     'GIT_COMMITTER_EMAIL':'exp7-backup@localhost', **(env or {})}
        result = subprocess.run(['git', '--git-dir', str(self.cache), *args], input=input_bytes,
                                capture_output=True, env=variables, timeout=120)
        if result.returncode:
            raise RuntimeError('Private backup Git operation failed: '+args[0])
        return result.stdout.decode().strip()

    def upload(self, items):
        if not items:
            return None
        with tempfile.TemporaryDirectory(prefix='backup-index-', dir=self.cache.parent) as tmp:
            env={'GIT_INDEX_FILE':str(Path(tmp)/'index')}
            if self.parent:
                self.git('read-tree', self.parent, env=env)
            else:
                self.git('read-tree', '--empty', env=env)
            for item in items:
                path=Path(item['archive'])
                if path.stat().st_size >= 90*1024**2:
                    raise ValueError('Archive is too large for ordinary GitHub storage')
                if sha(path) != item['sha256']:
                    raise ValueError('Archive hash changed before upload')
                blob=self.git('hash-object','-w',str(path))
                name='archives/'+item['trial_id']+'.tar.gz'
                self.git('update-index','--add','--cacheinfo',f'100644,{blob},{name}',env=env)
            tree=self.git('write-tree',env=env)
            args=['commit-tree',tree]
            if self.parent: args+=['-p',self.parent]
            commit=self.git(*args,input_bytes=b'Back up terminal experiment conversations\n')
            self.git('push',self.remote,commit+':refs/heads/'+self.branch)
            observed=self.git('ls-remote','--heads',self.remote,'refs/heads/'+self.branch).split()
            if not observed or observed[0] != commit:
                raise RuntimeError('Private backup remote confirmation failed')
            # Fetch into a separate object store and hash the remote blob bytes.
            envvars={**os.environ,'GIT_TERMINAL_PROMPT':'0'}
            subprocess.run(['git','--git-dir',str(self.verify_cache),'fetch','-q','--no-tags',
                            self.remote,'refs/heads/'+self.branch+':refs/remotes/exp7/backup'],check=True,
                           capture_output=True,timeout=120,env=envvars)
            for item in items:
                name='archives/'+item['trial_id']+'.tar.gz'
                proc=subprocess.Popen(['git','--git-dir',str(self.verify_cache),'show',commit+':'+name],
                                      stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=envvars)
                digest=hashlib.sha256()
                for chunk in iter(lambda:proc.stdout.read(1024*1024),b''):
                    digest.update(chunk)
                proc.stdout.close()
                if proc.wait(timeout=120) or digest.hexdigest() != item['sha256']:
                    raise RuntimeError('Remote archive bytes do not match original')
            self.git('update-ref','refs/heads/'+self.branch,commit)
            self.parent=commit
            return commit
