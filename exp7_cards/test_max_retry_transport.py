import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper, prompt_texts
from exp7_pre.runner import CallBudget
from .max_retry_transport import MaxRetryTransport, retryable
from .protocol import CardProtocol
from .runner import run_trial
from .schedule import build


class FakeConversation:
    """An explicit first-turn 429; rollback and same-thread retry are visible."""
    last = None
    def __init__(self, command, subject, directory, signature):
        FakeConversation.last = self
        self.command, self.subject, self.directory, self.signature = command, subject, directory, signature
        self.thread_id, self.last_turn, self.closed = None, None, False
        self.lock, self.process = __import__('threading').Lock(), types.SimpleNamespace(pid=1234)
        self.history, self.queue, self.calls = [], [], []
    def send(self, message, sent):
        sent.write((json.dumps(message)+'\n').encode()); sent.flush()
    def rpc(self, method, params, deadline, sent, received, messages):
        self.calls.append(method)
        self.send({'id':len(self.calls),'method':method,'params':params},sent)
        if method == 'initialize': return {}
        if method == 'thread/start':
            return {'model':'gpt-6-astra','reasoningEffort':'high','cwd':str(self.subject),
                    'approvalPolicy':'never','sandbox':{'type':'readOnly'},'instructionSources':[],
                    'thread':{'id':'same-thread'}}
        if method == 'turn/start':
            tid = 'turn-'+str(sum(x == 'turn/start' for x in self.calls))
            fail = tid == 'turn-1'
            self.history.append({'id':tid})
            if fail:
                self.queue.append({'method':'error','params':{'threadId':'same-thread','turnId':tid,
                    'error':{'message':'exceeded retry limit, last status: 429 Too Many Requests'},'willRetry':False}})
            else:
                usage={'total':{'inputTokens':5,'outputTokens':1},'last':{'inputTokens':5,'outputTokens':1}}
                self.queue += [{'method':'thread/tokenUsage/updated','params':{'threadId':'same-thread','turnId':tid,'tokenUsage':usage}},
                               {'method':'item/completed','params':{'threadId':'same-thread','turnId':tid,
                                'item':{'id':'answer-'+tid,'type':'agentMessage','text':'ok'}}}]
            self.queue.append({'method':'turn/completed','params':{'threadId':'same-thread',
                              'turn':{'id':tid,'status':'failed' if fail else 'completed',
                                      'error':{'message':'429 Too Many Requests'} if fail else None}}})
            return {'turn':{'id':tid}}
        if method == 'thread/revert':
            idx = next(i for i,t in enumerate(self.history) if t['id'] == params['beforeTurnId'])
            del self.history[idx:]
            return {'thread':{'id':'same-thread'}}
        if method == 'thread/turns/list':
            return {'data':self.history[:], 'nextCursor':None}
        raise AssertionError(method)
    def receive(self, deadline, received, messages):
        message = self.queue.pop(0)
        received.write((json.dumps(message)+'\n').encode()); received.flush(); messages.append(message)
        return message
    def consume_stderr(self): return ''
    def close(self): self.closed = True


