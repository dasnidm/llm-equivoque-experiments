"""Create or reuse twenty audited result PRs through structured GitHub REST."""
import json
import subprocess

from equivoque.core import ROOT, read_json, write_json
from equivoque2.protocol import CONFIG, frozen_hashes


def api(endpoint, body=None):
    command = ['gh','api',endpoint]
    if body is not None:
        command += ['--method','POST','--input','-']
    result = subprocess.run(command,input=json.dumps(body) if body is not None else None,
        text=True,capture_output=True,cwd=ROOT,check=True)
    return json.loads(result.stdout)


def main():
    frozen_hashes()
    config = read_json(CONFIG)
    finalized = read_json(ROOT / 'experiment2/runtime/finalized-workers.json')
    assert finalized['trials'] == 420
    repo = 'dasnidm/llm-equivoque-experiments'
    base = 'integration/' + config['run_id']
    existing=[]
    page=1
    while True:
        batch=api(f'repos/{repo}/pulls?state=all&per_page=100&page={page}')
        existing.extend(batch)
        if len(batch)<100:break
        page+=1
    records=[]
    for w in config['workers']:
        head=f"worker/{config['run_id']}/{w}"
        matches=[p for p in existing if p['head']['ref']==head and p['base']['ref']==base]
        if len(matches)>1:raise ValueError('Duplicate result PRs for '+w)
        if matches:
            pr=matches[0]
        else:
            directory=ROOT/'results'/config['run_id']/f'worker-{w}'
            # Before integration, use the independent sparse result worktree.
            if not directory.exists():
                directory=ROOT/'work/worker-trees'/config['run_id']/w/'results'/config['run_id']/f'worker-{w}'
            audit=read_json(directory/'audit.json')
            assert audit['integrity_ok'] and audit['collection_finished']
            body=(f"This shard supplies worker {w.upper()}'s 21 assigned three-round equivoque sessions "
                "with questions after each round and again after final disclosure. Exact prompts, "
                "answers, native logs, engine traces, partial endpoints, and failures are retained.\n\n"
                f"Validation: frozen protocol, session continuity, disjoint assignment, and native "
                f"SHA-256 audit passed. Status counts: {json.dumps(audit['counts'])}. "
                f"Evaluation invocations: {audit['subject_invocations']}. "
                f"Valid measurements: {json.dumps(audit['valid_measurements'])}. "
                f"Native files verified: {audit['raw_files_verified']}. "
                "Readiness calibration remains separately labeled and excluded from evaluation.\n\n"
                "Runtime-recovery evidence retains the original pending request and uniquely "
                "completed native response; no request was replayed. Recovered parent-observed "
                "exit status and duration remain unknown. Integration belongs on the separate "
                "experiment 2 branch; the frozen common source and experiment 1 are unchanged.")
            pr=api(f'repos/{repo}/pulls',{'title':f'Experiment 2 results: worker {w.upper()}',
                'head':head,'base':base,'body':body,'draft':True})
        records.append({'worker':w,'number':pr['number'],'url':pr['html_url'],'head':head,'base':base})
        print(json.dumps(records[-1]),flush=True)
        write_json(ROOT/'experiment2/runtime/result-prs.json',{'pull_requests':records})


if __name__=='__main__':
    main()
