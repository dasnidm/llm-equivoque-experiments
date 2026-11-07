"""Admission failures must never dispatch or replay scientific requests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import fallback


class AdmissionTests(unittest.TestCase):
    def test_live_old_process_prevents_even_creating_operation_files(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            operation = work / 'unstarted-operation'
            with self.assertRaises(fallback.Conflict):
                with fallback.fallback_lock(work, operation, [os.getpid()]):
                    self.fail('Live process granted execution lock')
            self.assertFalse(operation.exists())

    def test_catalog_shim_cannot_be_used_as_original_baseline(self):
        with patch.object(fallback.shutil, 'which', return_value='/tmp/shim/codex'), \
             patch.object(fallback, 'verify_freeze') as verify:
            with self.assertRaises(fallback.Conflict):
                fallback.baseline_readiness('/unused', '/unused/freeze')
            verify.assert_not_called()

    def test_stop_prevents_any_continuation_admission(self):
        evidence = ({}, {'status': 'returned_to_three'}, {}, {}, {}, {'global_stop': True})
        with patch.object(fallback, 'verify_fallback', return_value=evidence), \
             patch.object(fallback, 'save_status') as save, \
             patch.object(fallback, 'execute_recovery') as execute:
            with self.assertRaises(fallback.Conflict):
                fallback.execute_four(Mock(), Mock(), '/unused', '/unused')
            save.assert_not_called()
            execute.assert_not_called()

    def test_previously_admitted_continuation_cannot_be_replayed(self):
        evidence = ({}, {'status': 'continuation_admitted_once'}, {}, {}, {}, {'global_stop': False})
        with patch.object(fallback, 'verify_fallback', return_value=evidence), \
             patch.object(fallback, 'save_status') as save, \
             patch.object(fallback, 'execute_recovery') as execute:
            with self.assertRaises(fallback.Conflict):
                fallback.execute_four(Mock(), Mock(), '/unused', '/unused')
            save.assert_not_called()
            execute.assert_not_called()

    def test_future_hold_cannot_be_released_before_four_complete(self):
        coordinator = Mock()
        evidence = ({}, {'status': 'continuation_admitted_once'}, {}, {}, {}, {})
        with patch.object(fallback, 'verify_fallback', return_value=evidence):
            with self.assertRaises(fallback.Conflict):
                fallback.release(coordinator, '/unused', '/unused')
        coordinator._mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
