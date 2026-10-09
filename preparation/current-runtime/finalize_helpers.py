"""Publish disjoint helper results, then reunite canonical A–G ownership."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.audit import audit_worker
from equivoque.core import read_json,write_json,digest,frozen_hashes
from equivoque.runner import now
RUN='equivoque-2026-10-09-v1'
REPO='dasnidm/llm-equivoque-experiments'
assignments=read_json(ROOT/'preparation/current-runtime/executor-assignments-01.json')['executors']
progress=read_json(ROOT/'preparation/current-runtime/collection-progress.json')
assert all(progress['executors'][e]['exit_code']==0 for e in assignments)
frozen_hashes()
prs=json.loads(subprocess.check_output(['gh','pr','list','--repo',REPO,'--state','all','--limit','100',
                                     '--json','number,url,headRefName,baseRefName,state'],text=True))
issues=read_json(ROOT/'preparation/current-runtime/helper-issues-01.json')['assignments']
returns=[]
# Commit each original's completed exclusive share before merging helper paths.
for w in 'abcdefg':
    tree=ROOT/'work/worker-trees'/RUN/w
    subprocess.run(['git','add',f'results/{RUN}/worker-{w}'],cwd=tree,check=True)
    if subprocess.run(['git','diff','--cached','--quiet'],cwd=tree).returncode:
        subprocess.run(['git','commit','-m',f'Executor {w.upper()}: complete exclusive remaining share'],cwd=tree,check=True)
for e,a in assignments.items():
    if e in 'abcdefg':continue
    w=a['logical_worker'];tree=ROOT/'work/worker-trees'/RUN/e
    directory=tree/'results'/RUN/f'worker-{w}'
    states=[read_json(p)for p in (directory/'trials').glob('*.json')]
    assert {s['trial']['trial_id']for s in states}==set(a['trial_ids'])
    assert all(s['status']in ('complete','failed','interrupted')for s in states)
    audit=audit_worker(tree/'manifests'/RUN/f'worker-{w}.json',directory)
    assert audit['integrity_ok']
    (directory/'audit.json').rename(directory/f'executor-{e}-audit.json')
    report={'executor_id':e,'logical_worker':w,'exclusive_assigned':len(a['trial_ids']),
            'attempted':len(states),'counts':{k:sum(s['status']==k for s in states)for k in ('complete','failed','interrupted')},
            'subject_invocations':sum(len(s['turns'])+int(s.get('pending_turn')is not None)for s in states),
            'integrity_ok':True,'reported_at':now(),'note':'Partial original-manifest audit is intentional: executor owns only the exclusive listed IDs, while the unchanged logical A–G owner retains 300 trials. No replacements or replay.'}
    write_json(directory/f'executor-{e}-completion.json',report)
    subprocess.run(['git','add',f'results/{RUN}/worker-{w}'],cwd=tree,check=True)
    if subprocess.run(['git','diff','--cached','--quiet'],cwd=tree).returncode:
        subprocess.run(['git','commit','-m',f'Helper {e.upper()}: preserve exclusive results for logical worker {w.upper()}'],cwd=tree,check=True)
    branch=f'worker/{RUN}/{e}'
    subprocess.run(['git','push','origin',branch],cwd=tree,check=True)
    matches=[p for p in prs if p['headRefName']==branch and p['baseRefName']==f'integration/{RUN}']
    assert len(matches)<=1
    if matches:pr=matches[0]
    else:
        issue=next(i['number']for i in issues if i['executor_id']==e)
        body=ROOT/f'work/coordinator/helper-pr-{e}.md'
        body.write_text(f'Helper executor {e.upper()} completed its exclusive {len(states)}-trial subdivision of logical worker {w.upper()}\'s original frozen 300-trial manifest.\n\nCanonical prompts, targets, seeds, model/effort matrix, subject paths, four-turn native sessions and frozen source are unchanged. Only listed unstarted evaluation IDs were transferred; no extra evaluation trials or replacement calls were added. Raw transcripts/journals, helper preflight, executor provenance and exclusive-share audit are retained. The original A–G owner will publish a complete 300-trial audit after reunification.\n\nValidation: exclusive assigned ID set matched exactly; integrity audit passed.\n\nCloses #{issue}.\n')
        url=subprocess.check_output(['gh','pr','create','--repo',REPO,'--base',f'integration/{RUN}','--head',branch,
            '--title',f'Helper {e.upper()}: exclusive {RUN} results','--body-file',str(body)],text=True).strip()
        pr={'number':int(url.rsplit('/',1)[1]),'url':url}
    returns.append({'executor_id':e,'logical_worker':w,**pr})
    original=ROOT/'work/worker-trees'/RUN/w
    subprocess.run(['git','merge','--no-ff','-m',f'Reunite helper {e.upper()} results under original logical worker {w.upper()}',branch],cwd=original,check=True)
# The canonical seven manifests are now physically complete in their own trees.
for w in 'abcdefg':
    original=ROOT/'work/worker-trees'/RUN/w
    report=audit_worker(original/'manifests'/RUN/f'worker-{w}.json',original/'results'/RUN/f'worker-{w}')
    assert report['integrity_ok']and report['collection_finished']
write_json(ROOT/'preparation/current-runtime/helper-result-prs.json',returns)
print('All ten exclusive helper result branches audited and reunited under unchanged A–G ownership.',flush=True)
