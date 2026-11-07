"""Frozen, Git-coordinated Exp7 v2 worker with bounded loose-file storage.

``prepare`` and ``run`` explicitly make model calls. Each VM owns one model;
claims and publication are fast-forward Git updates, never force pushes.
Private durable states retain native evidence. Published records are an
allowlisted research view, not native logs or authentication/session metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from exp7_pre.runner import CallBudget, atomic_json

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"complete", "failed", "interrupted", "budget_exhausted"}
FORMATS = ("en_schema", "en_natural", "ko_schema", "ko_natural", "R_A", "en_schema")
GAMES = ("obj", "seq", "KK", "KD", "DK", "DD")
EFFORTS = ("low", "medium", "high")
HEARTBEAT_SECONDS = 60.0


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def cli_version():
    return subprocess.check_output(["codex", "--version"], text=True).strip()


def source_paths(root=ROOT):
    """Exact local dependencies; no preparation, native, or runtime files."""
    paths = set()
    for name in ("exp7_main_v2", "exp7_main", "exp7_pre", "equivoque", "sequence_replication"):
        folder = Path(root) / name
        paths.update(folder.glob("*.py"))
        paths.update(folder.glob("*.json"))
        paths.update((folder / "protocol").glob("*.json"))
    paths.add(Path(root) / "exp7_main" / "requirements.txt")
    paths.add(Path(root) / "exp7_main_v2" / "requirements.txt")
    return sorted(p for p in paths if p.is_file())


def freeze_bundle(bundle_dir, output, root=ROOT):
    """Offline immutable hash record. Run only after all source tests pass."""
    from .schedule import load_bundle
    root, bundle_dir, output = map(lambda p: Path(p).resolve(), (root, bundle_dir, output))
    plan = load_bundle(bundle_dir)
    if output.exists():
        raise ValueError("Freeze already exists; verify it rather than overwrite it")
    files = source_paths(root) + sorted(p for p in bundle_dir.iterdir() if p.is_file() and p != output)
    if not all(p.is_relative_to(root) for p in files):
        raise ValueError("Freeze inputs must be repository-relative")
    frozen = {"schema_version": 1, "run_id": plan["run_id"], "created_at": now(),
              "bundle": str(bundle_dir.relative_to(root)), "cli_version": cli_version(),
              "dependencies": {"jsonschema": importlib.metadata.version("jsonschema")},
              "manifest_sha256": sha(bundle_dir / "summary.json"),
              "files": {str(p.relative_to(root)): sha(p) for p in files},
              "planned_conversations": len(plan["trials"]),
              "evaluation_call_cap": 34 * len(plan["trials"]),
              "calibration_conversations_per_model": 18,
              "calibration_call_cap_per_model": 612,
              "note": "Hashes freeze inputs. Technical readiness is recorded separately; no model calls by freeze."}
    try:
        frozen["source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except subprocess.CalledProcessError:
        frozen["source_commit"] = None
    atomic_json(output, frozen)
    return frozen


def verify_freeze(path, root=ROOT, check_cli=True):
    root, path = Path(root).resolve(), Path(path).resolve()
    frozen = read_json(path)
    for relative, expected in frozen["files"].items():
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or not source.is_file() or sha(source) != expected:
            raise ValueError("Frozen source or assignment changed: " + relative)
    if check_cli and cli_version() != frozen["cli_version"]:
        raise ValueError("CLI version differs from the frozen version")
    if set(frozen.get("dependencies", {})) != {"jsonschema"}:
        raise ValueError("Frozen parser dependency version is missing")
    for package, version in frozen["dependencies"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError("Installed dependency differs from freeze: " + package)
    if sha(root / frozen["bundle"] / "summary.json") != frozen["manifest_sha256"]:
        raise ValueError("Frozen assignment summary differs")
    return frozen, sha(path)


def calibration_trials(trials, model, attempt="01"):
    """18 prespecified fresh sessions: every effort, every game and every arm.

    All six games and both frames appear within each effort. Every arm appears
    within each effort; this is not the full format x game factorial. Technical
    conversations share fixed stimuli but never become evaluation observations.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", attempt):
        raise ValueError("Invalid calibration attempt ID")
    selected = []
    rows = sorted((t for t in trials if t["model"] == model), key=lambda t: t["trial_id"])
    for effort_index, effort in enumerate(EFFORTS):
        for i, game in enumerate(GAMES):
            arm = FORMATS[(i + effort_index) % len(FORMATS)]
            frame = "cards" if i % 2 == 0 else "cats"
            candidates = [t for t in rows if t["effort"] == effort and t["game"] == game
                          and t["arm"] == arm and t["frame"] == frame]
            if not candidates:
                raise ValueError(f"Missing calibration combination: {model}/{effort}/{game}/{arm}/{frame}")
            trial = dict(candidates[0])
            trial["evaluation_source_trial_id"] = trial["trial_id"]
            trial["trial_id"] = f"cal-{attempt}-{model}-{effort}-{i + 1:02d}"
            trial["run_id"] += "-calibration-" + attempt
            trial["cohort"] = "technical_calibration"
            trial["split"] = "calibration"
            trial["fold"] = None
            selected.append(trial)
    return selected


