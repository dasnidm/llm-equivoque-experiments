import argparse
import json
from .audit import audit_worker
from .preflight import shared,worker,release
from .runner import run_worker


def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('service-preflight');a.add_argument('--output',required=True)
    a=s.add_parser('preflight');a.add_argument('--manifest',required=True);a.add_argument('--output',required=True);a.add_argument('--shared',required=True)
    a=s.add_parser('release');a.add_argument('--readiness',nargs=20,required=True);a.add_argument('--shared',required=True);a.add_argument('--output',required=True)
    a=s.add_parser('run');a.add_argument('--manifest',required=True);a.add_argument('--readiness',required=True);a.add_argument('--launch',required=True);a.add_argument('--controls',required=True)
    a=s.add_parser('audit');a.add_argument('--manifest',required=True);a.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='service-preflight':r=shared(args.output)
    elif args.command=='preflight':r=worker(args.manifest,args.output,args.shared)
    elif args.command=='release':r=release(args.readiness,args.shared,args.output)
    elif args.command=='audit':r=audit_worker(args.manifest,args.output)
    else:return 0 if run_worker(args.manifest,args.readiness,args.launch,args.controls) else 2
    print(json.dumps({k:v for k,v in r.items() if k not in ('inspections','session_ids')},indent=2))
    return 0 if r.get('ready',r.get('integrity_ok',True)) else 2


if __name__=='__main__':raise SystemExit(main())
