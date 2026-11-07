"""Audited capacity reservation, quiescent resize, and administrative hold release.

No model calls occur here. The existing future-job hold lets the current worker
finish every active conversation and its job before the next claim fails.
Reservation can change while that old pool drains; local concurrency changes
only after the old worker/supervisor are gone and their locks are available.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path

from exp7_pre.runner import atomic_json, now
from exp7_main_v2.coordination import GitCoordinator, Conflict, OwnershipError, validate_board


def read(path):
    return json.loads(Path(path).read_text())


def board_identity(board):
    return {k: board[k] for k in ("run_id", "manifest_sha256", "freeze_sha256", "source_commit")}


def _check(board, hold, bound, expected=None):
    if board["run_id"] != hold["run_id"] or bound["run_id"] != hold["run_id"]:
        raise Conflict("Operation run identity differs")
    if expected is not None and board_identity(board) != expected:
        raise Conflict("Frozen board identity changed")
    for key in ("model", "owner", "model_token"):
        if bound.get(key) != hold.get(key):
            raise OwnershipError("Local model ownership differs from administrative hold")
    model = board["models"][hold["model"]]
    if model.get("owner") != hold["owner"] or model.get("model_token") != hold["model_token"]:
        raise OwnershipError("Remote model ownership changed")
    if board["jobs"].get(hold["held_job"]["job_id"]) != hold["held_job"]:
        raise Conflict("Administrative hold changed or disappeared")
    return model


def _validate_hold(hold):
    if hold.get("schema_version") != 1 or hold.get("status") != "confirmed":
        raise Conflict("A confirmed administrative queue hold is required")
    original, held = hold["original_job"], hold["held_job"]
    if original.get("model") != hold.get("model"):
        raise Conflict("Administrative hold belongs to a different model")
    if original.get("status") != "open" or held.get("status") != "blocked":
        raise Conflict("Administrative hold must preserve a previously open job")
    if (original.get("calls") != 0 or original.get("owner") is not None
            or original.get("claim_token") is not None or original.get("result_ref") is not None
            or original.get("result_sha256") is not None
            or original.get("counts") != {"complete":0,"failed":0,"interrupted":0,"unstarted":original["n_trials"]}):
        raise Conflict("Held job was not pristine and unstarted")
    # Adopt the explicit operator hold created before this helper was installed.
    # It is deliberately owned by the operator, not an evaluation worker.
    if held.get("owner") != "operator-hold-c10-01":
        raise Conflict("Unexpected administrative hold owner")
    expected = deepcopy(original)
    expected.update(status="blocked", owner="operator-hold-c10-01", claim_token=hold["hold_token"],
                    ops_hold=held.get("ops_hold"))
    if held != expected or held.get("ops_hold", {}).get("operation_id") != hold["operation_id"]:
        raise Conflict("Hold changed scientific assignment, result, or accounting fields")
    if held.get("ops_hold", {}).get("non_inference") is not True:
        raise Conflict("Administrative hold is not explicitly marked as non-inference")


@contextmanager
def operation_lock(operation_dir):
    directory = Path(operation_dir).resolve()
    if not (directory / "hold.private.json").exists():
        raise Conflict("Existing hold.private.json is required")
    with (directory / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hold = read(directory / "hold.private.json")
        _validate_hold(hold)
        yield directory, hold


def process_alive(pid):
    if type(pid) is not int or pid <= 1:
        raise ValueError("An explicit previous process PID is required")
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
        if status.rsplit(")", 1)[1].strip().split()[0] in ("Z", "X"):
            return False
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        return True


@contextmanager
def quiescent_worker(work_dir, old_worker_pid, old_supervisor_pid, reconciliation_receipt=None,
                     stopped_calibration_receipt=None):
    """Require quiescence; an explicit verified receipt never permits replay."""
    work_dir = Path(work_dir).resolve()
    if process_alive(old_worker_pid) or process_alive(old_supervisor_pid):
        raise Conflict("Old worker or supervisor is still active; wait without interrupting conversations")
    with ExitStack() as stack:
        paths = [work_dir / "worker.lock"]
        if (work_dir / "launch-v1").exists():
            paths.append(work_dir / "launch-v1" / "launcher.lock")
        for path in paths:
            lock = stack.enter_context(path.open("a"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reconciled = set()
        if reconciliation_receipt is not None:
            # Import only after both operational locks are held. recovery uses
            # this module's read-only helpers, so a module-level import cycles.
            from .recovery import verify_reconciliation
            reconciled = {Path(path).resolve() for path in
                          verify_reconciliation(work_dir, reconciliation_receipt)}
            if len(reconciled) != 3:
                raise Conflict("This operation requires exactly three verified original interruptions")
            for path in reconciled:
                if not path.is_relative_to(work_dir):
                    raise Conflict("Reconciled state is outside this worker directory")
                parts = path.relative_to(work_dir).parts
                if len(parts) != 4 or parts[0] != "jobs" or parts[2] != "states" or path.suffix != ".json":
                    raise Conflict("Reconciliation may exempt only original job states")
        stopped_calibration = set()
        if stopped_calibration_receipt is not None:
            from .calibration_snapshot import verify_stopped_calibration_receipt
            stopped_calibration = {Path(path).resolve() for path in
                                   verify_stopped_calibration_receipt(work_dir, stopped_calibration_receipt)}
            if len(stopped_calibration) != 10:
                raise Conflict("This operation requires exactly ten verified stopped calibration states")
            for path in stopped_calibration:
                if not path.is_relative_to(work_dir):
                    raise Conflict("Stopped calibration state is outside this worker directory")
                parts = path.relative_to(work_dir).parts
                if (len(parts) != 4 or parts[:3] != ("calibration", "attempt-c10-01", "states")
                        or path.suffix != ".json"):
                    raise Conflict("Stopped calibration receipt may exempt only the preserved c10-01 attempt")
        exempted = reconciled | stopped_calibration
        sources = list((work_dir / "jobs").glob("*/states/*.json"))
        sources += list((work_dir / "calibration").glob("attempt-*/states/*.json"))
        matched = set()
        for path in sources:
            state = read(path)
            if state.get("status") == "active":
                raise Conflict("Active or uncertain request records remain; preserve and reconcile them")
            if state.get("pending_turn") is not None:
                if state.get("status") != "interrupted" or path.resolve() not in exempted:
                    raise Conflict("Active or uncertain request records remain; preserve and reconcile them")
                matched.add(path.resolve())
        if matched != exempted:
            raise Conflict("Explicit receipts no longer match every preserved immutable pending state")
        yield


def reserve_target(coordinator, work_dir, operation_dir, concurrency=10):
    """Reserve global headroom while the unchanged old local pool drains."""
    if type(concurrency) is not int or not 1 <= concurrency <= 10:
        raise ValueError("Concurrency must be an integer from 1 to 10")
    work_dir = Path(work_dir).resolve()
    with operation_lock(operation_dir) as (directory, hold):
        bound = read(work_dir / "identity.private.json")
        board = coordinator.status()
        _check(board, hold, bound)
        audit_path = directory / "capacity.private.json"
        if audit_path.exists():
            audit = read(audit_path)
            if (audit["operation_id"] != hold["operation_id"]
                    or audit["target_concurrency"] != concurrency
                    or audit["board_identity"] != board_identity(board)):
                raise Conflict("Existing capacity operation has different inputs")
        else:
            if board["models"][hold["model"]]["concurrency"] != bound["concurrency"]:
                raise Conflict("Initial local and remote capacity differ; inspect before reserving")
            audit = {"schema_version":1, "operation_id":hold["operation_id"], "status":"reserve_intent",
                     "created_at":now(), "board_identity":board_identity(board),
                     "model":hold["model"], "owner":hold["owner"],
                     "original_concurrency":bound["concurrency"], "target_concurrency":concurrency}
            atomic_json(audit_path, audit)
            os.chmod(audit_path, 0o600)

        def change(current):
            entry = _check(current, hold, bound, audit["board_identity"])
            others = sum(m["concurrency"] for name,m in current["models"].items()
                         if name != hold["model"] and m.get("owner") is not None)
            if others + concurrency > current["global_max_concurrency"]:
                raise Conflict("Other model reservations leave insufficient global capacity")
            if entry["concurrency"] not in (audit["original_concurrency"], concurrency):
                raise Conflict("Model capacity changed outside this operation")
            events = current.setdefault("operational_events", [])
            event = next((e for e in events if e.get("operation_id") == hold["operation_id"]
                          and e.get("action") == "reserve_capacity"), None)
            if event is not None:
                if event.get("to") != concurrency or entry["concurrency"] != concurrency:
                    raise Conflict("Capacity audit and reservation disagree")
                return
            entry["concurrency"] = concurrency
            events.append({"operation_id":hold["operation_id"], "action":"reserve_capacity",
                           "model":hold["model"], "from":audit["original_concurrency"], "to":concurrency,
                           "at":now(), "note":"Reservation only; old local pool remains unchanged until quiescence"})
            validate_board(current)
        updated = coordinator._mutate("Reserve capacity for " + hold["model"], change)
        if updated["models"][hold["model"]]["concurrency"] != concurrency:
            raise Conflict("Capacity reservation was not confirmed")
        if audit.get("status") != "local_resized":
            audit.update(status="reserved", reserved_at=now())
            atomic_json(audit_path, audit)
        return audit


def resize_local(coordinator, work_dir, operation_dir, old_worker_pid, old_supervisor_pid,
                 reconciliation_receipt=None, stopped_calibration_receipt=None):
    """Apply the reserved pool size locally only after the previous run drained."""
    work_dir = Path(work_dir).resolve()
    with operation_lock(operation_dir) as (directory, hold), quiescent_worker(
            work_dir, old_worker_pid, old_supervisor_pid, reconciliation_receipt,
            stopped_calibration_receipt=stopped_calibration_receipt):
        audit = read(directory / "capacity.private.json")
        bound = read(work_dir / "identity.private.json")
        board = coordinator.status()
        model = _check(board, hold, bound, audit["board_identity"])
        if audit["status"] not in ("reserved","local_resize_intent","local_resized"):
            raise Conflict("Capacity reservation must be confirmed first")
        if model["concurrency"] != audit["target_concurrency"]:
            raise Conflict("Remote reservation differs from target concurrency")
        if bound["concurrency"] not in (audit["original_concurrency"],audit["target_concurrency"]):
            raise Conflict("Local capacity changed outside this operation")
        if any(j["model"] == hold["model"] and j["status"] in ("claimed","running") for j in board["jobs"].values()):
            raise Conflict("Remote job is still active")
        if audit["status"] == "local_resized" and bound["concurrency"] == audit["target_concurrency"]:
            return audit
        audit.update(status="local_resize_intent", old_worker_pid=old_worker_pid,
                     old_supervisor_pid=old_supervisor_pid)
        atomic_json(directory / "capacity.private.json",audit)
        bound["concurrency"] = audit["target_concurrency"]
        atomic_json(work_dir / "identity.private.json",bound)
        os.chmod(work_dir / "identity.private.json",0o600)
        audit.update(status="local_resized", resized_at=now())
        atomic_json(directory / "capacity.private.json",audit)
        return audit


def verify_capacity_evidence(ready, attempt, audit):
    """Verify new local request overlap without reading scientific judgments."""
    from .measure import overlap_segments, seconds
    evidence=read(ready)
    if evidence.get("attempt") != attempt or evidence.get("calibration_call_cap") != 612:
        raise Conflict("Technical readiness attempt or fixed call cap differs")
    if seconds(evidence["created_at"]) <= seconds(audit["resized_at"]):
        raise Conflict("Readiness predates the local capacity change")
    intervals=[]
    entries=evidence.get("states",[])
    if len(entries) != 18:
        raise Conflict("Capacity check requires all 18 prespecified sessions")
    for item in entries:
        path=(ready.parent/item["path"]).resolve()
        if not path.is_relative_to(ready.parent.resolve()):
            raise Conflict("Technical state is outside its own attempt directory")
        state=read(path)
        if seconds(state["started_at"]) <= seconds(audit["resized_at"]):
            raise Conflict("Technical conversation began before the new capacity was adopted")
        for turn in state["turns"]:
            intervals.append((seconds(turn["requested_at"]),seconds(turn["received_at"])))
    if len(intervals) != 612:
        raise Conflict("Capacity check lacks exactly 612 recorded requests")
    peak=max((n for _,_,n in overlap_segments(intervals)),default=0)
    if peak != audit["target_concurrency"]:
        raise Conflict("Recorded local request peak did not match the reserved capacity")
    return {"observed_local_pending_peak":peak,"recorded_requests":len(intervals)}


def release_hold(coordinator, work_dir, operation_dir, old_worker_pid, old_supervisor_pid,
                 calibration_attempt, freeze_path, reconciliation_receipt=None,
                 stopped_calibration_receipt=None):
    """Release only after the fresh capacity calibration is independently valid."""
    from exp7_main_v2.worker import verify_freeze, verify_readiness, ROOT
    from exp7_main_v2.schedule import load_bundle
    if not calibration_attempt or calibration_attempt == "01" or "/" in calibration_attempt or "\\" in calibration_attempt:
        raise ValueError("A fresh explicit capacity calibration attempt is required")
    work_dir=Path(work_dir).resolve()
    with operation_lock(operation_dir) as (directory,hold), quiescent_worker(
            work_dir,old_worker_pid,old_supervisor_pid,reconciliation_receipt,
            stopped_calibration_receipt=stopped_calibration_receipt):
        audit=read(directory/"capacity.private.json")
        bound=read(work_dir/"identity.private.json")
        if any(bound.get(key) != hold.get(key) for key in ("run_id","model","owner","model_token")):
            raise OwnershipError("Local model ownership or run identity differs from administrative hold")
        continuation = None
        if stopped_calibration_receipt is not None:
            if calibration_attempt != "c10-02" or reconciliation_receipt is None:
                raise Conflict("Preserved c10-01 requires a fresh c10-02 pass and finalized four-ID continuation")
            reconciliation = read(reconciliation_receipt)
            if reconciliation.get("phase") != "finalized":
                raise Conflict("Original four never-started assignments must be finalized before queue release")
            continuation = reconciliation["completed_job"]
        frozen,freeze_digest=verify_freeze(freeze_path)
        plan=load_bundle(ROOT/frozen["bundle"])
        if audit["status"] not in ("local_resized","released") or bound["concurrency"] != audit["target_concurrency"]:
            raise Conflict("Local pool has not adopted the reserved target concurrency")
        if frozen["run_id"] != hold["run_id"] or freeze_digest != audit["board_identity"]["freeze_sha256"]:
            raise Conflict("Capacity probe uses another frozen experiment")
        ready=work_dir/"calibration"/("attempt-"+calibration_attempt)/"readiness.json"
        verify_readiness(ready,bound["model"],freeze_digest,plan["trials"],bound["owner"])
        capacity_evidence=verify_capacity_evidence(ready,calibration_attempt,audit)
        def change(board):
            if board_identity(board)!=audit["board_identity"]:
                raise Conflict("Frozen board identity changed")
            entry=board["models"][hold["model"]]
            if (entry.get("owner")!=hold["owner"] or entry.get("model_token")!=hold["model_token"]
                    or entry["concurrency"]!=audit["target_concurrency"]):
                raise OwnershipError("Model reservation changed")
            if board["global_stop"]:
                raise Conflict("Global STOP remains active; do not release the queue automatically")
            if continuation is not None and board["jobs"].get(continuation["job_id"]) != continuation:
                raise Conflict("Finalized continuation receipt differs from current remote completion")
            if any(j["model"]==hold["model"] and j["status"] in ("claimed","running") for j in board["jobs"].values()):
                raise Conflict("Remote job remains active")
            item=board["jobs"][hold["original_job"]["job_id"]]
            released=any(e.get("operation_id")==hold["operation_id"] and e.get("action")=="release_queue_hold"
                         for e in board.get("operational_events",[]))
            if released and item==hold["original_job"]:
                return
            if item!=hold["held_job"]:
                raise Conflict("Administrative hold was changed; do not overwrite it")
            board["jobs"][item["job_id"]]=deepcopy(hold["original_job"])
            board.setdefault("operational_events",[]).append({"operation_id":hold["operation_id"],
                "action":"release_queue_hold","model":hold["model"],"job_id":item["job_id"],
                "at":now(),"calibration_attempt":calibration_attempt,
                "note":"Exact original unstarted job restored after successful technical capacity check"})
            validate_board(board)
        updated=coordinator._mutate("Release capacity-probe queue hold",change)
        if updated["jobs"][hold["original_job"]["job_id"]]!=hold["original_job"]:
            raise Conflict("Queue release was not confirmed")
        audit.update(status="released",released_at=now(),calibration_attempt=calibration_attempt,
                     capacity_evidence=capacity_evidence)
        atomic_json(directory/"capacity.private.json",audit)
        return audit


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir",required=True)
    parser.add_argument("--operation-dir",required=True)
    parser.add_argument("--remote",default="https://github.com/dasnidm/llm-equivoque-experiments.git")
    parser.add_argument("--branch",default="exp7/main-v2-coordination")
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("status")
    reserve=commands.add_parser("reserve");reserve.add_argument("--concurrency",type=int,default=10)
    for name in ("resize-local","release"):
        child=commands.add_parser(name)
        child.add_argument("--old-worker-pid",type=int,required=True)
        child.add_argument("--old-supervisor-pid",type=int,required=True)
        child.add_argument("--reconciliation-receipt",
                           help="Explicit hash-verified exemption for three immutable original interruptions; never replay them")
        child.add_argument("--stopped-calibration-receipt",
                           help="Explicit archive-verified exemption for the ten preserved c10-01 interruptions")
        if name=="release":
            child.add_argument("--calibration-attempt",required=True)
            child.add_argument("--freeze",required=True)
    args=parser.parse_args(argv)
    try:
        coordinator=GitCoordinator(args.remote,args.branch,Path(args.operation_dir)/"coordination.git")
        if args.command=="reserve":
            result=reserve_target(coordinator,args.work_dir,args.operation_dir,args.concurrency)
        elif args.command=="resize-local":
            result=resize_local(coordinator,args.work_dir,args.operation_dir,args.old_worker_pid,args.old_supervisor_pid,
                                args.reconciliation_receipt,stopped_calibration_receipt=args.stopped_calibration_receipt)
        elif args.command=="release":
            result=release_hold(coordinator,args.work_dir,args.operation_dir,args.old_worker_pid,args.old_supervisor_pid,
                                args.calibration_attempt,args.freeze,args.reconciliation_receipt,
                                stopped_calibration_receipt=args.stopped_calibration_receipt)
        else:
            board=coordinator.status();hold=read(Path(args.operation_dir)/"hold.private.json")
            result={"status":"inspection","model":hold["model"],"held_job":hold["held_job"]["job_id"],
                    "held_status":board["jobs"][hold["held_job"]["job_id"]]["status"],
                    "reserved_concurrency":board["models"][hold["model"]]["concurrency"],
                    "local_concurrency":read(Path(args.work_dir)/"identity.private.json")["concurrency"],
                    "active_jobs":[j["job_id"] for j in board["jobs"].values()
                                   if j["model"]==hold["model"] and j["status"] in ("claimed","running")]}
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status":"blocked","error_type":type(exc).__name__,"message":str(exc)},ensure_ascii=False),flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