def calibration_valid(state):
    from .protocol import phase
    if state.get("status") != "complete" or state.get("pending_turn") is not None:
        return False
    turns = state.get("turns", [])
    if len(turns) != 34 or [r.get("turn") for r in turns] != list(range(1, 35)):
        return False
    for record in turns:
        parsed = record.get("parsed")
        if not record.get("ok") or not isinstance(parsed, dict):
            return False
        detail = parsed.get("_parse")
        if not isinstance(detail, dict) or detail.get("status") != "valid" or detail.get("format_compliant") is not True:
            return False
        fields = detail.get("fields")
        if not isinstance(fields, dict) or not fields:
            return False
        round_no, local = phase(state["trial"], record["turn"])
        allowed = {"valid", "uncertain"} if local == 5 else {"valid"}
        if local in (1, 2):
            expected_fields = {"selection"}
        elif local == 3 and state["trial"]["arm"] == "R_A" and round_no < 10:
            expected_fields = {"ack"}
            if parsed.get("ack") != "ok":
                return False
        elif local in (3, 6, 7):
            expected_fields = {"freedom", "impact", "counterfactual"}
        elif local == 4:
            expected_fields = {"rule" if state["trial"]["probe_arm"] == "explanation" else "acknowledgment"}
        else:
            expected_fields = {f"policy_{i}.{key}" for i in range(1, 5) for key in ("first_feedback", "second_feedback", "final")}
        if set(fields) != expected_fields:
            return False
        if not all(v in allowed for v in fields.values()):
            return False
        if not state["trial"]["format"].endswith("_natural") and detail.get("schema_valid") is not True:
            return False
        if local in (3, 6, 7) and "ack" not in parsed:
            if any(type(parsed.get(key)) is not int or not 1 <= parsed[key] <= 100 for key in ("freedom", "impact")):
                return False
            if parsed.get("counterfactual") not in ("yes", "no"):
                return False
        if record.get("tool_events", 0) or record.get("metadata_fallback"):
            return False
    return True


def verify_readiness(path, model, freeze_digest, trials, owner=None):
    evidence = read_json(path)
    expected = calibration_trials(trials, model, evidence.get("attempt", "01"))
    if not evidence.get("passed") or evidence.get("model") != model or evidence.get("freeze_sha256") != freeze_digest:
        raise ValueError("Successful exact-model, exact-freeze technical readiness required")
    if owner is not None and evidence.get("worker_owner") != owner:
        raise ValueError("Technical readiness belongs to a different worker")
    entries = evidence.get("states", [])
    if [e.get("trial_id") for e in entries] != [t["trial_id"] for t in expected]:
        raise ValueError("Readiness does not cover the prespecified 18 calibration sessions")
    for entry, trial in zip(entries, expected):
        state_path = Path(path).parent / entry["path"]
        if sha(state_path) != entry["sha256"]:
            raise ValueError("Calibration state changed")
        state = read_json(state_path)
        if state.get("trial") != trial or state.get("freeze_sha256") != freeze_digest or not calibration_valid(state):
            raise ValueError("Calibration integrity or required response parse failed")
        for record in state["turns"]:
            if not record.get("raw_files"):
                raise ValueError("Calibration native evidence is missing")
            for raw in record["raw_files"]:
                if sha(raw["path"]) != raw["sha256"]:
                    raise ValueError("Calibration native evidence changed")
    return evidence


