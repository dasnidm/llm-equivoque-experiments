"""Local integration of rolling technical sessions, never a live provider."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
from .max_retry_stage import run


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'loopback CLI fixture required')
class TechnicalStageTests(unittest.TestCase):
    def test_seven_fresh_cli_sessions_complete_and_are_audited(self):
        class Board:
            def __init__(self,*args): pass
            def status(self):
                return {'global_stop':True,'run_id':'equivoque-exp7-cards-200-20261115'}
        from .tool_surface_probe import probe
        def actual_probe(_binary,catalog): return probe(os.environ['CODEX_TEST_BINARY'],catalog)
        class Two429Responses(LocalResponses):
            def __init__(self):
                super().__init__(schema_answers=True); self.failures=0
            def events(self,body,transport,connection_id):
                fail=False
                with self._lock:
                    if body.get('generate') is not False and self.failures < 2:
                        self.failures+=1; fail=True
                if fail:
                    return [{'type':'error','status':429,'error':{'type':'rate_limit_error',
                             'code':'rate_limit_exceeded','message':'429 Too Many Requests'}}]
                return super().events(body,transport,connection_id)
        with tempfile.TemporaryDirectory() as d, Two429Responses() as service:
            root=Path(d)
            wrapper=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            with patch('exp7_cards.max_retry_stage.GitCoordinator',Board), \
                 patch('exp7_cards.max_retry_stage.probe_tool_surface',actual_probe):
                result=run(root/'stage',os.environ['EXP7_TEST_CATALOG'],concurrency=7,sessions=7,binary=str(wrapper))
            self.assertEqual(result['session_statuses'],{'complete':7},result)
            self.assertEqual(result['successful_calls'],238,result)
            self.assertEqual(result['actual_turn_starts'],240,result)
            self.assertEqual(result['retryable_error_attempts'],2,result)
            self.assertEqual(result['audits_passed'],7,result)
            self.assertEqual(result['uncertain_sessions'],0,result)
            self.assertEqual(len(service.requests),238)


if __name__=='__main__': unittest.main()
