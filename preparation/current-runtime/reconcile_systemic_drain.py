"""Reconcile observed existing-call exits without replay or new inference."""
import datetime
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import Protocol,read_json,write_json,digest,frozen_hashes,operate
from equivoque.runner import now,append_event
from equivoque.transport import overrides,provider_schema
RUN='equivoque-2026-10-09-v1'
REPORT=ROOT/'preparation/current-runtime/systemic-reconciliation-01.json'
assert not REPORT.exists()
drain=read_json(ROOT/'preparation/current-runtime/systemic-drain-01.json')
assert drain['status']=='all_existing_calls_drained'
frozen_hashes();protocol=Protocol();reports=[]
for e,evidence in drain['workers'].items():
    w=evidence['logical_worker'];path=Path(evidence['state_path']);state=read_json(path)
    request=state['pending_turn'];trial=state['trial'];turn=request['turn']
    assert trial['trial_id']==evidence['trial_id']and turn==evidence['turn']
    scratch=ROOT/'work/worker-trees'/RUN/w/'work'/RUN/w/state['scratch_id']
    raw=scratch/f'turn-{turn:02d}.events.jsonl';stderr_path=scratch/f'turn-{turn:02d}.stderr.txt'
    events=[];malformed=0
    for line in raw.read_text().splitlines():
        try:events.append(json.loads(line))
        except json.JSONDecodeError:malformed+=1
    stderr=stderr_path.read_text()
    ids=[x['thread_id']for x in events if x.get('type')=='thread.started']
    messages=[x['item']['text']for x in events if x.get('type')=='item.completed'and x.get('item',{}).get('type')=='agent_message']
    usage=[x.get('usage')for x in events if x.get('type')=='turn.completed']
    tools=[x.get('item',{}).get('type')for x in events if x.get('type')in ('item.started','item.completed')and x.get('item',{}).get('type')in ('command_execution','mcp_tool_call','web_search','file_change','collab_agent_tool_call')]
    fallback='fallback metadata'in stderr.lower()or any('fallback metadata'in str(x).lower()for x in events)
    next_id=ids[-1]if ids else state['session_id']
    timeout=evidence['external_deadline_kill']or (evidence['observed_exit_code']==-9)
    if evidence['observed_exit_code']==0 and usage:
        assert raw.stat().st_mtime<=evidence['deadline_unix'],'No late completed response may be accepted'
    feedback=state['route'][-1]if state['route']else None
    assert request['prompt']==protocol.prompt(trial,turn,feedback,state['remaining'])
    assert request['schema']==protocol.schema(turn,state['remaining'],trial['frame'])
    schema=scratch/f'turn-{turn:02d}.schema.json';system=scratch/'subject-system.txt'
    assert read_json(schema)==provider_schema(request['schema'])
    assert system.read_text()==protocol.data['system']
    command=['codex','exec']+(['resume']if state['session_id']else[])
    command+=['--ignore-user-config','--ignore-rules','--skip-git-repo-check','--json','--model',trial['model'],'--output-schema',str(schema)]
    command+=overrides(system,trial['effort'])
    command+=[state['session_id'],'-']if state['session_id']else['--sandbox','read-only','-C',str(scratch/'subject'),'-']
    if evidence['command']:assert evidence['command']==command
    ok=(evidence['observed_exit_code']==0 and not timeout and len(messages)==1 and bool(usage)and bool(next_id)and not tools and not malformed and not fallback and (not state['session_id']or next_id==state['session_id']))
    received=datetime.datetime.fromtimestamp(raw.stat().st_mtime,datetime.timezone.utc).isoformat()if ok else evidence['exit_observed_at']
    record={**request,'ok':ok,'session_id':next_id,'text':messages[-1]if messages else'',
        'events':events,'stderr':stderr,'command':command,'exit_code':evidence['observed_exit_code'],
        'timeout':timeout,'duration_seconds':None,'usage':usage[-1]if usage else None,
        'tool_events':tools,'metadata_fallback':fallback,'malformed_event_lines':malformed,
        'provider_schema':provider_schema(request['schema']),
        'provider_schema_note':'uniqueItems omitted; canonical duplicate-choice validation remains mandatory.',
        'received_at':received,'reconciled_at':now(),'command_reconstructed':True,
        'recovered_from_durable_events':ok,'exit_code_observed_from_proc':True,
        'external_deadline_watchdog':evidence['external_deadline_kill'],
        'reconciliation_note':'Existing request only; no new invocation or replay. Parent paused to stop new calls after multiple actual timeouts. Child exit observed from /proc; watchdog enforced the 300-second requested_at bound. Exact original monotonic duration is unavailable. Successful received_at is final event-file mtime; failures use observed child-exit time.'}
    journal=[json.loads(x)for x in path.with_suffix('.journal.jsonl').read_text().splitlines()]
    assert len(journal)==len(state['turns'])*2+1
    append_event(path.with_suffix('.journal.jsonl'),{'type':'response_checkpoint',**record})
    state['pending_turn']=None;state['turns'].append(record);state['session_id']=next_id
    if not ok:state.update(status='failed',error='Transport/session/tool-isolation failure',ended_at=received)
    else:
        try:
            parsed=protocol.parse_response(record['text'],turn,state['remaining'],trial['frame']);record['parsed']=parsed
            if turn<3:
                selected=parsed['selection'];state['remaining'],op=operate(state['remaining'],selected if turn==1 else[selected],trial['target']);state['route']+=op
            if turn==4:state.update(status='complete',ended_at=received)
        except(ValueError,TypeError)as error:state.update(status='failed',error=f'Response validation: {error}',ended_at=received)
    write_json(path,state)
    saved=path.parents[1]/f'systemic-drain-01-executor-{e}'/path.stem;saved.mkdir(parents=True)
    for source in (raw,stderr_path,schema,system):shutil.copyfile(source,saved/source.name)
    reports.append({'executor_id':e,'trial_id':trial['trial_id'],'turn':turn,'status_after':state['status'],
                    'exit_code':evidence['observed_exit_code'],'timeout':timeout,'model_invocations_added':0})
    print(e,turn,state['status'],evidence['observed_exit_code'],flush=True)
write_json(REPORT,{'reconciled_at':now(),'model_invocations_added':0,'workers':reports,
    'note':'Known existing call exits and durable streams reconciled. Failed/timeout trials stay terminal and are never replaced; partial states have no uncertain pending request.'})
