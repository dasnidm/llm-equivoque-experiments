"""Read-only replay and integrity audit for pre-experiment conversations."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from .transport import digest, command_for, subject_directory, unexpected_items, failure_events, recovered_transport_notices, https_fallback_in_recovery
from equivoque.transport import provider_schema


def audit_trial(expected_trial, protocol, state_path, expected_freeze_sha256):
    from .protocol import phase, operate_step
    path=Path(state_path)
    if not path.exists():
        return {'status':'unstarted','integrity_ok':True,'errors':[],'turns':0,'session_id':None,'tickets':[]}
    state=json.loads(path.read_text())
    errors=[]
    def err(text): errors.append(text)
    if state.get('trial')!=expected_trial: err('Assignment mismatch')
    if state.get('freeze_sha256')!=expected_freeze_sha256: err('Frozen configuration mismatch')
    if state.get('system_sha256')!=hashlib.sha256(protocol.system(expected_trial).encode()).hexdigest(): err('System instruction mismatch')
    if state.get('status')=='complete' and (state.get('pending_turn') is not None or len(state.get('turns',[]))!=3*expected_trial['n_rounds']+4):
        err('Complete state has pending or wrong turn count')
    rounds=[{'round':i,'order':list(expected_trial['order']),'remaining':list(expected_trial['order']),
             'route':'','selections':[],'final':None} for i in range(1,expected_trial['n_rounds']+1)]
    prev_id=None
    tickets=[]
    compactions=[]
    for i,record in enumerate(state.get('turns',[]),1):
        if record.get('turn')!=i: err(f'Turn {i}: sequence mismatch'); break
        r,local=phase(expected_trial,i)
        current=rounds[r-1]
        feedback=current['route'][-1] if current['route'] else None
        prompt=protocol.prompt(expected_trial,i,feedback,current['remaining'],rounds=rounds)
        schema=protocol.schema(i,current['remaining'],expected_trial['frame'],expected_trial)
        if record.get('round')!=r or record.get('local_turn')!=local: err(f'Turn {i}: phase mismatch')
        if record.get('prompt')!=prompt or record.get('schema')!=schema: err(f'Turn {i}: stimulus mismatch')
        if record.get('session_id_before')!=prev_id: err(f'Turn {i}: previous session mismatch')
        ticket=record.get('budget_ticket')
        if not isinstance(ticket,int): err(f'Turn {i}: missing ticket')
        else: tickets.append(ticket)
        files=record.get('raw_files',[])
        if state.get('transport')=='codex-native-optional-schema' and not files: err(f'Turn {i}: missing raw files')
        for item in files:
            p=Path(item['path'])
            if not p.is_file() or digest(p)!=item['sha256']: err(f'Turn {i}: raw file hash mismatch {p.name}')
        if state.get('transport')=='codex-native-optional-schema' and files and all(Path(x['path']).is_file() for x in files):
            named={Path(x['path']).name:Path(x['path']) for x in files}
            required={'subject-system.txt','prompt.txt','events.jsonl','stderr.txt'}
            if not required<=set(named) or len(named)!=len(files): err(f'Turn {i}: incomplete or duplicate native inventory')
            if 'prompt.txt' not in named or named['prompt.txt'].read_text()!=prompt: err(f'Turn {i}: raw prompt mismatch')
            if 'subject-system.txt' not in named or named['subject-system.txt'].read_text()!=protocol.system(expected_trial): err(f'Turn {i}: raw system mismatch')
            if schema is None:
                if 'schema.json' in named or '--output-schema' in record.get('command',[]): err(f'Turn {i}: unexpected output schema')
            else:
                if 'schema.json' not in named or '--output-schema' not in record.get('command',[]): err(f'Turn {i}: required output schema missing')
                elif json.loads(named['schema.json'].read_text())!=provider_schema(schema): err(f'Turn {i}: provider schema mismatch')
            if 'events.jsonl' in named:
                try:
                    events=[json.loads(line) for line in named['events.jsonl'].read_text().splitlines()]
                    messages=[e['item']['text'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
                    if record.get('ok') and messages!=[record.get('text')]: err(f'Turn {i}: native message mismatch')
                    ids=[e['thread_id'] for e in events if e.get('type')=='thread.started']
                    usage=[e.get('usage') for e in events if e.get('type')=='turn.completed']
                    forbidden=unexpected_items(events)
                    fallback=('stderr.txt' in named and 'fallback metadata' in named['stderr.txt'].read_text().lower()) or any('fallback metadata' in str(e).lower() for e in events)
                    nc=sum('compact' in str(e.get('type','')).lower() for e in events)
                    if nc: compactions.append({'turn':i,'count':nc})
                    if record.get('compaction_events')!=nc: err(f'Turn {i}: compaction count mismatch')
                    recovery=recovered_transport_notices(events)
                    if record.get('recovered_transport_events')!=len(recovery) or record.get('https_fallback')!=bool(https_fallback_in_recovery(events) and record.get('ok')): err(f'Turn {i}: recovery metadata mismatch')
                    if record.get('ok') and (not usage or forbidden or failure_events(events) or fallback or record.get('exit_code')!=0 or record.get('timeout')): err(f'Turn {i}: native completion or isolation failed')
                    if record.get('ok') and (ids[-1] if ids else prev_id)!=record.get('session_id'): err(f'Turn {i}: raw session ID mismatch')
                    if record.get('ok') and usage and record.get('usage')!=usage[-1]: err(f'Turn {i}: usage mismatch')
                    if required<=set(named):
                        cmd=command_for(expected_trial,named['subject-system.txt'],subject_directory(named['events.jsonl'].parent.parent),prev_id,named.get('schema.json'))
                        if cmd!=record.get('command'): err(f'Turn {i}: native command mismatch')
                except (ValueError,KeyError,TypeError): err(f'Turn {i}: malformed native events')
        if not record.get('ok'):
            if state.get('status')=='complete': err(f'Turn {i}: failed native request in complete state')
            break
        if not record.get('session_id') or (prev_id is not None and prev_id!=record['session_id']): err(f'Turn {i}: session mismatch')
        prev_id=record.get('session_id')
        try:
            parsed=protocol.parse_response(record['text'],i,current['remaining'],expected_trial['frame'],expected_trial)
            if not isinstance(parsed,dict): raise ValueError('Parsed result must be a dictionary')
            if local in (1,2):
                selection=parsed['selection'] if local==1 else [parsed['selection']]
                remaining,operation=operate_step(expected_trial,r,local,current['remaining'],selection)
                current['remaining']=list(remaining);current['route']+=operation;current['selections'].append(selection)
                if local==2: current['final']=remaining[0]
        except (ValueError,TypeError,KeyError) as exc:
            if local in (1,2):
                if state.get('status')!='failed': err(f'Turn {i}: bad selection in nonfailed session')
                break
            parsed={'_parse':'unparseable','error':str(exc)}
        if record.get('parsed')!=parsed: err(f'Turn {i}: parser output mismatch')
    if rounds!=state.get('rounds'): err('Replayed round paths differ')
    if state.get('session_id')!=prev_id and state.get('status')=='complete': err('Final session ID mismatch')
    return {'status':state['status'],'integrity_ok':not errors,'errors':errors,
            'turns':len(state.get('turns',[])),'session_id':state.get('session_id'),'tickets':tickets,'compactions':compactions}


def audit_batch(assignments, protocol, state_paths, expected_freeze_sha256):
    if len(assignments)!=len(state_paths): raise ValueError('Assignment and state path counts differ')
    rows=[audit_trial(t,protocol,p,expected_freeze_sha256) for t,p in zip(assignments,state_paths)]
    sessions=[r['session_id'] for r in rows if r['session_id']]
    tickets=[i for r in rows for i in r['tickets']]
    errors=[]
    if len(set(sessions))!=len(sessions): errors.append('Session ID reused across trials')
    if len(set(tickets))!=len(tickets): errors.append('Call-budget ticket reused')
    return {'assigned':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
            'integrity_ok':not errors and all(r['integrity_ok'] for r in rows),
            'complete':sum(r['status']=='complete' for r in rows),
            'errors':errors,'trials':rows}
