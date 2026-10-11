"""Audit assigned IDs, exact stimuli, sessions, raw files, and objective scores."""
import json
from pathlib import Path
from collections import Counter
from equivoque.core import ROOT, digest, read_json, write_json
from equivoque.transport import provider_schema
from .protocol import CONFIG, PROMPTS, PilotProtocol, frozen_hashes


def audit_worker(manifest, directory, allow_unattempted=False):
    directory=Path(directory)
    protocol=PilotProtocol()
    expected={t['trial_id']:t for t in manifest['trials']}
    records={}
    sessions=[]
    raw_count=0
    for path in (directory/'trials').glob('*.json'):
        s=read_json(path); tid=s['trial']['trial_id']
        if tid in records or tid not in expected or s['trial']!=expected[tid]:
            raise ValueError('Duplicate/unassigned/mismatched task')
        if s['protocol_sha256']!=digest(PROMPTS):
            raise ValueError('Protocol mismatch')
        if s['request']['prompt']!=protocol.prompt(expected[tid]) or s['request']['schema']!=protocol.schema(frame=s['trial']['frame']) or s['request']['session_id_before'] is not None:
            raise ValueError('Prompt/schema/session differs')
        journal=[json.loads(line) for line in path.with_suffix('.journal.jsonl').read_text().splitlines()]
        if journal[0]!={'type':'request_checkpoint',**s['request']}:
            raise ValueError('Request journal differs')
        result=s.get('result')
        if result:
            if len(journal)!=2 or journal[1]!={'type':'response_checkpoint',**result}:
                raise ValueError('Response journal differs')
            if result['provider_schema']!=provider_schema(s['request']['schema']):
                raise ValueError('Provider schema differs')
            for item in result.get('raw_files',[]):
                p=directory/item['path']
                if digest(p)!=item['sha256']:
                    raise ValueError('Native raw file changed')
                raw_count+=1
                if p.name.endswith('.events.jsonl'):
                    events=[json.loads(line) for line in p.read_text().splitlines()]
                    if events!=result['events']:
                        raise ValueError('Native events differ')
                if p.name.endswith('.stderr.txt') and p.read_text()!=result['stderr']:
                    raise ValueError('Native stderr differs')
                if p.name.endswith('.schema.json') and read_json(p)!=result['provider_schema']:
                    raise ValueError('Native schema differs')
                if p.name=='subject-system.txt' and p.read_text()!=protocol.data['system']:
                    raise ValueError('Native system differs')
            if result.get('session_id'): sessions.append(result['session_id'])
        if s['status']=='complete':
            if not result or not result['ok'] or result['timeout'] or result['tool_events'] or result['metadata_fallback']:
                raise ValueError('Invalid completed native turn')
            if protocol.parse(result['text'],s['trial']['frame'])!=s['response'] or protocol.score(s['trial'],s['response'])!=s['correct']:
                raise ValueError('Response/score changed')
            events=result['events']
            sessions_in_events=[e['thread_id'] for e in events if e.get('type')=='thread.started']
            answers=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
            usage=[e.get('usage') for e in events if e.get('type')=='turn.completed']
            if sessions_in_events!=[result['session_id']] or answers!=[result['text']] or usage!=[result['usage']]:
                raise ValueError('Native final/session/usage differs')
            command=result['command']
            if command[command.index('--model')+1]!=s['trial']['model'] or 'model_reasoning_effort='+json.dumps(s['trial']['effort']) not in command or 'resume' in command:
                raise ValueError('Requested native configuration differs')
        elif s['status'] not in ('failed','interrupted'):
            raise ValueError('Active/unknown task at final audit')
        records[tid]=s
    if len(sessions)!=len(set(sessions)):
        raise ValueError('Session reused')
    if not allow_unattempted and len(records)!=len(expected):
        raise ValueError('Unattempted tasks remain')
    report={'worker_id':manifest['worker_id'],'assigned':len(expected),'attempted':len(records),
            'unattempted':len(expected)-len(records),'counts':dict(Counter(s['status'] for s in records.values())),
            'evaluation_invocations':len(records),'sessions':sessions,'raw_files_verified':raw_count,'passed':True}
    return report,list(records.values())


def union(output):
    frozen_hashes()
    config=read_json(CONFIG)
    reports=[]; states=[]
    for w in config['workers']:
        manifest=read_json(ROOT/'manifests'/config['run_id']/f'worker-{w}.json')
        directory=ROOT/'results'/config['run_id']/f'worker-{w}'
        report,records=audit_worker(manifest,directory)
        write_json(directory/'audit.json',report)
        reports.append(report); states.extend(records)
    tids=[s['trial']['trial_id'] for s in states]
    sessions=[x for r in reports for x in r['sessions']]
    scheduled={t['trial_id'] for t in read_json(ROOT/'manifests'/config['run_id']/'schedule.json')['trials']}
    if len(tids)!=len(set(tids)) or set(tids)!=scheduled or len(sessions)!=len(set(sessions)):
        raise ValueError('Union IDs/sessions differ')
    report={'run_id':config['run_id'],'assigned':len(scheduled),'attempted':len(states),
            'counts':dict(Counter(s['status'] for s in states)), 'evaluation_invocations':len(states),
            'unique_sessions':len(sessions),'raw_files_verified':sum(r['raw_files_verified'] for r in reports),
            'workers':reports,'passed':True}
    write_json(output,report)
    return report,states
