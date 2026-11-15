import json
from pathlib import Path
import tempfile
import unittest

from .technical_dashboard import snapshot


class TechnicalDashboardTests(unittest.TestCase):
    def test_snapshot_exposes_counts_but_not_response_or_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stage = root/'stage-01'
            (stage/'states').mkdir(parents=True)
            (stage/'profile.json').write_text(json.dumps({'target_rpm': 100, 'concurrency': 7}))
            (stage/'states'/'tech-stage-01-001.json').write_text(json.dumps({
                'trial': {'model': 'gpt-6-astra', 'effort': 'high'}, 'status': 'active',
                'turns': [{'text': 'PRIVATE RESPONSE'}], 'error': 'PRIVATE ERROR'}))
            result = snapshot(root, True)
            self.assertIn('gpt-6-astra', result)
            self.assertIn('1 / 34', result)
            self.assertNotIn('PRIVATE', result)


if __name__ == '__main__':
    unittest.main()
