"""Exercise real native request serialization offline; never requests inference."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from equivoque.core import Protocol
from equivoque.isolation import inspect_request


@unittest.skipUnless(shutil.which('codex'), 'Native CLI unavailable for offline serialization')
class IsolationTests(unittest.TestCase):
    def test_native_body_has_no_tools_or_role_hints(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            catalog = subprocess.run(['codex', 'debug', 'models', '--bundled'],
                capture_output=True, text=True, check=True, timeout=20)
            (root / 'catalog.json').write_text(catalog.stdout)
            result = inspect_request(Protocol(), {
                'configuration_id': 'gpt-6-sol-low', 'model': 'gpt-6-sol', 'effort': 'low'},
                root / 'inspection', root / 'catalog.json')
            self.assertTrue(result['passed'], result['errors'])
            self.assertEqual(result['tool_counts'], [0])
            self.assertEqual(result['live_subject_invocations'], 0)
            bodies = json.loads((root / 'inspection/requests.json').read_text())
            self.assertEqual(bodies[0]['model'], 'gpt-6-sol')


if __name__ == '__main__':
    unittest.main()
