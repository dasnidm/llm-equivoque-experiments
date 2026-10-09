"""Release only unstarted IDs and known-safe partial native sessions."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import read_json,write_json,digest,frozen_hashes
from equivoque.runner import now
RUN='equivoque-2026-10-09-v1'
frozen_hashes();prior=read_json(ROOT/'preparation/current-runtime/executor-assignments-01.json')
service=ROOT/'preparation/current-runtime/service-preflight-01/readiness.json'
assert read_json(service)['ready']
path=ROOT/'preparation/current-runtime/executor-assignments-02.json'
assert not path.exists()
entries={};remaining=set();terminal=set();partials=[]
for e,a in prior['executors'].items():
    w=a['logical_worker'];tree=ROOT/'work/worker-trees'/RUN/e
    output=tree/'results'/RUN/f'worker-{w}'
    ready=output/f'preflight-service-resume-01-executor-{e}/readiness.json'
    r=read_json(ready);assert r['ready']and r['shared_live_service_sha256']==digest(service)
    selected=[]
    for trial_id in a['trial_ids']:
        state_path=output/'trials'/(trial_id.replace('/','__')+'.json')
        if state_path.exists():
            s=read_json(state_path);assert not s.get('pending_turn')
            if s['status']in ('complete','failed','interrupted'):terminal.add(trial_id);continue
            assert s['status']=='active';partials.append(trial_id)
        selected.append(trial_id);assert trial_id not in remaining;remaining.add(trial_id)
    entries[e]={'logical_worker':w,'readiness':str(ready),'trial_ids':selected}
terminal.update(prior['terminal_trial_ids_before_expansion'])
scheduled={t['trial_id']for t in read_json(ROOT/'manifests'/RUN/'schedule.json')['trials']}
assert remaining|terminal==scheduled and not remaining&terminal
write_json(path,{'run_id':RUN,'base_commit':prior['base_commit'],'created_at':now(),
    'executors':entries,'terminal_trial_ids_before_resumption':sorted(terminal),
    'partial_trial_ids':partials,'freeze_sha256':prior['freeze_sha256'],
    'note':'Same exclusive A–Q ownership/subsequence. Only unstarted IDs and known-safe next turns are eligible. Seven failed IDs remain terminal. No uncertain request, new trial or replacement is included.'})
write_json(ROOT/'preparation/current-runtime/coordinator-launch-04.json',{'run_id':RUN,
    'base_commit':prior['base_commit'],'freeze_sha256':prior['freeze_sha256'],
    'executor_assignment_sha256':digest(path),'shared_live_service_sha256':digest(service),
    'workers_ready':list('abcdefg'),'executors_ready':list('abcdefghijklmnopq'),'released_at':now(),
    'maximum_authorized_executor_count':17,'initial_active_trial_limit':2,
    'reason':'Restore collection after actual 300-second timeouts, keeping seventeen executors and unchanged frozen subjects; use measured service concurrency and stop new trials on further systemic failure.'})
controls=ROOT/'work/coordinator/resume-02-controls';controls.mkdir()
write_json(controls/'limit.json',{'limit':2,'updated_at':now()})
write_json(controls/'queue.json',{'queue':[],'active':[]})
print('Eligible IDs:',len(remaining),'known partial sessions:',len(partials),'terminal:',len(terminal),flush=True)
