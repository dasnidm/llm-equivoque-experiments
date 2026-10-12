"""Freeze the new source without modifying any previous experiment."""
from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, FREEZE


def main():
    config = read_json(CONFIG)
    old = ROOT / 'experiment7/protocol/freeze.json'
    paths = set(read_json(old)['files']) | {str(old.relative_to(ROOT)), 'SEQUENCE_REPLICATION_PLAN.md'}
    for pattern in ('*.py', '*.md', 'protocol/*.json'):
        paths |= {str(p.relative_to(ROOT)) for p in (ROOT / 'sequence_replication').glob(pattern) if p != FREEZE}
    paths |= {str(p.relative_to(ROOT)) for p in (ROOT / 'manifests' / config['run_id']).glob('*.json')}
    write_json(FREEZE, {'run_id': config['run_id'], 'scope': config['scope'],
                       'files': {p: digest(ROOT / p) for p in sorted(paths)}})
    print('Frozen', len(paths), 'files; SHA-256', digest(FREEZE))


if __name__ == '__main__':
    main()
