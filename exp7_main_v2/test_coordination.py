"""Real local-Git checks for v2 cache durability; no model/network calls."""
import json
import os
from pathlib import Path
import subprocess
import threading
from unittest import mock
import unittest

from exp7_main import test_coordination as v1_tests
from exp7_main_v2.coordination import (
    Conflict, CoordinationError, CoordinationUnavailable, GitCoordinator,
    PENDING_PREFIX, TRACKING_REF, fetch_tracking_head, maybe_maintain_cache,
    protect_pending_commit, release_confirmed_pending, safe_cache_repack,
)


class CoordinationV2Tests(v1_tests.CoordinationTests):
    """Keep the v1 ownership/race regressions, plus durable-cache invariants."""
    def coordinator(self, cls=GitCoordinator):
        self.counter += 1
        return cls(str(self.remote), self.branch, self.root / f"cache-{self.counter}")

    def git(self, cache, *args):
        return subprocess.check_output(["git", "--git-dir", str(cache), *args], text=True).strip()

    def pending(self, cache):
        return self.git(cache, "for-each-ref", "--format=%(refname)", PENDING_PREFIX).splitlines()

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

    def test_tracking_ref_is_present_after_bootstrap_and_status(self):
        initial = self.git(self.admin.cache_dir, "rev-parse", TRACKING_REF)
        client = self.coordinator()
        client.status()
        self.assertEqual(self.git(client.cache_dir, "rev-parse", TRACKING_REF), initial)
        self.assertEqual(self.pending(self.admin.cache_dir), [])
        state = json.loads((self.admin.cache_dir / "maintenance.json").read_text())
        self.assertEqual(state["confirmed_operations"], 1)

    def test_next_fetch_advertises_previous_head(self):
        client = self.coordinator()
        client.status()
        old = self.git(client.cache_dir, "rev-parse", TRACKING_REF)
        self.admin.set_stop(True, "Trace incremental fetch")
        trace = self.root / "packets.txt"
        with mock.patch.dict(os.environ, {"GIT_TRACE_PACKET": str(trace)}):
            client.status()
        self.assertIn("fetch> have " + old, trace.read_text())
        self.assertNotEqual(self.git(client.cache_dir, "rev-parse", TRACKING_REF), old)

    def test_remote_rewind_is_rejected_and_tracking_tip_retained(self):
        first = self.git(self.admin.cache_dir, "rev-parse", TRACKING_REF)
        self.admin.set_stop(True, "Later remote revision")
        client = self.coordinator()
        client.status()
        later = self.git(client.cache_dir, "rev-parse", TRACKING_REF)
        # Simulate an external remote rewind in this disposable local fixture.
        self.git(self.remote, "update-ref", "refs/heads/" + self.branch, first, later)
        with self.assertRaises(Conflict):
            client.status()
        self.assertEqual(self.git(client.cache_dir, "rev-parse", TRACKING_REF), later)
        self.assertEqual(self.git(client.cache_dir, "cat-file", "-t", later), "commit")

    def test_ambiguous_push_retains_commit_and_board_through_repack(self):
        class DroppedPush(GitCoordinator):
            def _git(self, *args, **kwargs):
                if args[0] == "push":
                    raise CoordinationUnavailable("Simulated response uncertainty")
                return super()._git(*args, **kwargs)
        client = self.coordinator(DroppedPush)
        client.max_attempts = 1
        with self.assertRaises(Conflict):
            client.claim_model("m1", "vm-uncertain")
        refs = self.pending(client.cache_dir)
        self.assertEqual(len(refs), 1)
        pending_commit = self.git(client.cache_dir, "rev-parse", refs[0])
        before = self.git(client.cache_dir, "show", pending_commit + ":board.json")
        self.assertEqual(json.loads(before)["models"]["m1"]["owner"], "vm-uncertain")
        with client._lock():
            safe_cache_repack(client.cache_dir, compact=True)
        self.assertEqual(self.pending(client.cache_dir), refs)
        self.assertEqual(self.git(client.cache_dir, "show", pending_commit + ":board.json"), before)
        self.assertIsNone(self.admin.status()["models"]["m1"]["owner"])
        confirmed = self.git(client.cache_dir, "rev-parse", TRACKING_REF)
        with client._lock(), self.assertRaises(CoordinationError):
            release_confirmed_pending(client.cache_dir, refs[0], confirmed)
        self.assertEqual(self.pending(client.cache_dir), refs)

    def test_lost_ack_retains_tracking_tip_and_releases_confirmed_pending(self):
        class LostAck(GitCoordinator):
            def _git(self, *args, **kwargs):
                value = super()._git(*args, **kwargs)
                if args[0] == "push":
                    raise CoordinationUnavailable("Lost acknowledgement after accepted push")
                return value
        client = self.coordinator(LostAck)
        token = client.claim_model("m1", "vm-1")
        self.assertEqual(client.status()["models"]["m1"]["model_token"], token)
        self.assertEqual(self.pending(client.cache_dir), [])
        head = self.git(client.cache_dir, "rev-parse", TRACKING_REF)
        self.assertEqual(self.git(client.cache_dir, "cat-file", "-t", head), "commit")

    def test_maintenance_is_periodic_and_preserves_reachable_data(self):
        client = GitCoordinator(str(self.remote), self.branch, self.root / "maintenance.git", maintenance_every=2)
        client.set_stop(True, "First update")
        self.assertFalse(list((client.cache_dir / "objects" / "pack").glob("*.pack")))
        client.set_stop(False, "Second update")
        self.assertTrue(list((client.cache_dir / "objects" / "pack").glob("*.pack")))
        state = json.loads((client.cache_dir / "maintenance.json").read_text())
        self.assertEqual(state["confirmed_operations"], 2)
        self.assertEqual(state["last_maintenance_operation"], 2)
        self.assertNotIn("maintenance_error", state)
        self.assertFalse(client.status()["global_stop"])

    def test_maintenance_failure_does_not_retry_confirmed_operation(self):
        client = GitCoordinator(str(self.remote), self.branch, self.root / "maintenance-failure.git", maintenance_every=1)
        with mock.patch("exp7_main_v2.coordination.safe_cache_repack",
                        side_effect=CoordinationUnavailable("Synthetic packing failure")):
            token = client.claim_model("m1", "vm-1")
        self.assertEqual(client.status()["models"]["m1"]["model_token"], token)
        state = json.loads((client.cache_dir / "maintenance.json").read_text())
        self.assertIn("maintenance_error", state)
        self.assertEqual(state["confirmed_operations"], 1)
        self.assertEqual(self.pending(client.cache_dir), [])

    def test_malformed_tracking_and_pending_references_are_rejected(self):
        with self.admin._lock():
            with self.assertRaises(ValueError):
                fetch_tracking_head(str(self.remote), self.branch, self.admin.cache_dir,
                                    tracking_ref="refs/heads/unsafe")
            with self.assertRaises(ValueError):
                protect_pending_commit(self.admin.cache_dir, "HEAD")


if __name__ == "__main__":
    unittest.main()
