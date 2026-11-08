"""Verify and privately preserve a finished capacity stage, without pruning."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

from exp7_backup_v1.sidecar import verify_private_repository, _remote_readback
from exp7_main_v2.worker import ResultPublisher


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--stage', required=True)
    p.add_argument('--branch', default='capacity/equivoque-2026-11-08-exp7-capacity-v1',
                   help='Separate immutable raw-evidence branch for a technical study')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.stage):
        raise ValueError('Invalid stage')
    source = args.root / args.stage
    if not (source / 'summary.json').is_file():
        raise ValueError('Stage has not closed its transport and written a summary')
    out = args.root / 'backups' / args.stage
    out.mkdir(parents=True, exist_ok=True)
    archive, index = out / 'evidence.tar.gz', out / 'index.json'
    if archive.exists() or index.exists():
        raise FileExistsError('Existing backup is immutable')
    members = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink prohibited')
        if path.is_file() and not path.name.endswith('.lock'):
            data = path.read_bytes()
            members.append({'path': path.relative_to(source).as_posix(), 'bytes': len(data), 'sha256': sha(data)})
    with archive.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for item in members:
            path = source / item['path']
            if sha(path.read_bytes()) != item['sha256']:
                raise ValueError('Source evidence changed')
            tar.add(path, arcname=item['path'], recursive=False)
    with tarfile.open(archive, 'r:gz') as tar:
        for item in members:
            data = tar.extractfile(item['path']).read()
            if len(data) != item['bytes'] or sha(data) != item['sha256']:
                raise ValueError('Archive verification failed')
    if archive.stat().st_size >= 95_000_000:
        raise ValueError('Archive exceeds GitHub upload budget; preserve locally')
    index.write_text(json.dumps({'stage': args.stage, 'archive_sha256': sha(archive.read_bytes()),
                                 'members': members}, indent=2) + '\n')
    repository = verify_private_repository('dasnidm/llm-equivoque-exp7-raw')
    publisher = ResultPublisher('https://github.com/' + repository['full_name'] + '.git',
                               args.branch, out / 'publication.git')
    expected = {}
    for path in (archive, index):
        target = args.stage + '/' + path.name
        publisher.publish(path, target)
        data = path.read_bytes()
        expected[target] = {'bytes': len(data), 'sha256': sha(data)}
    commit = _remote_readback(publisher, expected)
    receipt = {'stage': args.stage, 'private_repository_id': repository['id'], 'remote_commit': commit,
               'branch': publisher.branch, 'files': expected, 'local_sources_retained': True}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
