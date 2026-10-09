import argparse
import json
from pathlib import Path

from .audit import audit_worker
from .core import ROOT, digest, frozen_hashes, read_json, write_json
from .preflight import preflight
from .runner import run_worker


def main():
    parser = argparse.ArgumentParser(description='Frozen equivoque collection tools')
    commands = parser.add_subparsers(dest='command', required=True)
    pre = commands.add_parser('preflight')
    pre.add_argument('--manifest', required=True)
    pre.add_argument('--output', required=True)
    pre.add_argument('--live', action='store_true')
    run = commands.add_parser('run')
    run.add_argument('--manifest', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--readiness', required=True)
    run.add_argument('--launch', required=True)
    audit = commands.add_parser('audit')
    audit.add_argument('--manifest', required=True)
    audit.add_argument('--output', required=True)
    release = commands.add_parser('release')
    release.add_argument('--readiness', nargs=7, required=True)
    release.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'preflight':
        report = preflight(args.manifest, args.output, args.live)
        print(json.dumps({'ready': report['ready'], 'errors': report['errors'],
                          'subject_invocations': report['subject_invocations']}, indent=2))
        return 0 if report['ready'] else 2
    if args.command == 'run':
        run_worker(args.manifest, args.output, args.readiness, args.launch)
        report = audit_worker(args.manifest, args.output)
    elif args.command == 'audit':
        report = audit_worker(args.manifest, args.output)
    else:
        frozen_hashes()
        reports = [read_json(path) for path in args.readiness]
        expected = digest(ROOT / 'protocol/freeze.json')
        if (any(not report.get('ready') or report.get('freeze_sha256') != expected
                for report in reports) or
                {r['worker_id'] for r in reports} != set('abcdefg') or
                len({r['base_commit'] for r in reports}) != 1):
            raise ValueError('All seven workers must be ready at the same frozen revision')
        config = read_json(ROOT / 'protocol/run.v1.json')
        for report in reports:
            manifest = ROOT / 'manifests' / config['run_id'] / (
                'worker-' + report['worker_id'] + '.json')
            if report.get('manifest_sha256') != digest(manifest):
                raise ValueError('Readiness manifest mismatch')
        report = {'run_id': config['run_id'], 'freeze_sha256': expected,
                  'base_commit': reports[0]['base_commit'],
                  'workers_ready': list('abcdefg')}
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report.get('integrity_ok', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
