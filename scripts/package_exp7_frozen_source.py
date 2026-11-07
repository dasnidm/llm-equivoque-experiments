"""Build and verify a small distributable from exact frozen input files.

No model calls, repository history, native logs or credentials are included.
The optional README files explain deployment and are indexed separately from
the immutable scientific input hashes already present in freeze.json.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(root, freeze, output, prefix):
    root, freeze, output = map(lambda p: Path(p).resolve(), (root, freeze, output))
    if not prefix or '/' in prefix or prefix in ('.', '..'):
        raise ValueError('A single safe archive prefix is required')
    info = json.loads(freeze.read_text())
    entries = dict(info['files'])
    entries[str(freeze.relative_to(root))] = digest(freeze.read_bytes())
    for relative in ('exp7_main/README.md', 'exp7_main_v2/README.md'):
        path = root / relative
        if path.is_file():
            entries[relative] = digest(path.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('Use a new output path; existing packages are immutable')
    expected = {}
    with output.open('xb') as target:
        with gzip.GzipFile(fileobj=target, mode='wb', filename='', mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for relative, sha in sorted(entries.items()):
                    path = root / relative
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise ValueError('Unsafe source member: ' + relative)
                    data = path.read_bytes()
                    if digest(data) != sha:
                        raise ValueError('Frozen source differs: ' + relative)
                    name = prefix + '/' + relative
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o644
                    member.mtime = 0
                    archive.addfile(member, io.BytesIO(data))
                    expected[name] = (len(data), sha)
    seen = set()
    with tarfile.open(output, 'r:gz') as archive:
        for member in archive:
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError('Archive membership mismatch')
            data = archive.extractfile(member).read()
            if (len(data), digest(data)) != expected[member.name]:
                raise ValueError('Archive member verification failed: ' + member.name)
            seen.add(member.name)
    if seen != set(expected):
        raise ValueError('Archive members missing')
    sha = digest(output.read_bytes())
    checksum = output.parent / 'SHA256SUMS'
    if checksum.exists():
        raise ValueError('Checksum file already exists; use a separate release directory')
    checksum.write_text(sha + '  ' + output.name + '\n')
    return {'run_id': info['run_id'], 'source_commit': info['source_commit'],
            'files': len(entries), 'logical_source_bytes': sum(v[0] for v in expected.values()),
            'archive_bytes': output.stat().st_size, 'sha256': sha,
            'verified_every_member': True, 'archive': str(output), 'checksum': str(checksum)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--freeze', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prefix', default='exp7-main-v2')
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.freeze, args.output, args.prefix), indent=2))
