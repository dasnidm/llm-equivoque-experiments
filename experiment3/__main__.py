import argparse
import json
from . import preflight, runner


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('shared'); s.add_argument('--output',required=True)
    s=sub.add_parser('preflight'); s.add_argument('--manifest',required=True); s.add_argument('--output',required=True); s.add_argument('--shared',required=True)
    s=sub.add_parser('run'); s.add_argument('--manifest',required=True); s.add_argument('--readiness',required=True); s.add_argument('--launch',required=True); s.add_argument('--controls',required=True)
    s=sub.add_parser('release'); s.add_argument('--readiness',nargs='+',required=True); s.add_argument('--shared',required=True); s.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='shared': r=preflight.shared(a.output)
    elif a.command=='preflight': r=preflight.worker(a.manifest,a.output,a.shared)
    elif a.command=='release': r=preflight.release(a.readiness,a.shared,a.output)
    else: return 0 if runner.worker(a.manifest,a.readiness,a.launch,a.controls) else 2
    print(json.dumps(r))
    return 0 if r.get('ready',a.command=='release') else 2


if __name__=='__main__':
    raise SystemExit(main())
