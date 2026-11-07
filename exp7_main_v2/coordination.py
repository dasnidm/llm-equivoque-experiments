"""Version 2 Git caches: durable negotiation tips and protected pending pushes.

The scientific protocol and v1 coordination state machine are unchanged.
Tracking refs prevent every new fetch from negotiating with an empty local
history. Pending refs protect commits until remote acknowledgement is verified.
All cache mutations and maintenance must run under the caller's local lock.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from exp7_main.coordination import (
    BOARD_PATH, Conflict, CoordinationError, CoordinationUnavailable,
    GitCoordinator as _V1GitCoordinator, NoCapacity, OwnershipError,
    SCHEMA_VERSION, Stopped, TERMINAL, new_board, render_readme, utc_now,
    validate_board,
)


TRACKING_REF = "refs/remotes/exp7/head"
PENDING_PREFIX = "refs/exp7/pending/"


def _git(cache_dir, *args, timeout=30, check=True):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(["git", "--git-dir", str(cache_dir), *args],
                                text=True, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CoordinationUnavailable("Git cache operation unavailable or timed out") from exc
    if check and result.returncode:
        # Remote and helper errors can contain credentials; keep them out of logs.
        raise CoordinationUnavailable(f"Git cache operation failed (exit {result.returncode})")
    return result


def _resolve(cache_dir, ref, timeout=30):
    result = _git(cache_dir, "show-ref", "--verify", "--hash", ref, timeout=timeout, check=False)
    if result.returncode == 1:
        return None
    if result.returncode:
        # show-ref returns128 for a missing ref in some Git versions.
        known = _git(cache_dir, "for-each-ref", "--format=%(objectname)", ref, timeout=timeout)
        if not known.stdout.strip():
            return None
        raise CoordinationUnavailable("Cannot resolve cache reference")
    return result.stdout.strip()


def fetch_tracking_head(remote: str, branch: str, cache_dir: str | Path,
                        timeout=30, tracking_ref=TRACKING_REF) -> str:
    """Fetch and persist a verified FF tip; caller holds its cache's local lock.

    FETCH_HEAD is only a temporary observation. The durable ref is changed only
    after the old tip is verified to be an ancestor of the observed remote tip.
    A deleted/missing/rewound branch never grants permission or resets the tip.
    """
    if not remote or str(remote).startswith("-"):
        raise ValueError("Invalid Git remote")
    _git(cache_dir, "check-ref-format", "refs/heads/" + branch, timeout=timeout)
    _git(cache_dir, "check-ref-format", tracking_ref, timeout=timeout)
    if not tracking_ref.startswith("refs/remotes/"):
        raise ValueError("Tracking reference must be under refs/remotes/")
    old = _resolve(cache_dir, tracking_ref, timeout)
    # Disable implicit maintenance. Explicit maintenance below preserves refs,
    # runs under the same lock, and never expires unreachable uncertain objects.
    _git(cache_dir, "-c", "gc.auto=0", "-c", "maintenance.auto=false", "fetch", "--no-tags",
         remote, "refs/heads/" + branch, timeout=timeout)
    head = _git(cache_dir, "rev-parse", "FETCH_HEAD^{commit}", timeout=timeout).stdout.strip()
    if old is not None:
        ancestry = _git(cache_dir, "merge-base", "--is-ancestor", old, head, timeout=timeout, check=False)
        if ancestry.returncode == 1:
            raise Conflict("Remote branch rewound or diverged; retained previous tracking tip")
        if ancestry.returncode:
            raise CoordinationUnavailable("Cannot verify remote branch ancestry")
    expected = old or "0" * len(head)
    _git(cache_dir, "update-ref", tracking_ref, head, expected, timeout=timeout)
    return head


def protect_pending_commit(cache_dir: str | Path, commit: str, timeout=30) -> str:
    """Durably retain the new commit before sending a push; caller holds lock."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("A full commit ID is required")
    kind = _git(cache_dir, "cat-file", "-t", commit, timeout=timeout).stdout.strip()
    if kind != "commit":
        raise ValueError("Only a commit can be protected as a pending push")
    ref = PENDING_PREFIX + commit
    current = _resolve(cache_dir, ref, timeout)
    if current not in (None, commit):
        raise CoordinationError("Pending reference points to a different object")
    _git(cache_dir, "update-ref", ref, commit, current or "0" * len(commit), timeout=timeout)
    return ref


def release_confirmed_pending(cache_dir: str | Path, pending_ref: str,
                              confirmed_head: str, timeout=30,
                              tracking_ref=TRACKING_REF) -> bool:
    """Release only after confirmation is reachable from the durable remote tip."""
    if not pending_ref.startswith(PENDING_PREFIX):
        raise ValueError("Not an Exp7 pending reference")
    commit = _resolve(cache_dir, pending_ref, timeout)
    if commit is None:
        return False
    tracked = _resolve(cache_dir, tracking_ref, timeout)
    if tracked is None:
        raise CoordinationError("No durable remote tip; pending push remains protected")
    for ancestor, descendant in ((commit, confirmed_head), (confirmed_head, tracked)):
        verified = _git(cache_dir, "merge-base", "--is-ancestor", ancestor, descendant,
                        timeout=timeout, check=False)
        if verified.returncode:
            raise CoordinationError("Push is not durably confirmed; pending reference retained")
    _git(cache_dir, "update-ref", "-d", pending_ref, commit, timeout=timeout)
    return True


