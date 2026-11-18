"""Failure, FIFO, and real-CLI loopback coverage for queued retries."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper, prompt_texts, schema_example
from exp7_pre.audit import audit_trial
from exp7_pre.runner import CallBudget
from .protocol import CardProtocol
from .queued_retry_audit import audit_queued_trial
from .queued_retry_runner import run_trial
from .queued_retry_transport import FairAdmissionQueue, ProcessExited, QueuedRetryTransport, retryable
from .schedule import build
from .technical_sweep import initialize_sqlite, technical_trials
from .test_max_retry_transport import FakeConversation


class Process:
    def __init__(self): self.pid, self.returncode = 4321, None
    def poll(self): return self.returncode
    def wait(self):
        while self.returncode is None:time.sleep(.005)
        return self.returncode


class LiveConversation(FakeConversation):
    def __init__(self,command,subject,directory,signature):
        super().__init__(command,subject,directory,signature)
        self.process=Process();self.final_files=None
        self.stderr_path=directory/'process.stderr.log';self.stderr_path.touch()
    def close(self):
        self.closed=True
        if self.process.returncode is None:self.process.returncode=0


class ManyFailures(LiveConversation):
    def rpc(self,method,params,deadline,sent,received,messages):
        result=super().rpc(method,params,deadline,sent,received,messages)
        if method=='turn/start':
            tid=result['turn']['id']; n=sum(x=='turn/start' for x in self.calls)
            if n<=25 and n!=1:
                self.queue=[{'method':'error','params':{'threadId':'same-thread','turnId':tid,
                    'error':{'message':'429 Too Many Requests'},'willRetry':False}},
                    {'method':'turn/completed','params':{'threadId':'same-thread',
                     'turn':{'id':tid,'status':'failed','error':{'message':'429 Too Many Requests'}}}}]
        return result


class DiesAfterRollback(LiveConversation):
    def rpc(self,method,params,deadline,sent,received,messages):
        result=super().rpc(method,params,deadline,sent,received,messages)
        if method=='thread/turns/list':self.process.returncode=9
        return result


class BadRollback(LiveConversation):
    def rpc(self,method,params,deadline,sent,received,messages):
        result=super().rpc(method,params,deadline,sent,received,messages)
        if method=='thread/turns/list':return {'data':[{'id':'unexpected'}],'nextCursor':None}
        return result


class TimeoutOnce(LiveConversation):
    def __init__(self,*args):
        super().__init__(*args);self.timed_out=False
    def receive(self,deadline,received,messages):
        if not self.timed_out:
            self.timed_out=True
            raise TimeoutError('simulated slow live process')
        return super().receive(deadline,received,messages)


class DiesWhileWaiting(LiveConversation):
    def receive(self,deadline,received,messages):
        self.process.returncode=9
        raise TimeoutError('simulated process exit')


class DiesBetweenTurns(LiveConversation):
    def rpc(self,method,params,deadline,sent,received,messages):
        result=super().rpc(method,params,deadline,sent,received,messages)
        if method=='turn/start' and result['turn']['id']=='turn-1':
            tid='turn-1'; usage={'total':{'inputTokens':5,'outputTokens':1},'last':{'inputTokens':5,'outputTokens':1}}
            # A valid schema selection ensures the first logical turn commits.
            self.queue=[{'method':'thread/tokenUsage/updated','params':{'threadId':'same-thread','turnId':tid,'tokenUsage':usage}},
                        {'method':'item/completed','params':{'threadId':'same-thread','turnId':tid,
                         'item':{'id':'answer-'+tid,'type':'agentMessage','text':json.dumps(schema_example(params['outputSchema']))}}},
                        {'method':'turn/completed','params':{'threadId':'same-thread','turn':{'id':tid,'status':'completed'}}}]
        return result
    def receive(self,deadline,received,messages):
        message=super().receive(deadline,received,messages)
        if message.get('method')=='turn/completed':self.process.returncode=9
        return message


class LiveAfterFirst(DiesBetweenTurns):
    def receive(self,deadline,received,messages):
        return FakeConversation.receive(self,deadline,received,messages)


class DiesAfterUnsafeTurn(LiveConversation):
    def rpc(self,method,params,deadline,sent,received,messages):
        result=super().rpc(method,params,deadline,sent,received,messages)
        if method=='turn/start':
            tid=result['turn']['id']
            self.queue.insert(0,{'method':'item/completed','params':{'threadId':'same-thread','turnId':tid,
                              'item':{'id':'forbidden-item','type':'commandExecution'}}})
        return result
    def consume_stderr(self):
        self.process.returncode=9
        return ''


class QueuedRetryTests(unittest.TestCase):
    def test_duplicate_concurrent_sample_is_rejected_before_second_run(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=QueuedRetryTransport(timeout=5);entered=threading.Event();release=threading.Event()
            def blocked(*args):
                entered.set()
                if not release.wait(3):raise TimeoutError('fixture not released')
                return {'status':'complete'}
            def execute():
                return run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',
                                 CallBudget(root/'budget.json','fixture',34),'a'*64)
            with patch('exp7_cards.queued_retry_runner.durable_trial',side_effect=blocked):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(execute)
                    self.assertTrue(entered.wait(3))
                    try:
                        with self.assertRaises(BlockingIOError):execute()
                    finally:release.set()
                    self.assertEqual(future.result()['status'],'complete')
            self.assertEqual(t.total_sent,0)
            t.close()

    def test_missing_send_gate_fails_before_creating_process(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation') as conversation:
            t=QueuedRetryTransport(timeout=5)
            with self.assertRaises(RuntimeError):
                t.request({'trial_id':'x','model':'gpt-6-astra','effort':'high'},
                          'q',None,'system',None,Path(d)/'native',1)
            conversation.assert_not_called()
            self.assertFalse((Path(d)/'native').exists())
            t.close()

    def test_fifo_queue_does_not_lose_dead_waiter_or_block_followers(self):
        q=FairAdmissionQueue()
        blocker=(0,'blocker')
        with q.condition:q.pending.append(blocker)
        results=[]; alive={'a':True,'b':True,'c':True}
        def worker(k):
            try:results.append((k,q.admit(k,lambda:alive[k])))
            except ProcessExited:results.append((k,'exited'))
        threads=[]
        for key in ('a','b','c'):
            t=threading.Thread(target=worker,args=(key,));t.start();threads.append(t)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with q.condition:
                    if any(x[1]==key for x in q.pending):break
                time.sleep(.005)
            else:self.fail('Waiter did not enter queue')
        alive['b']=False
        with q.condition:q.pending.remove(blocker);q.condition.notify_all()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual([key for _,key in q.dispatched],['a','c'])
        self.assertIn(('b','exited'),results)
        self.assertFalse(q.pending)

    def test_more_than_20_retries_use_same_process_and_durable_journal(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',ManyFailures), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            trial={'trial_id':'many','model':'gpt-6-astra','effort':'high'}
            result=t.request(trial,'question',None,'system',None,root/'native',1)
            self.assertTrue(result['ok'],result['protocol_violations'])
            self.assertEqual(result['retry_count'],25)
            self.assertEqual(len(t.sent_stamps),26)
            self.assertEqual(len((root/'native'/'turn-01-retries.journal.jsonl').read_text().splitlines()),25)
            self.assertEqual(result['session_id'],'same-thread')
            self.assertEqual(t.process_state('many'),'alive')
            self.assertEqual([key for _,key in t.admission_queue.dispatched],['many']*26)
            t.close()

    def test_live_timeout_waits_without_duplicate_send(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',TimeoutOnce), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            trial={'trial_id':'slow','model':'gpt-6-astra','effort':'high'}
            result=t.request(trial,'question',None,'system',None,root/'native',1)
            self.assertTrue(result['ok'],result['protocol_violations'])
            # One 429 and one retry; the timeout itself must not add a send.
            self.assertEqual(len(t.sent_stamps),2)
            self.assertEqual(result['retry_count'],1)
            self.assertEqual(t.process_state('slow'),'alive')
            t.close()

    def test_process_exit_is_failed_sample_not_restarted(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',DiesAfterRollback), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'failed',state)
            self.assertEqual(state['failure_kind'],'process_exited')
            self.assertIsNotNone(state['pending_turn'])
            self.assertEqual(len(t.sent_stamps),1)
            before=len(t.sent_stamps)
            self.assertEqual(run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',
                                       CallBudget(root/'budget.json','fixture',34),'a'*64)['status'],'failed')
            self.assertEqual(len(t.sent_stamps),before)
            t.close()

    def test_process_that_never_started_is_not_a_failed_sample(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',side_effect=OSError('cannot start')), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'unstarted',state)
            self.assertEqual(state['failure_kind'],'process_not_started')
            self.assertEqual(len(t.sent_stamps),0)
            t.close()

    def test_controller_exception_does_not_close_live_subject(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);native_dir=root/'native';native_dir.mkdir()
            subject=native_dir/'subject';subject.mkdir()
            t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            c=LiveConversation(['codex','app-server','--stdio'],subject,native_dir,())
            t._conversations[trial['trial_id']]=c
            with patch('exp7_cards.queued_retry_runner.durable_trial',side_effect=OSError('checkpoint failed')):
                with self.assertRaises(OSError):
                    run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',
                              CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(t.process_state(trial['trial_id']),'alive')
            self.assertIn(trial['trial_id'],t.held_processes)
            with self.assertRaises(RuntimeError):t.close()
            t.held_processes.clear();t.close()  # fake-only test cleanup

    def test_unverified_rollback_holds_live_process_instead_of_retrying(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',BadRollback), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'held',state)
            self.assertEqual(t.process_state(trial['trial_id']),'alive')
            self.assertEqual(len(t.sent_stamps),1)
            with self.assertRaises(RuntimeError):t.close()
            again=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(again['status'],'held')
            self.assertEqual(len(t.sent_stamps),1)
            # Losing controller state is not proof that the original process
            # died; a new controller must not start a replacement or replay.
            new_controller=QueuedRetryTransport(timeout=5)
            recovered=run_trial(trial,CardProtocol(),new_controller,root/'state.json',root/'native',
                                CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(recovered['status'],'held')
            self.assertEqual(new_controller.total_sent,0)
            with self.assertRaises(ValueError):
                run_trial(trial,CardProtocol(),new_controller,root/'state.json',root/'native',
                          CallBudget(root/'budget.json','fixture',34),'b'*64)
            self.assertEqual(json.loads((root/'state.json').read_text())['status'],'held')
            new_controller.close()
            # An actually exited held process becomes a failed sample, without
            # spawning a new process or replaying the pending turn.
            t._conversations[trial['trial_id']].process.returncode=9
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                after=json.loads((root/'state.json').read_text())
                if after['status']=='failed' and trial['trial_id'] not in t.held_processes:break
                time.sleep(.01)
            else:self.fail(f'Held process exit not reconciled: {t.watcher_errors}')
            self.assertEqual(after['status'],'failed')
            self.assertEqual(after['failure_kind'],'process_exited')
            self.assertEqual(len(t.sent_stamps),1)
            t.close()

    def test_process_exit_while_waiting_is_failed(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',DiesWhileWaiting), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['failure_kind'],'process_exited')
            self.assertEqual(len(t.sent_stamps),1)
            t.close()

    def test_process_exit_between_turns_preserves_completed_history(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',DiesBetweenTurns), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'failed',state)
            self.assertEqual(state['failure_kind'],'process_exited')
            self.assertEqual(len(state['turns']),1)
            self.assertTrue(state['turns'][0]['ok'])
            self.assertEqual(state['pending_turn']['turn'],2)
            self.assertEqual(len(t.sent_stamps),1)
            t.close()

    def test_dead_process_after_unsafe_turn_does_not_leave_stale_hold(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',DiesAfterUnsafeTurn), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(state['status'],'failed',state)
            self.assertEqual(state['failure_kind'],'process_exited')
            self.assertNotIn(trial['trial_id'],t.held_processes)
            t.close()

    def test_budget_exhaustion_does_not_kill_live_process(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, \
             patch('exp7_persistent.transport._Conversation',LiveAfterFirst), \
             patch('exp7_persistent.transport.validate_startup',lambda *args:None), \
             patch.object(QueuedRetryTransport,'_command',lambda *args:['codex','app-server','--stdio']):
            root=Path(d);t=QueuedRetryTransport(timeout=5);t.before_send=lambda:None
            state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',1),'a'*64)
            self.assertEqual(state['status'],'held',state)
            self.assertEqual(len(state['turns']),1)
            self.assertEqual(t.process_state(trial['trial_id']),'alive')
            self.assertEqual(t.total_sent,1)
            with self.assertRaises(RuntimeError):t.close()
            t._conversations[trial['trial_id']].process.returncode=9
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and trial['trial_id'] in t.held_processes:time.sleep(.01)
            self.assertNotIn(trial['trial_id'],t.held_processes)
            t.close()

    def test_unclassified_failed_checkpoint_is_not_assumed_dead(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=QueuedRetryTransport(timeout=5)
            path=root/'state.json'
            path.write_text(json.dumps({'trial':trial,'freeze_sha256':'a'*64,'transport':t.name,
                                        'status':'failed','pending_turn':{'turn':1}}))
            result=run_trial(trial,CardProtocol(),t,path,root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(result['status'],'held')
            self.assertEqual(result['hold_reason'],'process_identity_unknown')
            self.assertEqual(t.total_sent,0)
            t.close()

    def test_unclassified_failed_checkpoint_keeps_known_live_process_open(self):
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);native_dir=root/'native';native_dir.mkdir()
            subject=native_dir/'subject';subject.mkdir()
            t=QueuedRetryTransport(timeout=5);c=LiveConversation(['codex','app-server','--stdio'],subject,native_dir,())
            t._conversations[trial['trial_id']]=c
            path=root/'state.json'
            path.write_text(json.dumps({'trial':trial,'freeze_sha256':'a'*64,'transport':t.name,
                                        'status':'failed','pending_turn':{'turn':1}}))
            result=run_trial(trial,CardProtocol(),t,path,root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
            self.assertEqual(result['status'],'held')
            self.assertIn(trial['trial_id'],t.held_processes)
            self.assertEqual(t.process_state(trial['trial_id']),'alive')
            with self.assertRaises(RuntimeError):t.close()
            c.process.returncode=9
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and trial['trial_id'] in t.held_processes:time.sleep(.01)
            self.assertEqual(json.loads(path.read_text())['status'],'failed')
            self.assertNotIn(trial['trial_id'],t.held_processes)
            t.close()

    def test_only_verified_failed_terminal_turns_are_requeued(self):
        msg=[{'method':'turn/completed','params':{'threadId':'t','turn':{'id':'x','status':'failed'}}}]
        result={'ok':False,'tool_events':0,'compaction_events':0,
                'events':[{'type':'error','message':'any explicit terminal error'}]}
        self.assertTrue(retryable(result,msg,'t','x'))
        self.assertFalse(retryable(result,[], 't','x'))
        self.assertFalse(retryable({**result,'tool_events':1},msg,'t','x'))
        self.assertFalse(retryable({**result,'compaction_events':1},msg,'t','x'))


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'loopback CLI fixture required')
class RealCliQueuedTests(unittest.TestCase):
    def test_real_cli_process_death_marks_sample_failed_without_restart(self):
        class Paused(LocalResponses):
            def __init__(self):super().__init__(schema_answers=True);self.started=threading.Event();self.release=threading.Event()
            def events(self,body,transport,connection_id):
                if body.get('generate') is not False:
                    self.started.set();self.release.wait(10)
                return super().events(body,transport,connection_id)
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, Paused() as service:
            root=Path(d);wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=QueuedRetryTransport(timeout=30,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            def execute():
                return run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',
                                 CallBudget(root/'budget.json','fixture',34),'a'*64)
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(execute)
                    self.assertTrue(service.started.wait(10),'CLI did not start a model request')
                    process=t._conversations[trial['trial_id']].process
                    process.kill();process.wait(timeout=5);service.release.set()
                    state=future.result(timeout=10)
                self.assertEqual(state['status'],'failed',state)
                self.assertEqual(state['failure_kind'],'process_exited')
                self.assertIsNotNone(state['pending_turn'])
                self.assertEqual(t.total_sent,1)
            finally:
                service.release.set();t.close()

    def test_actual_cli_retry_in_middle_of_session(self):
        class FailSixth(LocalResponses):
            def __init__(self):super().__init__(schema_answers=True);self.failures=0
            def events(self,body,transport,connection_id):
                if body.get('generate') is not False and len(self.requests)==5 and self.failures==0:
                    self.failures=1
                    return [{'type':'error','status':429,'error':{'type':'rate_limit_error',
                             'code':'rate_limit_exceeded','message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, FailSixth() as service:
            root=Path(d);wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=QueuedRetryTransport(timeout=30,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            try:
                state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
                self.assertEqual(state['status'],'complete',state.get('error'))
                self.assertEqual(state['turns'][5]['retry_count'],1)
                self.assertEqual(len({x['process_pid'] for x in state['turns']}),1)
                self.assertEqual(len({x['session_id'] for x in state['turns']}),1)
                before=prompt_texts(service.requests[4]['body'])
                after=prompt_texts(service.requests[5]['body'])
                self.assertEqual(after,before+[state['turns'][5]['prompt']])
                report=audit_queued_trial(trial,CardProtocol(),root/'state.json','a'*64)
                self.assertTrue(report['integrity_ok'],report['errors'])
            finally:t.close()

    def test_actual_cli_25_429s_then_full_34_turn_session(self):
        class TwentyFive429(LocalResponses):
            def __init__(self):super().__init__(schema_answers=True);self.failures=0
            def events(self,body,transport,connection_id):
                if body.get('generate') is not False and self.failures<25:
                    self.failures+=1
                    return [{'type':'error','status':429,'error':{'type':'rate_limit_error',
                             'code':'rate_limit_exceeded','message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        _,rows=build();trial=next(x for x in rows if x['model']=='gpt-6-astra' and x['effort']=='high')
        with tempfile.TemporaryDirectory() as d, TwentyFive429() as service:
            root=Path(d);wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            t=QueuedRetryTransport(timeout=30,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            t.before_send=lambda:None
            try:
                state=run_trial(trial,CardProtocol(),t,root/'state.json',root/'native',CallBudget(root/'budget.json','fixture',34),'a'*64)
                self.assertEqual(state['status'],'complete',state.get('error'))
                self.assertEqual(state['turns'][0]['retry_count'],25)
                self.assertEqual(len({x['process_pid'] for x in state['turns']}),1)
                self.assertEqual(len({x['session_id'] for x in state['turns']}),1)
                self.assertEqual(len(service.requests),34)
                self.assertEqual(prompt_texts(service.requests[0]['body']).count(state['turns'][0]['prompt']),1)
                report=audit_queued_trial(trial,CardProtocol(),root/'state.json','a'*64)
                self.assertTrue(report['integrity_ok'],report['errors'])
                journal=next(Path(x['path']) for x in state['turns'][0]['raw_files']
                             if x['path'].endswith('-retries.journal.jsonl'))
                first=json.loads(journal.read_text().splitlines()[0])
                raw=next(Path(x['path']) for x in first['raw_files'] if x['path'].endswith('events.jsonl'))
                raw.write_text(raw.read_text()+'\n')
                changed=audit_queued_trial(trial,CardProtocol(),root/'state.json','a'*64)
                self.assertFalse(changed['integrity_ok'])
            finally:t.close()

    def test_rolling_7_sessions_34_turns_with_429_and_separate_processes(self):
        class Two429(LocalResponses):
            def __init__(self):super().__init__(schema_answers=True);self.failures=0
            def events(self,body,transport,connection_id):
                fail=False
                with self._lock:
                    if body.get('generate') is not False and self.failures<2:
                        self.failures+=1;fail=True
                if fail:return [{'type':'error','status':429,'error':{'type':'rate_limit_error',
                                'code':'rate_limit_exceeded','message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        with tempfile.TemporaryDirectory() as d, Two429() as service:
            root=Path(d);wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            transport=QueuedRetryTransport(timeout=30,codex_binary=str(wrapper),catalog_path=os.environ['EXP7_TEST_CATALOG'])
            initialize_sqlite(root,transport)
            transport.before_send=lambda:None
            trials=technical_trials('queued-offline',7)
            budget=CallBudget(root/'budget.json','fixture',238)
            def execute(t):
                return run_trial(t,CardProtocol(),transport,root/'states'/(t['trial_id']+'.json'),root/'native',budget,'a'*64)
            try:
                with ThreadPoolExecutor(max_workers=7) as pool: states=list(pool.map(execute,trials))
                self.assertTrue(all(s['status']=='complete' for s in states),[(s['status'],s.get('error')) for s in states])
                self.assertEqual(len(service.requests),238)
                self.assertEqual(len(transport.sent_stamps),240)
                self.assertEqual(len({s['session_id'] for s in states}),7)
                self.assertEqual(len({s['turns'][0]['process_pid'] for s in states}),7)
                for s in states:
                    self.assertEqual(len(s['turns']),34)
                    self.assertEqual(len({t['process_pid'] for t in s['turns']}),1)
                    self.assertTrue(audit_trial(s['trial'],CardProtocol(),root/'states'/(s['trial']['trial_id']+'.json'),'a'*64)['integrity_ok'])
                    report=audit_queued_trial(s['trial'],CardProtocol(),root/'states'/(s['trial']['trial_id']+'.json'),'a'*64)
                    self.assertTrue(report['integrity_ok'],report['errors'])
            finally:transport.close()


if __name__=='__main__':unittest.main()
