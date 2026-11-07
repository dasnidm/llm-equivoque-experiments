"""Offline tests: no native model calls or network access."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from .runner import CallBudget, run_trial, atomic_json
from .audit import audit_trial, audit_batch
from .transport import command_for, subject_directory, unexpected_items, failure_events, recovered_transport_notices, https_fallback_in_recovery, NativeTransport, digest, HOST_DISABLED_NOTICE


def phase(trial,turn):
    if turn<=3*trial['n_rounds']:
        return (turn-1)//3+1,(turn-1)%3+1
    return trial['n_rounds'],turn-3*trial['n_rounds']+3


def operate_step(trial,r,local,remaining,selection):
    if any(x not in remaining for x in selection): raise ValueError('not available')
    if len(selection)!=(2 if local==1 else 1) or len(set(selection))!=len(selection): raise ValueError('bad selection')
    return list(selection),'K'


def recovery_events():
    """Synthetic diagnostic with public endpoint, no live URLs or tokens."""
    base='unexpected status 403 Forbidden: Unknown error, url: wss://chatgpt.com/backend-api/codex/responses, cf-ray: 0123456789abcdef-LAX'
    return ([{'type':'error','message':f'Reconnecting... {i}/5 ({base})'} for i in range(2,6)]
            +[{'type':'item.completed','item':{'type':'error','message':'Falling back from WebSockets to HTTPS transport. '+base}}])


class StubProtocol:
    def system(self,trial): return 'Neutral system.'
    def prompt(self,trial,turn,feedback=None,remaining=None,rounds=None):
        return json.dumps({'turn':turn,'remaining':remaining,'feedback':feedback,'completed':[r['final'] for r in rounds]})
    def schema(self,turn,remaining=None,frame='cards',trial=None):
        return None if phase(trial,turn)[1] >= 3 else {'type':'object'}
    def parse_response(self,text,turn,remaining=None,frame='cards',trial=None):
        local=phase(trial,turn)[1]
        if local in (1,2): return json.loads(text)
        if text=='bad': raise ValueError('cannot classify')
        return {'value':text}


class FakeTransport:
    name='offline-fake'
    def __init__(self, bad_selection=False, bad_eval=False, fail_at=None, exception_at=None, changed_at=None):
        self.calls=[];self.bad_selection=bad_selection;self.bad_eval=bad_eval
        self.fail_at=fail_at;self.exception_at=exception_at;self.changed_at=changed_at
    def request(self,trial,prompt,schema,system,session_id,directory,turn):
        self.calls.append(turn)
        if self.exception_at==turn: raise RuntimeError('ambiguous native error')
        local=phase(trial,turn)[1]
        if local==1: text=json.dumps({'selection':['A','A'] if self.bad_selection else ['A','B']})
        elif local==2:text=json.dumps({'selection':'A'})
        elif self.bad_eval and turn==3:text='bad'
        else:text='answer'
        return {'ok':turn!=self.fail_at,'session_id':'changed' if turn==self.changed_at else 'session-1','text':text,'raw_files':[]}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name);self.proto=StubProtocol();self.freeze='a'*64
        self.root_patch=patch('exp7_pre.transport.ROOT',self.p/'checkout')
        self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.trial={'trial_id':'r/t','n_rounds':2,'order':['A','B','C','D'],'frame':'cards','model':'example','effort':'high'}
        self.proto_patch=patch.dict('sys.modules',{'exp7_pre.protocol':types.SimpleNamespace(phase=phase,operate_step=operate_step)})
        self.proto_patch.start();self.addCleanup(self.proto_patch.stop)
    def run_case(self,transport,limit=50):
        return run_trial(self.trial,self.proto,transport,self.p/'trial.json',self.p/'native',CallBudget(self.p/'budget.json','run',limit),self.freeze)
    def test_complete_and_audit(self):
        t=FakeTransport(bad_eval=True);s=self.run_case(t)
        self.assertEqual((s['status'],len(s['turns']),len(t.calls)),('complete',10,10))
        self.assertEqual(s['turns'][2]['parsed']['_parse'],'unparseable')
        self.assertEqual([r['final'] for r in s['rounds']],['A','A'])
        a=audit_trial(self.trial,self.proto,self.p/'trial.json',self.freeze)
        self.assertTrue(a['integrity_ok'],a['errors'])
        self.assertTrue(audit_batch([self.trial],self.proto,[self.p/'trial.json'],self.freeze)['integrity_ok'])
        self.run_case(t);self.assertEqual(len(t.calls),10)
    def test_invalid_selection_stops_and_does_not_replay(self):
        t=FakeTransport(bad_selection=True);s=self.run_case(t)
        self.assertEqual(s['status'],'failed');self.assertEqual(t.calls,[1])
        self.run_case(t);self.assertEqual(t.calls,[1])
    def test_uncertain_exception_cannot_replay(self):
        t=FakeTransport(exception_at=2);s=self.run_case(t)
        self.assertEqual(s['status'],'interrupted');self.assertEqual(s['pending_turn']['turn'],2)
        self.run_case(t);self.assertEqual(t.calls,[1,2])
    def test_existing_pending_is_interrupted(self):
        t=FakeTransport();self.run_case(t)
        p=self.p/'trial.json';s=json.loads(p.read_text());s.update(status='active',pending_turn={'turn':11});atomic_json(p,s)
        self.assertEqual(self.run_case(t)['status'],'interrupted');self.assertEqual(len(t.calls),10)
    def test_transport_failure_and_session_swap(self):
        t=FakeTransport(changed_at=2);s=self.run_case(t)
        self.assertEqual(s['status'],'failed');self.assertIn('session ID',s['error'])
    def test_budget_is_strict_and_global(self):
        budget=CallBudget(self.p/'concurrent.json','run',5)
        with ThreadPoolExecutor(max_workers=12) as pool:
            tickets=list(pool.map(lambda i: budget.reserve(str(i),1),range(20)))
        self.assertEqual(sorted(x for x in tickets if x is not None),[1,2,3,4,5])
        self.assertEqual(json.loads((self.p/'concurrent.json').read_text())['used'],5)
        with self.assertRaises(ValueError):CallBudget(self.p/'concurrent.json','run',6).reserve('x',1)
    def test_budget_exhaustion_no_native_call(self):
        t=FakeTransport();s=self.run_case(t,limit=3)
        self.assertEqual(s['status'],'budget_exhausted');self.assertEqual(t.calls,[1,2,3])
    def test_optional_output_schema(self):
        trial={'model':'m','effort':'high'}
        self.assertNotIn('--output-schema',command_for(trial,'/tmp/sys','/tmp/subject',None,None))
        self.assertIn('--output-schema',command_for(trial,'/tmp/sys','/tmp/subject','thread','/tmp/schema'))
    def test_subject_cwd_is_opaque_stable_and_not_raw_directory(self):
        raw=self.p/'results'/'equivoque-exp7-calibration'/'arm-K'/'gpt-6-astra'/'uuid'
        first=subject_directory(raw);second=subject_directory(raw)
        other=subject_directory(raw.parent/'another-uuid')
        self.assertEqual(first,second);self.assertNotEqual(first,other)
        self.assertEqual(first.parent.parent.name,'native-study')
        self.assertEqual(first.name,'subject');self.assertNotEqual(first,raw/'subject')
        for label in ('equivoque','exp7','calibration','arm-K','gpt-6-astra'):
            self.assertNotIn(label,str(first))
        self.assertEqual(len(first.parent.name),24)
    def test_unknown_and_collaboration_items_fail_closed(self):
        events=[{'type':'item.completed','item':{'type':'agent_message'}},
                {'type':'item.completed','item':{'type':'reasoning'}},
                {'type':'item.completed','item':{'type':'collab_tool_call'}},
                {'type':'item.started','item':{'type':'function_call'}},
                {'type':'item.updated','item':{'type':'new_unrecognized_tool'}}]
        self.assertEqual(len(unexpected_items(events)),3)
    def test_hash_and_assignment_mismatch_block_resume(self):
        self.run_case(FakeTransport())
        with self.assertRaises(ValueError):
            run_trial(self.trial,self.proto,FakeTransport(),self.p/'trial.json',self.p/'native',CallBudget(self.p/'budget.json','run',50),'b'*64)
    def test_only_exact_preturn_host_notice_is_allowed(self):
        notice={'type':'item.completed','item':{'type':'error','message':HOST_DISABLED_NOTICE}}
        started={'type':'turn.started'}
        thread={'type':'thread.started','thread_id':'s'}
        self.assertEqual(unexpected_items([thread,notice,started]),[])
        self.assertEqual(len(unexpected_items([notice,started])),1)
        self.assertEqual(len(unexpected_items([thread,notice])),1)
        self.assertEqual(len(unexpected_items([started,notice])),1)
        self.assertEqual(len(unexpected_items([thread,notice,dict(notice),started])),1)
        other={'type':'item.completed','item':{'type':'error','message':'Different failure'}}
        self.assertEqual(len(unexpected_items([other,started])),1)
    def test_recovery_requires_valid_diagnostics_and_successful_turn(self):
        import copy
        baseline=[{'type':'thread.started','thread_id':'s'}, {'type':'turn.started'}, *recovery_events(),
                  {'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
                  {'type':'turn.completed','usage':{'input_tokens':1}}]
        self.assertEqual(len(recovered_transport_notices(baseline)),5)
        self.assertTrue(https_fallback_in_recovery(baseline))
        self.assertEqual(unexpected_items(baseline),[]);self.assertEqual(failure_events(baseline),[])
        bad=[]
        bad.append([e for e in baseline if e['type']!='turn.completed'])
        bad.append([e for e in baseline if e.get('item',{}).get('type')!='agent_message'])
        bad.append(baseline+[{'type':'error','message':'unrecognized error'}])
        bad.append(baseline+[{'type':'item.completed','item':{'type':'collab_tool_call'}}])
        bad.append(baseline+[{'type':'turn.failed'}])
        bad.append(baseline+[{'type':'item.completed','item':{'type':'agent_message','text':'duplicate'}}])
        invalid_counter=copy.deepcopy(baseline);invalid_counter[2]['message']=invalid_counter[2]['message'].replace('2/5','6/5');bad.append(invalid_counter)
        empty_reason=copy.deepcopy(baseline);empty_reason[3]['message']='Reconnecting... 1/5 (   )';bad.append(empty_reason)
        empty_fallback=copy.deepcopy(baseline);empty_fallback[6]['item']['message']='Falling back from WebSockets to HTTPS transport. ';bad.append(empty_fallback)
        after_end=baseline[:2]+baseline[-2:]+baseline[2:-2];bad.append(after_end)
        bad.append([e for e in baseline if e['type']!='turn.started'])
        for events in bad:
            self.assertEqual(recovered_transport_notices(events),[])
            self.assertTrue(unexpected_items(events) or failure_events(events))
    def test_websocket_recovery_does_not_require_contiguous_counter_values(self):
        # A native stream can reconnect 2/5 only or 2/5 .. 5/5 and then
        # complete over the same transport, with no HTTPS fallback item.
        for n in (1,2,3,4):
            events=[{'type':'thread.started','thread_id':'s'},{'type':'turn.started'},
                    *recovery_events()[:n],
                    {'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
                    {'type':'turn.completed','usage':{'input_tokens':1}}]
            self.assertEqual(len(recovered_transport_notices(events)),n)
            self.assertFalse(https_fallback_in_recovery(events))
            self.assertEqual(unexpected_items(events),[]);self.assertEqual(failure_events(events),[])
        skipped=[{'type':'thread.started','thread_id':'s'},{'type':'turn.started'},
                 recovery_events()[0],recovery_events()[2],
                 {'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
                 {'type':'turn.completed','usage':{'input_tokens':1}}]
        self.assertEqual(len(recovered_transport_notices(skipped)),2)
        self.assertFalse(failure_events(skipped))
    def test_reconnect_cycles_can_restart_and_follow_fallback(self):
        retry=recovery_events()
        prefix=[{'type':'thread.started','thread_id':'s'},{'type':'turn.started'}]
        suffix=[{'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
                {'type':'turn.completed','usage':{'input_tokens':1}}]
        # Historical native CLI sessions exhibit a restarted retry cycle.
        for indexes in ([0,1,2,0,1,2,3],[0,0,1,2,3]):
            events=prefix+[retry[i] for i in indexes]+suffix
            self.assertEqual(len(recovered_transport_notices(events)),len(indexes))
            self.assertFalse(https_fallback_in_recovery(events))
            self.assertFalse(unexpected_items(events));self.assertFalse(failure_events(events))
            fallback=prefix+[retry[i] for i in indexes]+[retry[4]]+suffix
            self.assertEqual(len(recovered_transport_notices(fallback)),len(indexes)+1)
            self.assertTrue(https_fallback_in_recovery(fallback))
        incomplete=prefix+[retry[0],retry[1],retry[0],retry[1],retry[4]]+suffix
        self.assertEqual(len(recovered_transport_notices(incomplete)),5)
        after_fallback=prefix+retry+[{'type':'error','message':'Reconnecting... 1/5 (stream disconnected before completion: provider error)'}]+suffix
        self.assertEqual(len(recovered_transport_notices(after_fallback)),6)
        self.assertTrue(https_fallback_in_recovery(after_fallback))
    def test_recovery_does_not_rescue_nonzero_exit_or_changed_session(self):
        class FakePopen:
            returncode_to_use=0
            def __init__(self,cmd,stdin,stdout,stderr,text,cwd,start_new_session):
                self.out=stdout;self.returncode=self.returncode_to_use
            def communicate(self,prompt,timeout):
                events=[{'type':'thread.started','thread_id':'other'}, {'type':'turn.started'}, *recovery_events(),
                        {'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
                        {'type':'turn.completed','usage':{'input_tokens':1}}]
                for e in events:self.out.write(json.dumps(e)+'\n')
            def wait(self):return self.returncode
        trial={'model':'m','effort':'high'}
        with patch('exp7_pre.transport.subprocess.Popen',FakePopen):
            result=NativeTransport().request(trial,'p',None,'s','expected',self.p/'native-1',1)
            self.assertFalse(result['ok']);self.assertFalse(result['https_fallback'])
            FakePopen.returncode_to_use=1
            result=NativeTransport().request(trial,'p',None,'s',None,self.p/'native-2',1)
            self.assertFalse(result['ok']);self.assertFalse(result['https_fallback'])
    def test_failed_changed_session_retains_integrity_with_recovery_bundle(self):
        class FakePopen:
            def __init__(self,cmd,stdin,stdout,stderr,text,cwd,start_new_session):
                self.out=stdout;self.returncode=0
            def communicate(self,prompt,timeout):
                n=json.loads(prompt)['turn']
                session='changed' if n==2 else 'original'
                text=json.dumps({'selection':['A','B']}) if n==1 else json.dumps({'selection':'A'})
                events=[{'type':'thread.started','thread_id':session}, {'type':'turn.started'}]
                if n==2:events+=recovery_events()
                events += [{'type':'item.completed','item':{'type':'agent_message','text':text}},
                           {'type':'turn.completed','usage':{'input_tokens':1}}]
                for e in events:self.out.write(json.dumps(e)+'\n')
            def wait(self):return self.returncode
        with patch('exp7_pre.transport.subprocess.Popen',FakePopen):
            s=self.run_case(NativeTransport())
        self.assertEqual(s['status'],'failed')
        self.assertFalse(s['turns'][-1]['https_fallback']);self.assertEqual(s['turns'][-1]['recovered_transport_events'],5)
        checked=audit_trial(self.trial,self.proto,self.p/'trial.json',self.freeze)
        self.assertTrue(checked['integrity_ok'],checked['errors'])
    def test_native_raw_events_and_audit_offline(self):
        cwds=[]
        class FakePopen:
            def __init__(self,cmd,stdin,stdout,stderr,text,cwd,start_new_session):
                self.out=stdout;self.returncode=0;cwds.append(Path(cwd))
            def communicate(self,prompt,timeout):
                n=json.loads(prompt)['turn'];local=phase({'n_rounds':2},n)[1]
                text=json.dumps({'selection':['A','B']}) if local==1 else json.dumps({'selection':'A'}) if local==2 else 'answer'
                events=[{'type':'thread.started','thread_id':'native-fake'},
                        {'type':'turn.started'},
                        {'type':'item.completed','item':{'type':'agent_message','text':text}},
                        {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
                if n==5:events.insert(1,{'type':'context.compacted'})
                if n==7:events[2:2]=recovery_events()
                if n==8:events[2:2]=recovery_events()[:2]
                for e in events:self.out.write(json.dumps(e)+'\n')
            def wait(self):return self.returncode
        with patch('exp7_pre.transport.subprocess.Popen',FakePopen):
            t=NativeTransport();s=self.run_case(t)
        self.assertEqual(s['status'],'complete')
        a=audit_trial(self.trial,self.proto,self.p/'trial.json',self.freeze)
        self.assertTrue(a['integrity_ok'],a['errors']);self.assertEqual(a['compactions'],[{'turn':5,'count':1}])
        self.assertEqual(len(set(cwds)),1)
        self.assertEqual(cwds[0],subject_directory(self.p/'native'/s['scratch_id']))
        self.assertTrue(all(str(x['path']).startswith(str(self.p/'native')) for t in s['turns'] for x in t['raw_files']))
        self.assertTrue(s['turns'][6]['https_fallback']);self.assertEqual(s['turns'][6]['recovered_transport_events'],5)
        self.assertFalse(s['turns'][7]['https_fallback']);self.assertEqual(s['turns'][7]['recovered_transport_events'],2)
        # Rehashing edited raw bytes is insufficient if state/text no longer match.
        state=json.loads((self.p/'trial.json').read_text());record=state['turns'][2]
        events=next(x for x in record['raw_files'] if x['path'].endswith('events.jsonl'))
        p=Path(events['path']);p.write_text(p.read_text().replace('answer','altered'));events['sha256']=digest(p)
        atomic_json(self.p/'trial.json',state)
        bad=audit_trial(self.trial,self.proto,self.p/'trial.json',self.freeze)
        self.assertFalse(bad['integrity_ok']);self.assertTrue(any('native message mismatch' in x for x in bad['errors']))


class RealProtocolFakeTransport:
    name='offline-fake-real-protocol'
    def __init__(self,protocol): self.protocol=protocol
    def request(self,trial,prompt,schema,system,session_id,directory,turn):
        from .protocol import phase, operate_step
        r,local=phase(trial,turn);arm=trial['arm'];names=self.protocol.choice_names('cards',trial)
        remaining,_=operate_step(trial,r,1,trial['order'],['A','B'])
        if local==1:
            chosen=[names['A'],names['B']]
            text=', '.join(chosen) if arm=='F' else json.dumps({'selection':chosen},ensure_ascii=False)
        elif local==2:
            chosen=names[remaining[0]]
            text=chosen if arm=='F' else json.dumps({'selection':chosen},ensure_ascii=False)
        elif local==3 and arm=='R' and r<10:text='{"ack":"ok"}'
        elif local in (3,6,7):
            text=('Freedom: 100\nImpact: 100\nCounterfactual: yes' if arm in ('N','F') else '{"freedom":100,"impact":100,"counterfactual":"yes"}')
        elif local==4:
            key='rule' if trial['probe_arm']=='explanation' else 'acknowledgment'
            text='observed' if arm in ('N','F') else json.dumps({key:'observed'})
        else:
            rows={f'policy_{i}':{'first_feedback':'uncertain','second_feedback':'uncertain','final':'uncertain'} for i in range(1,5)}
            text=('\n'.join(f'Policy {i}: first_feedback = uncertain; second_feedback = uncertain; final = uncertain' for i in range(1,5)) if arm in ('N','F') else json.dumps(rows))
        # Check the launcher sends precisely the per-turn condition.
        assert (schema is None)==(arm=='F' or (arm=='N' and local>=3) or (arm=='JS' and local in (3,6,7)))
        assert system==self.protocol.system(trial)
        return {'ok':True,'session_id':session_id or 'offline-'+trial['trial_id'],'text':text,'raw_files':[]}


class RealProtocolIntegrationTests(unittest.TestCase):
    def test_all_arms_and_conditions(self):
        from .protocol import PreProtocol, make_probe_policies
        proto=PreProtocol()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);budget=CallBudget(root/'budget.json','offline',8*3*34)
            assignments,paths=[],[]
            for arm in ['A','J','P','K','JS','N','R','F']:
                for kind in ['obj','seq','unforced']:
                    trial={'trial_id':arm+'-'+kind,'n_rounds':10,'model':'example','effort':'high',
                           'frame':'cards','order':['A','B','C','D'],'arm':arm,'kind':kind,
                           'targets':['A']*10 if kind=='obj' else list('ABCDABCDAB'),
                           'stage_rule':'DD','probe_arm':'neutral',
                           'probe_policies':make_probe_policies(['A','B','C','D'],123),'prompt_variant':'p1'}
                    path=root/'trials'/(trial['trial_id']+'.json');transport=RealProtocolFakeTransport(proto)
                    result=run_trial(trial,proto,transport,path,root/'native',budget,'b'*64)
                    self.assertEqual(result['status'],'complete',f'{arm} {kind}: {result.get("error")}')
                    self.assertEqual(len(result['turns']),34)
                    self.assertEqual(len(result['rounds'][-1]['route']),2)
                    assignments.append(trial);paths.append(path)
            audit=audit_batch(assignments,proto,paths,'b'*64)
            self.assertTrue(audit['integrity_ok'],audit)
            self.assertEqual(audit['complete'],24)


if __name__=='__main__':unittest.main()
