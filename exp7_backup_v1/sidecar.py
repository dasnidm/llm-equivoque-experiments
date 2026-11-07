"""Back up verified terminal-job archives to an explicitly private repository.

This is an independent, versioned sidecar. It never calls a model, claims an
experiment job, modifies frozen source, deletes compressed archives, or reads
the shared Codex authentication/session databases. Only this worker's verified
v2 states/native archive, its index, and a derived completion record are sent.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

from exp7_pre.runner import atomic_json
from exp7_main_v2.storage import verify_archive, StorageError
from exp7_main_v2.worker import ResultPublisher

VERSION = "1.0.0"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,160}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_GIT_BLOB = 90 * 1024**2
NATIVE_NAMES = {"subject-system.txt", "prompt.txt", "events.jsonl", "stderr.txt", "schema.json"}


class BackupError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class BackupTransient(BackupError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(path):
    path = Path(path).absolute()
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise BackupError("unsafe_path", "Backup inputs must not contain symlinks")
    return path


def _regular(path):
    path = _path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise BackupError("unsafe_file", "Backup inputs must be regular files with one filesystem link")
    return path


def _read(path):
    return json.loads(_regular(path).read_text())


def _signature(path):
    value = _regular(path).stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def _repository_metadata(data, repository):
    if not isinstance(data, dict) or str(data.get("full_name", "")).casefold() != repository.casefold():
        raise BackupError("repository_mismatch", "Repository identity did not match the requested destination")
    if data.get("private") is not True or data.get("visibility") not in (None, "private"):
        raise BackupError("repository_not_private", "Raw backup requires a private GitHub repository")
    if data.get("archived") or data.get("disabled"):
        raise BackupError("repository_unwritable", "The private repository is archived or disabled")
    permissions = data.get("permissions", {})
    if permissions.get("push") is not True and permissions.get("admin") is not True:
        raise BackupError("repository_no_push", "Current GitHub credentials do not have push permission")
    if type(data.get("id")) is not int or data["id"] <= 0:
        raise BackupError("repository_missing_id", "The destination has no stable GitHub repository ID")
    return data


def verify_private_repository(repository):
    """Read safe GitHub metadata; never print tokens or raw error output."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise BackupError("invalid_repository", "Use an explicit owner/repository destination")
    try:
        result = subprocess.run(["gh", "api", "repos/" + repository, "--jq",
            "{id,full_name,private,visibility,archived,disabled,permissions}"],
            check=True, capture_output=True, text=True, timeout=30,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"})
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise BackupTransient("repository_unavailable", "Cannot verify private repository access; no raw upload permitted") from exc
    return _repository_metadata(data, repository)


def _identity(work):
    path = work / "identity.private.json"
    if not path.exists():
        return None
    identity = _read(path)
    for field in ("run_id", "model", "owner", "model_token"):
        if not isinstance(identity.get(field), str) or not SAFE_ID.fullmatch(identity[field]):
            raise BackupError("invalid_worker_identity", "Worker ownership identity is missing or invalid")
    return identity


def _approved_freeze(work, identity):
    freezes = set()
    for path in (work / "calibration").glob("attempt-*/readiness.json"):
        ready = _read(path)
        if (ready.get("passed") is True and ready.get("model") == identity["model"]
                and ready.get("worker_owner") == identity["owner"]):
            digest = ready.get("freeze_sha256", "")
            if isinstance(digest, str) and SHA256.fullmatch(digest):
                freezes.add(digest)
    if len(freezes) != 1:
        raise BackupError("readiness_freeze_missing", "A unique successful readiness freeze for this worker/model is required")
    return next(iter(freezes))


def _bind_destination(state_dir, identity, repository):
    expected = {"schema_version": 1, "run_id": identity["run_id"], "model": identity["model"],
                "owner": identity["owner"], "repository": repository["full_name"], "repository_id": repository["id"]}
    path = state_dir / "destination.private.json"
    if path.exists():
        if _read(path) != expected:
            raise BackupError("destination_changed", "Existing backup state belongs to a different worker or repository")
    else:
        atomic_json(path, expected)
        os.chmod(path, 0o600)


def _local_binding(work, identity, job_id):
    if not SAFE_ID.fullmatch(job_id):
        raise BackupError("invalid_job_id", "Invalid archive job ID")
    job_dir = _path(work / "jobs" / job_id)
    archive = _regular(work / "archives" / (job_id + ".tar.gz"))
    manifest = _regular(work / "archives" / (job_id + ".manifest.json"))
    marker_path = job_dir / "archive-receipt.private.json"
    marker, claim, index = _read(marker_path), _read(job_dir / "claim.private.json"), _read(manifest)
    completion = index.get("completion", {})
    for field in ("model", "owner"):
        if claim.get(field) != identity[field] or completion.get(field) != identity[field]:
            raise BackupError("foreign_job", "Archive does not belong to this worker/model")
    if claim.get("model_token") != identity["model_token"]:
        raise BackupError("foreign_claim", "Job model ownership token differs from this worker")
    if any(record.get("job_id") != job_id for record in (claim, completion, marker)):
        raise BackupError("job_id_mismatch", "Job/claim/archive receipt identities differ")
    if not claim.get("claim_token") or any(record.get("claim_token") != claim["claim_token"] for record in (completion, marker)):
        raise BackupError("claim_mismatch", "Archive receipt does not match the completed claim")
    ids = claim.get("trial_ids")
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(not isinstance(x, str) or not SAFE_ID.fullmatch(x) for x in ids):
        raise BackupError("invalid_trial_ids", "Invalid trial membership in archive claim")
    if completion.get("trial_ids") != ids or completion.get("status") not in ("complete", "partial_failed"):
        raise BackupError("uncompleted_job", "Only confirmed terminal jobs can be backed up")
    counts = completion.get("counts", {})
    if (not isinstance(counts, dict) or not set(counts) <= {"complete", "failed", "interrupted", "unstarted"}
            or any(type(value) is not int or value < 0 for value in counts.values())
            or counts.get("interrupted", 0) or counts.get("unstarted", 0)
            or counts.get("complete", 0) + counts.get("failed", 0) != len(ids)):
        raise BackupError("uncertain_job", "Pending, interrupted, or unstarted trial data is outside this backup contract")
    for field in ("result_ref", "result_sha256"):
        if not completion.get(field) or marker.get(field) != completion[field]:
            raise BackupError("result_receipt_mismatch", "Archive and publication receipts differ")
    if sha(_regular(job_dir / "public.jsonl.gz")) != completion["result_sha256"]:
        raise BackupError("public_result_changed", "Completed public result no longer matches its archive receipt")
    if (_path(marker.get("archive", "")) != archive or _path(marker.get("manifest", "")) != manifest
            or marker.get("archive_sha256") != index.get("archive_sha256")
            or marker.get("manifest_sha256") != sha(manifest)):
        raise BackupError("archive_receipt_mismatch", "Archive paths or checksums differ from the durable receipt")
    state_members = {"states/" + tid + suffix for tid in ids for suffix in (".json", ".journal.jsonl", ".json.lock")}
    for relative in index.get("files", {}):
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] not in ("states", "native"):
            raise BackupError("unexpected_archive_member", "Archive contains data outside states/native")
        if parts[0] == "states" and relative not in state_members:
            raise BackupError("unexpected_state_file", "Archive contains a state file outside its assigned trial IDs")
        if parts[0] == "native":
            system = len(parts) == 3 and parts[2] == "subject-system.txt"
            turn = (len(parts) == 4 and re.fullmatch(r"turn-(?:0[1-9]|[12][0-9]|3[0-4])", parts[2])
                    and parts[3] in NATIVE_NAMES - {"subject-system.txt"})
            if len(parts) < 3 or not re.fullmatch(r"[0-9a-f]{32}", parts[1]) or not (system or turn):
                raise BackupError("unexpected_native_file", "Archive includes an unsupported native path; shared authentication/database files are excluded")
    return {"archive": archive, "manifest": manifest, "marker": marker_path, "index": index,
            "claim": claim, "job_dir": job_dir, "trial_ids": ids,
            "source_signatures": {"archive": _signature(archive), "manifest": _signature(manifest),
                                  "marker": _signature(marker_path), "claim": _signature(job_dir / "claim.private.json")}}


