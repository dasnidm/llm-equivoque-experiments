"""Technical-stage unit and loopback integration tests; no live model calls."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
from dataclasses import asdict
from .fast_pacing import StageResult
from .technical_sweep import TechnicalGate, run_stage, run_sweep, technical_trials
from .schedule import MODELS


class TechnicalSweepTests(unittest.TestCase):
    def test_fresh_calibration_trials_cover_models(self):
        for n in (7, 14, 70):
            rows = technical_trials('unit', n)
            self.assertEqual(len({t['trial_id'] for t in rows}), n)
            self.assertEqual({t['model'] for t in rows}, set(MODELS))
            self.assertTrue(all(t['split'] == 'calibration' for t in rows))
            if n == 7:
                self.assertEqual({t['effort'] for t in rows}, {'low', 'medium', 'high'})
                self.assertIn(('gpt-5.6-sol', 'high'), {(t['model'], t['effort']) for t in rows})
        with self.assertRaises(ValueError):
            technical_trials('../bad', 7)
        with self.assertRaises(ValueError):
            technical_trials('unit', 6)

    def test_technical_gate_checks_original_board_and_stop(self):
        class Board:
            def status(self):
                return {'global_stop': True, 'run_id': 'equivoque-exp7-cards-200-20261115'}
        gate = TechnicalGate(Board())
        gate.check()
        gate.observe({'ok': False, 'stderr': '429 Too Many Requests', 'events': []})
        with self.assertRaises(RuntimeError):
            gate.check()

    def test_sweep_accumulates_short_measurement_then_stops_on_rate_limit(self):
        calls = []
        def fake_stage(root, stage, rpm, concurrency, catalog, *, binary):
            calls.append((stage, rpm, concurrency))
            result = StageResult(target_rpm=rpm, concurrency=concurrency,
                                 successful_calls=80, duration_seconds=50,
                                 native_429=int(len(calls) == 3))
            return {'stage': stage, 'stage_result': asdict(result)}
        with tempfile.TemporaryDirectory() as d, patch('exp7_cards.technical_sweep.run_stage', fake_stage):
            result = run_sweep(d, 'fresh', 'fixture', max_stages=5)
            self.assertEqual(result['status'], 'stop')
            self.assertEqual(calls, [('stage-01', 100, 7), ('stage-02', 100, 7), ('stage-03', 110, 7)])
            with self.assertRaises(FileExistsError):
                run_sweep(d, 'fresh', 'fixture')
            self.assertEqual(len(calls), 3)


@unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                     'loopback CLI and seven-model catalogue are required')
class TechnicalSweepLoopbackTests(unittest.TestCase):
    def test_seven_concurrent_complete_sessions(self):
        class Board:
            def __init__(self, *args):
                pass
            def status(self):
                return {'global_stop': True, 'run_id': 'equivoque-exp7-cards-200-20261115'}
        with tempfile.TemporaryDirectory() as d, LocalResponses(schema_answers=True) as service:
            root = Path(d)
            fake_binary = make_cli_wrapper(root, os.environ['CODEX_TEST_BINARY'], service.base_url)
            from .tool_surface_probe import probe
            def probe_real_binary(_binary, catalog):
                return probe(os.environ['CODEX_TEST_BINARY'], catalog)
            with patch('exp7_cards.technical_sweep.GitCoordinator', Board), \
                    patch('exp7_cards.technical_sweep.probe_tool_surface', probe_real_binary):
                summary = run_stage(root/'stages', 'unit', 1000, 7,
                                    os.environ['EXP7_TEST_CATALOG'], binary=str(fake_binary))
            self.assertEqual(summary['session_statuses'], {'complete': 7}, summary)
            self.assertEqual(summary['successful_calls'], 238, summary)
            self.assertEqual(summary['actual_turn_starts'], 238, summary)
            self.assertEqual(summary['audits_passed'], 7, summary)
            self.assertEqual(summary['forbidden_tool_events'], 0, summary)
            self.assertEqual(summary['compaction_events'], 0, summary)
            self.assertEqual(summary['uncertain_sessions'], 0, summary)
            self.assertEqual(len(service.requests), 238)
            with patch('exp7_cards.technical_sweep.GitCoordinator', Board), \
                    patch('exp7_cards.technical_sweep.probe_tool_surface', probe_real_binary):
                with self.assertRaises(FileExistsError):
                    run_stage(root/'stages', 'unit', 1000, 7,
                              os.environ['EXP7_TEST_CATALOG'], binary=str(fake_binary))


if __name__ == '__main__':
    unittest.main()
