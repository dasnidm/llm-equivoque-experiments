"""Publish all captured results, including coherent live-state/raw snapshots."""
import collections
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import read_json,write_json,digest,frozen_hashes
from equivoque.runner import now
RUN='equivoque-2026-10-09-v1'
REPO='dasnidm/llm-equivoque-experiments'
EPOCH='live-01'
lock=(ROOT/'work/coordinator/publication.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX)
registry=ROOT/'preparation/current-runtime'/f'live-push-{EPOCH}.json'
assert not registry.exists(),'An existing snapshot must not be silently overwritten'
assignment=read_json(ROOT/'preparation/current-runtime/executor-assignments-01.json')['executors']
frozen_hashes()
started=now();records={};seen=set();global_counts=collections.Counter()

def consistent_journal(path,state):
    expected=len(state['turns'])*2+int(state.get('pending_turn')is not None)
    for _ in range(100):
        data=path.read_bytes()if path.exists()else b''
        lines=data.splitlines(keepends=True)
        try:events=[json.loads(line)for line in lines[:expected]]
        except json.JSONDecodeError:events=[]
        if len(events)==expected:
            assert [e['type']for e in events]==['request_checkpoint','response_checkpoint']*len(state['turns'])+(['request_checkpoint']if state.get('pending_turn')else[])
            for turn,event in zip(state['turns'],events[1::2]):
                assert {k:v for k,v in turn.items()if k!='parsed'}=={k:v for k,v in event.items()if k!='type'}
            if state.get('pending_turn'):
                assert {k:v for k,v in events[-1].items()if k!='type'}==state['pending_turn']
            return b''.join(lines[:expected]),data
        time.sleep(.01)
    raise RuntimeError('Could not capture coherent durable checkpoint prefix: '+str(path))

# Read all trees first: network pushes do not extend the snapshot capture interval.
for e,a in assignment.items():
    w=a['logical_worker'];tree=ROOT/'work/worker-trees'/RUN/e
    directory=tree/'results'/RUN/f'worker-{w}'
    snapshot=directory/f'snapshot-{EPOCH}-executor-{e}'
    assert not snapshot.exists();snapshot.mkdir(parents=True)
    states=[];counts=collections.Counter();terminal_paths=[];raw_files=0
    for path in sorted((directory/'trials').glob('*.json')):
        payload=path.read_bytes();state=json.loads(payload);trial_id=state['trial']['trial_id']
        assert trial_id not in seen,'Duplicate trial ownership';seen.add(trial_id)
        counts[state['status']]+=1;global_counts[state['status']]+=1
        journal,full=consistent_journal(path.with_suffix('.journal.jsonl'),state)
        captured=snapshot/'trials'/path.name;captured.parent.mkdir(exist_ok=True)
        captured.write_bytes(payload);captured.with_suffix('.journal.jsonl').write_bytes(journal)
        if journal!=full:(snapshot/'trials'/(path.stem+'.journal-at-read.jsonl')).write_bytes(full)
        original=ROOT/'work/worker-trees'/RUN/w/'work'/RUN/w/state['scratch_id']
        raw_directory=snapshot/'native-raw'/path.stem
        raw_directory.mkdir(parents=True)
        source_files=[original/'subject-system.txt',*original.glob('turn-*.events.jsonl'),
                      *original.glob('turn-*.stderr.txt'),*original.glob('turn-*.schema.json')]
        hashes={}
        for source in source_files:
            if not source.exists():continue
            data=source.read_bytes();(raw_directory/source.name).write_bytes(data)
            hashes[source.name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                'ends_with_newline':data.endswith(b'\n')}
            raw_files+=1
        states.append({'trial_id':trial_id,'status':state['status'],'turns_recorded':len(state['turns']),
            'pending_turn':state.get('pending_turn',{}).get('turn')if state.get('pending_turn')else None,
            'state_sha256':hashlib.sha256(payload).hexdigest(),
            'journal_prefix_sha256':hashlib.sha256(journal).hexdigest(),'native_raw':hashes})
        if state['status']in ('complete','failed','interrupted'):
            terminal_paths.extend([str(path.relative_to(tree)),str(path.with_suffix('.journal.jsonl').relative_to(tree))])
    write_json(snapshot/'SNAPSHOT.json',{'run_id':RUN,'executor_id':e,'logical_worker':w,
        'capture_started_at':started,'captured_at':now(),'counts':dict(counts),'records':states,
        'note':'Read-only snapshot during ongoing collection. State and exact journal prefix match. Pending native streams can be incomplete. Snapshot records are excluded from primary trial-file discovery and do not authorize replay. No model call was added.'})
    paths=terminal_paths+[str(snapshot.relative_to(tree))]
    for name in ('provenance.json',f'executor-{e}-provenance.json'):
        if (directory/name).exists():paths.append(str((directory/name).relative_to(tree)))
    for ready in directory.glob('preflight*/readiness.json'):
        if read_json(ready).get('ended_at'):paths.append(str(ready.parent.relative_to(tree)))
    paths.extend(str(p.relative_to(tree))for p in directory.glob('recovery-*'))
    records[e]={'logical_worker':w,'counts':dict(counts),'captured_trials':len(states),
                'native_raw_files':raw_files,'paths':paths,'snapshot_path':str(snapshot.relative_to(tree))}
captured_at=now()
for e,record in records.items():
    tree=ROOT/'work/worker-trees'/RUN/e
    subprocess.run(['git','add','--',*record.pop('paths')],cwd=tree,check=True)
    subprocess.run(['git','commit','-m',f'Executor {e.upper()}: publish all captured results and live raw snapshot'],cwd=tree,check=True,stdout=subprocess.DEVNULL)
    branch=f'worker/{RUN}/{e}'
    subprocess.run(['git','push','origin',branch],cwd=tree,check=True,stdout=subprocess.DEVNULL)
    record['branch']=branch
    record['commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
    record['url']=f'https://github.com/{REPO}/tree/{record["commit"]}/results/{RUN}/worker-{record["logical_worker"]}'
    print(json.dumps({'executor':e,'pushed':True,'counts':record['counts']}),flush=True)

branch=f'snapshot/{RUN}/{EPOCH}'
tree=ROOT/'work/snapshot-trees'/RUN/EPOCH
assert not tree.exists()
subprocess.run(['git','worktree','add','-b',branch,str(tree),'HEAD'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
for e in assignment:
    subprocess.run(['git','merge','--no-ff','-m',f'Capture executor {e.upper()} current results in incomplete snapshot',
                    records[e]['branch']],cwd=tree,check=True,stdout=subprocess.DEVNULL)
snapshot_record={'run_id':RUN,'capture_started_at':started,'capture_finished_at':captured_at,
    'counts':dict(global_counts),'captured_trial_ids':len(seen),'executors':records,
    'snapshot_branch':branch,'snapshot_url':f'https://github.com/{REPO}/tree/{branch}',
    'collection_incomplete':True,'model_invocations_added':0,
    'note':'User requested all results so far to be pushed. Original seventeen result branches and this separate combined snapshot are published. Main and the final integration/analysis gate remain unchanged. Active states/raw streams are explicitly snapshot-only; no uncertain request is replayed.'}
write_json(tree/'LIVE_SNAPSHOT.json',snapshot_record)
(tree/'LIVE_SNAPSHOT.md').write_text(f'# Incomplete live data snapshot\n\nRun: `{RUN}`. Captured between {started} and {captured_at}.\n\nStatuses captured: {json.dumps(dict(global_counts),sort_keys=True)} across {len(seen)} unique attempted evaluation IDs. The full planned roster remains 2,100 trials. Seventeen executors continue collection.\n\nAll current terminal records, preflight/recovery evidence and coherent live-state/native-raw snapshots are retained under `results/{RUN}/worker-*/`. Pending streams can be incomplete. `snapshot-live-01-executor-*/` files are historical snapshot evidence, excluded from evaluation-file discovery and never an instruction to replay. No result analysis was run on this incomplete snapshot.\n\nThe original result branches were also updated. See `LIVE_SNAPSHOT.json` for capture accounting, per-executor commit links and raw-file inventories. Main is unchanged, and full integration/analysis waits for collection completion.\n')
subprocess.run(['git','add','LIVE_SNAPSHOT.md','LIVE_SNAPSHOT.json'],cwd=tree,check=True)
subprocess.run(['git','commit','-m','Describe incomplete combined live data snapshot'],cwd=tree,check=True,stdout=subprocess.DEVNULL)
subprocess.run(['git','push','-u','origin',branch],cwd=tree,check=True,stdout=subprocess.DEVNULL)
snapshot_record['snapshot_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
write_json(registry,snapshot_record)
shutil.copyfile(Path(__file__),ROOT/'preparation/current-runtime/push_live_snapshot.py')
subprocess.run(['git','add',str(registry),'preparation/current-runtime/push_live_snapshot.py'],cwd=ROOT,check=True)
subprocess.run(['git','commit','-m','Record complete live snapshot publication across seventeen branches'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
subprocess.run(['git','push','origin',f'integration/{RUN}'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
print(json.dumps({'published':True,'counts':dict(global_counts),'snapshot_url':snapshot_record['snapshot_url']}),flush=True)
