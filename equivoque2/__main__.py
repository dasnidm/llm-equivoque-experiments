import argparse
import json

from .audit import audit_worker
from .preflight import release, shared, worker
from .runner import run_worker


def main():
    parser = argparse.ArgumentParser(description='Experiment 2 frozen nine-turn trials')
    commands = parser.add_subparsers(dest='command', required=True)
    service = commands.add_parser('service-preflight')
    service.add_argument('--output', required=True)
    pre = commands.add_parser('preflight')
    pre.add_argument('--manifest', required=True)
    pre.add_argument('--output', required=True)
    pre.add_argument('--shared', required=True)
    gate = commands.add_parser('release')
    gate.add_argument('--readiness', nargs=20, required=True)
    gate.add_argument('--shared', required=True)
    gate.add_argument('--output', required=True)
    run = commands.add_parser('run')
    run.add_argument('--manifest', required=True)
    run.add_argument('--readiness', required=True)
    run.add_argument('--launch', required=True)
    run.add_argument('--controls', required=True)
    audit = commands.add_parser('audit')
    audit.add_argument('--manifest', required=True)
    audit.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'service-preflight':
        result = shared(args.output)
    elif args.command == 'preflight':
        result = worker(args.manifest, args.output, args.shared)
    elif args.command == 'release':
        result = release(args.readiness, args.shared, args.output)
    elif args.command == 'audit':
        result = audit_worker(args.manifest, args.output)
    else:
        return 0 if run_worker(args.manifest, args.readiness, args.launch, args.controls) else 2
    print(json.dumps({k: v for k, v in result.items() if k not in ('session_ids', 'offline_inspections', 'offline_inspection')}, indent=2))
    return 0 if result.get('ready', result.get('integrity_ok', True)) else 2


if __name__ == '__main__':
    raise SystemExit(main())
