"""Offline tampering checks against retained original RPC evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from equivoque.transport import overrides, provider_schema
from .audit import audit_turn
from .transport import normalize_turn, PersistentTransport


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trial = {'model': 'model-test', 'effort': 'high'}
        self.prompt, self.system = 'Select A or B.', 'Answer only the participant prompt.'
        self.schema = {'type': 'object', 'properties': {'selection': {'type': 'string'}}, 'required': ['selection']}
        self.write('subject-system.txt', self.system, raw=True)
        config = {k: json.loads(v) for k, v in
                  (x.split('=', 1) for x in overrides(self.root/'subject-system.txt', 'high')[1::2])}
        self.sent = [
            {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'codex_exec'}}},
            {'method': 'initialized'},
            {'id': 2, 'method': 'thread/start', 'params': {'model': 'model-test', 'cwd': '/opaque/subject',
                'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': False,
                'historyMode': 'paginated', 'allowProviderModelFallback': False, 'dynamicTools': [], 'config': config}},
            {'id': 3, 'method': 'turn/start', 'params': {'threadId': 'thread-1', 'turnTrigger': 'exec',
                'input': [{'type': 'text', 'text': self.prompt, 'text_elements': []}], 'cwd': '/opaque/subject',
                'approvalPolicy': 'never', 'effort': 'high', 'outputSchema': provider_schema(self.schema)}}]
        answer = {'id': 'answer-1', 'type': 'agentMessage', 'text': '{"selection":"A"}'}
        self.received = [
            {'id': 1, 'result': {}},
            {'id': 2, 'result': {'thread': {'id': 'thread-1'}, 'model': 'model-test', 'reasoningEffort': 'high',
                'cwd': '/opaque/subject', 'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly'}, 'instructionSources': []}},
            {'id': 3, 'result': {'turn': {'id': 'turn-1', 'status': 'inProgress'}}},
            {'method': 'item/completed', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'item': answer}},
            {'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
                'tokenUsage': {'total': {'inputTokens': 30, 'outputTokens': 4}, 'last': {'inputTokens': 30, 'outputTokens': 4}}}},
            {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {'id': 'turn-1',
                'status': 'completed', 'items': [answer], 'error': None}}}]
        self.command = ['codex', 'app-server', '--stdio'] + overrides(self.root/'subject-system.txt', 'high')
        self.adapter = {'transport': PersistentTransport.name, 'process_pid': 1234, 'thread_id': 'thread-1',
                        'turn_id': 'turn-1', 'command': self.command, 'normalization_start_index': 2,
                        'catalog_sha256': None, 'events_are_derived': True}
        normalized = normalize_turn(self.received[2:], 'thread-1', 'turn-1')
        self.record = {**normalized, 'prompt': self.prompt, 'schema': self.schema,
                       'provider_schema': provider_schema(self.schema), 'session_id': 'thread-1',
                       'app_server_turn_id': 'turn-1', 'session_id_before': None, 'process_pid': 1234,
                       'command': self.command, 'metadata_fallback': False, 'exit_code': 0, 'timeout': False,
                       'malformed_event_lines': 0, 'event_count': len(normalized['events'])}
        self.write('prompt.txt', self.prompt, raw=True)
        self.write('schema.json', provider_schema(self.schema))
        self.write('stderr.txt', '', raw=True)
        self.write('rpc-sent.jsonl', self.sent, lines=True)
        self.write('rpc-received.jsonl', self.received, lines=True)
        self.write('events.jsonl', normalized['events'], lines=True)
        self.write('adapter.json', self.adapter)
        self.rehash()

    def write(self, name, value, *, raw=False, lines=False):
        text = value if raw else ''.join(json.dumps(x)+'\n' for x in value) if lines else json.dumps(value)+'\n'
        (self.root/name).write_text(text)

    def rehash(self):
        self.record['raw_files'] = [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                                    for p in sorted(self.root.iterdir()) if p.is_file()]

    def audit(self, **kwargs):
        return audit_turn(self.record, expected_prompt=self.prompt, expected_system=self.system,
                          expected_schema=self.schema, expected_trial=self.trial, **kwargs)

    def assert_rejected(self, substring):
        result = self.audit()
        self.assertFalse(result['integrity_ok'], result)
        self.assertTrue(any(substring in error for error in result['errors']), result)

    def test_valid_original_trace(self):
        self.assertEqual(self.audit(), {'integrity_ok': True, 'errors': []})

    def test_raw_hash_tampering(self):
        self.write('prompt.txt', 'Changed prompt', raw=True)
        self.assert_rejected('hash mismatch')

    def test_rehashed_rpc_prompt_drift_is_detected(self):
        self.sent[-1]['params']['input'][0]['text'] = 'A different prompt'
        self.write('rpc-sent.jsonl', self.sent, lines=True)
        self.rehash()
        self.assert_rejected('Original RPC prompt mismatch')

    def test_rehashed_duplicate_turn_submission_is_replay(self):
        self.sent.append(copy.deepcopy(self.sent[-1]))
        self.write('rpc-sent.jsonl', self.sent, lines=True)
        self.rehash()
        self.assert_rejected('exactly one turn/start')

    def test_rehashed_schema_drift(self):
        self.sent[-1]['params']['outputSchema'] = None
        self.write('rpc-sent.jsonl', self.sent, lines=True)
        self.rehash()
        self.assert_rejected('Original RPC schema mismatch')

    def test_rehashed_terminal_identity_drift(self):
        self.received[-1]['params']['threadId'] = 'other-thread'
        self.write('rpc-received.jsonl', self.received, lines=True)
        self.rehash()
        self.assert_rejected('Terminal thread/turn identity mismatch')

    def test_rehashed_derived_answer_drift(self):
        derived = copy.deepcopy(self.record['events'])
        derived[2]['item']['text'] = 'Different answer'
        self.write('events.jsonl', derived, lines=True)
        self.rehash()
        self.assert_rejected('Derived events differ')

    def test_adapter_cannot_hide_protocol_events(self):
        self.adapter['normalization_start_index'] = 3
        self.write('adapter.json', self.adapter)
        self.rehash()
        self.assert_rejected('Normalization boundary mismatch')

    def test_pid_stays_constant_across_conversation(self):
        result = self.audit(expected_pid=9999)
        self.assertFalse(result['integrity_ok'])
        self.assertIn('Process PID mismatch', result['errors'])

    def test_missing_original_trace_is_rejected(self):
        (self.root/'rpc-received.jsonl').unlink()
        self.rehash()
        self.assert_rejected('Missing required raw artifacts')

    def test_duplicate_named_artifact_is_rejected(self):
        self.record['raw_files'].append(dict(self.record['raw_files'][0]))
        self.assert_rejected('Duplicate raw artifact name')

    def test_rehashed_effective_model_change(self):
        self.received[1]['result']['model'] = 'other-model'
        self.write('rpc-received.jsonl', self.received, lines=True)
        self.rehash()
        self.assert_rejected('Effective model or effort mismatch')

    def test_record_usage_cannot_disagree_with_rpc(self):
        self.record['usage'] = {'input_tokens': 9999}
        self.assert_rejected('Normalized result mismatch: usage')

    def test_rehashed_cli_configuration_cannot_drift(self):
        self.command += ['-c', 'features.shell_tool=true']
        self.write('adapter.json', self.adapter)
        self.rehash()
        self.assert_rejected('Unexpected extra CLI configuration')

    def test_followup_keeps_process_and_has_only_one_submission(self):
        self.sent = [self.sent[-1]]
        self.sent[0]['id'] = 4
        self.received = self.received[2:]
        self.received[0]['id'] = 4
        self.received[0]['result']['turn']['id'] = 'turn-2'
        for message in self.received[1:]:
            params = message['params']
            if 'turnId' in params:
                params['turnId'] = 'turn-2'
            if 'turn' in params:
                params['turn']['id'] = 'turn-2'
        self.received[2]['params']['tokenUsage']['total'] = {'inputTokens': 60, 'outputTokens': 8}
        normalized = normalize_turn(self.received, 'thread-1', 'turn-2')
        self.record.update(normalized, app_server_turn_id='turn-2', session_id_before='thread-1')
        self.adapter.update(turn_id='turn-2', normalization_start_index=0)
        self.write('adapter.json', self.adapter)
        self.write('rpc-sent.jsonl', self.sent, lines=True)
        self.write('rpc-received.jsonl', self.received, lines=True)
        self.write('events.jsonl', normalized['events'], lines=True)
        self.rehash()
        self.assertEqual(self.audit(previous_session_id='thread-1', expected_pid=1234),
                         {'integrity_ok': True, 'errors': []})

    def add_catalog(self):
        self.write('model-catalog.json', {'models': [{'slug': 'model-test'}]})
        snapshot = self.root/'model-catalog.json'
        self.command += ['-c', 'model_catalog_json=' + json.dumps(str(snapshot))]
        self.adapter['catalog_sha256'] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        self.write('adapter.json', self.adapter)
        self.rehash()

    def test_catalog_snapshot_is_independently_audited(self):
        self.add_catalog()
        self.assertTrue(self.audit()['integrity_ok'])

    def test_rehashed_catalog_bytes_must_match_adapter_digest(self):
        self.add_catalog()
        self.write('model-catalog.json', {'models': [{'slug': 'other-model'}]})
        self.rehash()
        self.assert_rejected('catalog snapshot hash mismatch')

    def test_catalog_command_cannot_reference_unretained_external_file(self):
        self.add_catalog()
        self.command[-1] = 'model_catalog_json=' + json.dumps('/external/model-catalog.json')
        self.write('adapter.json', self.adapter)
        self.rehash()
        self.assert_rejected('catalog snapshot path mismatch')

    def test_immutable_close_artifacts_are_verified(self):
        self.write('process.stderr.log', 'final stderr\n', raw=True)
        self.write('close-diagnostics.json', {'process_pid': 1234, 'closed': True})
        self.rehash()
        self.assertTrue(self.audit()['integrity_ok'])
        self.write('process.stderr.log', 'altered stderr\n', raw=True)
        self.assert_rejected('Raw file hash mismatch')


if __name__ == '__main__':
    unittest.main()
