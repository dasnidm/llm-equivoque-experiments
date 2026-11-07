"""Narrow opt-in quiescence exclusion for immutable stopped c10-01 evidence."""
from contextlib import ExitStack,nullcontext
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .control import Conflict,atomic_json,main,quiescent_worker,release_hold


class StoppedCalibrationControlTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="exp7-stopped-cal-control-")
        self.addCleanup(temp.cleanup);self.work=Path(temp.name)
        (self.work/"launch-v1").mkdir()
        self.receipt=self.work/"calibration-c10-01.stopped.manifest.json"
        self.paths={self.work/"calibration"/"attempt-c10-01"/"states"/(f"cal-{i}.json") for i in range(10)}
        for path in self.paths:
            atomic_json(path,{"status":"interrupted","pending_turn":{"turn":11}})
        stack=ExitStack();self.addCleanup(stack.close)
        self.alive=stack.enter_context(patch("exp7_ops_v1.control.process_alive",return_value=False))
        self.verify=stack.enter_context(patch("exp7_ops_v1.calibration_snapshot.verify_stopped_calibration_receipt",
                                             return_value=self.paths,create=True))

    def test_default_and_original_job_receipt_do_not_excuse_failed_calibration(self):
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work,99901,99902): pass
        self.verify.assert_not_called()
        old={self.work/"jobs"/"job"/"states"/(f"old-{i}.json") for i in range(3)}
        for path in old: atomic_json(path,{"status":"interrupted","pending_turn":{"turn":1}})
        with patch("exp7_ops_v1.recovery.verify_reconciliation",return_value=old):
            with self.assertRaises(Conflict):
                with quiescent_worker(self.work,99901,99902,self.work/"old-receipt"): pass
        self.verify.assert_not_called()

    def test_two_explicit_receipts_verify_under_locks_and_preserve_all13_states(self):
        old={self.work/"jobs"/"job"/"states"/(f"old-{i}.json") for i in range(3)}
        for path in old: atomic_json(path,{"status":"interrupted","pending_turn":{"turn":1}})
        before={path:path.read_bytes() for path in self.paths|old}
        def verify(work,receipt):
            self.assertEqual(work,self.work);self.assertEqual(receipt,self.receipt)
            for path in [self.work/"worker.lock",self.work/"launch-v1"/"launcher.lock"]:
                with path.open("a") as handle,self.assertRaises(BlockingIOError):
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return self.paths
        self.verify.side_effect=verify
        with patch("exp7_ops_v1.recovery.verify_reconciliation",return_value=old):
            with quiescent_worker(self.work,99901,99902,self.work/"old-receipt",self.receipt):
                self.assertEqual({p:p.read_bytes() for p in before},before)
        self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_corrupted_archive_or_receipt_blocks(self):
        self.verify.side_effect=ValueError("Archive checksum changed")
        with self.assertRaisesRegex(ValueError,"checksum"):
            with quiescent_worker(self.work,99901,99902,stopped_calibration_receipt=self.receipt): pass

    def test_exclusion_requires_exactly10_c10_01_state_paths(self):
        paths=sorted(self.paths)
        for proposed in [set(paths[:9]),set(paths+[self.work/"calibration/attempt-c10-01/states/extra.json"]),
                         set(paths[:9]+[self.work/"calibration/attempt-c10-02/states/new.json"]),
                         set(paths[:9]+[self.work/"jobs/job/states/other.json"]),
                         set(paths[:9]+[self.work.parent/"outside.json"])]:
            with self.subTest(proposed=sorted(map(str,proposed))):
                self.verify.return_value=proposed
                with self.assertRaises(Conflict):
                    with quiescent_worker(self.work,99901,99902,stopped_calibration_receipt=self.receipt): pass

    def test_changed_or_active_or_extra_pending_records_remain_blocked(self):
        path=next(iter(self.paths));original=path.read_bytes()
        for state in [{"status":"active","pending_turn":{"turn":11}},
                      {"status":"interrupted","pending_turn":None}]:
            atomic_json(path,state)
            with self.assertRaises(Conflict):
                with quiescent_worker(self.work,99901,99902,stopped_calibration_receipt=self.receipt): pass
        path.write_bytes(original)
        extra=self.work/"calibration/attempt-c10-02/states/fresh.json"
        atomic_json(extra,{"status":"interrupted","pending_turn":{"turn":1}})
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work,99901,99902,stopped_calibration_receipt=self.receipt): pass

    def test_live_process_blocks_before_archive_verification(self):
        self.alive.return_value=True
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work,99901,99902,stopped_calibration_receipt=self.receipt): pass
        self.verify.assert_not_called()

    def test_cli_forwards_optional_receipt_to_requested_action(self):
        base=["--work-dir",str(self.work),"--operation-dir",str(self.work/"operation")]
        flags=["--old-worker-pid","99901","--old-supervisor-pid","99902",
               "--stopped-calibration-receipt",str(self.receipt)]
        with patch("exp7_ops_v1.control.GitCoordinator"),patch("builtins.print"), \
             patch("exp7_ops_v1.control.resize_local",return_value={}) as resize, \
             patch("exp7_ops_v1.control.release_hold",return_value={}) as release:
            self.assertEqual(main(base+["resize-local"]+flags),0)
            self.assertEqual(resize.call_args.kwargs["stopped_calibration_receipt"],str(self.receipt))
            self.assertEqual(main(base+["release"]+flags+["--freeze","freeze.json","--calibration-attempt","c10-02"]),0)
            self.assertEqual(release.call_args.kwargs["stopped_calibration_receipt"],str(self.receipt))

    def test_release_requires_new_attempt_and_finalized_four_id_continuation(self):
        from .test_control import ControlTests
        fixture=ControlTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.resized()
        receipt=fixture.op/"incomplete-reconciliation.json"
        atomic_json(receipt,{"phase":"preserved_before_continuation"})
        with patch("exp7_ops_v1.control.quiescent_worker",return_value=nullcontext()):
            for attempt in ("c10-01","c10-02"):
                with self.subTest(attempt=attempt),self.assertRaises(Conflict):
                    release_hold(fixture.coord,fixture.work,fixture.op,99901,99902,attempt,
                                 fixture.root/"freeze.json",receipt,self.receipt)
        self.assertEqual(fixture.coord.status()["jobs"]["j3"],fixture.hold["held_job"])


if __name__=="__main__":
    unittest.main()
