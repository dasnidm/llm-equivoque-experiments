"""Back up an inactive persistent technical attempt, without pruning sources."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import tarfile

from exp7_backup_v1.sidecar import verify_private_repository, _remote_readback
from exp7_main_v2.worker import ResultPublisher


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work-dir', required=True, type=Path)
    p.add_argument('--attempt', default='01')
    p.add_argument('--repository', default='dasnidm/llm-equivoque-exp7-raw')
    args = p.parse_args()
    work = args.work_dir.resolve()
    identity = json.loads((work / 'identity.private.json').read_text())
    run, model = identity['run_id'], identity['model']
    folder = work / 'calibration' / ('attempt-' + args.attempt)
    if not folder.is_dir() or '/' in args.attempt or '..' in args.attempt:
        raise ValueError('Invalid or absent calibration attempt')
    with (work / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        metadata = verify_private_repository(args.repository)
        output = work / 'calibration-backups' / ('attempt-' + args.attempt)
        output.mkdir(parents=True, exist_ok=True)
        archive = output / 'calibration.tar.gz'
        manifest = output / 'manifest.json'
        if archive.exists() or manifest.exists():
            raise FileExistsError('Existing technical backup is immutable; inspect it first')
        members = []
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlinks are prohibited in calibration backup')
            if path.is_file() and not path.name.endswith('.lock'):
                relative = path.relative_to(folder).as_posix()
                data = path.read_bytes()
                members.append({'path': relative, 'bytes': len(data), 'sha256': digest(data)})
        if not members:
            raise ValueError('No calibration evidence to back up')
        with archive.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as tar:
            for member in members:
                path = folder / member['path']
                if digest(path.read_bytes()) != member['sha256']:
                    raise ValueError('Calibration evidence changed during backup')
                tar.add(path, arcname=member['path'], recursive=False)
        with tarfile.open(archive, 'r:gz') as tar:
            for member in members:
                data = tar.extractfile(member['path']).read()
                if len(data) != member['bytes'] or digest(data) != member['sha256']:
                    raise ValueError('Calibration archive verification failed')
        if archive.stat().st_size >= 95_000_000:
            raise ValueError('Archive too large for GitHub; keep local evidence and inspect')
        manifest.write_text(json.dumps({'run_id': run, 'model': model, 'attempt': args.attempt,
                                        'archive_sha256': digest(archive.read_bytes()),
                                        'members': members}, indent=2) + '\n')
        branch = 'raw/' + run + '/' + model
        remote = 'https://github.com/' + metadata['full_name'] + '.git'
        publisher = ResultPublisher(remote, branch, output / 'publication.git')
        expected = {}
        for path in (archive, manifest):
            target = 'calibration/attempt-' + args.attempt + '/' + path.name
            data = path.read_bytes()
            publisher.publish(path, target)
            expected[target] = {'bytes': len(data), 'sha256': digest(data)}
        head = _remote_readback(publisher, expected)
        receipt = {'branch': branch, 'remote_commit': head, 'files': expected,
                   'repository_id': metadata['id'], 'private': True,
                   'local_sources_retained': True}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
