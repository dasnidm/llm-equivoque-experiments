"""Verify the separate no-tool metadata profile with no live inference."""
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
from exp7_persistent.transport import PersistentTransport
from .catalog_isolation import REMOVED, sanitize
from .schedule import EFFORTS, MODELS


class CatalogueTests(unittest.TestCase):
    def test_only_declared_tool_metadata_changes(self):
        original = {'models': [{'slug': 'm', 'context_window': 42, 'tool_mode': 'code_mode_only',
                    'multi_agent_version': 'v2', 'apply_patch_tool_type': 'freeform',
                    'node_repl_disabled': False, 'experimental_supported_tools': ['clock'],
                    'model_messages': {'base_instructions': 'unchanged'}}]}
        before = copy.deepcopy(original)
        result = sanitize(original)
        self.assertEqual(original, before)
        m = result['models'][0]
        self.assertTrue(all(k not in m for k in REMOVED))
        self.assertTrue(m['node_repl_disabled'])
        self.assertEqual(m['experimental_supported_tools'], [])
        self.assertEqual(m['context_window'], 42)
        self.assertEqual(m['model_messages'], before['models'][0]['model_messages'])


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'set CODEX_TEST_BINARY and EXP7_TEST_CATALOG for loopback CLI test')
class CatalogueCliTests(unittest.TestCase):
    def test_all_seven_models_and_efforts_have_no_advertised_tools(self):
        data = json.loads(Path(os.environ['EXP7_TEST_CATALOG']).read_text())
        self.assertTrue(set(MODELS) <= {x['slug'] for x in data['models']})
        with tempfile.TemporaryDirectory() as d, LocalResponses(schema_answers=True) as service:
            root = Path(d)
            catalogue = root/'no-tools.json'
            catalogue.write_text(json.dumps(sanitize(data)))
            wrapper = make_cli_wrapper(root, os.environ['CODEX_TEST_BINARY'], service.base_url)
            transport = PersistentTransport(timeout=30, codex_binary=str(wrapper), catalog_path=catalogue)
            schema = {'type':'object','properties':{'answer':{'type':'string'}},
                      'required':['answer'],'additionalProperties':False}
            try:
                for model in MODELS:
                    for effort in EFFORTS:
                        tid = f'offline-{model}-{effort}'
                        trial = {'trial_id':tid,'model':model,'effort':effort}
                        result = transport.request(trial, 'Synthetic question.', schema,
                                                   'Synthetic system.', None, root/tid, 1)
                        self.assertTrue(result['ok'], result.get('protocol_violations'))
                        transport.close_trial(tid)
                self.assertEqual(len(service.requests), 21)
                self.assertEqual(len(service.warmups), 21)
                self.assertEqual({r['body']['model'] for r in service.requests}, set(MODELS))
                for record in service.warmups + service.requests:
                    body = record['body']
                    self.assertFalse(body.get('tools'))
                    self.assertFalse(any(item.get('type') == 'additional_tools' and item.get('tools')
                                         for item in body.get('input', [])))
            finally:
                transport.close()


if __name__ == '__main__':
    unittest.main()
