"""Offline launch freeze/preflight checks; fake CLI and no network calls."""
import json
import fcntl
from collections import Counter
from concurrent.futures import Future
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import launch
from .protocol import ARMS
from .transport import NativeTransport


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.manifest=self.root/'manifests'/'study'/'schedule.json'
        self.manifest.parent.mkdir(parents=True)
        self.profile={'model':'example','effort':'high'}
        self.doc={'run_id':'study','call_cap':34,'profiles':[self.profile],'purpose':'calibration','trials':[]}
        self.manifest.write_text(json.dumps(self.doc))
        self.source=self.root/'source.txt';self.source.write_text('v1')
        for patcher in [patch.object(launch,'ROOT',self.root),
                        patch('exp7_pre.transport.ROOT',self.root/'checkout'),
                        patch.object(launch,'source_paths',lambda:[self.source]),
                        patch.object(launch.subprocess,'check_output',return_value='test-cli 1.0\n')]:
            patcher.start();self.addCleanup(patcher.stop)

    def test_source_and_frozen_archive_immutability(self):
        p=launch.freeze(self.manifest)
        self.assertEqual(launch.verify(self.manifest)[1],launch.sha(p))
        self.source.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'Frozen file changed'):launch.verify(self.manifest)
        self.source.write_text('v1')
        (p.parent/'frozen-source'/'source.txt').write_text('tampered archive')
        with self.assertRaisesRegex(ValueError,'Frozen archive changed'):launch.verify(self.manifest)

    def test_changed_manifest_fails_freeze_verification(self):
        launch.freeze(self.manifest)
        self.doc['call_cap']=35;self.manifest.write_text(json.dumps(self.doc))
        with self.assertRaises(ValueError):launch.verify(self.manifest)

    def test_preflight_schema_on_then_off_same_session(self):
        calls=[];launch.freeze(self.manifest)
        class FakePopen:
            def __init__(self,cmd,stdin,stdout,stderr,text,cwd,start_new_session):
                self.out=stdout;self.returncode=0;calls.append(cmd)
            def communicate(self,prompt,timeout):
                text='{"ok":true}' if '"ok":true' in prompt else 'READY'
                events=[{'type':'thread.started','thread_id':'same'},
                        {'type':'turn.started'},
                        {'type':'item.completed','item':{'type':'agent_message','text':text}},
                        {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
                for e in events:self.out.write(json.dumps(e)+'\n')
            def wait(self):return self.returncode
        with patch('exp7_pre.transport.subprocess.Popen',FakePopen):
            self.assertTrue(launch.preflight(self.manifest,self.root/'preflight',1))
        self.assertEqual(len(calls),2)
        self.assertIn('--output-schema',calls[0]);self.assertNotIn('--output-schema',calls[1])
        self.assertIn('resume',calls[1]);self.assertIn('same',calls[1])
        support=json.loads((self.root/'preflight'/'support.json').read_text())
        self.assertTrue(support['passed']);self.assertEqual(support['profiles'],[self.profile])
        self.assertTrue(launch.verify_support(self.root/'preflight'/'support.json',self.doc)['passed'])
        records_path=self.root/'preflight'/'records.json';support_path=self.root/'preflight'/'support.json'
        records=json.loads(records_path.read_text())
        event=next(x for x in records[1]['raw_files'] if x['path'].endswith('events.jsonl'))
        event_file=Path(event['path']);original=event_file.read_text();event_file.write_text(original.replace('READY','WRONG'))
        event['sha256']=launch.sha(event_file);records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        with self.assertRaisesRegex(ValueError,'metadata differs'):launch.verify_support(support_path,self.doc)
        event_file.write_text(original);event['sha256']=launch.sha(event_file)
        records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        self.assertTrue(launch.verify_support(support_path,self.doc)['passed'])
        command=records[0]['command'];idx=next(i for i,x in enumerate(command) if x.startswith('model_reasoning_effort='));old_command=command[idx]
        command[idx]='model_reasoning_effort="low"';records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        with self.assertRaisesRegex(ValueError,'native command'):launch.verify_support(support_path,self.doc)
        command[idx]=old_command;records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        extra=json.dumps({'type':'item.updated','item':{'type':'collab_tool_call'}})+'\n'
        event_file.write_text(original+extra);event['sha256']=launch.sha(event_file);records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        with self.assertRaisesRegex(ValueError,'metadata differs'):launch.verify_support(support_path,self.doc)
        event_file.write_text(original);event['sha256']=launch.sha(event_file);records_path.write_text(json.dumps(records));support['records_sha256']=launch.sha(records_path);support_path.write_text(json.dumps(support))
        raw=Path(records[0]['raw_files'][-1]['path']);raw.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'evidence changed'):launch.verify_support(self.root/'preflight'/'support.json',self.doc)
        with self.assertRaises(ValueError):launch.preflight(self.manifest,self.root/'preflight',1)

    def test_preflight_fails_closed_on_transport_error(self):
        launch.freeze(self.manifest)
        class FakeTransport:
            def __init__(self,timeout):pass
            def request(self,*args):return {'ok':False,'session_id':None,'text':'','events':[],'stderr':'','raw_files':[]}
        with patch.object(launch,'NativeTransport',FakeTransport):
            self.assertFalse(launch.preflight(self.manifest,self.root/'failure',1))
        support=json.loads((self.root/'failure'/'support.json').read_text())
        self.assertFalse(support['passed'])

    def test_quality_gate_uses_parseability_not_response_direction(self):
        from .analyze import FIELDS
        eval_manifest={'run_id':'study','profiles':[self.profile],'cases':[{'structure_sha256':'eval'}]}
        cal_manifest={'run_id':'study-calibration','purpose':'calibration','profiles':[self.profile],
                      'cases':[{'structure_sha256':'cal'}],
                      'trials':[{'trial_id':f'{arm}-{kind}','arm':arm,'kind':kind}
                                for arm in ARMS for kind in ('obj','seq','unforced')]}
        eval_out=self.root/'results'/'study';eval_out.mkdir(parents=True)
        cal_out=self.root/'results'/'study-calibration';(cal_out/'states').mkdir(parents=True)
        freeze={'files':{'source.txt':'abc'},'manifest':'manifests/cal/schedule.json'}
        (eval_out/'freeze.json').write_text(json.dumps(freeze));(cal_out/'freeze.json').write_text(json.dumps(freeze))
        def write_records(impact,cf,bad_arm=None):
            for t in cal_manifest['trials']:
                records=[]
                for turn in [*range(3,31,3),32,33,34]:
                    fields={'freedom':'valid','impact':'valid','counterfactual':'valid'}
                    if t['arm']==bad_arm:fields['impact']='unparseable'
                    parsed={'freedom':100,'impact':impact,'counterfactual':cf,'_parse':{'fields':fields}}
                    if turn==32:
                        parsed={'_parse':{'fields':{f'policy_{i}.{f}':'uncertain' for i in range(1,5) for f in FIELDS}}}
                    records.append({'turn':turn,'parsed':parsed})
                (cal_out/'states'/(t['trial_id']+'.json')).write_text(json.dumps({'turns':records}))
        audit={'integrity_ok':True,'complete':24,'assigned':24}
        with patch.object(launch,'verify',return_value=(cal_manifest,'digest')),patch.object(launch,'audit_batch',return_value=audit):
            write_records(1,'no');a=launch.verify_calibration(cal_out/'audit.json',eval_manifest)
            write_records(100,'yes');b=launch.verify_calibration(cal_out/'audit.json',eval_manifest)
            self.assertTrue(a['passed']);self.assertEqual(a,b)
            write_records(1,'no',bad_arm='F')
            with self.assertRaisesRegex(ValueError,'parser/format gate failed'):
                launch.verify_calibration(cal_out/'audit.json',eval_manifest)
            incomplete={**cal_manifest,'trials':[dict(t) for t in cal_manifest['trials']]}
            next(t for t in incomplete['trials'] if t['arm']=='F')['arm']='N'
            with patch.object(launch,'verify',return_value=(incomplete,'digest')):
                with self.assertRaisesRegex(ValueError,'cover each arm and procedure'):
                    launch.verify_calibration(cal_out/'audit.json',eval_manifest)

    def test_one_global_launcher_lock_per_run(self):
        out=self.root/'results'/'study';out.mkdir(parents=True)
        args=SimpleNamespace(manifest=self.manifest)
        with patch.object(launch,'verify',return_value=(self.doc,'sha')),patch.object(launch,'run_locked',return_value='ok'):
            with (out/'.launch.lock').open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):launch.run(args)
            self.assertEqual(launch.run(args),'ok')

    def test_status_separates_records_reservations_and_pending(self):
        out=self.root/'results'/'study';(out/'states').mkdir(parents=True)
        doc={**self.doc,'trials':[{'trial_id':'t0'},{'trial_id':'t1'}]}
        self.manifest.write_text(json.dumps(doc))
        (out/'states'/'t0.json').write_text(json.dumps({'status':'interrupted','turns':[{},{}],'pending_turn':{'turn':3}}))
        (out/'budget.json').write_text(json.dumps({'run_id':'study','limit':34,'used':3}))
        result=launch.status(self.manifest)
        self.assertEqual(result['recorded_responses'],2);self.assertEqual(result['reserved_attempts'],3)
        self.assertEqual(result['pending_requests'],1);self.assertNotIn('logical_invocations',result)

    def test_failed_completion_batch_does_not_submit_more(self):
        out=self.root/'results'/'study';out.mkdir(parents=True)
        support=self.root/'support.json';support.write_text('{}')
        rows=[{'trial_id':f't{i}','model':'m','arm':'A','kind':'obj'} for i in range(4)]
        doc={**self.doc,'trials':rows}
        args=SimpleNamespace(manifest=self.manifest,support=support,calibration_audit=None,
                             timeout=1,concurrency=2,per_model_concurrency=2,wall_hours=1,max_sessions=None)
        started=[]
        def fake_trial(t,*args):
            started.append(t['trial_id'])
            return {'status':'failed' if t['trial_id']=='t1' else 'complete','turns':[],
                    'error':'selection failed'}
        class FakePool:
            def __init__(self,max_workers):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def submit(self,fn,*args):
                f=Future();f.set_result(fn(*args));return f
        def fake_wait(active,timeout,return_when):return list(active),set()
        with patch.object(launch,'verify',return_value=(doc,'a'*64)),patch.object(launch,'verify_support'),\
             patch.object(launch,'run_trial',side_effect=fake_trial),patch.object(launch,'ThreadPoolExecutor',FakePool),\
             patch.object(launch,'wait',side_effect=fake_wait),patch.object(launch,'status'):
            launch.run_locked(args)
        self.assertEqual(started,['t0','t1'])

    def test_per_model_cap_and_first_eligible_without_head_of_line_block(self):
        out=self.root/'results'/'study';out.mkdir(parents=True)
        support=self.root/'support.json';support.write_text('{}')
        ids=[('A0','A'),('A1','A'),('A2','A'),('B0','B'),('B1','B'),('C0','C')]
        rows=[{'trial_id':i,'model':m,'effort':'high' if i!='A1' else 'low','arm':'A','kind':'obj'} for i,m in ids]
        doc={**self.doc,'trials':rows}
        args=SimpleNamespace(manifest=self.manifest,support=support,calibration_audit=None,
                             timeout=1,concurrency=4,per_model_concurrency=2,wall_hours=1,max_sessions=None)
        started=[];submitted=[];observed_counts=[]
        class FakePool:
            def __init__(self,max_workers):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def submit(self,fn,*args):
                t=args[0];f=Future();f.trial=t;started.append(t['trial_id']);submitted.append(f)
                live=Counter(x.trial['model'] for x in submitted if not x.done())
                observed_counts.append(dict(live))
                return f
        nwait=[0]
        def fake_wait(active,timeout,return_when):
            order=['B0','A0'];target=order[nwait[0]] if nwait[0]<2 else None;nwait[0]+=1
            done=[f for f,t in active.items() if target is None or t['trial_id']==target]
            for f in done:f.set_result({'status':'complete','turns':[]})
            return done,set(active)-set(done)
        with patch.object(launch,'verify',return_value=(doc,'a'*64)),patch.object(launch,'verify_support'),\
             patch.object(launch,'ThreadPoolExecutor',FakePool),patch.object(launch,'wait',side_effect=fake_wait),\
             patch.object(launch,'status'):
            launch.run_locked(args)
        self.assertEqual(started,['A0','A1','B0','B1','C0','A2'])
        self.assertTrue(all(sum(c.values())<=4 and max(c.values())<=2 for c in observed_counts))
        metadata=json.loads(next((out/'launches').glob('*.json')).read_text())
        self.assertEqual(metadata['concurrency'],4);self.assertEqual(metadata['per_model_concurrency'],2)

    def test_resume_skips_terminal_states_and_never_replaces_failed(self):
        out=self.root/'results'/'study';(out/'states').mkdir(parents=True)
        support=self.root/'support.json';support.write_text('{}')
        rows=[{'trial_id':s,'model':'m','arm':'A','kind':'obj'}
              for s in ('complete','failed','interrupted','budget_exhausted','active','unstarted')]
        for s in ('complete','failed','interrupted','budget_exhausted','active'):
            (out/'states'/(s+'.json')).write_text(json.dumps({'status':s}))
        doc={**self.doc,'trials':rows}
        args=SimpleNamespace(manifest=self.manifest,support=support,calibration_audit=None,
                             timeout=1,concurrency=2,per_model_concurrency=2,wall_hours=1,max_sessions=None)
        started=[]
        def fake_trial(t,*args):started.append(t['trial_id']);return {'status':'complete','turns':[]}
        class FakePool:
            def __init__(self,max_workers):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def submit(self,fn,*args):f=Future();f.set_result(fn(*args));return f
        def fake_wait(active,timeout,return_when):return list(active),set()
        with patch.object(launch,'verify',return_value=(doc,'a'*64)),patch.object(launch,'verify_support'),\
             patch.object(launch,'run_trial',side_effect=fake_trial),patch.object(launch,'ThreadPoolExecutor',FakePool),\
             patch.object(launch,'wait',side_effect=fake_wait),patch.object(launch,'status'):
            launch.run_locked(args)
        self.assertEqual(started,['active','unstarted'])
        for s in ('complete','failed','interrupted','budget_exhausted'):
            self.assertEqual(json.loads((out/'states'/(s+'.json')).read_text())['status'],s)

    def test_later_uncertain_pending_blocks_all_new_submissions(self):
        out=self.root/'results'/'study';(out/'states').mkdir(parents=True)
        support=self.root/'support.json';support.write_text('{}')
        rows=[{'trial_id':s,'model':'m','arm':'A','kind':'obj'} for s in ('first_unstarted','later_pending','last_unstarted')]
        record={'status':'interrupted','pending_turn':{'turn':3,'reason':'transport uncertain'}}
        state_path=out/'states'/'later_pending.json';state_path.write_text(json.dumps(record))
        original=state_path.read_bytes();doc={**self.doc,'trials':rows}
        args=SimpleNamespace(manifest=self.manifest,support=support,calibration_audit=None,
                             timeout=1,concurrency=8,per_model_concurrency=2,wall_hours=1,max_sessions=None)
        with patch.object(launch,'verify',return_value=(doc,'a'*64)),patch.object(launch,'verify_support'),\
             patch.object(launch,'run_trial') as launch_trial,patch.object(launch,'ThreadPoolExecutor') as pool:
            with self.assertRaisesRegex(ValueError,'Uncertain pending request in later_pending'):
                launch.run_locked(args)
            launch_trial.assert_not_called();pool.assert_not_called()
        self.assertEqual(state_path.read_bytes(),original)
        self.assertFalse((out/'states'/'first_unstarted.json').exists())
        self.assertFalse((out/'budget.json').exists())

    def test_cli_defaults_and_invalid_per_model_caps(self):
        argv=['exp7_pre.launch','run','--manifest',str(self.manifest),'--support',str(self.root/'support.json')]
        with patch.object(sys,'argv',argv),patch.object(launch,'run') as call:
            launch.main()
            self.assertEqual(call.call_args.args[0].concurrency,8)
            self.assertEqual(call.call_args.args[0].per_model_concurrency,2)
        for bad in ('0','41'):
            with patch.object(sys,'argv',argv+['--per-model-concurrency',bad]),patch.object(launch,'run') as call:
                with self.assertRaises(SystemExit):launch.main()
                call.assert_not_called()


if __name__=='__main__':unittest.main()
