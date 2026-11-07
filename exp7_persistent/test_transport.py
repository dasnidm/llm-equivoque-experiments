"""Offline subprocess tests; the fake server never contacts a model provider."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from .transport import PersistentTransport, digest, isolation_preflight, normalize_turn


SERVER = r'''
import json,os,sys,time
def emit(x):
 print(json.dumps(x),flush=True)
thread='thread-'+str(os.getpid()); counter=0
for line in sys.stdin:
 r=json.loads(line);m=r['method'];p=r.get('params',{})
 if m=='initialize':emit({'id':r['id'],'result':{'userAgent':'fake'}})
 elif m=='thread/start':
  if p['model']=='startup-warning':emit({'method':'configWarning','params':{'message':'unrecognized config'}})
  emit({'id':r['id'],'result':{'model':p['model'],'reasoningEffort':p['config']['model_reasoning_effort'],
       'cwd':p['cwd'],'approvalPolicy':'never','sandbox':{'type':'readOnly'},'instructionSources':[],
       'thread':{'id':thread}}})
 elif m=='turn/start':
  counter+=1;turn='turn-'+str(counter);prompt=p['input'][0]['text']
  emit({'id':r['id'],'result':{'turn':{'id':turn,'status':'inProgress','items':[]}}})
  if prompt=='HANG':time.sleep(20);continue
  if prompt=='CRASH':sys.exit(2)
  if prompt=='AUTH_CRASH':print('HTTP 401 Unauthorized',file=sys.stderr,flush=True);sys.exit(2)
  tid='wrong-thread' if prompt=='FOREIGN' else thread
  def note(method,**kw):emit({'method':method,'params':{'threadId':tid,'turnId':turn,**kw}})
  if prompt=='TOOL':note('item/completed',item={'id':'tool','type':'commandExecution','command':'bad'})
  if prompt=='RETRY':note('error',error={'message':'429 Too Many Requests'},willRetry=True)
  if prompt=='ERROR':note('error',error={'message':'429 Too Many Requests'},willRetry=False)
  if prompt=='REROUTE':note('model/rerouted',fromModel='original',toModel='other')
  answer={'id':'answer','type':'agentMessage','text':str(counter)}
  note('item/completed',item=answer)
  if prompt=='DUPLICATE':note('item/completed',item={'id':'answer2','type':'agentMessage','text':'two'})
  if prompt!='NO_USAGE':
   u={'inputTokens':counter*10,'cachedInputTokens':0,'cacheWriteInputTokens':0,'outputTokens':counter,
      'reasoningOutputTokens':0,'totalTokens':counter*11}
   note('thread/tokenUsage/updated',tokenUsage={'total':u,'last':{**u,'inputTokens':10,'outputTokens':1,'totalTokens':11}})
  emit({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'completed','items':[answer]}}})
  if prompt=='INTERTURN':time.sleep(.05);print('failed to refresh available models: 429 Too Many Requests',file=sys.stderr,flush=True)
'''


class FakeTransport(PersistentTransport):
    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = script

    def _command(self, trial, system_path):
        return [sys.executable, '-u', str(self.script)]


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / 'server.py'
        self.script.write_text(SERVER)
        self.trial = {'trial_id': 'trial1', 'model': 'fake-model', 'effort': 'low'}
        self.preflight = patch('exp7_persistent.transport.isolation_preflight')
        self.preflight.start(); self.addCleanup(self.preflight.stop)
        self.subject = patch('exp7_persistent.transport.subject_directory', side_effect=lambda p:p/'subject')
        self.subject.start(); self.addCleanup(self.subject.stop)
        self.transport = FakeTransport(self.script, timeout=2)
        self.addCleanup(self.transport.close)

    def request(self, prompt='hello', turn=1, session=None, schema=None, trial=None, folder='raw'):
        return self.transport.request(trial or self.trial,prompt,schema,'fixed system',session,self.root/folder,turn)

    def test_34_turns_use_one_process_one_thread_and_immutable_evidence(self):
        sid = None; pids=set(); ids=set(); first=None
        for turn in range(1,35):
            schema={'type':'object','properties':{}} if turn % 2 else None
            result=self.request(turn=turn,session=sid,schema=schema)
            self.assertTrue(result['ok'],result)
            self.assertEqual(result['text'],str(turn))
            self.assertEqual(result['usage']['input_tokens'],10*turn)
            self.assertEqual(result['usage_last']['input_tokens'],10)
            sid=result['session_id'];pids.add(result['process_pid']);ids.add(sid)
            sent=[json.loads(x) for x in (self.root/'raw'/f'turn-{turn:02d}'/'rpc-sent.jsonl').read_text().splitlines()]
            methods=[r['method'] for r in sent]
            self.assertEqual(methods,['initialize','initialized','thread/start','turn/start'] if turn==1 else ['turn/start'])
            self.assertEqual(sent[-1]['params']['outputSchema'],schema)
            if first is None:first=result['raw_files']
        self.assertEqual(len(pids),1);self.assertEqual(len(ids),1)
        process=self.transport._conversations['trial1'].process
        self.transport.close_trial('trial1')
        self.assertIsNotNone(process.poll())
        for entry in first:self.assertEqual(digest(entry['path']),entry['sha256'])

    def test_independent_trials_have_separate_process_and_thread(self):
        a=self.request()
        b=self.request(trial={**self.trial,'trial_id':'trial2'},folder='other')
        self.assertNotEqual(a['session_id'],b['session_id'])
        self.assertNotEqual(a['process_pid'],b['process_pid'])
        self.transport.close_trial('trial1')
        b2=self.request(session=b['session_id'],turn=2,trial={**self.trial,'trial_id':'trial2'},folder='other')
        self.assertTrue(b2['ok'])
        self.assertEqual(b['process_pid'],b2['process_pid'])

    def test_timeout_preserves_sent_request_and_never_replays(self):
        self.transport.timeout=.3
        with self.assertRaises(TimeoutError):self.request('HANG')
        sent=self.root/'raw'/'turn-01'/'rpc-sent.jsonl'
        self.assertEqual(sum(json.loads(x)['method']=='turn/start' for x in sent.read_text().splitlines()),1)
        with self.assertRaises(FileExistsError):self.request('HANG')
        self.assertIsNotNone(self.transport._conversations['trial1'].process.poll())

    def test_crash_does_not_start_another_process(self):
        with self.assertRaises(RuntimeError):self.request('CRASH')
        pid=self.transport._conversations['trial1'].process.pid
        with self.assertRaises(ValueError):self.request(turn=2)
        self.assertEqual(pid,self.transport._conversations['trial1'].process.pid)

    def test_uncertain_prior_session_cannot_be_resumed(self):
        with self.assertRaises(ValueError):self.request(session='old',turn=2)
        self.assertFalse(self.transport._conversations)

    def test_tool_duplicate_missing_usage_reroute_terminal_error_fail(self):
        for prompt in ['TOOL','DUPLICATE','NO_USAGE','REROUTE','ERROR']:
            with self.subTest(prompt=prompt):
                result=self.request(prompt,folder=prompt,trial={**self.trial,'trial_id':prompt})
                self.assertFalse(result['ok'])
                self.assertTrue(result['protocol_violations'])

    def test_recovered_error_keeps_success_but_preserves_rate_limit_signal(self):
        result=self.request('RETRY')
        self.assertTrue(result['ok'])
        self.assertEqual(result['recovered_transport_events'],1)
        self.assertIn('429',json.dumps(result['events']))

    def test_identity_change_cannot_leak_between_trials(self):
        a=self.request()
        with self.assertRaises(ValueError):
            self.request(turn=2,session=a['session_id'],trial={**self.trial,'model':'other'})

    def test_before_send_runs_after_pacing_and_before_turn_start(self):
        calls=[]
        self.transport.before_send=lambda:calls.append(time.monotonic())
        self.request()
        self.assertGreaterEqual(len(calls),3)

    def test_interturn_stderr_is_consumed_by_next_turn(self):
        a=self.request('INTERTURN')
        time.sleep(.1)
        b=self.request(session=a['session_id'],turn=2)
        self.assertIn('429',b['stderr'])
        self.assertTrue(b['ok'])

    def test_auth_crash_preserves_classifiable_diagnostics_on_exception(self):
        with self.assertRaises(RuntimeError) as caught:self.request('AUTH_CRASH')
        self.assertIn('401',caught.exception.transport_diagnostics)
        self.assertIn('Unauthorized',(self.root/'raw'/'process.stderr.log').read_text())

    def test_unknown_startup_warning_prevents_turn_submission(self):
        with self.assertRaisesRegex(ValueError,'startup diagnostic'):
            self.request(trial={**self.trial,'model':'startup-warning'})
        sent=(self.root/'raw'/'turn-01'/'rpc-sent.jsonl').read_text()
        self.assertNotIn('turn/start',sent)

    def test_close_preserves_late_stderr_and_delivers_to_gate(self):
        self.request('INTERTURN')
        time.sleep(.1)
        observations=[]
        self.transport.after_close=observations.append
        evidence=self.transport.close_trial('trial1')
        self.assertEqual({Path(x['path']).name for x in evidence},{'process.stderr.log','close-diagnostics.json'})
        self.assertIn('429',observations[0]['stderr'])
        for item in evidence:self.assertEqual(digest(item['path']),item['sha256'])


class IsolationTests(unittest.TestCase):
    def test_config_and_rules_fail_closed_without_modifying_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);subject=root/'subject';subject.mkdir()
            native=root/'native';native.mkdir()
            with patch.dict(os.environ,{'CODEX_HOME':str(native)}):
                isolation_preflight(subject)
                (native/'config.toml').write_text('model="unexpected"\n')
                with self.assertRaisesRegex(ValueError,'config'):isolation_preflight(subject)
                (native/'config.toml').write_text('# empty configuration\n')
                isolation_preflight(subject)
                (native/'rules').mkdir();(native/'rules'/'custom.rules').write_text('anything')
                with self.assertRaisesRegex(ValueError,'rules'):isolation_preflight(subject)

    def test_nonfinite_configuration_rejected(self):
        for kwargs in [{'timeout':float('nan')},{'timeout':float('inf')},{'min_start_interval':float('nan')}]:
            with self.assertRaises(ValueError):PersistentTransport(**kwargs)

    def test_unsupported_cli_stops_before_server_start(self):
        transport=PersistentTransport()
        with patch('exp7_persistent.transport.subprocess.check_output',return_value='codex-cli other\n'):
            with self.assertRaisesRegex(ValueError,'requires codex-cli'):
                transport._command({'effort':'low'},Path('/unused/system.txt'))


if __name__=='__main__':unittest.main()
