"""Exercise real Git races and interruption semantics without network/model calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from exp7_main.coordination import (
    Conflict, CoordinationError, CoordinationUnavailable, GitCoordinator,
    NoCapacity, OwnershipError, Stopped, new_board, render_readme, validate_board,
)


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-git-test-")
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)],
                       check=True, capture_output=True)
        self.branch = "exp7/test-coordination"
        self.counter = 0
        self.jobs = [{"job_id": "job-1", "model": "m1", "trial_ids": ["t1", "t2"]},
                     {"job_id": "job-2", "model": "m2", "trial_ids": ["t3"]},
                     {"job_id": "job-3", "model": "m1", "trial_ids": ["t4"]}]
        self.board = new_board("test-run", "a" * 64, "b" * 40, self.jobs,
                               global_stop=False, global_max_concurrency=2)
        self.admin = self.coordinator()
        self.admin.bootstrap(self.board)

    def tearDown(self):
        self.temp.cleanup()

    def coordinator(self, cls=GitCoordinator):
        self.counter += 1
        return cls(str(self.remote), self.branch, self.root / f"cache-{self.counter}")

    def claim(self):
        c = self.coordinator()
        token = c.claim_model("m1", "vm-1")
        job = c.claim_job("m1", "vm-1", token)
        return c, token, job

    def test_fresh_board_is_stopped_and_does_not_alias_inputs(self):
        board = new_board("new-run", "c" * 64, "d" * 40, self.jobs)
        self.assertTrue(board["global_stop"])
        self.assertNotIn("order", self.jobs[0])
        self.assertEqual(board["jobs"]["job-1"]["call_cap"], 68)

    def test_optional_execution_freeze_is_validated(self):
        board = new_board("test", "a" * 64, "b" * 40, self.jobs, freeze_sha256="f" * 64)
        self.assertEqual(board["freeze_sha256"], "f" * 64)
        with self.assertRaises(CoordinationError):
            new_board("test", "a" * 64, "b" * 40, self.jobs, freeze_sha256="invalid")

    def test_readme_is_committed_and_updates_with_board(self):
        initial = subprocess.check_output(["git", "--git-dir", str(self.remote), "show",
            "refs/heads/" + self.branch + ":README.md"], text=True)
        self.assertIn("ENABLED", initial)
        self.assertIn("**4대화 · 3작업**", initial)
        self.assertIn("미시작·미보고 **4**", initial)
        c, token, job = self.claim()
        args = ("m1", "vm-1", token, job["job_id"], job["claim_token"])
        c.complete_job(*args, counts={"complete": 1, "failed": 1, "interrupted": 0, "unstarted": 0},
            calls=35, result_ref="deadbeef:results/job-1.json", result_sha256="e" * 64)
        self.admin.set_stop(True, "Review capacity")
        observed = subprocess.check_output(["git", "--git-dir", str(self.remote), "show",
            "refs/heads/" + self.branch + ":README.md"], text=True)
        self.assertIn("STOP", observed)
        self.assertIn("Review capacity", observed)
        self.assertIn("**1 / 2**", observed)
        self.assertIn("| m1 | vm-1 | 1 | 1/0/0/0/1/0 | 1/1/0/1 | 35 |", observed)
        self.assertIn("| m2 | 미배정 | 0 | 1/0/0/0/0/0 | 0/0/0/1 | 0 |", observed)
        self.assertIn("미시작·미보고 **2**", observed)
        self.assertIn("deadbeef:results/job-1.json", observed)
        self.assertIn("b" * 40, observed)
        self.assertIn("a" * 64, observed)
        rendered = render_readme(self.admin.status(), "https://github.com/example/repo")
        self.assertIn("https://github.com/example/repo/blob/deadbeef/results/job-1.json", rendered)

    def test_existing_branch_cannot_be_reinitialized(self):
        changed = deepcopy(self.board)
        changed["run_id"] = "replacement"
        with self.assertRaises(Conflict):
            self.coordinator().bootstrap(changed)
        self.assertEqual(self.admin.status()["run_id"], "test-run")

    def test_duplicate_trial_or_job_is_rejected(self):
        jobs = deepcopy(self.jobs)
        jobs[1]["trial_ids"] = ["t1"]
        with self.assertRaises(CoordinationError):
            new_board("test", "a" * 64, "b" * 40, jobs)
        with self.assertRaises(CoordinationError):
            new_board("test", "a" * 64, "b" * 40, self.jobs + [self.jobs[0]])

    def test_claim_run_result_and_next_job(self):
        c, token, job = self.claim()
        self.assertEqual(job["job_id"], "job-1")
        args = ("m1", "vm-1", token, job["job_id"], job["claim_token"])
        self.assertEqual(c.assert_permission(*args)["status"], "claimed")
        self.assertEqual(c.mark_running(*args)["status"], "running")
        result = c.complete_job(*args, counts={"complete": 2, "failed": 0,
            "interrupted": 0, "unstarted": 0}, calls=68,
            result_ref="deadbeef:results/job-1.json", result_sha256="e" * 64)
        self.assertEqual(result["status"], "complete")
        with self.assertRaises(OwnershipError):
            c.assert_permission(*args)
        self.assertEqual(c.claim_job("m1", "vm-1", token)["job_id"], "job-3")

    def test_stop_prevents_new_calls_but_preserves_results_and_heartbeat(self):
        c, token, job = self.claim()
        args = ("m1", "vm-1", token, job["job_id"], job["claim_token"])
        self.admin.set_stop(True, "Capacity error; drain and report")
        with self.assertRaises(Stopped):
            c.assert_permission(*args)
        with self.assertRaises(Stopped):
            c.mark_running(*args)
        with self.assertRaises(Stopped):
            self.coordinator().claim_model("m2", "vm-2")
        c.heartbeat(*args)
        result = c.complete_job(*args, counts={"complete": 0, "failed": 1,
            "interrupted": 1, "unstarted": 0}, calls=5,
            result_ref="deadbeef:results/partial.json", result_sha256="e" * 64)
        self.assertEqual(result["status"], "partial_failed")
        self.assertTrue(self.admin.status()["global_stop"])

    def test_blocked_and_stale_jobs_are_not_reclaimed(self):
        c, token, job = self.claim()
        args = ("m1", "vm-1", token, job["job_id"], job["claim_token"])
        result = c.complete_job(*args, counts={"complete": 0, "failed": 1,
            "interrupted": 0, "unstarted": 1}, calls=1,
            result_ref="deadbeef:results/stopped.json", result_sha256="e" * 64)
        self.assertEqual(result["status"], "blocked")
        with self.assertRaises(Conflict):
            c.claim_job("m1", "vm-1", token)
        with self.assertRaises(OwnershipError):
            self.coordinator().claim_model("m1", "vm-1")
        with self.assertRaises(OwnershipError):
            self.coordinator().claim_model("m1", "vm-other")

    def test_wrong_tokens_never_grant_permission(self):
        c, token, job = self.claim()
        with self.assertRaises(OwnershipError):
            c.assert_permission("m1", "vm-1", token, job["job_id"], "wrong")
        with self.assertRaises(OwnershipError):
            c.assert_permission("m1", "vm-1", "wrong", job["job_id"], job["claim_token"])

    def test_counts_budget_and_terminal_replacement_rejected(self):
        c, token, job = self.claim()
        args = ("m1", "vm-1", token, job["job_id"], job["claim_token"])
        counts = {"complete": 2, "failed": 0, "interrupted": 0, "unstarted": 0}
        for calls in (0, 67, 69):
            with self.assertRaises(ValueError):
                c.complete_job(*args, counts=counts, calls=calls,
                    result_ref="commit:path", result_sha256="f" * 64)
        c.complete_job(*args, counts=counts, calls=68,
                       result_ref="commit:path", result_sha256="f" * 64)
        # Retrying the exact metadata acknowledgement is safe and does not replay inference.
        c.complete_job(*args, counts=counts, calls=68,
                       result_ref="commit:path", result_sha256="f" * 64)
        with self.assertRaises(Conflict):
            c.complete_job(*args, counts=counts, calls=68,
                           result_ref="different:path", result_sha256="e" * 64)

    def test_unavailable_remote_fails_closed(self):
        c, token, job = self.claim()
        c.remote = str(self.root / "missing.git")
        with self.assertRaises(CoordinationUnavailable):
            c.assert_permission("m1", "vm-1", token, job["job_id"], job["claim_token"])

    def test_lost_push_acknowledgement_is_confirmed_by_readback(self):
        class LostAck(GitCoordinator):
            def _git(self, *args, **kwargs):
                result = super()._git(*args, **kwargs)
                if args[0] == "push":
                    raise CoordinationUnavailable("Simulated response loss after accepted push")
                return result
        c = self.coordinator(LostAck)
        token = c.claim_model("m1", "vm-1")
        self.assertEqual(self.admin.status()["models"]["m1"]["model_token"], token)

    def test_unconfirmed_push_does_not_claim(self):
        class DroppedPush(GitCoordinator):
            def _git(self, *args, **kwargs):
                if args[0] == "push":
                    raise CoordinationUnavailable("Simulated failure before remote accepted push")
                return super()._git(*args, **kwargs)
        c = self.coordinator(DroppedPush)
        c.max_attempts = 2
        with self.assertRaises(Conflict):
            c.claim_model("m1", "vm-1")
        self.assertIsNone(self.admin.status()["models"]["m1"]["owner"])

    def race_coordinators(self):
        barrier = threading.Barrier(2)
        class Racing(GitCoordinator):
            first_push = True
            def _push_and_confirm(self, commit):
                if self.first_push:
                    self.first_push = False
                    barrier.wait(timeout=10)
                return super()._push_and_confirm(commit)
        return self.coordinator(Racing), self.coordinator(Racing)

    def test_same_model_claim_race_has_exactly_one_winner(self):
        first, second = self.race_coordinators()
        def claim(c, owner):
            try:
                return (owner, c.claim_model("m1", owner))
            except CoordinationError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda x: claim(*x), [(first, "vm-a"), (second, "vm-b")]))
        winners = [result for result in results if result]
        self.assertEqual(len(winners), 1)
        model = self.admin.status()["models"]["m1"]
        self.assertEqual((model["owner"], model["model_token"]), winners[0])

    def test_same_job_claim_race_has_exactly_one_winner(self):
        token = self.admin.claim_model("m1", "vm-1")
        first, second = self.race_coordinators()
        def claim(c):
            try:
                return c.claim_job("m1", "vm-1", token)
            except CoordinationError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [first, second]))
        self.assertEqual(sum(result is not None for result in results), 1)
        board = self.admin.status()
        self.assertEqual(board["jobs"]["job-1"]["status"], "claimed")
        self.assertEqual(board["jobs"]["job-3"]["status"], "open")

    def test_different_model_race_preserves_both_updates(self):
        first, second = self.race_coordinators()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: pair[0].claim_model(pair[1], pair[1]),
                                    [(first, "m1"), (second, "m2")]))
        board = self.admin.status()
        self.assertEqual(board["models"]["m1"]["model_token"], results[0])
        self.assertEqual(board["models"]["m2"]["model_token"], results[1])
        self.assertEqual(sum(m["concurrency"] for m in board["models"].values()), 2)

    def test_global_reserved_concurrency_cap(self):
        self.admin.claim_model("m1", "vm-1", concurrency=2)
        with self.assertRaises(NoCapacity):
            self.coordinator().claim_model("m2", "vm-2", concurrency=1)
        self.assertIsNone(self.admin.status()["models"]["m2"]["owner"])


if __name__ == "__main__":
    unittest.main()