class PermissionGate:
    """Shared thread-safe permission cache; STOP is polled at most 10s apart.

    A remote STOP cannot cancel already sent provider requests. Network or
    ownership uncertainty fails closed. STOP has bounded polling latency, not
    instantaneous cross-VM semantics.
    """
    def __init__(self, coordinator, model, owner, model_token, job=None, ttl=10.0):
        if not 0 <= ttl <= 10:
            raise ValueError("Permission cache TTL must be between 0 and 10 seconds")
        self.coordinator, self.model, self.owner, self.model_token = coordinator, model, owner, model_token
        self.job, self.ttl = job, ttl
        self.expected_identity = getattr(coordinator, "worker_expected_identity", None)
        self._checked = None
        self._lock = threading.Lock()
        self.stopped = threading.Event()

    def check(self, force=False):
        with self._lock:
            if self.stopped.is_set():
                raise RuntimeError("Worker stopped before request")
            try:
                monitor = getattr(self.coordinator, "worker_storage_monitor", None)
                if monitor is not None:
                    monitor.check()
                if not force and self._checked is not None and time.monotonic() - self._checked < self.ttl:
                    return
                board = self.coordinator.status()
                if self.expected_identity and any(board.get(k) != v for k, v in self.expected_identity.items()):
                    raise RuntimeError("Frozen coordination identity changed")
                entry = board["models"][self.model]
                if board["global_stop"] or entry.get("owner") != self.owner or entry.get("model_token") != self.model_token:
                    raise RuntimeError("Permission stopped or model ownership changed")
                if self.job is not None:
                    current = board["jobs"][self.job["job_id"]]
                    if (current.get("model") != self.model or current.get("owner") != self.owner
                            or current.get("claim_token") != self.job["claim_token"]
                            or current.get("status") not in ("claimed", "running")):
                        raise RuntimeError("Job ownership or status changed")
            except Exception:
                self.stopped.set()
                raise
            self._checked = time.monotonic()

    def observe(self, result):
        # Check diagnostics, never the participant's answer text, for rate limits.
        diagnostics = str(result.get("stderr", ""))
        for event in result.get("events", []):
            if event.get("type") in ("error", "turn.failed", "thread.failed"):
                diagnostics += "\n" + json.dumps(event, ensure_ascii=False)
            elif event.get("item", {}).get("type") == "error":
                diagnostics += "\n" + json.dumps(event["item"], ensure_ascii=False)
        capacity = re.search(r"\b429\b|rate[ _-]?limit|too many requests", diagnostics, flags=re.I)
        authentication = re.search(r"\b401\b|unauthorized|invalid[ _-]?(?:auth|token)|token[ _-]?refresh|refresh[ _-]?token|authentication failed|access token could not be refreshed|please sign in again|token[_ -]?expired", diagnostics, flags=re.I)
        if capacity or authentication:
            self.stopped.set()
            try:
                self.coordinator.set_stop(True, "Capacity/authentication diagnostic observed; preserve requests and inspect before resuming")
            except Exception:
                # Local halt is guaranteed; a failed remote update is reported
                # by the local job state and must not authorize another request.
                pass


class GatedTransport:
    def __init__(self, transport, gate):
        self.transport, self.gate, self.name = transport, gate, transport.name

    def request(self, *args, **kwargs):
        self.gate.check()
        response = self.transport.request(*args, **kwargs)
        self.gate.observe(response)
        return response


class StorageMonitor:
    """Watch work and native-session filesystems without deleting CLI state.

    The monitor is shared by all conversations on a VM. A failed check halts
    this worker and attempts to publish global STOP; no model request follows
    an uncertain or failed storage check. The 60-second cache is a bound on
    polling frequency, not a disk-space reservation or instantaneous stop.
    """
    def __init__(self, paths, coordinator, ttl=60.0):
        if not 0 <= ttl <= 60:
            raise ValueError("Storage cache TTL must be between 0 and 60 seconds")
        self.paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
        self.coordinator, self.ttl = coordinator, ttl
        self._checked = None
        self._lock = threading.Lock()
        self.stopped = threading.Event()
        self.metrics = []

    def check(self, force=False):
        from .storage import disk_guard
        with self._lock:
            if self.stopped.is_set():
                raise RuntimeError("Worker halted by storage guard")
            if not force and self._checked is not None and time.monotonic() - self._checked < self.ttl:
                return self.metrics
            try:
                self.metrics = [disk_guard(p) for p in self.paths]
            except Exception:
                self.stopped.set()
                try:
                    self.coordinator.set_stop(True, "Storage guard failed: inspect free bytes/inodes before resuming")
                except Exception:
                    pass
                raise
            self._checked = time.monotonic()
            return self.metrics


def heartbeat_due(coordinator, bound, job=None):
    """At most one heartbeat per model/job per minute; claims/results update separately."""
    stamp = time.monotonic()
    key = (bound["model"], None if job is None else job["job_id"])
    times = getattr(coordinator, "worker_heartbeat_times", None)
    if times is None:
        coordinator.worker_heartbeat_times = times = {}
    previous = times.setdefault(key, stamp)
    if stamp - previous < HEARTBEAT_SECONDS:
        return False
    args = [bound["model"], bound["owner"], bound["model_token"]]
    if job is not None:
        args += [job["job_id"], job["claim_token"]]
    coordinator.heartbeat(*args)
    times[key] = stamp
    return True