def safe_cache_repack(cache_dir: str | Path, timeout=60, compact=False,
                      tracking_ref=TRACKING_REF) -> dict:
    """Pack under caller's lock; never run prune or an expiry command.

    A tracking ref must exist, and all pending push refs are verified before and
    after packing. Incremental packing bounds loose objects; occasional compact
    packing also retains unreachable objects already in existing packs.
    """
    cache_dir = Path(cache_dir)
    if _git(cache_dir, "rev-parse", "--is-bare-repository", timeout=timeout).stdout.strip() != "true":
        raise CoordinationError("Only a dedicated bare cache may be maintained")
    if _resolve(cache_dir, tracking_ref, timeout) is None:
        raise CoordinationError("No tracked remote head; skip cache maintenance")
    refs_before = _git(cache_dir, "for-each-ref", "--format=%(refname) %(objectname)",
                       PENDING_PREFIX, timeout=timeout).stdout
    command = ["repack", "-d", "--keep-unreachable", "--no-write-bitmap-index"]
    if compact:
        command.append("-a")
    _git(cache_dir, *command, timeout=timeout)
    refs_after = _git(cache_dir, "for-each-ref", "--format=%(refname) %(objectname)",
                      PENDING_PREFIX, timeout=timeout).stdout
    if refs_before != refs_after:
        raise CoordinationError("Pending references changed during cache maintenance")
    for line in refs_before.splitlines():
        _, commit = line.split(" ", 1)
        _git(cache_dir, "cat-file", "-e", commit + "^{commit}", timeout=timeout)
    return {"at": utc_now(), "compact": bool(compact), "pending_refs": len(refs_before.splitlines()),
            "git_count_objects": _git(cache_dir, "count-objects", "-v", timeout=timeout).stdout.strip()}


def maybe_maintain_cache(cache_dir: str | Path, *, every=128, timeout=60,
                          tracking_ref=TRACKING_REF) -> dict | None:
    """Increment a bounded metadata file and pack periodically under caller lock.

    Maintenance errors are recorded separately from already confirmed remote
    operations; they never cause an inference retry. No scientific files live in
    this dedicated cache. This function does not expire uncertain pending refs.
    """
    if not isinstance(every, int) or isinstance(every, bool) or every < 1:
        raise ValueError("Maintenance period must be a positive integer")
    cache_dir = Path(cache_dir)
    path = cache_dir / "maintenance.json"
    if path.exists():
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise CoordinationError("Invalid cache maintenance metadata") from exc
    else:
        state = {"confirmed_operations": 0, "last_maintenance_operation": 0}
    state["confirmed_operations"] += 1
    if state["confirmed_operations"] - state["last_maintenance_operation"] >= every:
        try:
            compact = len(list((cache_dir / "objects" / "pack").glob("*.pack"))) >= 16
            state["last_result"] = safe_cache_repack(cache_dir, timeout=timeout,
                                                     compact=compact, tracking_ref=tracking_ref)
            state.pop("maintenance_error", None)
        except CoordinationError as exc:
            state["maintenance_error"] = {"at": utc_now(), "message": str(exc)}
        state["last_maintenance_operation"] = state["confirmed_operations"]
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(state, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return state.get("last_result")


class GitCoordinator(_V1GitCoordinator):
    def __init__(self, *args, maintenance_every=128, **kwargs):
        self.maintenance_every = maintenance_every
        super().__init__(*args, **kwargs)

    def _read(self):
        head = fetch_tracking_head(self.remote, self.branch, self.cache_dir, self.timeout)
        try:
            board = json.loads(self._git("show", head + ":" + BOARD_PATH))
        except (ValueError, TypeError) as exc:
            raise CoordinationError("Remote board is not valid JSON") from exc
        validate_board(board)
        return head, board

    def _push_and_confirm(self, commit):
        pending_ref = protect_pending_commit(self.cache_dir, commit, self.timeout)
        confirmed = super()._push_and_confirm(commit)
        if confirmed is not None:
            head = _resolve(self.cache_dir, TRACKING_REF, self.timeout)
            release_confirmed_pending(self.cache_dir, pending_ref, head, self.timeout)
            maybe_maintain_cache(self.cache_dir, every=self.maintenance_every)
        # A rejected or ambiguous commit stays protected until explicit review.
        return confirmed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", default="exp7/main-v2-coordination")
    parser.add_argument("--cache-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    boot = commands.add_parser("bootstrap")
    boot.add_argument("--board", type=Path, required=True)
    for name in ("stop", "resume"):
        item = commands.add_parser(name)
        item.add_argument("--reason", required=True)
    args = parser.parse_args()
    coordinator = GitCoordinator(args.remote, args.branch, args.cache_dir)
    if args.command == "bootstrap":
        board = coordinator.bootstrap(json.loads(args.board.read_text()))
    elif args.command in {"stop", "resume"}:
        board = coordinator.set_stop(args.command == "stop", args.reason)
    else:
        board = coordinator.status()
    print(json.dumps(board, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