class RetryTransportTests(unittest.TestCase):
    def test_terminal_429_is_rolled_back_and_retried_in_same_thread(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation', FakeConversation), \
             patch('exp7_persistent.transport.validate_startup', lambda *args: None), \
             patch.object(MaxRetryTransport, '_command', lambda *args: ['codex','app-server','--stdio']):
            root=Path(d)
            t=MaxRetryTransport(timeout=20)
            t.before_send=lambda:None
            trial={'trial_id':'fixture','model':'gpt-6-astra','effort':'high'}
            first=t.request(trial,'question',None,'system',None,root/'native',1)
            self.assertTrue(first['ok'], first['protocol_violations'])
            self.assertEqual(first['session_id'],'same-thread')
            self.assertEqual(len(first['retry_records']),1)
            self.assertEqual(FakeConversation.last.history,[{'id':'turn-2'}])
            self.assertEqual(FakeConversation.last.calls.count('turn/start'),2)
            self.assertIn('thread/revert',FakeConversation.last.calls)
            second=t.request(trial,'next',None,'system','same-thread',root/'native',2)
            self.assertTrue(second['ok'])
            self.assertEqual(FakeConversation.last.history,[{'id':'turn-2'},{'id':'turn-3'}])
            self.assertEqual(len(t.sent_stamps),3)

    def test_uncertain_or_unsafe_failures_are_not_retried(self):
        msg=[{'method':'turn/completed','params':{'threadId':'t','turn':{'id':'x','status':'failed'}}}]
        result={'ok':False,'tool_events':0,'compaction_events':0,
                'events':[{'type':'error','message':'last status: 429 Too Many Requests'}]}
        self.assertTrue(retryable(result,msg,'t','x'))
        self.assertFalse(retryable({**result,'compaction_events':1},msg,'t','x'))
        self.assertFalse(retryable({**result,'protocol_violations':['Forbidden item started']},msg,'t','x'))
        fallback = {'method':'warning','params':{'message':'Falling back from WebSockets to HTTPS transport. test'}}
        self.assertTrue(retryable(result,msg+[fallback],'t','x'))
        self.assertFalse(retryable(result,msg+[{'method':'warning','params':{'message':'Unknown warning'}}],'t','x'))
        self.assertFalse(retryable(result,[], 't','x'))
        self.assertFalse(retryable({**result,'events':[{'type':'error','message':'retry_429=false'}]},msg,'t','x'))


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'loopback CLI fixture is required')
class RealCliTests(unittest.TestCase):
    def test_34_turns_remain_in_one_process_and_thread(self):
        _,rows=build()
        trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high' and x['game']=='seq')
        with tempfile.TemporaryDirectory() as d, LocalResponses(schema_answers=True) as service:
            root=Path(d)
            wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=MaxRetryTransport(timeout=30,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            try:
                state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
                self.assertEqual(state['status'],'complete',state.get('error'))
                self.assertEqual(len(service.requests),34)
                self.assertEqual(len({x['session_id'] for x in state['turns']}),1)
                self.assertEqual(len({x['process_pid'] for x in state['turns']}),1)
                self.assertTrue(all(not x['retry_records'] for x in state['turns']))
            finally:
                t.close()

    def test_actual_cli_429_recovery_keeps_single_visible_prompt(self):
        class RateLimitedResponses(LocalResponses):
            def __init__(self):
                super().__init__()
                self.failures=0
            def events(self,body,transport,connection_id):
                if body.get('generate') is not False and self.failures < 2:
                    self.failures += 1
                    return [{'type':'error','status':429,
                             'error':{'type':'rate_limit_error','code':'rate_limit_exceeded',
                                      'message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        with tempfile.TemporaryDirectory() as d, RateLimitedResponses() as service:
            root=Path(d)
            wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=MaxRetryTransport(timeout=90,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            trial={'trial_id':'429-fixture','model':'gpt-6-astra','effort':'high'}
            try:
                result=t.request(trial,'Synthetic question.',None,'Synthetic system.',None,root/'native',1)
                self.assertTrue(result['ok'],(result['protocol_violations'],result['events']))
                self.assertEqual(service.failures,2)
                # Verify retry path actually reached application-level recovery,
                # rather than only the CLI's internal transport retry.
                self.assertGreaterEqual(len(result['retry_records']),1)
                self.assertEqual(len(t._conversations[trial['trial_id']].completed_turn_ids),1)
                self.assertEqual(prompt_texts(service.requests[-1]['body']).count('Synthetic question.'),1)
            finally:
                t.close()

    def test_actual_cli_429_after_prior_success_retains_history(self):
        class FailSecondResponses(LocalResponses):
            def __init__(self):
                super().__init__(); self.failed=False
            def events(self,body,transport,connection_id):
                if body.get('generate') is not False and len(self.requests)==1 and not self.failed:
                    self.failed=True
                    return [{'type':'error','status':429,'error':{'type':'rate_limit_error',
                             'code':'rate_limit_exceeded','message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        with tempfile.TemporaryDirectory() as d, FailSecondResponses() as service:
            root=Path(d)
            wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=MaxRetryTransport(timeout=90,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            trial={'trial_id':'later-429','model':'gpt-6-astra','effort':'high'}
            try:
                first=t.request(trial,'First question.',None,'Synthetic system.',None,root/'native',1)
                self.assertTrue(first['ok'])
                second=t.request(trial,'Second question.',None,'Synthetic system.',first['session_id'],root/'native',2)
                self.assertTrue(second['ok'],second['protocol_violations'])
                self.assertEqual(len(second['retry_records']),1)
                self.assertEqual(second['session_id'],first['session_id'])
                self.assertEqual(len(t._conversations[trial['trial_id']].completed_turn_ids),2)
                self.assertEqual(prompt_texts(service.requests[-1]['body']).count('Second question.'),1)
            finally:
                t.close()

    def test_actual_cli_retry_after_websocket_fallback(self):
        class FallBackResponses(LocalResponses):
            def __init__(self): super().__init__(); self.failed=0
        with tempfile.TemporaryDirectory() as d, FallBackResponses() as service:
            # Force the real CLI's WebSocket-to-HTTP fallback through a 403
            # handshake, as observed in the first live unpaced stage.
            def reject_websocket(handler):
                handler.send_error(403)
            def rate_limit_http(handler):
                body=json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
                if body.get('generate') is not False and service.failed < 6:
                    service.failed+=1
                    payload=json.dumps({'error':{'type':'rate_limit_error','code':'rate_limit_exceeded',
                                                 'message':'429 Too Many Requests'}}).encode()
                    handler.send_response(429)
                    handler.send_header('Content-Type','application/json')
                else:
                    events=service.events(body,'https',None)
                    payload=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
                    handler.send_response(200)
                    handler.send_header('Content-Type','text/event-stream')
                handler.send_header('Content-Length',str(len(payload)))
                handler.end_headers();handler.wfile.write(payload);handler.wfile.flush()
            service.server.RequestHandlerClass.do_GET=reject_websocket
            service.server.RequestHandlerClass.do_POST=rate_limit_http
            root=Path(d)
            wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=MaxRetryTransport(timeout=90,max_attempts=20,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            trial={'trial_id':'fallback-429','model':'gpt-6-astra','effort':'high'}
            try:
                result=t.request(trial,'Fallback question.',None,'Synthetic system.',None,root/'native',1)
                self.assertTrue(result['ok'],(result['protocol_violations'],result['events']))
                self.assertTrue(service.failed)
                self.assertGreaterEqual(len(result['retry_records']),1)
                self.assertEqual(len(t._conversations[trial['trial_id']].completed_turn_ids),1)
            finally:
                t.close()


if __name__=='__main__':
    unittest.main()
