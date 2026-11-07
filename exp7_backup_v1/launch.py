"""Supervise the unchanged v2 worker and a separate private-archive uploader.

Run in a persistent terminal or detach this process. No inference retries, CLI
credential copying, source changes, or automatic model reassignment occur here.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from exp7_main_v2.worker import ROOT, now, verify_freeze
from exp7_pre.runner import atomic_json
from .sidecar import verify_private_repository


@contextmanager
def launch_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "launcher.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def worker_command(args, stage):
    options = ["--freeze", str(Path(args.freeze).resolve()), "--work-dir",
               str(Path(args.work_dir).resolve()), "--model", args.model,
               "--concurrency", str(args.concurrency), "--timeout", str(args.timeout)]
    if args.owner:
        options += ["--owner", args.owner]
    return [sys.executable, "-m", "exp7_main_v2.worker", stage, *options]


def stages(args, status, worker_log, backup_process):
    """A failed calibration never advances to evaluation or starts a retry."""
    for stage in ("prepare", "run"):
        if backup_process.poll() is not None:
            status("backup_process_exited", worker_stage=stage,
                   backup_exit_code=backup_process.returncode)
            return 3
        status(stage, backup_pid=backup_process.pid)
        process = subprocess.Popen(worker_command(args, stage), cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=worker_log,
                                   stderr=subprocess.STDOUT)
        status(stage, worker_pid=process.pid, backup_pid=backup_process.pid)
        code = process.wait()
        if code:
            status("worker_failed", worker_stage=stage, worker_exit_code=code)
            return code
    return 0


def supervise(args):
    work = Path(args.work_dir).resolve()
    directory = work / "launch-v1"
    with launch_lock(directory):
        def status(stage, **extra):
            atomic_json(directory / "status.json", {
                "stage": stage, "updated_at": now(), "pid": os.getpid(), **extra})

        status("preflight")
        # These checks precede claiming a model and all model requests.
        try:
            verify_private_repository(args.repository)
            verify_freeze(args.freeze)
            # Detect an already running worker without interfering with its lock.
            with (work / "worker.lock").open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as exc:
            status("preflight_failed", error_type=type(exc).__name__)
            raise
        base = [sys.executable, "-m", "exp7_backup_v1"]
        options = ["--work-dir", str(work), "--repository", args.repository]
        with (directory / "worker.log").open("ab", buffering=0) as worker_log, \
             (directory / "backup.log").open("ab", buffering=0) as backup_log:
            backup = subprocess.Popen(base + ["watch", *options, "--interval", "60"],
                                      cwd=ROOT, stdin=subprocess.DEVNULL,
                                      stdout=backup_log, stderr=subprocess.STDOUT)
            code = stages(args, status, worker_log, backup)
            # Worker has returned: stop only the uploader, then flush any newly
            # closed archives. Compressed archives are always retained locally.
            if backup.poll() is None:
                backup.terminate()
                try:
                    backup.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    status("backup_still_finishing", worker_exit_code=code,
                           backup_pid=backup.pid)
                    return code or 4
            flush = subprocess.call(base + ["once", *options], cwd=ROOT,
                                    stdin=subprocess.DEVNULL, stdout=backup_log,
                                    stderr=subprocess.STDOUT)
            status("worker_returned", worker_exit_code=code, backup_exit_code=flush,
                   note="Check authoritative board: a returned worker can be stopped or out of jobs.")
            return code or flush


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--repository", default="dasnidm/llm-equivoque-exp7-raw")
    parser.add_argument("--model", default="auto")
    parser.add_argument("--owner")
    parser.add_argument("--concurrency", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        return supervise(args)
    except Exception as exc:
        # External subprocess errors can include private paths or credentials.
        print(json.dumps({"stage": "launcher_failed", "error_type": type(exc).__name__,
                          "note": "Preserve the work directory; inspect private launch-v1 logs."}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
