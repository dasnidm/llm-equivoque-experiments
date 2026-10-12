from equivoque.core import ROOT,digest,read_json,write_json
from .protocol import CONFIG,FREEZE


def main():
    config=read_json(CONFIG)
    paths=set()
    for f in ('protocol/freeze.json','experiment2/protocol/freeze.json','experiment3/protocol/freeze.json'):
        paths|=set(read_json(ROOT/f)['files']);paths.add(f)
    paths.add('EXPERIMENT_7_PLAN.md')
    paths|={str(p.relative_to(ROOT)) for p in (ROOT/'experiment7').glob('*.py')}
    paths|={str(p.relative_to(ROOT)) for p in (ROOT/'experiment7').glob('*.md')}
    paths|={str(p.relative_to(ROOT)) for p in (ROOT/'experiment7/protocol').glob('*.json') if p!=FREEZE}
    paths|={str(p.relative_to(ROOT)) for p in (ROOT/'manifests'/config['run_id']).glob('*.json')}
    write_json(FREEZE,{'run_id':config['run_id'],'scope':'28_session_pilot_only',
                      'files':{p:digest(ROOT/p) for p in sorted(paths)}})
    print('Frozen '+str(len(paths))+' files; SHA-256 '+digest(FREEZE))


if __name__=='__main__':main()