TRIAL_FIELDS = {"trial_id", "run_id", "model", "effort", "configuration_id", "frame", "arm", "game", "kind",
                "format", "measurement", "n_rounds", "order", "targets", "stage_rule", "probe_arm", "probe_seed",
                "probe_policies", "split", "fold", "cohort", "cell_id", "replicate", "evaluation_source_trial_id"}
TURN_FIELDS = {"turn", "round", "local_turn", "prompt", "schema", "text", "parsed", "ok", "requested_at", "received_at",
               "duration_seconds", "usage", "provider_schema", "tool_events", "compaction_events", "startup_notices",
               "https_fallback", "recovered_transport_events", "metadata_fallback", "malformed_event_lines", "timeout", "exit_code"}


def public_state(state):
    out = {"schema_version": 1, "trial": {k: v for k, v in state["trial"].items() if k in TRIAL_FIELDS},
           "status": state["status"], "freeze_sha256": state["freeze_sha256"],
           "system_sha256": state.get("system_sha256"), "started_at": state.get("started_at"),
           "ended_at": state.get("ended_at"), "rounds": state.get("rounds", []), "turns": [],
           "pending_request": state.get("pending_turn") is not None}
    for record in state.get("turns", []):
        clean = {k: v for k, v in record.items() if k in TURN_FIELDS}
        clean["raw_evidence_hashes"] = [{"name": Path(r["path"]).name, "sha256": r["sha256"]}
                                         for r in record.get("raw_files", [])]
        out["turns"].append(clean)
    serialized = json.dumps(out, ensure_ascii=False)
    if re.search(r"(?:github_pat_|gh[pousr]_|sk-)[A-Za-z0-9_\-]{20,}|Bearer\s+[A-Za-z0-9_.\-]{20,}", serialized):
        raise ValueError("Potential credential in export; preserve locally and review before publication")
    return out