def _verify_states(binding, identity, expected_freeze):
    """Bind archived scientific states to this run/model and a single freeze."""
    wanted = {"states/" + tid + ".json": tid for tid in binding["trial_ids"]}
    found, freezes, scratches = set(), set(), set()
    with tarfile.open(binding["archive"], "r:gz") as archive:
        for member in archive:
            if member.name not in wanted:
                continue
            if not member.isfile() or member.size > 32 * 1024**2:
                raise BackupError("invalid_archived_state", "Invalid or oversized archived state")
            stream = archive.extractfile(member)
            state = json.load(stream)
            trial = state.get("trial", {})
            if (trial.get("trial_id") != wanted[member.name] or trial.get("run_id") != identity["run_id"]
                    or trial.get("model") != identity["model"] or state.get("status") not in ("complete", "failed")
                    or state.get("pending_turn") is not None):
                raise BackupError("archived_state_mismatch", "Archived state belongs to another run/model or contains an uncertain request")
            freeze = state.get("freeze_sha256", "")
            if not isinstance(freeze, str) or not SHA256.fullmatch(freeze):
                raise BackupError("invalid_freeze", "Archived state lacks a valid frozen-source identity")
            freezes.add(freeze)
            scratch = state.get("scratch_id", "")
            if not isinstance(scratch, str) or not re.fullmatch(r"[0-9a-f]{32}", scratch):
                raise BackupError("invalid_archived_scratch", "Archived state has an invalid native-session directory identity")
            scratches.add(scratch)
            found.add(member.name)
    if found != set(wanted) or freezes != {expected_freeze}:
        raise BackupError("archived_state_coverage", "Archive state coverage or freeze identities differ")
    if any(PurePosixPath(path).parts[1] not in scratches for path in binding["index"]["files"] if path.startswith("native/")):
        raise BackupError("foreign_native_session", "Archive includes another conversation's native evidence")
    return next(iter(freezes))


