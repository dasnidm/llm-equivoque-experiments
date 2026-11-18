"""Audit logical turns and every durable retry without loading journals wholesale."""
import json
from pathlib import Path
import sqlite3

from equivoque.transport import overrides, provider_schema
from exp7_pre.audit import audit_trial as audit_protocol
from exp7_pre.transport import digest
from exp7_persistent.transport import normalize_turn, validate_startup
from .queued_retry_transport import QueuedRetryTransport, retryable


class _AttemptIds:
    """Disk-backed temporary set; retries have no configured upper bound."""
    def __init__(self):
        self.db=sqlite3.connect('')
        self.db.execute('create table attempt_ids (id text primary key)')
    def __contains__(self,key):
        return self.db.execute('select 1 from attempt_ids where id=?',(key,)).fetchone() is not None
    def add(self,key):
        if not isinstance(key,str) or not key:raise ValueError('Invalid turn ID')
        self.db.execute('insert into attempt_ids (id) values (?)',(key,))
    def close(self):self.db.close()


def _rows(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            value = json.loads(line)
            if not isinstance(value,dict):
                raise ValueError('Malformed RPC row')
            yield value


def _files(entries):
    result={}
    for item in entries:
        p=Path(item['path'])
        if p.name in result or not p.is_file() or digest(p)!=item['sha256']:
            raise ValueError('Missing, duplicate, or changed evidence')
        result[p.name]=p
    return result


def _attempt(paths, record, trial, session, pid, first, system_path, catalog_path):
    sent=list(_rows(paths['rpc-sent.jsonl']))
    received=list(_rows(paths['rpc-received.jsonl']))
    events=list(_rows(paths['events.jsonl']))
    adapter=json.loads(paths['adapter.json'].read_text())
    methods=[m.get('method') for m in sent]
    wanted=['initialize','initialized','thread/start','turn/start'] if first else ['turn/start']
    if methods != wanted:
        raise ValueError('Unexpected process/thread startup sequence')
    if (adapter.get('transport') != QueuedRetryTransport.name or adapter.get('process_pid') != pid
            or adapter.get('thread_id') != session or adapter.get('command') != record.get('command')):
        raise ValueError('Session, process or adapter identity mismatch')
    command=record.get('command',[])
    expected=[command[0],'app-server','--stdio']+overrides(system_path,trial['effort']) if command else []
    tail=command[len(expected):]
    if not expected or command[:len(expected)] != expected:
        raise ValueError('CLI settings differ from frozen protocol')
    if catalog_path is None:
        if tail or adapter.get('catalog_sha256') is not None:
            raise ValueError('Unexpected catalog')
    elif (len(tail)!=2 or tail[0]!='-c' or not tail[1].startswith('model_catalog_json=')
          or json.loads(tail[1].split('=',1)[1])!=str(catalog_path)
          or adapter.get('catalog_sha256')!=digest(catalog_path)):
        raise ValueError('Catalog identity mismatch')
    ids=[m['id'] for m in sent if 'id' in m]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate RPC request ID')
    for request_id in ids:
        acknowledgements=[m for m in received if m.get('id')==request_id]
        if len(acknowledgements)!=1 or 'result' not in acknowledgements[0] or 'error' in acknowledgements[0]:
            raise ValueError('Missing or duplicate RPC acknowledgement')
    if any('id' in m and (m['id'] not in ids or 'method' in m) for m in received):
        raise ValueError('Unexpected RPC response or server request')
    start=sent[-1];params=start.get('params',{})
    if (params.get('threadId') != session or params.get('effort') != trial['effort']
            or params.get('approvalPolicy') != 'never' or params.get('turnTrigger') != 'exec'
            or params.get('input') != [{'type':'text','text':record['prompt'],'text_elements':[]}]
            or params.get('outputSchema') != provider_schema(record['schema'])):
        raise ValueError('Turn prompt, schema or session mismatch')
    if paths['prompt.txt'].read_text() != record['prompt']:
        raise ValueError('Saved prompt mismatch')
    effective_schema=provider_schema(record['schema'])
    if effective_schema is None:
        if 'schema.json' in paths:raise ValueError('Unexpected schema')
    elif 'schema.json' not in paths or json.loads(paths['schema.json'].read_text()) != effective_schema:
        raise ValueError('Saved schema mismatch')
    acknowledgements=[m for m in received if m.get('id') == start.get('id')]
    tid=adapter.get('turn_id')
    if len(acknowledgements)!=1 or acknowledgements[0].get('result',{}).get('turn',{}).get('id') != tid:
        raise ValueError('Turn acknowledgement mismatch')
    boundary=adapter.get('normalization_start_index')
    if type(boundary) is not int or boundary<0 or boundary>len(received):
        raise ValueError('Invalid startup boundary')
    if first:
        thread=sent[-2]
        tparams=thread.get('params',{})
        ack=[m for m in received if m.get('id') == thread.get('id')]
        effective=ack[0].get('result',{}) if len(ack)==1 else {}
        if (len(ack)!=1 or effective.get('thread',{}).get('id') != session
                or tparams.get('model') != trial['model'] or tparams.get('sandbox') != 'read-only'
                or tparams.get('approvalPolicy') != 'never' or tparams.get('dynamicTools') != []
                or tparams.get('ephemeral') is not False or tparams.get('allowProviderModelFallback') is not False
                or tparams.get('historyMode') != 'paginated'
                or tparams.get('config') != {k:json.loads(v) for k,v in
                    (entry.split('=',1) for entry in overrides(system_path,trial['effort'])[1::2])}
                or effective.get('model') != trial['model'] or effective.get('reasoningEffort') != trial['effort']
                or effective.get('cwd') != tparams.get('cwd') or effective.get('approvalPolicy') != 'never'
                or effective.get('sandbox',{}).get('type') != 'readOnly' or effective.get('instructionSources')):
            raise ValueError('Initial thread configuration mismatch')
        if boundary != next(i for i,m in enumerate(received) if m.get('id') == thread.get('id'))+1:
            raise ValueError('Startup boundary mismatch')
        validate_startup(received[:boundary],session)
    elif boundary != 0:
        raise ValueError('Unexpected startup on an existing session')
    normalized=normalize_turn(received[boundary:],session,tid)
    if normalized['events'] != events:
        raise ValueError('Event derivation mismatch')
    return tid, normalized, received[boundary:]


def audit_queued_trial(trial,protocol,state_path,freeze):
    result=audit_protocol(trial,protocol,state_path,freeze)
    path=Path(state_path)
    if not path.exists():return result
    state=json.loads(path.read_text())
    errors=result['errors']
    if state.get('transport')!=QueuedRetryTransport.name:errors.append('Wrong transport profile')
    expected_ids=[];session=state.get('session_id');pid=None;attempt_ids=_AttemptIds(); first=True
    for record in state.get('turns',[]):
        index=record.get('turn')
        try:
            if not record.get('ok'):break
            if record.get('session_id')!=session:raise ValueError('Session changed')
            if pid is None:pid=record.get('process_pid')
            if (type(pid) is not int or pid <= 0 or not isinstance(session,str) or not session
                    or record.get('process_pid')!=pid):raise ValueError('Process or session identity invalid')
            final=_files(record['raw_files'])
            system=final['subject-system.txt'];catalog=final.get('model-catalog.json')
            if system.read_text()!=protocol.system(trial):raise ValueError('System instruction mismatch')
            journals=[p for name,p in final.items() if name.endswith('-retries.journal.jsonl')]
            retries=record.get('retry_count',0)
            if type(retries) is not int or retries<0 or len(journals)!=(1 if retries else 0):
                raise ValueError('Retry journal missing or unexpected')
            seen=0
            if journals:
                for entry in _rows(journals[0]):
                    seen+=1
                    if entry.get('attempt')!=seen:raise ValueError('Retry sequence mismatch')
                    files=_files(entry['raw_files'])
                    tid,normalized,messages=_attempt(files,record,trial,session,pid,first,system,catalog)
                    first=False
                    if tid!=entry.get('turn_id') or tid in attempt_ids or not retryable(normalized,messages,session,tid):
                        raise ValueError('Retry was not a unique confirmed failed turn')
                    attempt_ids.add(tid)
                    sent=list(_rows(files['revert-sent.jsonl']));received=list(_rows(files['revert-received.jsonl']))
                    if ([x.get('method') for x in sent] != ['thread/revert','thread/turns/list']
                            or sent[0].get('params',{}).get('threadId')!=session
                            or sent[0].get('params',{}).get('beforeTurnId')!=tid):
                        raise ValueError('Retry rollback target mismatch')
                    acks=[x for x in received if x.get('id') == sent[0].get('id')]
                    lists=[x for x in received if x.get('id') == sent[1].get('id')]
                    if (len(acks)!=1 or acks[0].get('result',{}).get('thread',{}).get('id')!=session
                            or len(lists)!=1 or lists[0].get('result',{}).get('nextCursor') is not None
                            or [t.get('id') for t in lists[0].get('result',{}).get('data',[])]!=expected_ids):
                        raise ValueError('Rollback history mismatch')
            if seen!=retries:raise ValueError('Retry count does not match durable journal')
            tid,normalized,_=_attempt(final,record,trial,session,pid,first,system,catalog)
            first=False
            if tid in attempt_ids or tid != record.get('app_server_turn_id'):
                raise ValueError('Repeated or mismatched final turn ID')
            attempt_ids.add(tid)
            if any(record.get(k)!=v for k,v in normalized.items() if k!='events'):
                raise ValueError('Final result differs from RPC')
            expected_ids.append(tid)
        except (KeyError,ValueError,TypeError,IndexError,OSError,sqlite3.Error) as exc:
            errors.append(f'Turn {index}: {exc}')
    attempt_ids.close()
    result['integrity_ok']=not errors
    return result
