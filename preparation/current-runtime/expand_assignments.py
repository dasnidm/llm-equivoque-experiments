"""Partition remaining frozen trial IDs into 17 disjoint executor schedules."""
import collections
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import digest, read_json, write_json, frozen_hashes
from equivoque.runner import now
RUN='equivoque-2026-10-09-v1'
frozen_hashes()
settings=read_json(ROOT/'work/coordinator/expansion-config.json')
path=ROOT/'preparation/current-runtime/executor-assignments-01.json'
assert not path.exists()
executors={}
terminal=set()
remaining=set()
for worker in 'abcdefg':
    tree=ROOT/'work/worker-trees'/RUN/worker
    manifest=read_json(tree/'manifests'/RUN/f'worker-{worker}.json')
    directory=tree/'results'/RUN/f'worker-{worker}'
    members=[worker]+[e for e,w in settings['helper_to_logical_worker'].items() if w==worker]
    for e in members:
        output=ROOT/'work/worker-trees'/RUN/e/'results'/RUN/f'worker-{worker}'
        ready=directory/'preflight-05/readiness.json' if e==worker else output/f'preflight-helper-{e}-01/readiness.json'
        assert read_json(ready)['ready']
        executors[e]={'logical_worker':worker,'readiness':str(ready),'trial_ids':[]}
    groups=collections.OrderedDict()
    for trial in manifest['trials']:
        slug=trial['trial_id'].replace('/','__')
        state_path=directory/'trials'/(slug+'.json')
        if state_path.exists():
            state=read_json(state_path)
            assert state['trial']==trial and not state.get('pending_turn')
            if state['status'] in ('complete','failed','interrupted'):
                terminal.add(trial['trial_id'])
                continue
            assert state['status']=='active'
            executors[worker]['trial_ids'].append(trial['trial_id'])
            remaining.add(trial['trial_id'])
            continue
        groups.setdefault((trial['configuration_id'],trial['case_id']),[]).append(trial['trial_id'])
        remaining.add(trial['trial_id'])
    # Keep as-yet-unstarted paired frames on the same executor. Manifest order
    # remains the order within each disjoint subsequence.
    for ids in groups.values():
        e=min(members,key=lambda x:(len(executors[x]['trial_ids']),members.index(x)))
        executors[e]['trial_ids'].extend(ids)
    positions={t['trial_id']:i for i,t in enumerate(manifest['trials'])}
    for e in members:executors[e]['trial_ids'].sort(key=positions.__getitem__)
flat=[t for e in executors.values() for t in e['trial_ids']]
scheduled={t['trial_id'] for t in read_json(ROOT/'manifests'/RUN/'schedule.json')['trials']}
assert len(flat)==len(set(flat)) and set(flat)==remaining
assert not terminal & remaining and terminal|remaining==scheduled and len(scheduled)==2100
write_json(path,{'run_id':RUN,'base_commit':settings['base_commit'],'created_at':now(),
    'authorization':settings['authorization'],'freeze_sha256':digest(ROOT/'protocol/freeze.json'),
    'terminal_trial_ids_before_expansion':sorted(terminal),'executors':dict(sorted(executors.items())),
    'allocation_note':'The original seven 300-trial manifests remain canonical ownership. Only remaining trial execution is subdivided; unstarted paired frames stay together when present on the same original shard. Existing partial trials stay with their original executor. No new or replacement evaluation IDs.'})
write_json(ROOT/'preparation/current-runtime/coordinator-launch-03.json',{
    'run_id':RUN,'base_commit':settings['base_commit'],'freeze_sha256':digest(ROOT/'protocol/freeze.json'),
    'executor_assignment_sha256':digest(path),'executors_ready':list('abcdefghijklmnopq'),
    'workers_ready':list('abcdefg'),'released_at':now(),
    'authorization':settings['authorization'],'maximum_concurrency':17,
    'expansion_stages':[17], 'immediate_expansion_authorization':'User explicitly requested immediate concurrency 17 because of time constraints; intermediate stages are omitted.','no_duplicate_trial_ids':True})
print(json.dumps({e:len(a['trial_ids']) for e,a in executors.items()},indent=2))
