"""Reconstruct stimuli, targets and paths; verify every archived native byte."""
import collections
import json
from pathlib import Path
from equivoque.core import digest, operate, read_json
from .protocol import SequenceProtocol, phase


def audit_worker(manifest_path, directory, allow_simulation=False):
    manifest, directory = read_json(manifest_path),Path(directory)
    protocol = SequenceProtocol()
    errors, sessions, counts = [],[],collections.Counter()
    invocations, measurements, compactions = 0,0,[]
    expected = {t['trial_id']:t for t in manifest['trials']}
    seen = set()
    for path in sorted((directory/'trials').glob('*.json')):
        s = read_json(path); t = s['trial']; tid=t['trial_id']
        def error(message): errors.append(tid+': '+message)
        if tid not in expected or t!=expected.get(tid) or tid in seen:
            error('Unassigned, changed or duplicate trial')
            continue
        seen.add(tid);counts[s['status']]+=1
        invocations+=len(s['turns'])+int(s.get('pending_turn') is not None)
        if s['transport']!='codex-native' and not allow_simulation: error('Simulation is not evaluation')
        if s['protocol_sha256']!=digest(protocol.path): error('Protocol hash mismatch')
        if s.get('session_id'): sessions.append(s['session_id'])
        rounds = [{'remaining':list(t['order']),'route':''} for _ in t['targets']]
        journal = [json.loads(line) for line in path.with_suffix('.journal.jsonl').read_text().splitlines()]
        requests = [j for j in journal if j['type']=='request_checkpoint']
        responses = [j for j in journal if j['type']=='response_checkpoint']
        if len(responses)!=len(s['turns']) or len(requests)!=len(s['turns'])+int(s.get('pending_turn') is not None):
            error('Durable journal length mismatch')
        for i, record in enumerate(s['turns'],1):
            r, local=phase(t,i); current=rounds[r-1]
            feedback=current['route'][-1] if current['route'] else None
            prompt=protocol.prompt(t,i,feedback,current['remaining'])
            schema=protocol.schema(i,current['remaining'],t['frame'],t)
            if record['turn']!=i or record['prompt']!=prompt or record['schema']!=schema:
                error('Stimulus or schema mismatch at turn '+str(i))
            if i<=len(requests) and any(requests[i-1].get(k)!=record.get(k) for k in ('turn','prompt','schema','session_id_before','requested_at')):
                error('Request journal mismatch')
            if i<=len(responses) and any(responses[i-1].get(k)!=record.get(k) for k in ('turn','text','session_id','ok','received_at','raw_files')):
                error('Response journal mismatch')
            if record.get('ok'):
                if record['session_id']!=s['session_id'] or record.get('tool_events') or record.get('metadata_fallback'):
                    error('Native continuity or isolation mismatch')
                try:
                    parsed=protocol.parse_response(record['text'],i,current['remaining'],t['frame'],t)
                    if parsed!=record.get('parsed'): error('Parsed response mismatch')
                    if local in (1,2):
                        selection=parsed['selection'] if local==1 else [parsed['selection']]
                        current['remaining'],op=operate(current['remaining'],selection,t['targets'][r-1])
                        current['route']+=op
                    elif local==3: measurements+=1
                except (ValueError,TypeError) as e:
                    if s['status']=='complete' or 'parsed' in record: error('Invalid response '+str(e))
            if any('compact' in e.get('type','').lower() for e in record.get('events',[])):
                compactions.append({'trial_id':tid,'turn':i})
        for i,current in enumerate(rounds):
            saved=s['rounds'][i]
            if saved['remaining']!=current['remaining'] or saved['route']!=current['route'] or saved['target']!=t['targets'][i]:
                error('Saved engine state mismatch')
            if len(current['route'])==2 and current['remaining']!=[t['targets'][i]]:
                error('Round-specific force invariant failed')
        if s['status']=='complete' and (len(s['turns'])!=3*t['n_rounds']+3 or s.get('pending_turn')):
            error('Incomplete session labeled complete')
        if s['transport']=='codex-native':
            archive=directory/'native-raw'/tid.replace('/','__')
            files=read_json(archive/'files.json')['files']
            listed={f['path']:f['sha256'] for f in files}
            actual={str(p.relative_to(directory)):digest(p) for p in archive.iterdir() if p.is_file() and p.name!='files.json'}
            if listed!=actual: error('Native archive file inventory/hash mismatch')
            if (archive/'subject-system.txt').read_text()!=protocol.data['system']: error('Native system mismatch')
            for record in s['turns']:
                for f in record.get('raw_files',[]):
                    if listed.get(f['path'])!=f['sha256']: error('Historical native hash mismatch')
                n=record['turn']
                events=[json.loads(line) for line in (archive/f'turn-{n:02d}.events.jsonl').read_text().splitlines()]
                if events!=record['events'] or (archive/f'turn-{n:02d}.stderr.txt').read_text()!=record['stderr']:
                    error('Native event/stderr bytes mismatch')
                if read_json(archive/f'turn-{n:02d}.schema.json')!=record['provider_schema']:
                    error('Effective native schema mismatch')
    if len(sessions)!=len(set(sessions)):errors.append('Duplicate native session within worker')
    return {'run_id':manifest['run_id'],'worker_id':manifest['worker_id'],'integrity_ok':not errors,
            'assigned':len(expected),'attempted':len(seen),'unattempted':len(expected)-len(seen),
            'counts':dict(counts),'subject_invocations':invocations,'valid_measurements':measurements,
            'session_ids':sessions,'compaction_events':compactions,'errors':errors}
