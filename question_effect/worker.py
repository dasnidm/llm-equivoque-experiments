"""One directly launched worker; no automatic supervisor or failed-turn replay."""
import argparse,fcntl,json
from pathlib import Path
from equivoque.core import ROOT,digest,read_json,write_json
from equivoque.transport import CodexTransport
from sequence_replication.runner import run_trial
from question_effect.protocol import QuestionProtocol

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',required=True);args=p.parse_args()
    spec=read_json(ROOT/'question_effect/design.json')
    for name,expected in read_json(ROOT/'question_effect/freeze.json')['files'].items():
        if digest(ROOT/name)!=expected: raise ValueError('Frozen file changed: '+name)
    trials=read_json(ROOT/'question_effect/assignments.json')[args.worker]
    out=ROOT/'results'/spec['run_id']/('worker-'+args.worker)
    out.mkdir(parents=True,exist_ok=True)
    lock=(out/'.runner.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol=QuestionProtocol();transport=CodexTransport(protocol,300)
    for trial in trials:
        path=out/'trials'/(trial['trial_id'].replace('/','__')+'.json')
        if path.exists():
            state=read_json(path)
            if state['status']=='complete':continue
            raise RuntimeError('Incomplete attempt requires coordinator review; no automatic replay')
        state=run_trial(trial,protocol,transport,path,Path(spec['scratch_root']))
        print(json.dumps({'trial_id':trial['trial_id'],'status':state['status']}),flush=True)
        if state['status']!='complete':raise RuntimeError('Failed attempt retained; coordinator review required')
    write_json(out/'done.json',{'worker':args.worker,'complete':len(trials)})

if __name__=='__main__':main()
