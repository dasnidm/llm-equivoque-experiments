"""Offline real-CLI wire check; fails closed when any tools are advertised.

Uses the existing loopback fake service and dummy credentials. No live provider
request is sent. The precise tool names are retained, never conversation IDs.
"""
import json
import os
from pathlib import Path
import tempfile

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
from exp7_persistent.transport import PersistentTransport


def probe(binary, catalog, model='gpt-6-astra', effort='high'):
    with tempfile.TemporaryDirectory() as d, LocalResponses() as service:
        root = Path(d)
        wrapper = make_cli_wrapper(root, binary, service.base_url)
        transport = PersistentTransport(timeout=30, codex_binary=str(wrapper), catalog_path=catalog)
        try:
            result = transport.request({'trial_id': 'offline-tool-surface', 'model': model, 'effort': effort},
                                       'Synthetic question.', None, 'Synthetic system.', None, root/'native', 1)
        finally:
            transport.close()
        names = set()
        for record in service.warmups + service.requests:
            body = record['body']
            names.update(t.get('name', t.get('type', 'unknown')) for t in body.get('tools', []))
            for item in body.get('input', []):
                if item.get('type') == 'additional_tools':
                    for group in item.get('tools', []):
                        for tool in group.get('tools', []):
                            names.add(group.get('name', 'unknown')+'.'+tool.get('name', 'unknown'))
        return {'cli_response_ok': bool(result.get('ok')), 'model_calls': 0,
                'advertised_tool_count': len(names), 'advertised_tools': sorted(names),
                'no_tool_isolation_passed': bool(result.get('ok')) and not names}


if __name__ == '__main__':
    binary, catalog = os.environ.get('CODEX_TEST_BINARY'), os.environ.get('EXP7_TEST_CATALOG')
    if not binary or not catalog:
        raise SystemExit('CODEX_TEST_BINARY and EXP7_TEST_CATALOG are required')
    result = probe(binary, catalog)
    print(json.dumps(result, indent=2))
    if not result['no_tool_isolation_passed']:
        raise SystemExit(2)
