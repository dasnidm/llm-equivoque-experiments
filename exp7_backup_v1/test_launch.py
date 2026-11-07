"""Offline launcher ordering and exclusion tests; no real child/model/remote calls."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import launch


class FakeProcess:
    def __init__(self, pid, *, result=0, running=True):
        self.pid = pid
        self.result = result
        self.returncode = None if running else result
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self.result
        return self.result

    def terminate(self):
        self.terminated = True


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-backup-launch-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.args = SimpleNamespace(
            freeze=str(self.work / "freeze.json"), work_dir=str(self.work),
            repository="example/private-raw", model="fake-model", owner="vm-a",
            concurrency=3, timeout=300,
        )

    def commandline(self):
        return ["--freeze", self.args.freeze, "--work-dir", self.args.work_dir,
                "--repository", self.args.repository, "--model", self.args.model,
                "--owner", self.args.owner, "--concurrency", "3"]

    def status(self):
        return json.loads((self.work / "launch-v1" / "status.json").read_text())

    def mocks(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        private = stack.enter_context(patch.object(launch, "verify_private_repository"))
        freeze = stack.enter_context(patch.object(launch, "verify_freeze"))
        popen = stack.enter_context(patch.object(launch.subprocess, "Popen"))
        call = stack.enter_context(patch.object(launch.subprocess, "call", return_value=0))
        return private, freeze, popen, call

    def test_private_repository_failure_starts_no_child_and_redacts_error(self):
        private, freeze, popen, call = self.mocks()
        private.side_effect = RuntimeError("secret-token-and-private-path")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(launch.main(self.commandline()), 2)
        private.assert_called_once_with(self.args.repository)
        freeze.assert_not_called()
        popen.assert_not_called()
        call.assert_not_called()
        self.assertEqual(self.status()["stage"], "preflight_failed")
        self.assertNotIn("secret-token-and-private-path", output.getvalue())
        self.assertNotIn("secret-token-and-private-path", json.dumps(self.status()))

    def test_changed_frozen_source_starts_no_child(self):
        _, freeze, popen, call = self.mocks()
        freeze.side_effect = ValueError("Frozen source changed")
        with self.assertRaises(ValueError):
            launch.supervise(self.args)
        popen.assert_not_called()
        call.assert_not_called()
        self.assertEqual(self.status()["stage"], "preflight_failed")

    def test_duplicate_launcher_lock_starts_no_child_or_preflight(self):
        private, freeze, popen, call = self.mocks()
        with launch.launch_lock(self.work / "launch-v1"):
            with self.assertRaises(BlockingIOError):
                launch.supervise(self.args)
        private.assert_not_called()
        freeze.assert_not_called()
        popen.assert_not_called()
        call.assert_not_called()

    def test_existing_worker_lock_starts_no_child(self):
        private, freeze, popen, call = self.mocks()
        with (self.work / "worker.lock").open("a") as handle:
            launch.fcntl.flock(handle, launch.fcntl.LOCK_EX | launch.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                launch.supervise(self.args)
        private.assert_called_once()
        freeze.assert_called_once()
        popen.assert_not_called()
        call.assert_not_called()

    def test_failed_calibration_never_launches_evaluation_or_retry(self):
        _, _, popen, call = self.mocks()
        backup = FakeProcess(101)
        failed_prepare = FakeProcess(102, result=7)
        popen.side_effect = [backup, failed_prepare]
        self.assertEqual(launch.supervise(self.args), 7)
        commands = [item.args[0] for item in popen.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][1:4], ["-m", "exp7_backup_v1", "watch"])
        self.assertEqual(commands[1][1:4], ["-m", "exp7_main_v2.worker", "prepare"])
        self.assertTrue(backup.terminated)
        self.assertEqual(call.call_args.args[0][1:4], ["-m", "exp7_backup_v1", "once"])
        self.assertEqual(self.status()["worker_exit_code"], 7)

    def test_preflight_then_watch_then_prepare_then_run_then_final_backup(self):
        private, freeze, popen, call = self.mocks()
        events = []
        private.side_effect = lambda repository: events.append("private")
        freeze.side_effect = lambda path: events.append("freeze")
        processes = iter([FakeProcess(101), FakeProcess(102), FakeProcess(103)])

        def start(command, **kwargs):
            events.append(command[3])
            self.assertEqual(kwargs["stdin"], launch.subprocess.DEVNULL)
            return next(processes)

        popen.side_effect = start
        call.side_effect = lambda command, **kwargs: events.append(command[3]) or 0
        self.assertEqual(launch.supervise(self.args), 0)
        self.assertEqual(events, ["private", "freeze", "watch", "prepare", "run", "once"])
        commands = [item.args[0] for item in popen.call_args_list][1:]
        self.assertEqual(commands[0][4:], commands[1][4:])
        self.assertEqual(self.status()["stage"], "worker_returned")

    def test_already_dead_uploader_starts_no_worker(self):
        _, _, popen, _ = self.mocks()
        popen.return_value = FakeProcess(101, result=9, running=False)
        self.assertEqual(launch.supervise(self.args), 3)
        self.assertEqual(popen.call_count, 1)

    def test_worker_failure_is_not_hidden_by_successful_final_backup(self):
        _, _, popen, call = self.mocks()
        popen.side_effect = [FakeProcess(101), FakeProcess(102), FakeProcess(103, result=6)]
        call.return_value = 0
        self.assertEqual(launch.supervise(self.args), 6)
        self.assertEqual(self.status()["worker_exit_code"], 6)

    def test_final_backup_failure_is_reported_when_worker_succeeds(self):
        _, _, popen, call = self.mocks()
        popen.side_effect = [FakeProcess(101), FakeProcess(102), FakeProcess(103)]
        call.return_value = 8
        self.assertEqual(launch.supervise(self.args), 8)
        self.assertEqual(self.status()["backup_exit_code"], 8)

    def test_real_backup_entrypoint_propagates_non_success_exit_code(self):
        # An empty directory has no identity, so this never accesses GitHub,
        # creates a worker, or calls a model. Exercise the actual __main__.
        result = launch.subprocess.run(
            [launch.sys.executable, "-m", "exp7_backup_v1", "once",
             "--work-dir", str(self.work), "--repository", self.args.repository],
            cwd=launch.ROOT, stdin=launch.subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "waiting_identity")


if __name__ == "__main__":
    unittest.main()
