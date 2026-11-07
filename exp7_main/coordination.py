"""Fail-closed, Git-backed coordination for independent Exp7 main workers.

The common branch is the authority. A mutation is committed on its freshly
fetched head, pushed without force/rebase, and read back before permission is
returned. Git operations may be retried; this module never retries inference.
The cache is a dedicated bare repository, not an experimental source checkout.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable
from urllib.parse import quote, urlsplit
import uuid


BOARD_PATH = "board.json"
SCHEMA_VERSION = 1
TERMINAL = {"complete", "partial_failed", "blocked"}


class CoordinationError(RuntimeError):
    """No inference permission follows an unsuccessful coordination operation."""


class CoordinationUnavailable(CoordinationError):
    pass


class Conflict(CoordinationError):
    pass


class OwnershipError(CoordinationError):
    pass


class Stopped(CoordinationError):
    pass


class NoCapacity(CoordinationError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _positive_int(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_board(board: dict) -> None:
    """Reject malformed assignments and lost ownership rather than guessing."""
    if board.get("schema_version") != SCHEMA_VERSION:
        raise CoordinationError("Unsupported board schema")
    if not board.get("run_id") or not _sha256(board.get("manifest_sha256")):
        raise CoordinationError("Run identity or manifest SHA-256 missing")
    if not re.fullmatch(r"[0-9a-f]{40,64}", board.get("source_commit", "")):
        raise CoordinationError("Frozen source commit is required")
    if "freeze_sha256" in board and not _sha256(board["freeze_sha256"]):
        raise CoordinationError("Invalid frozen execution contract SHA-256")
    if not isinstance(board.get("global_stop"), bool):
        raise CoordinationError("Explicit global_stop is required")
    if not _positive_int(board.get("global_max_concurrency")):
        raise CoordinationError("Invalid global concurrency cap")
    models, jobs = board.get("models"), board.get("jobs")
    if not isinstance(models, dict) or not models or not isinstance(jobs, dict) or not jobs:
        raise CoordinationError("Models and jobs must be nonempty mappings")
    ids, orders = set(), set()
    for job_id, job in jobs.items():
        if job.get("job_id") != job_id or job.get("model") not in models:
            raise CoordinationError("Job identity/model mismatch")
        if job.get("status") not in {"open", "claimed", "running"} | TERMINAL:
            raise CoordinationError("Unknown job state")
        trial_ids = job.get("trial_ids")
        if not isinstance(trial_ids, list) or not trial_ids:
            raise CoordinationError("Jobs require nonempty trial_ids")
        if any(not isinstance(t, str) or not t for t in trial_ids):
            raise CoordinationError("Invalid trial ID")
        if len(set(trial_ids)) != len(trial_ids) or ids.intersection(trial_ids):
            raise CoordinationError("Trial IDs overlap across jobs")
        ids.update(trial_ids)
        if job.get("n_trials") != len(trial_ids) or job.get("call_cap") != 34 * len(trial_ids):
            raise CoordinationError("Job budget differs from assigned conversations")
        if not isinstance(job.get("order"), int) or job["order"] in orders:
            raise CoordinationError("Job order is missing or duplicated")
        orders.add(job["order"])
        if job["status"] != "open" and (not job.get("owner") or not job.get("claim_token")):
            raise CoordinationError("Claimed job lacks ownership evidence")
    reserved = 0
    for name, model in models.items():
        if model.get("model") != name:
            raise CoordinationError("Model identity mismatch")
        if model.get("owner") is not None:
            if not model.get("model_token") or not _positive_int(model.get("concurrency")):
                raise CoordinationError("Claimed model lacks concurrency/ownership")
            reserved += model["concurrency"]
    if reserved > board["global_max_concurrency"]:
        raise CoordinationError("Reserved concurrency exceeds global cap")


def new_board(run_id: str, manifest_sha256: str, source_commit: str,
              jobs: list[dict], *, global_stop: bool = True,
              global_max_concurrency: int = 10, freeze_sha256: str | None = None) -> dict:
    """Make a stopped-by-default board from immutable disjoint assignments."""
    now = utc_now()
    board = {"schema_version": SCHEMA_VERSION, "run_id": run_id,
             "manifest_sha256": manifest_sha256, "source_commit": source_commit,
             "created_at": now, "updated_at": now, "global_stop": global_stop,
             "stop_reason": "Awaiting launch readiness" if global_stop else "Initial launch enabled",
             "global_max_concurrency": global_max_concurrency, "models": {}, "jobs": {}}
    if freeze_sha256 is not None:
        board["freeze_sha256"] = freeze_sha256
    for order, raw in enumerate(jobs):
        item = deepcopy(raw)
        job_id, model = item["job_id"], item["model"]
        if job_id in board["jobs"]:
            raise CoordinationError("Duplicate job ID")
        item.update(order=order, status="open", owner=None, claim_token=None,
                    claimed_at=None, heartbeat_at=None, result_ref=None, result_sha256=None,
                    counts={"complete": 0, "failed": 0, "interrupted": 0,
                            "unstarted": len(item["trial_ids"])}, calls=0)
        item["n_trials"] = len(item["trial_ids"])
        item["call_cap"] = 34 * item["n_trials"]
        board["jobs"][job_id] = item
        board["models"].setdefault(model, {"model": model, "owner": None,
            "model_token": None, "concurrency": 0, "claimed_at": None, "heartbeat_at": None})
    validate_board(board)
    return board


def _github_repository_url(remote: str) -> str | None:
    """Derive public navigation links without copying credentials into README."""
    if remote.startswith("git@github.com:"):
        path = remote[len("git@github.com:"):]
    else:
        parsed = urlsplit(remote)
        if parsed.scheme not in {"http", "https", "ssh"} or parsed.hostname != "github.com":
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git").rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        return None
    return "https://github.com/" + path


def _md(value) -> str:
    return (html.escape(str(value), quote=False).replace("\n", " ")
            .replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;")
            .replace("`", "&#96;"))


def render_readme(board: dict, repository_url: str | None = None) -> str:
    """Render a compact branch landing page from the same committed board."""
    validate_board(board)
    jobs = list(board["jobs"].values())
    count_keys = ("complete", "failed", "interrupted", "unstarted")
    status_keys = ("open", "claimed", "running", "complete", "partial_failed", "blocked")
    totals = {key: sum(j["counts"][key] for j in jobs) for key in count_keys}
    assigned = sum(j["n_trials"] for j in jobs)
    calls = sum(j["calls"] for j in jobs)
    reserved = sum(m["concurrency"] for m in board["models"].values() if m["owner"] is not None)
    enabled = "STOP — 새 호출 중단" if board["global_stop"] else "ENABLED — 작업 선점·실행 허용"
    lines = ["# 실험 7 작업 현황", "", f"**{enabled}**", "",
             f"- 실행: `{_md(board['run_id'])}`",
             f"- 갱신 시각: {_md(board['updated_at'])} (UTC)",
             f"- 상태 사유: {_md(board.get('stop_reason', ''))}",
             f"- 예약 병렬 수 / 전역 상한: **{reserved} / {board['global_max_concurrency']}**",
             f"- 배정: **{assigned:,}대화 · {len(jobs):,}작업**",
             f"- 보고된 대화: 완료 **{totals['complete']:,}**, 실패 **{totals['failed']:,}**, "
             f"중단 **{totals['interrupted']:,}**, 미시작·미보고 **{totals['unstarted']:,}**",
             f"- 보고된 논리 호출: **{calls:,} / {sum(j['call_cap'] for j in jobs):,}**", "",
             "[전체 작업·소유권·결과 참조 JSON](board.json)", "",
             "대화·호출 집계는 작업 결과가 게시될 때 갱신된다. 미시작·미보고에는 아직 결과가 게시되지 않은 "
             "실행 중 작업도 포함된다. 예약 병렬 수는 실제 진행 중인 요청 수가 아니다. "
             "STOP 전파에는 작업자의 확인 주기와 진행 중 요청 종료 시간이 필요하다.", "",
             "| 모델 | 담당 VM | 예약 병렬 | 작업 상태¹ | 대화 상태² | 보고 호출 | 마지막 heartbeat (UTC) |",
             "|---|---|---:|---|---|---:|---|"]
    for name, model in sorted(board["models"].items()):
        selected = [j for j in jobs if j["model"] == name]
        states = "/".join(str(sum(j["status"] == key for j in selected)) for key in status_keys)
        counts = "/".join(f"{sum(j['counts'][key] for j in selected):,}" for key in count_keys)
        lines.append(f"| {_md(name)} | {_md(model['owner'] or '미배정')} | {model['concurrency']} | "
                     f"{states} | {counts} | {sum(j['calls'] for j in selected):,} | "
                     f"{_md(model.get('heartbeat_at') or '—')} |")
    lines.extend(["", "¹ 작업: 미배정 / 선점 / 실행 / 완료 / 일부 실패 / 보류.",
                  "² 대화: 완료 / 실패 / 중단 / 미시작·미보고.", "", "## 동결 정보", ""])
    commit = board["source_commit"]
    source = f"[`{commit}`]({repository_url}/tree/{commit})" if repository_url else f"`{commit}`"
    lines.extend([f"- 소스 commit: {source}", f"- 배정 요약 SHA-256: `{board['manifest_sha256']}`"])
    if board.get("freeze_sha256"):
        lines.append(f"- 실행 계약 SHA-256: `{board['freeze_sha256']}`")
    completed = sorted((j for j in jobs if j.get("result_ref")),
                       key=lambda j: (j.get("completed_at", ""), j["order"]), reverse=True)
    lines.extend(["", "## 최근 게시 결과", ""])
    if not completed:
        lines.append("게시된 작업 결과가 없다.")
    else:
        lines.extend(["최근 20개까지 표시한다. 전체 목록과 결과 SHA-256은 board.json에 보존한다.", "",
                      "| 작업 | 모델 | 상태 | 결과 |", "|---|---|---|---|"])
        for item in completed[:20]:
            ref = item["result_ref"]
            match = re.fullmatch(r"([0-9a-f]{7,64}):(.+)", ref)
            if repository_url and match and not Path(match[2]).is_absolute() and ".." not in Path(match[2]).parts:
                result = f"[결과 보기]({repository_url}/blob/{match[1]}/{quote(match[2], safe='/')})"
            else:
                result = f"`{_md(ref)}`"
            lines.append(f"| {_md(item['job_id'])} | {_md(item['model'])} | {_md(item['status'])} | {result} |")
    lines.extend(["", "작업은 원격 선점 확인 후 실행한다. 중단·응답 불확실·보류 작업은 자동으로 재배정하지 않는다.", ""])
    return "\n".join(lines)


class GitCoordinator:
    def __init__(self, remote: str, branch: str, cache_dir: str | Path,
                 timeout: float = 30, max_attempts: int = 5):
        if not remote or not branch or branch.startswith("-"):
            raise ValueError("A remote and a named coordination branch are required")
        if timeout <= 0 or max_attempts < 1:
            raise ValueError("Invalid timeout/retry count")
        self.remote, self.branch = str(remote), branch
        self.cache_dir = Path(cache_dir).resolve()
        self.timeout, self.max_attempts = timeout, max_attempts
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock():
            if not (self.cache_dir / "HEAD").exists():
                if any(p.name != ".coordinator.lock" for p in self.cache_dir.iterdir()):
                    raise CoordinationError("Cache must be empty or a dedicated bare repository")
                self._git("init", "--bare", ".")
            if self._git("rev-parse", "--is-bare-repository").strip() != "true":
                raise CoordinationError("Coordination cache must be bare")
            self._git("check-ref-format", "refs/heads/" + self.branch)

    @contextmanager
    def _lock(self):
        with (self.cache_dir / ".coordinator.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _git(self, *args: str, input_text: str | None = None,
             env_extra: dict | None = None, check: bool = True) -> str | subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update(GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="Exp7 Coordinator",
                   GIT_AUTHOR_EMAIL="exp7-coordinator@invalid", GIT_COMMITTER_NAME="Exp7 Coordinator",
                   GIT_COMMITTER_EMAIL="exp7-coordinator@invalid")
        if env_extra:
            env.update(env_extra)
        try:
            result = subprocess.run(["git", "-C", str(self.cache_dir), *args],
                input=input_text, text=True, capture_output=True, timeout=self.timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CoordinationUnavailable("Git operation unavailable or timed out; no permission granted") from exc
        if not check:
            return result
        if result.returncode:
            # Do not echo arbitrary remote/helper output, which can contain credentials.
            raise CoordinationUnavailable(f"Git {args[0]} failed (exit {result.returncode}); no permission granted")
        return result.stdout

    def _read(self) -> tuple[str, dict]:
        self._git("fetch", "--no-tags", self.remote, "refs/heads/" + self.branch)
        head = self._git("rev-parse", "FETCH_HEAD").strip()
        try:
            board = json.loads(self._git("show", head + ":" + BOARD_PATH))
        except (ValueError, TypeError) as exc:
            raise CoordinationError("Remote board is not valid JSON") from exc
        validate_board(board)
        return head, board

    def status(self) -> dict:
        with self._lock():
            _, board = self._read()
            return board

    def _commit(self, parent: str | None, board: dict, message: str) -> str:
        validate_board(board)
        content = json.dumps(board, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        blob = self._git("hash-object", "-w", "--stdin", input_text=content).strip()
        readme_blob = self._git("hash-object", "-w", "--stdin",
            input_text=render_readme(board, _github_repository_url(self.remote))).strip()
        with tempfile.TemporaryDirectory(prefix="coord-index-", dir=self.cache_dir) as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self._git("read-tree", parent if parent else "--empty", env_extra=env)
            self._git("update-index", "--add", "--cacheinfo", "100644", blob, BOARD_PATH, env_extra=env)
            self._git("update-index", "--add", "--cacheinfo", "100644", readme_blob, "README.md", env_extra=env)
            tree = self._git("write-tree", env_extra=env).strip()
        args = ["commit-tree", tree]
        if parent:
            args += ["-p", parent]
        return self._git(*args, input_text=message + "\n").strip()

    def _push_and_confirm(self, commit: str) -> dict | None:
        # Even an error/timeout may mean the remote accepted the push. Always read back.
        try:
            self._git("push", "--porcelain", self.remote,
                      commit + ":refs/heads/" + self.branch, check=False)
        except CoordinationUnavailable:
            pass
        head, board = self._read()
        ancestor = self._git("merge-base", "--is-ancestor", commit, head, check=False)
        return board if ancestor.returncode == 0 else None

    def bootstrap(self, board: dict) -> dict:
        """Create a new coordination branch only; never overwrite an existing one."""
        validate_board(board)
        with self._lock():
            refs = self._git("ls-remote", "--heads", self.remote, "refs/heads/" + self.branch)
            if refs.strip():
                raise Conflict("Coordination branch already exists; inspect status instead")
            commit = self._commit(None, board, "Initialize " + board["run_id"] + " coordination")
            confirmed = self._push_and_confirm(commit)
            if confirmed is None:
                raise Conflict("Another initializer won; existing board preserved")
            return confirmed

    def _mutate(self, label: str, fn: Callable[[dict], None]) -> dict:
        with self._lock():
            identity = None
            for _ in range(self.max_attempts):
                parent, board = self._read()
                current_identity = (board["run_id"], board["manifest_sha256"], board["source_commit"], board.get("freeze_sha256"))
                if identity is None:
                    identity = current_identity
                elif current_identity != identity:
                    raise CoordinationError("Frozen run identity changed during coordination")
                fn(board)  # Recheck all preconditions against every new remote head.
                board["updated_at"] = utc_now()
                commit = self._commit(parent, board, label)
                confirmed = self._push_and_confirm(commit)
                if confirmed is not None:
                    return confirmed
            raise Conflict("Concurrent board updates prevented confirmation; no permission granted")

    @staticmethod
    def _model(board: dict, model: str, owner: str, model_token: str, *, allow_stop=False) -> dict:
        if board["global_stop"] and not allow_stop:
            raise Stopped(board.get("stop_reason", "Global stop"))
        item = board["models"].get(model)
        if item is None or not owner or not model_token or (item["owner"], item["model_token"]) != (owner, model_token):
            raise OwnershipError("Model ownership/token not confirmed")
        return item

    @classmethod
    def _job(cls, board: dict, model: str, owner: str, model_token: str,
             job_id: str, claim_token: str, *, allow_stop=False) -> dict:
        cls._model(board, model, owner, model_token, allow_stop=allow_stop)
        item = board["jobs"].get(job_id)
        if item is None or not claim_token or (item["model"], item["owner"], item["claim_token"]) != (model, owner, claim_token):
            raise OwnershipError("Job ownership/token not confirmed")
        return item

    def claim_model(self, model: str, owner: str, concurrency: int = 1) -> str:
        if not owner or not _positive_int(concurrency):
            raise ValueError("Owner and positive concurrency required")
        token = uuid.uuid4().hex
        def change(board):
            if board["global_stop"]:
                raise Stopped(board["stop_reason"])
            item = board["models"].get(model)
            if item is None:
                raise OwnershipError("Model is not assigned in this run")
            if item["owner"] is not None:
                raise OwnershipError("Model already claimed; automatic takeover is prohibited")
            reserved = sum(m["concurrency"] for m in board["models"].values() if m["owner"] is not None)
            if reserved + concurrency > board["global_max_concurrency"]:
                raise NoCapacity("Global reserved concurrency cap would be exceeded")
            item.update(owner=owner, model_token=token, concurrency=concurrency,
                        claimed_at=utc_now(), heartbeat_at=utc_now())
        board = self._mutate("Claim model " + model + " for " + owner, change)
        self._model(board, model, owner, token)
        return token

    def claim_job(self, model: str, owner: str, model_token: str) -> dict | None:
        token, selected = uuid.uuid4().hex, []
        def change(board):
            self._model(board, model, owner, model_token)
            candidates = [j for j in board["jobs"].values() if j["model"] == model]
            if any(j["status"] in {"claimed", "running", "blocked"} for j in candidates):
                raise Conflict("Model has a claimed/running/blocked job; inspect it before proceeding")
            opened = [j for j in candidates if j["status"] == "open"]
            if not opened:
                return
            item = min(opened, key=lambda j: j["order"])
            selected[:] = [item["job_id"]]
            item.update(status="claimed", owner=owner, claim_token=token,
                        claimed_at=utc_now(), heartbeat_at=utc_now())
        board = self._mutate("Claim next job for " + model, change)
        if not selected:
            return None
        return deepcopy(self._job(board, model, owner, model_token, selected[0], token))

    def assert_permission(self, model: str, owner: str, model_token: str,
                          job_id: str, claim_token: str) -> dict:
        item = self._job(self.status(), model, owner, model_token, job_id, claim_token)
        if item["status"] not in {"claimed", "running"}:
            raise OwnershipError("Job is not executable")
        return deepcopy(item)

    def mark_running(self, model: str, owner: str, model_token: str,
                     job_id: str, claim_token: str) -> dict:
        def change(board):
            item = self._job(board, model, owner, model_token, job_id, claim_token)
            if item["status"] not in {"claimed", "running"}:
                raise Conflict("Cannot start a terminal job")
            item.update(status="running", heartbeat_at=utc_now())
        board = self._mutate("Start " + job_id, change)
        return deepcopy(self._job(board, model, owner, model_token, job_id, claim_token))

    def heartbeat(self, model: str, owner: str, model_token: str,
                  job_id: str | None = None, claim_token: str | None = None) -> dict:
        def change(board):
            self._model(board, model, owner, model_token, allow_stop=True)["heartbeat_at"] = utc_now()
            if job_id:
                self._job(board, model, owner, model_token, job_id, claim_token, allow_stop=True)["heartbeat_at"] = utc_now()
        return self._mutate("Heartbeat " + owner, change)

    def complete_job(self, model: str, owner: str, model_token: str, job_id: str,
                     claim_token: str, counts: dict, calls: int,
                     result_ref: str, result_sha256: str) -> dict:
        if not result_ref or not _sha256(result_sha256):
            raise ValueError("Immutable result reference and SHA-256 required")
        if set(counts) != {"complete", "failed", "interrupted", "unstarted"}:
            raise ValueError("All four outcome counts are required")
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values()):
            raise ValueError("Counts must be nonnegative integers")
        if not isinstance(calls, int) or isinstance(calls, bool) or calls < 0:
            raise ValueError("Calls must be a nonnegative integer")
        def change(board):
            item = self._job(board, model, owner, model_token, job_id, claim_token, allow_stop=True)
            if sum(counts.values()) != item["n_trials"] or calls > item["call_cap"]:
                raise ValueError("Outcome total or call budget mismatch")
            if calls < counts["complete"] * 34:
                raise ValueError("Complete conversations require 34 logical calls each")
            desired = "blocked" if counts["unstarted"] else ("complete" if counts["complete"] == item["n_trials"] else "partial_failed")
            payload = dict(status=desired, counts=deepcopy(counts), calls=calls,
                           result_ref=result_ref, result_sha256=result_sha256)
            if item["status"] in TERMINAL:
                if any(item.get(k) != v for k, v in payload.items()):
                    raise Conflict("Terminal result already recorded; no replacement allowed")
                return
            if item["status"] not in {"claimed", "running"}:
                raise Conflict("Only a claimed job can be completed")
            item.update(payload, completed_at=utc_now(), heartbeat_at=utc_now())
        board = self._mutate("Record result for " + job_id, change)
        return deepcopy(self._job(board, model, owner, model_token, job_id, claim_token, allow_stop=True))

    def set_stop(self, stopped: bool, reason: str) -> dict:
        if not isinstance(stopped, bool) or not reason.strip():
            raise ValueError("An explicit stop state and reason are required")
        def change(board):
            board.update(global_stop=stopped, stop_reason=reason, stop_updated_at=utc_now())
        return self._mutate(("Stop: " if stopped else "Resume: ") + reason, change)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", default="exp7/main-v1-coordination")
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
