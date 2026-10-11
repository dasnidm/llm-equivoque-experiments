from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, FREEZE


def main():
    config=read_json(CONFIG)
    paths=set(read_json(ROOT/'protocol/freeze.json')['files']) | set(read_json(ROOT/'experiment2/protocol/freeze.json')['files'])
    paths |= {'protocol/freeze.json','experiment2/protocol/freeze.json','EXPERIMENT_3_PILOT_PLAN.md'}
    paths |= {str(p.relative_to(ROOT)) for p in (ROOT/'experiment3').glob('*.py')}
    paths |= {str(p.relative_to(ROOT)) for p in (ROOT/'experiment3').glob('*.md')}
    paths |= {str(p.relative_to(ROOT)) for p in (ROOT/'experiment3/protocol').glob('*.json') if p!=FREEZE}
    paths |= {str(p.relative_to(ROOT)) for p in (ROOT/'manifests'/config['run_id']).glob('*.json')}
    write_json(FREEZE,{'run_id':config['run_id'],'scope':'pilot_only','status':'prepared_pending_live_readiness',
               'files':{p:digest(ROOT/p) for p in sorted(paths)}})
    print('Frozen '+str(len(paths))+' files; SHA-256 '+digest(FREEZE))


if __name__=='__main__':main()