def export_job(states, path):
    path = Path(path)
    payload = b"".join((json.dumps(public_state(s), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
                       for s in states)
    compressed = gzip.compress(payload, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != compressed:
            raise ValueError("Existing public result differs; never replace a published record")
    else:
        with path.open("xb") as stream:
            stream.write(compressed)
            stream.flush()
            os.fsync(stream.fileno())
    return sha(path)


class ResultPublisher:
    """Append an immutable batch file on a model-specific result branch."""
    def __init__(self, remote, branch, cache_dir, timeout=45):
        self.remote, self.branch, self.cache, self.timeout = remote, branch, Path(cache_dir), timeout
        self.cache.mkdir(parents=True, exist_ok=True)
        if not (self.cache / "HEAD").exists():
            subprocess.run(["git", "init", "--bare", str(self.cache)], check=True, capture_output=True)

    def _git(self, *args, input=None, env=None, check=True):
        return subprocess.run(["git", "--git-dir", str(self.cache), *args], input=input,
                              capture_output=True, check=check, timeout=self.timeout, env=env)

    def _head(self):
        result = self._git("ls-remote", self.remote, "refs/heads/" + self.branch)
        lines = result.stdout.decode().splitlines()
        if not lines:
            return None
        if len(lines) != 1:
            raise RuntimeError("Ambiguous result branch")
        from .coordination import fetch_tracking_head
        return fetch_tracking_head(self.remote, self.branch, self.cache, timeout=self.timeout,
                                   tracking_ref="refs/remotes/exp7/results")

    def _existing(self, commit, target):
        if commit is None:
            return None
        result = self._git("show", commit + ":" + target, check=False)
        return result.stdout if result.returncode == 0 else None

    def publish(self, path, target):
        if Path(target).is_absolute() or ".." in Path(target).parts or not re.fullmatch(r"[A-Za-z0-9_./-]+", target):
            raise ValueError("Invalid repository result path")
        content = Path(path).read_bytes()
        with (self.cache / "publisher.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for _ in range(3):
                parent = self._head()
                existing = self._existing(parent, target)
                if existing is not None:
                    if existing != content:
                        raise ValueError("Remote result already exists with different bytes")
                    return parent + ":" + target
                blob = self._git("hash-object", "-w", "--stdin", input=content).stdout.decode().strip()
                index = self.cache / ("index-" + uuid.uuid4().hex)
                env = {**os.environ, "GIT_INDEX_FILE": str(index), "GIT_AUTHOR_NAME": "Exp7 worker",
                       "GIT_AUTHOR_EMAIL": "exp7-worker@localhost", "GIT_COMMITTER_NAME": "Exp7 worker",
                       "GIT_COMMITTER_EMAIL": "exp7-worker@localhost"}
                try:
                    self._git("read-tree", parent if parent else "--empty", env=env)
                    self._git("update-index", "--add", "--cacheinfo", "100644", blob, target, env=env)
                    tree = self._git("write-tree", env=env).stdout.decode().strip()
                    args = ["commit-tree", tree]
                    if parent:
                        args += ["-p", parent]
                    commit = self._git(*args, input=("Record " + target + "\n").encode(), env=env).stdout.decode().strip()
                finally:
                    index.unlink(missing_ok=True)
                from .coordination import protect_pending_commit, release_confirmed_pending, maybe_maintain_cache
                pending_ref = protect_pending_commit(self.cache, commit, timeout=self.timeout)
                # Any timeout is ambiguous: inspect the remote before doing
                # anything else. Rebuild from a fresh parent, never rebase.
                try:
                    self._git("push", self.remote, commit + ":refs/heads/" + self.branch)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    pass
                observed = self._head()
                uploaded = self._existing(observed, target)
                if uploaded == content:
                    # A same-byte publication by another writer is a valid
                    # receipt, but its unrelated commit cannot justify dropping
                    # our protected pending object.
                    from .coordination import CoordinationError
                    try:
                        release_confirmed_pending(self.cache, pending_ref, observed, timeout=self.timeout,
                                                  tracking_ref="refs/remotes/exp7/results")
                    except CoordinationError:
                        pass
                    maybe_maintain_cache(self.cache, tracking_ref="refs/remotes/exp7/results")
                    return observed + ":" + target
                if uploaded is not None:
                    raise ValueError("Publication conflict: remote bytes differ")
            raise RuntimeError("Result publication not confirmed; do not complete or rerun the job")


@contextmanager
def local_worker_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def bind_model(coordinator, work_dir, requested_model, models, concurrency, owner=None):
    from .coordination import Conflict, OwnershipError
    identity = Path(work_dir) / "identity.private.json"
    if identity.exists():
        bound = read_json(identity)
        if requested_model != "auto" and requested_model != bound["model"]:
            raise ValueError("This worker directory is already bound to another model")
        if owner is not None and owner != bound["owner"]:
            raise ValueError("Owner differs from durable worker identity")
        board = coordinator.status()
        entry = board["models"][bound["model"]]
        if entry.get("owner") != bound["owner"] or entry.get("model_token") != bound["model_token"]:
            raise RuntimeError("Saved model ownership is no longer authoritative")
        if entry["concurrency"] != concurrency:
            raise ValueError("Concurrency differs from model's reserved capacity")
        return bound
    owner = owner or ("vm-" + uuid.uuid4().hex[:12])
    board = coordinator.status()
    candidates = models if requested_model == "auto" else [requested_model]
    for model in candidates:
        if model not in board["models"]:
            raise ValueError("Model absent from frozen coordination board")
        if board["models"][model].get("owner") is not None:
            continue
        try:
            token = coordinator.claim_model(model, owner, concurrency=concurrency)
        except Exception as exc:
            # The same requested owner/token cannot be recovered after a
            # failed API return without inspecting the remote authoritative
            # state. Do not assume a different model is safe to claim.
            current = coordinator.status()
            owned = [(m, v) for m, v in current["models"].items() if v.get("owner") == owner]
            if len(owned) == 1:
                model, entry = owned[0]
                token = entry["model_token"]
            elif (isinstance(exc, (Conflict, OwnershipError)) and current["models"][model].get("owner") is not None
                  and requested_model == "auto" and not current["global_stop"]):
                board = current
                continue
            else:
                raise
        bound = {"model": model, "owner": owner, "model_token": token, "concurrency": concurrency,
                 "run_id": board["run_id"], "created_at": now()}
        atomic_json(identity, bound)
        os.chmod(identity, 0o600)
        return bound
    raise RuntimeError("No unowned model is available; do not take another VM's model")


def prepare_model(trials, bound, coordinator, directory, freeze_digest, timeout, attempt="01"):
    from .protocol import MainProtocol
    from .runner import run_trial, NativeTransport
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    selected = calibration_trials(trials, bound["model"], attempt)
    readiness_path = directory / "readiness.json"
    if readiness_path.exists():
        verify_readiness(readiness_path, bound["model"], freeze_digest, trials, bound["owner"])
        return read_json(readiness_path)
    gate = PermissionGate(coordinator, bound["model"], bound["owner"], bound["model_token"])
    transport = GatedTransport(NativeTransport(timeout=timeout), gate)
    budget = CallBudget(directory / "budget.json", selected[0]["run_id"] + ":" + bound["model"], 612)
    states = {}

    def execute(trial):
        gate.check()
        path = directory / "states" / (trial["trial_id"] + ".json")
        state = run_trial(trial, MainProtocol(), transport, path, directory / "native", budget, freeze_digest)
        return state, {"trial_id": trial["trial_id"], "path": str(path.relative_to(directory)), "sha256": sha(path)}

    iterator = iter(selected)
    failed = False
    with ThreadPoolExecutor(max_workers=bound["concurrency"]) as pool:
        pending = {}
        for _ in range(bound["concurrency"]):
            trial = next(iterator, None)
            if trial:
                pending[pool.submit(execute, trial)] = trial["trial_id"]
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future)
                state, entry = future.result()
                states[entry["trial_id"]] = entry
                if not calibration_valid(state):
                    failed = True
                    gate.stopped.set()
                atomic_json(directory / "progress.json", {"model": bound["model"], "attempt": attempt,
                            "finished": len(states), "assigned": 18, "last_status": state["status"],
                            "updated_at": now(), "failed": failed})
            if not failed and not gate.stopped.is_set():
                try:
                    heartbeat_due(coordinator, bound)
                except Exception:
                    gate.stopped.set()
                    raise
                for _ in finished:
                    trial = next(iterator, None)
                    if trial:
                        pending[pool.submit(execute, trial)] = trial["trial_id"]
    if failed or len(states) != 18:
        raise RuntimeError("Technical calibration failed; preserve attempt and inspect before any evaluation")
    evidence = {"passed": True, "model": bound["model"], "freeze_sha256": freeze_digest,
                "attempt": attempt, "worker_owner": bound["owner"],
                "states": [states[t["trial_id"]] for t in selected],
                "created_at": now(), "calibration_call_cap": 612,
                "scope": "18 technical conversations; all efforts/arms/games and both frames, not full factorial",
                "semantic_review": "Automated protocol/parse integrity; no independent human semantic review asserted"}
    atomic_json(readiness_path, evidence)
    verify_readiness(readiness_path, bound["model"], freeze_digest, trials, bound["owner"])
    return evidence


def owned_job(coordinator, bound, work_dir):
    monitor = getattr(coordinator, "worker_storage_monitor", None)
    if monitor is not None:
        monitor.check(force=True)
    board = coordinator.status()
    active = [j for j in board["jobs"].values() if j["model"] == bound["model"] and j["status"] in ("claimed", "running")]
    if len(active) > 1:
        raise RuntimeError("Multiple active jobs for one model")
    if active:
        job = active[0]
        marker = Path(work_dir) / "jobs" / job["job_id"] / "claim.private.json"
        if not marker.exists() or read_json(marker) != job_identity(job, bound):
            raise RuntimeError("Active remote job lacks matching local durable claim; inspect instead of replaying")
        coordinator.assert_permission(bound["model"], bound["owner"], bound["model_token"], job["job_id"], job["claim_token"])
        return job
    job = coordinator.claim_job(bound["model"], bound["owner"], bound["model_token"])
    if job:
        marker = Path(work_dir) / "jobs" / job["job_id"] / "claim.private.json"
        atomic_json(marker, job_identity(job, bound))
        os.chmod(marker, 0o600)
    return job


def job_identity(job, bound):
    return {"job_id": job["job_id"], "claim_token": job["claim_token"], "model": bound["model"],
            "owner": bound["owner"], "model_token": bound["model_token"], "trial_ids": job["trial_ids"]}


def execute_job(job, bound, coordinator, trials_by_id, work_dir, freeze_digest, timeout):
    from .protocol import MainProtocol
    from .runner import run_trial, NativeTransport
    directory = Path(work_dir) / "jobs" / job["job_id"]
    if ((directory / "archive-receipt.private.json").exists()
            or (Path(work_dir) / "archives" / (job["job_id"] + ".manifest.json")).exists()):
        raise RuntimeError("Archived job cannot be executed again, even if remote state is reopened")
    chosen = [trials_by_id[i] for i in job["trial_ids"]]
    if len(set(job["trial_ids"])) != len(chosen) or any(t["model"] != bound["model"] for t in chosen):
        raise ValueError("Job IDs repeat or cross model ownership")
    if job["call_cap"] != len(chosen) * 34:
        raise ValueError("Job call cap differs from frozen allocation")
    coordinator.mark_running(bound["model"], bound["owner"], bound["model_token"], job["job_id"], job["claim_token"])
    gate = PermissionGate(coordinator, bound["model"], bound["owner"], bound["model_token"], job)
    transport = GatedTransport(NativeTransport(timeout=timeout), gate)
    budget = CallBudget(directory / "budget.json", chosen[0]["run_id"] + ":" + job["job_id"], job["call_cap"])
    iterator = iter(chosen)
    states = {}

    def submit_one(pool):
        if gate.stopped.is_set():
            return None
        trial = next(iterator, None)
        if trial is None:
            return None
        gate.check()
        path = directory / "states" / (trial["trial_id"] + ".json")
        return pool.submit(run_trial, trial, MainProtocol(), transport, path,
                           directory / "native", budget, freeze_digest), trial["trial_id"]

    with ThreadPoolExecutor(max_workers=bound["concurrency"]) as pool:
        pending = {}
        for _ in range(bound["concurrency"]):
            submitted = submit_one(pool)
            if submitted:
                pending[submitted[0]] = submitted[1]
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                tid = pending.pop(future)
                states[tid] = future.result()
            atomic_json(directory / "progress.json", {"job_id": job["job_id"], "finished": len(states),
                        "assigned": len(chosen), "statuses": dict(Counter(s["status"] for s in states.values())),
                        "updated_at": now(), "stopped": gate.stopped.is_set()})
            try:
                heartbeat_due(coordinator, bound, job)
            except Exception:
                gate.stopped.set()
                raise
            for _ in finished:
                if gate.stopped.is_set():
                    break
                submitted = submit_one(pool)
                if submitted:
                    pending[submitted[0]] = submitted[1]
    # Include any previously completed states when resuming an owned batch.
    output = []
    counts = Counter({"complete": 0, "failed": 0, "interrupted": 0, "unstarted": 0})
    for trial in chosen:
        path = directory / "states" / (trial["trial_id"] + ".json")
        if path.exists():
            state = read_json(path)
            if state["trial"] != trial or state["freeze_sha256"] != freeze_digest:
                raise ValueError("Existing state does not match this assignment")
            if state["status"] not in TERMINAL:
                raise RuntimeError("Active state remains; preserve and inspect before completion")
            counts["interrupted" if state["status"] == "budget_exhausted" else state["status"]] += 1
            output.append(state)
        else:
            counts["unstarted"] += 1
            output.append({"trial": trial, "status": "unstarted", "freeze_sha256": freeze_digest,
                           "rounds": [], "turns": [], "pending_turn": None})
    calls = read_json(directory / "budget.json")["used"] if (directory / "budget.json").exists() else 0
    path = directory / "public.jsonl.gz"
    digest = export_job(output, path)
    return {"path": str(path), "sha256": digest, "counts": dict(counts), "calls": calls,
            "stopped": gate.stopped.is_set()}


def finalize_job(job, bound, coordinator, publisher, result, work_dir, run_id):
    """Publish and confirm completion before compacting any local raw records."""
    from .storage import archive_completed_job
    target = f"results/{run_id}/{bound['model']}/{job['job_id']}.jsonl.gz"
    result_ref = publisher.publish(result["path"], target)
    completed = coordinator.complete_job(bound["model"], bound["owner"], bound["model_token"],
                                         job["job_id"], job["claim_token"], counts=result["counts"],
                                         calls=result["calls"], result_ref=result_ref,
                                         result_sha256=result["sha256"])
    archive = None
    # Interrupted/pending jobs remain loose for reconciliation. A completed
    # scientific failure with no uncertain request can be archived exactly.
    if completed["status"] in ("complete", "partial_failed") and not result["counts"].get("interrupted") and not result["counts"].get("unstarted"):
        archive = archive_completed_job(Path(work_dir) / "jobs" / job["job_id"], Path(work_dir) / "archives",
                                        completion=completed, expected_trial_ids=job["trial_ids"], prune=True)
        if not (Path(work_dir) / "jobs" / job["job_id"] / "archive-receipt.private.json").exists():
            raise RuntimeError("Archiver did not preserve its durable no-replay receipt")
    return {"result_ref": result_ref, "completed": completed, "archive": archive}


def archive_backlog(coordinator, bound, work_dir):
    """Compact only this worker's confirmed terminal jobs and preserved claims."""
    from .storage import archive_completed_job
    work_dir = Path(work_dir)
    board = coordinator.status()
    archived = []
    for job in board["jobs"].values():
        if job["model"] != bound["model"] or job.get("owner") != bound["owner"]:
            continue
        if job["status"] not in ("complete", "partial_failed"):
            continue
        if job.get("counts", {}).get("interrupted") or job.get("counts", {}).get("unstarted"):
            continue
        directory = work_dir / "jobs" / job["job_id"]
        claim = directory / "claim.private.json"
        if not claim.exists() or read_json(claim) != job_identity(job, bound):
            raise RuntimeError("Completed job lacks this worker's durable claim; do not compact")
        archived.append(archive_completed_job(directory, work_dir / "archives", completion=job,
                                              expected_trial_ids=job["trial_ids"], prune=True))
    return archived


def run_worker(args):
    from .coordination import GitCoordinator
    from .schedule import load_bundle
    frozen, freeze_digest = verify_freeze(args.freeze)
    plan = load_bundle(ROOT / frozen["bundle"])
    trials = plan["trials"]
    models = list(dict.fromkeys(t["model"] for t in trials))
    work = Path(args.work_dir).resolve()
    if not 1 <= args.concurrency <= 10:
        raise ValueError("Worker concurrency must be 1..10 and reserved on the common board")
    with local_worker_lock(work):
        coordinator = GitCoordinator(args.remote, args.coordination_branch, work / "coordination.git")
        board = coordinator.status()
        if (board["run_id"] != frozen["run_id"] or board["manifest_sha256"] != frozen["manifest_sha256"]
                or board.get("freeze_sha256") != freeze_digest):
            raise ValueError("Remote board belongs to a different frozen allocation")
        coordinator.worker_expected_identity = {k: board[k] for k in ("run_id", "manifest_sha256", "freeze_sha256", "source_commit")}
        storage_paths = [work]
        native_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        if native_home.exists():
            storage_paths.append(native_home)
        coordinator.worker_storage_monitor = StorageMonitor(storage_paths, coordinator)
        coordinator.worker_storage_monitor.check(force=True)
        bound = bind_model(coordinator, work, args.model, models, args.concurrency, args.owner)
        print(json.dumps({"model": bound["model"], "owner": bound["owner"], "mode": args.command}, ensure_ascii=False), flush=True)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", args.calibration_attempt):
            raise ValueError("Invalid calibration attempt ID")
        readiness = work / "calibration" / ("attempt-" + args.calibration_attempt) / "readiness.json"
        if args.command == "prepare":
            return prepare_model(trials, bound, coordinator, readiness.parent, freeze_digest, args.timeout, args.calibration_attempt)
        verify_readiness(readiness, bound["model"], freeze_digest, trials, bound["owner"])
        archive_backlog(coordinator, bound, work)
        publisher = ResultPublisher(args.remote, args.results_prefix + "/" + bound["model"], work / "publication.git")
        by_id = {t["trial_id"]: t for t in trials}
        finished = 0
        while args.max_jobs is None or finished < args.max_jobs:
            verify_freeze(args.freeze)
            job = owned_job(coordinator, bound, work)
            if job is None:
                return {"model": bound["model"], "finished_jobs": finished, "remaining_jobs": 0}
            result = execute_job(job, bound, coordinator, by_id, work, freeze_digest, args.timeout)
            finalized = finalize_job(job, bound, coordinator, publisher, result, work, frozen["run_id"])
            result_ref = finalized["result_ref"]
            finished += 1
            print(json.dumps({"job_id": job["job_id"], "model": bound["model"], "counts": result["counts"],
                              "calls": result["calls"], "result_ref": result_ref,
                              "archived": finalized["archive"] is not None}, ensure_ascii=False), flush=True)
            if result["stopped"]:
                return {"model": bound["model"], "finished_jobs": finished, "stopped": True}
        return {"model": bound["model"], "finished_jobs": finished}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freezing = sub.add_parser("freeze", help="Offline: create immutable source and assignment hash record")
    freezing.add_argument("--bundle", required=True)
    freezing.add_argument("--output", required=True)
    checking = sub.add_parser("verify", help="Offline: verify frozen bytes and CLI version")
    checking.add_argument("--freeze", required=True)
    for name in ("prepare", "run"):
        child = sub.add_parser(name, help="Explicit native model calls: " + ("technical calibration" if name == "prepare" else "evaluation"))
        child.add_argument("--freeze", required=True)
        child.add_argument("--remote", default="https://github.com/dasnidm/llm-equivoque-experiments.git")
        child.add_argument("--coordination-branch", default="exp7/main-v2-coordination")
        child.add_argument("--results-prefix", default="exp7/main-v2-results")
        child.add_argument("--work-dir", required=True, help="Persistent private VM-local directory; preserve across restarts")
        child.add_argument("--model", default="auto")
        child.add_argument("--owner")
        child.add_argument("--concurrency", type=int, default=1)
        child.add_argument("--timeout", type=float, default=300)
        child.add_argument("--calibration-attempt", default="01", help="Explicit technical attempt ID; failed attempts are never overwritten or automatically retried")
        child.add_argument("--max-jobs", type=int)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze_bundle(args.bundle, args.output)
    elif args.command == "verify":
        frozen, digest = verify_freeze(args.freeze)
        result = {"verified": True, "run_id": frozen["run_id"], "freeze_sha256": digest}
    else:
        result = run_worker(args)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