@contextmanager
def _archive_lock(work, job_id):
    path = _path(work / "archives" / (job_id + ".archive.lock"))
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupTransient("archive_busy", "Worker is still finalizing this archive") from exc
        yield


def _copy_stage(source, target, expected_sha):
    if target.exists():
        if sha(_regular(target)) != expected_sha:
            raise BackupError("stage_changed", "Existing backup staging file differs")
        return
    temp = target.with_name(target.name + ".pending")
    _path(temp)
    with _regular(source).open("rb") as source_stream, temp.open("wb") as target_stream:
        shutil.copyfileobj(source_stream, target_stream, 1024**2)
        target_stream.flush()
        os.fsync(target_stream.fileno())
    os.chmod(temp, 0o600)
    if sha(temp) != expected_sha:
        raise BackupError("stage_checksum", "Archive changed during backup staging")
    os.replace(temp, target)


def _atomic_bytes(path, content):
    fd, temp = tempfile.mkstemp(prefix=".backup-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _remote_readback(publisher, expected):
    """Fetch the remote branch again, then hash the fetched immutable blobs."""
    with (publisher.cache / "publisher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        head = publisher._head()
        if not head:
            raise BackupTransient("remote_missing", "Private backup branch was not found after publication")
        for target, entry in expected.items():
            content = publisher._existing(head, target)
            if content is None or len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise BackupTransient("remote_checksum", "Remote backup checksum did not match; local archives remain intact")
        return head


def backup_job(work, identity, job_id, repository, publisher, state_dir, repository_check, reverify=False):
    """Idempotent, fully verified upload. Original compressed files are retained."""
    work, state_dir = Path(work), Path(state_dir)
    expected_freeze = _approved_freeze(work, identity)
    receipt_path = state_dir / "receipts" / (job_id + ".json")
    with _archive_lock(work, job_id):
        binding = _local_binding(work, identity, job_id)
        if receipt_path.exists():
            receipt = _read(receipt_path)
            expected = (identity["run_id"], identity["model"], identity["owner"], repository["id"], job_id,
                        binding["index"]["archive_sha256"], sha(binding["manifest"]), expected_freeze, publisher.branch)
            observed = tuple(receipt.get(k) for k in ("run_id", "model", "owner", "repository_id", "job_id",
                                                     "archive_sha256", "manifest_sha256", "freeze_sha256", "branch"))
            if receipt.get("status") != "verified" or expected != observed:
                raise BackupError("backup_receipt_mismatch", "Existing backup receipt belongs to different source bytes or destination")
            if receipt.get("source_signatures") == binding["source_signatures"] and not reverify:
                return {"job_id": job_id, "status": "already_verified", "receipt": str(receipt_path)}
        index = verify_archive(binding["archive"], binding["manifest"])
        freeze = _verify_states(binding, identity, expected_freeze)
        stage = state_dir / "staging" / job_id
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        artifacts = {"archive.tar.gz": (binding["archive"], index["archive_sha256"]),
                     "manifest.json": (binding["manifest"], sha(binding["manifest"]))}
        for name, (source, digest) in artifacts.items():
            if source.stat().st_size > MAX_GIT_BLOB:
                raise BackupError("artifact_too_large", "Archive exceeds the sidecar's Git blob limit; retain it and choose a chunked/object-store backup")
            _copy_stage(source, stage / name, digest)
        record = {"schema_version": 1, "sidecar_version": VERSION, "run_id": identity["run_id"],
                  "model": identity["model"], "owner": identity["owner"], "job_id": job_id,
                  "freeze_sha256": freeze, "completion": index["completion"],
                  "archive_sha256": index["archive_sha256"], "manifest_sha256": artifacts["manifest.json"][1],
                  "archive_created_at": index.get("created_at"),
                  "scope": "Only verified owned v2 states/native archive; no shared CLI authentication or database files"}
        record_bytes = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        record_path = stage / "backup.json"
        if record_path.exists() and record_path.read_bytes() != record_bytes:
            raise BackupError("stage_record_changed", "Existing backup completion record differs")
        if not record_path.exists():
            _atomic_bytes(record_path, record_bytes)
        signatures = binding["source_signatures"]
    # Release the worker's archive lock before network I/O. Upload immutable
    # staged snapshots; then recheck the originals before acknowledging backup.
    base = f"raw/{identity['run_id']}/{identity['model']}/{job_id}"
    expected = {}
    for name in ("archive.tar.gz", "manifest.json", "backup.json"):
        current = _repository_metadata(repository_check(), repository["full_name"])
        if current["id"] != repository["id"]:
            raise BackupError("repository_recreated", "Repository ID changed during backup")
        source, target = stage / name, base + "/" + name
        expected[target] = {"bytes": source.stat().st_size, "sha256": sha(source)}
        publisher.publish(source, target)
    final_repository = _repository_metadata(repository_check(), repository["full_name"])
    if final_repository["id"] != repository["id"]:
        raise BackupError("repository_recreated", "Repository ID changed before final backup verification")
    remote_head = _remote_readback(publisher, expected)
    with _archive_lock(work, job_id):
        current = _local_binding(work, identity, job_id)
        if current["source_signatures"] != signatures:
            raise BackupError("source_changed", "Local archive changed while its snapshot was uploaded")
        receipt = {"schema_version": 1, "sidecar_version": VERSION, "status": "verified", "verified_at": now(),
                   "repository": repository["full_name"], "repository_id": repository["id"],
                   "branch": publisher.branch, "remote_commit": remote_head,
                   "run_id": identity["run_id"], "model": identity["model"], "owner": identity["owner"], "job_id": job_id,
                   "freeze_sha256": freeze,
                   "archive_sha256": index["archive_sha256"], "manifest_sha256": artifacts["manifest.json"][1],
                   "source_signatures": signatures, "files": expected,
                   "local_compressed_archive_retained": True}
        atomic_json(receipt_path, receipt)
        os.chmod(receipt_path, 0o600)
    for name in ("archive.tar.gz", "manifest.json", "backup.json"):
        (stage / name).unlink()
    stage.rmdir()
    return {"job_id": job_id, "status": "verified", "receipt": str(receipt_path),
            "remote_commit": remote_head, "bytes": sum(x["bytes"] for x in expected.values())}


def once(work_dir, repository, *, reverify=False, repository_check=None, publisher_factory=None):
    """One scan; errors are durable structured status, never false success."""
    work = _path(work_dir)
    state_dir = work / "backup-v1"
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    status = {"schema_version": 1, "sidecar_version": VERSION, "updated_at": now(),
              "repository": repository, "status": "scanning", "verified": 0, "already_verified": 0,
              "pending": 0, "blocked": 0, "archives_seen": 0, "jobs": []}
    try:
        identity = _identity(work)
        if identity is None:
            status["status"] = "waiting_identity"
            return status
        status.update(run_id=identity["run_id"], model=identity["model"], owner=identity["owner"])
        manifests = sorted((work / "archives").glob("*.manifest.json"))
        status["archives_seen"] = len(manifests)
        checker = repository_check or (lambda: verify_private_repository(repository))
        metadata = _repository_metadata(checker(), repository)
        _bind_destination(state_dir, identity, metadata)
        branch = f"raw/{identity['run_id']}/{identity['model']}"
        factory = publisher_factory or ResultPublisher
        publisher = factory("https://github.com/" + metadata["full_name"] + ".git", branch, state_dir / "publication.git")
        for manifest in manifests:
            job_id = manifest.name.removesuffix(".manifest.json")
            if not (work / "jobs" / job_id / "archive-receipt.private.json").exists():
                status["pending"] += 1
                status["jobs"].append({"job_id": job_id, "status": "waiting_archive_receipt"})
                continue
            try:
                result = backup_job(work, identity, job_id, metadata, publisher, state_dir, checker, reverify)
                status[result["status"]] += 1
                status["jobs"].append(result)
            except BackupTransient as exc:
                status["pending"] += 1
                status["jobs"].append({"job_id": job_id, "status": "pending", "error": exc.code})
                break
            except (BackupError, StorageError, ValueError, KeyError, FileNotFoundError) as exc:
                status["blocked"] += 1
                status["jobs"].append({"job_id": job_id, "status": "blocked", "error": getattr(exc, "code", type(exc).__name__)})
                if isinstance(exc, BackupError) and exc.code.startswith("repository_"):
                    break
            except Exception as exc:
                status["pending"] += 1
                status["jobs"].append({"job_id": job_id, "status": "pending", "error": type(exc).__name__})
                break
        status["unscanned"] = len(manifests) - len(status["jobs"])
        status["pending"] += status["unscanned"]
        status["status"] = "blocked" if status["blocked"] else "pending" if status["pending"] else "up_to_date"
    except BackupError as exc:
        status.update(status="waiting_destination" if isinstance(exc, BackupTransient) else "blocked", error=exc.code)
    except Exception as exc:
        status.update(status="pending", error=type(exc).__name__)
    finally:
        status["updated_at"] = now()
        atomic_json(state_dir / "status.json", status)
    return status


@contextmanager
def sidecar_lock(work_dir):
    folder = _path(work_dir) / "backup-v1"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _path(folder / "sidecar.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError("sidecar_already_running", "Another backup sidecar already owns this worker directory") from exc
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Read-only verification of private GitHub write access")
    check.add_argument("--repository", required=True)
    for name in ("once", "watch"):
        child = sub.add_parser(name, help="Back up verified owned terminal-job archives")
        child.add_argument("--work-dir", required=True)
        child.add_argument("--repository", required=True)
        child.add_argument("--reverify", action="store_true", help="Recheck previously verified uploads from the remote")
        if name == "watch":
            child.add_argument("--interval", type=float, default=60)
    args = parser.parse_args(argv)
    if args.command == "check":
        metadata = verify_private_repository(args.repository)
        print(json.dumps({"verified_private_write_access": True, "repository": metadata["full_name"], "repository_id": metadata["id"]}))
        return 0
    interval = getattr(args, "interval", 60)
    if not 10 <= interval <= 300:
        raise BackupError("invalid_interval", "Watch interval must be 10..300 seconds")
    with sidecar_lock(args.work_dir):
        while True:
            result = once(args.work_dir, args.repository, reverify=args.reverify)
            print(json.dumps({k:v for k,v in result.items() if k != "jobs"}, ensure_ascii=False), flush=True)
            if args.command == "once":
                return 0 if result["status"] == "up_to_date" else 1
            if (Path(args.work_dir) / "backup-v1" / "STOP").exists():
                return 0
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                if (Path(args.work_dir) / "backup-v1" / "STOP").exists():
                    return 0
                time.sleep(min(1, max(0, deadline-time.monotonic())))


def entrypoint(argv=None):
    try:
        return main(argv)
    except BackupError as exc:
        print(json.dumps({"status": "blocked", "error": exc.code, "message": str(exc)}, ensure_ascii=False), flush=True)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__,
                          "message": "Inspect private sidecar status; local compressed archives remain intact."}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
