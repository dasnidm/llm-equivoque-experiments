"""Quiescence exceptions remain narrow; no real requests or remote mutations."""
from contextlib import ExitStack
import fcntl
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from .control import Conflict, atomic_json, main, quiescent_worker


class ReconciledControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-reconciled-control-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        (self.work / "launch-v1").mkdir()
        self.receipt = self.work / "reconciliation.private.json"
        self.paths = {
            self.work / "jobs" / "job-003" / "states" / (tid + ".json")
            for tid in ("main-032598", "main-034481", "main-036662")
        }
        for path in self.paths:
            atomic_json(path, {"status": "interrupted", "pending_turn": {"turn": 4}})

    def mocks(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        alive = stack.enter_context(patch("exp7_ops_v1.control.process_alive", return_value=False))
        verify = stack.enter_context(patch("exp7_ops_v1.recovery.verify_reconciliation", return_value=self.paths))
        return alive, verify

    def test_default_still_rejects_all_pending_records(self):
        _, verify = self.mocks()
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work, 100001, 100002):
                self.fail("Default guard must remain closed")
        verify.assert_not_called()

    def test_exact_receipt_is_verified_under_both_locks_and_preserves_bytes(self):
        _, verify = self.mocks()
        before = {path: path.read_bytes() for path in self.paths}

        def verified(work, receipt):
            self.assertEqual(work, self.work)
            self.assertEqual(receipt, self.receipt)
            for path in (self.work / "worker.lock", self.work / "launch-v1" / "launcher.lock"):
                with path.open("a") as handle:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.paths

        verify.side_effect = verified
        with quiescent_worker(self.work, 100001, 100002, self.receipt):
            self.assertEqual({path: path.read_bytes() for path in self.paths}, before)
        verify.assert_called_once_with(self.work, self.receipt)
        self.assertEqual({path: path.read_bytes() for path in self.paths}, before)

    def test_receipt_verification_failure_never_grants_exception(self):
        _, verify = self.mocks()
        verify.side_effect = Conflict("Preserved raw evidence changed")
        with self.assertRaisesRegex(Conflict, "evidence changed"):
            with quiescent_worker(self.work, 100001, 100002, self.receipt):
                self.fail("A changed artifact cannot grant quiescence")

    def test_even_listed_active_state_is_rejected(self):
        self.mocks()
        atomic_json(next(iter(self.paths)), {"status": "active", "pending_turn": {"turn": 4}})
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work, 100001, 100002, self.receipt):
                self.fail("Receipt must never excuse an active conversation")

    def test_new_pending_job_or_calibration_state_is_rejected(self):
        self.mocks()
        for relative in ("jobs/job-004/states/new.json", "calibration/attempt-c10-01/states/new.json"):
            with self.subTest(relative=relative):
                path = self.work / relative
                atomic_json(path, {"status": "interrupted", "pending_turn": {"turn": 1}})
                with self.assertRaises(Conflict):
                    with quiescent_worker(self.work, 100001, 100002, self.receipt):
                        self.fail("An unlisted pending request must block")
                path.unlink()

    def test_exemptions_must_be_exactly_three_original_job_paths(self):
        _, verify = self.mocks()
        paths = sorted(self.paths)
        invalid = [set(paths[:2]), set(paths + [self.work / "jobs/extra/states/fourth.json"]),
                   set(paths[:2] + [self.work / "calibration/attempt-01/states/other.json"]),
                   set(paths[:2] + [self.work.parent / "outside-state.json"])]
        for proposed in invalid:
            with self.subTest(proposed=sorted(map(str, proposed))):
                verify.return_value = proposed
                with self.assertRaises(Conflict):
                    with quiescent_worker(self.work, 100001, 100002, self.receipt):
                        self.fail("Receipt exemption scope must stay narrow")

    def test_receipt_cannot_silently_accept_cleared_pending_checkpoint(self):
        self.mocks()
        atomic_json(next(iter(self.paths)), {"status": "interrupted", "pending_turn": None})
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work, 100001, 100002, self.receipt):
                self.fail("Original pending checkpoints must remain present")

    def test_live_process_or_held_worker_lock_prevents_receipt_verification(self):
        alive, verify = self.mocks()
        alive.return_value = True
        with self.assertRaises(Conflict):
            with quiescent_worker(self.work, 100001, 100002, self.receipt):
                self.fail("Live previous process must block")
        verify.assert_not_called()
        alive.return_value = False
        with (self.work / "worker.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                with quiescent_worker(self.work, 100001, 100002, self.receipt):
                    self.fail("Active worker lock must block")
        verify.assert_not_called()

    def test_cli_forwards_explicit_receipt_only_to_requested_control_action(self):
        base = ["--work-dir", str(self.work), "--operation-dir", str(self.work / "operation")]
        args = ["--old-worker-pid", "100001", "--old-supervisor-pid", "100002",
                "--reconciliation-receipt", str(self.receipt)]
        with patch("exp7_ops_v1.control.GitCoordinator") as coordinator, \
             patch("exp7_ops_v1.control.resize_local", return_value={}) as resize, \
             patch("exp7_ops_v1.control.release_hold", return_value={}) as release, \
             patch("builtins.print"):
            self.assertEqual(main(base + ["resize-local"] + args), 0)
            self.assertEqual(resize.call_args.args[-1], str(self.receipt))
            release.assert_not_called()
            self.assertEqual(main(base + ["release"] + args +
                                  ["--calibration-attempt", "c10-01", "--freeze", "freeze.json"]), 0)
            self.assertEqual(release.call_args.args[-1], str(self.receipt))

    def test_real_reconciliation_bridge_preserves_three_pending_states(self):
        from exp7_main.test_protocol import example
        from exp7_main.test_runner import FakeTransport
        from exp7_main_v2.protocol import MainProtocol
        from exp7_main_v2.runner import CallBudget, run_trial
        from exp7_main_v2.coordination import GitCoordinator, new_board
        from exp7_main_v2.worker import ResultPublisher, export_job, job_identity, sha
        from .recovery import prepare_recovery

        root = self.work / "integration"
        root.mkdir()
        remote = root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        coordinator = GitCoordinator(str(remote), "coordination", root / "coord.git")
        publisher = ResultPublisher(str(remote), "results", root / "results.git")
        ids = ["interrupted-1", "interrupted-2", "interrupted-3", "new-1", "new-2", "new-3", "new-4"]
        trials = {tid: example(trial_id=tid, run_id="run") for tid in ids}
        coordinator.bootstrap(new_board("run", "b"*64, "c"*40,
            [{"job_id": "job", "model": "fake", "trial_ids": ids}],
            global_stop=False, global_max_concurrency=10, freeze_sha256="a"*64))
        token = coordinator.claim_model("fake", "owner", concurrency=3)
        job = coordinator.claim_job("fake", "owner", token)
        bound = {"model": "fake", "owner": "owner", "model_token": token,
                 "run_id": "run", "concurrency": 3}
        work = root / "work"
        directory = work / "jobs" / "job"
        directory.mkdir(parents=True)
        operation = work / "ops-v1" / "continuation"
        operation.mkdir(parents=True)
        atomic_json(work / "identity.private.json", bound)
        atomic_json(directory / "claim.private.json", job_identity(job, bound))
        budget = CallBudget(directory / "budget.json", "run:job", 238)
        states = [run_trial(trials[tid], MainProtocol(), FakeTransport(MainProtocol(), raise_at=2),
                            directory / "states" / (tid+".json"), directory / "native", budget, "a"*64)
                  for tid in ids[:3]]
        states += [{"trial": trials[tid], "status": "unstarted", "freeze_sha256": "a"*64,
                    "turns": [], "rounds": [], "pending_turn": None} for tid in ids[3:]]
        digest = export_job(states, directory / "public.jsonl.gz")
        reference = publisher.publish(directory / "public.jsonl.gz", "results/original.jsonl.gz")
        coordinator.complete_job("fake", "owner", token, "job", job["claim_token"],
            counts={"complete": 0, "failed": 0, "interrupted": 3, "unstarted": 4},
            calls=6, result_ref=reference, result_sha256=digest)
        intent = prepare_recovery(coordinator, publisher, work, operation, trials, "a"*64, "job", ids[3:])
        receipt = operation / "reconciliation.private.json"
        with patch("exp7_ops_v1.control.process_alive", return_value=False):
            with self.assertRaises(Conflict):
                with quiescent_worker(work, 100001, 100002):
                    self.fail("No implicit receipt adoption")
            with quiescent_worker(work, 100001, 100002, receipt):
                for relative, expected in intent["prior_files"].items():
                    self.assertEqual(sha(directory / relative), expected)
            # The real verifier, rather than a mocked callback, must detect
            # any edit to a preserved state before granting another exception.
            path = directory / "states" / (ids[0]+".json")
            path.write_bytes(path.read_bytes()+b" ")
            with self.assertRaises(Conflict):
                with quiescent_worker(work, 100001, 100002, receipt):
                    self.fail("Changed original state must block")


if __name__ == "__main__":
    unittest.main()
