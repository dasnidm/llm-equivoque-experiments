"""Audited return from two failed ten-way probes to the proven three-way pool.

No STOP is cleared here. The two failed calibrations and all uncertain turns
remain immutable. Only the four original never-started assignments may run.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack,contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import shutil

from exp7_main_v2.coordination import GitCoordinator,Conflict,OwnershipError,validate_board
from exp7_main_v2.worker import ROOT,ResultPublisher,StorageMonitor,verify_freeze,verify_readiness,sha
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.runner import atomic_json,now
from .control import read,process_alive,board_identity,_validate_hold
from .recovery import verify_reconciliation,execute_recovery
from .measure import overlap_segments,seconds


@contextmanager
def fallback_lock(work,operation,stopped_pids):
    if not stopped_pids or any(process_alive(pid) for pid in stopped_pids):
        raise Conflict("Every explicitly recorded previous worker/probe must have exited")
    work,operation=Path(work).resolve(),Path(operation).resolve();operation.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        paths=[operation/"fallback.lock",work/"worker.lock"]
        if (work/"launch-v1").exists():paths.append(work/"launch-v1"/"launcher.lock")
        for path in paths:
            lock=stack.enter_context(path.open("a"));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def baseline_readiness(work,freeze_path):
    executable=shutil.which("codex")
    real=Path("/opt/codex/bin/codex").resolve()
    if not executable or Path(executable).resolve()!=real:
        raise Conflict("Fallback requires the original CLI PATH; no catalog shim may be active")
    frozen,digest=verify_freeze(freeze_path)
    plan=load_bundle(ROOT/frozen["bundle"]);bound=read(Path(work)/"identity.private.json")
    ready=Path(work)/"calibration/attempt-01/readiness.json"
    evidence=verify_readiness(ready,bound["model"],digest,plan["trials"],bound["owner"])
    if evidence.get("attempt")!="01" or evidence.get("calibration_call_cap")!=612:
        raise Conflict("The original successful readiness panel is required")
    intervals=[]
    for row in evidence["states"]:
        state=read(ready.parent/row["path"])
        intervals += [(seconds(t["requested_at"]),seconds(t["received_at"])) for t in state["turns"]]
    peak=max((n for _,_,n in overlap_segments(intervals)),default=0)
    if len(intervals)!=612 or peak!=3:
        raise Conflict("Original readiness must prove all612 successful calls with local request peak3")
    return {"frozen":frozen,"freeze_sha256":digest,"trials":{t["trial_id"]:t for t in plan["trials"]},
            "readiness_sha256":sha(ready),"binary_sha256":sha(real),"observed_local_pending_peak":peak}


def preserved_uncertainty(work,recovery_operation,calibration_receipts,freeze_digest):
    from .calibration_snapshot import verify_terminal_calibration_snapshot
    work=Path(work).resolve()
    original=verify_reconciliation(work,Path(recovery_operation)/"reconciliation.private.json")
    if len(original)!=3:raise Conflict("Exactly three original interrupted conversations must remain preserved")
    paths=set(original)
    if set(calibration_receipts)!={"c10-01","c10-02"}:
        raise Conflict("Both failed ten-way calibration receipts are required")
    for attempt,receipt in calibration_receipts.items():
        verified=verify_terminal_calibration_snapshot(work,receipt,expected_attempt=attempt,
                                                     expected_freeze_sha256=freeze_digest)
        if len(verified)!=10:raise Conflict("Each failed calibration must preserve exactly ten interruptions")
        for path in verified:
            path=Path(path).resolve()
            if not path.is_relative_to(work/"calibration"/("attempt-"+attempt)/"states"):
                raise Conflict("Technical preservation receipt includes an unrelated state")
        paths.update(verified)
    if len(paths)!=23:raise Conflict("Preservation receipts must bind23 distinct terminal interruptions")
    seen=set()
    sources=list((work/"jobs").glob("*/states/*.json"))+list((work/"calibration").glob("attempt-*/states/*.json"))
    for path in sources:
        state=read(path)
        if state.get("status")=="active":raise Conflict("An active conversation still exists")
        pending=state.get("pending_turn")
        if pending is None:continue
        if path.resolve() not in paths or state.get("status")!="interrupted":
            raise Conflict("An unacknowledged uncertain request remains")
        native=path.parent.parent/"native"/state["scratch_id"]/("turn-%02d"%pending["turn"])
        if native.exists() or native.is_symlink():
            raise Conflict("A preserved pending checkpoint has native dispatch evidence")
        seen.add(path.resolve())
    if seen!=paths:raise Conflict("The23 preserved pending checkpoints changed")
    return sorted(str(path.relative_to(work)) for path in paths)


def verify_evidence(work,freeze_path,recovery_operation,calibration_receipts):
    baseline=baseline_readiness(work,freeze_path)
    exclusions=preserved_uncertainty(work,recovery_operation,calibration_receipts,baseline["freeze_sha256"])
    recovery_path=Path(recovery_operation)/"intent.private.json"
    recovery=read(recovery_path)
    if recovery["board_identity"]["freeze_sha256"]!=baseline["freeze_sha256"]:
        raise Conflict("Recovery and baseline belong to different frozen experiments")
    return baseline,recovery,{"baseline_readiness_sha256":baseline["readiness_sha256"],
        "binary_sha256":baseline["binary_sha256"],"recovery_intent_sha256":sha(recovery_path),
        "calibration_receipt_sha256":{attempt:sha(path) for attempt,path in calibration_receipts.items()},
        "preserved_pending_paths":exclusions}


def check_owner(board,bound,identity):
    if board_identity(board)!=identity or bound["run_id"]!=identity["run_id"]:
        raise Conflict("Frozen run identity changed")
    entry=board["models"][bound["model"]]
    if entry.get("owner")!=bound["owner"] or entry.get("model_token")!=bound["model_token"]:
        raise OwnershipError("Original model ownership changed")
    return entry


def save_status(operation,status,intent_sha,**extra):
    data={"status":status,"intent_sha256":intent_sha,"at":now(),**extra}
    atomic_json(Path(operation)/"status.private.json",data);return data


def downgrade(coordinator,work,operation,capacity_operation,recovery_operation,calibration_receipts,freeze_path):
    """CAS only this model's reservation10→3; never alter STOP or assignments."""
    work,operation=Path(work).resolve(),Path(operation).resolve()
    baseline,recovery,proof=verify_evidence(work,freeze_path,recovery_operation,calibration_receipts)
    bound=read(work/"identity.private.json");hold=read(Path(capacity_operation)/"hold.private.json");_validate_hold(hold)
    if any(bound[k]!=hold[k] for k in ("run_id","model","owner","model_token")):
        raise OwnershipError("Capacity hold belongs to another worker")
    board=coordinator.status();entry=check_owner(board,bound,recovery["board_identity"])
    if board["jobs"][recovery["original_job"]["job_id"]]!=recovery["original_job"]:
        raise Conflict("Original blocked job changed before fallback")
    if board["jobs"][hold["held_job"]["job_id"]]!=hold["held_job"]:
        raise Conflict("Future-job hold changed before fallback")
    if read(Path(recovery_operation)/"status.private.json")["status"]!="planned":
        raise Conflict("The four-ID continuation has already been admitted")
    intent_path=operation/"intent.private.json"
    if intent_path.exists():
        intent=read(intent_path)
        if intent["proof"]!=proof or intent["model"]!=bound["model"] or intent["owner"]!=bound["owner"]:
            raise Conflict("Existing fallback intent differs")
    else:
        if bound["concurrency"]!=10 or entry["concurrency"]!=10:
            raise Conflict("This operation only decreases the recorded ten-way reservation to three")
        intent={"schema_version":1,"operation_id":operation.name,"created_at":now(),"model":bound["model"],
                "owner":bound["owner"],"model_token":bound["model_token"],"board_identity":board_identity(board),
                "global_max_concurrency":board["global_max_concurrency"],"original_bound":bound,
                "capacity_operation":str(Path(capacity_operation).resolve()),"recovery_operation":str(Path(recovery_operation).resolve()),
                "calibration_receipts":{k:str(Path(v).resolve()) for k,v in calibration_receipts.items()},
                "freeze_path":str(Path(freeze_path).resolve()),"proof":proof,
                "original_capacity_audit":read(Path(capacity_operation)/"capacity.private.json"),
                "abandoned_attempts":["c10-01","c10-02"],"target_concurrency":3,
                "policy":"Both ten-way probes failed catalog429; return to original validated three-way transport; never replay23 interruptions"}
        atomic_json(intent_path,intent);os.chmod(intent_path,0o600)
    intent_sha=sha(intent_path)
    save_status(operation,"decrease_intent",intent_sha)
    def change(current):
        remote=check_owner(current,bound,intent["board_identity"])
        if current["global_max_concurrency"]!=intent["global_max_concurrency"]:
            raise Conflict("Global capacity changed; inspect instead of overwriting")
        if current["jobs"][recovery["original_job"]["job_id"]]!=recovery["original_job"] or current["jobs"][hold["held_job"]["job_id"]]!=hold["held_job"]:
            raise Conflict("Original job or future hold changed during fallback")
        if any(j["model"]==bound["model"] and j["status"] in ("claimed","running") for j in current["jobs"].values()):
            raise Conflict("Another job is active")
        events=current.setdefault("operational_events",[])
        prior=next((e for e in events if e.get("operation_id")==intent["operation_id"] and e.get("action")=="return_to_validated_three"),None)
        if prior:
            if prior["intent_sha256"]!=intent_sha or remote["concurrency"]!=3:raise Conflict("Prior fallback differs")
            return
        if remote["concurrency"]!=10:raise Conflict("Reservation changed before the decrease")
        remote["concurrency"]=3
        events.append({"operation_id":intent["operation_id"],"action":"return_to_validated_three","intent_sha256":intent_sha,
                       "model":bound["model"],"from":10,"to":3,"at":now(),"failed_attempts":intent["abandoned_attempts"]})
        validate_board(current)
    confirmed=coordinator._mutate("Return only this model to validated concurrency3",change)
    if confirmed["models"][bound["model"]]["concurrency"]!=3:raise Conflict("Reservation decrease not confirmed")
    bound["concurrency"]=3;atomic_json(work/"identity.private.json",bound);os.chmod(work/"identity.private.json",0o600)
    return save_status(operation,"returned_to_three",intent_sha,failed_ten_way_attempts=intent["abandoned_attempts"])


def verify_fallback(coordinator,work,operation):
    operation=Path(operation);intent=read(operation/"intent.private.json");status=read(operation/"status.private.json")
    if sha(operation/"intent.private.json")!=status["intent_sha256"]:raise Conflict("Fallback intent changed")
    baseline,recovery,proof=verify_evidence(work,intent["freeze_path"],intent["recovery_operation"],intent["calibration_receipts"])
    if proof!=intent["proof"]:raise Conflict("Frozen fallback evidence changed")
    bound=read(Path(work)/"identity.private.json")
    if any(bound[k]!=intent["original_bound"][k] for k in ("model","owner","model_token","run_id")) or bound["concurrency"]!=3:
        raise OwnershipError("Local identity differs from the validated fallback")
    board=coordinator.status();entry=check_owner(board,bound,intent["board_identity"])
    if entry["concurrency"]!=3 or board["global_max_concurrency"]!=intent["global_max_concurrency"]:
        raise Conflict("Remote reservation/global capacity differs from fallback")
    event=next((e for e in board.get("operational_events",[]) if e.get("operation_id")==intent["operation_id"] and e.get("action")=="return_to_validated_three"),None)
    if not event or event.get("intent_sha256")!=status["intent_sha256"]:raise Conflict("Remote decrease lacks this fallback receipt")
    return intent,status,baseline,recovery,bound,board


def execute_four(coordinator,publisher,work,operation,timeout=300,transport_factory=None):
    intent,status,baseline,recovery,bound,board=verify_fallback(coordinator,work,operation)
    if status["status"]!="returned_to_three":raise Conflict("Fallback continuation has already been admitted; never replay")
    if board["global_stop"]:raise Conflict("STOP remains active; helper never clears it")
    save_status(operation,"continuation_admitted_once",status["intent_sha256"])
    receipt=execute_recovery(coordinator,publisher,work,intent["recovery_operation"],baseline["trials"],timeout,transport_factory)
    completed=receipt["completed_job"];original=recovery["original_job"]
    expected=dict(original["counts"]);expected["complete"]+=4;expected["unstarted"]=0
    success=completed["status"]=="partial_failed" and completed["counts"]==expected and completed["calls"]==original["calls"]+136
    return save_status(operation,"continuation_complete" if success else "continuation_failed",
                       status["intent_sha256"],completed_job=completed)


def release(coordinator,work,operation):
    intent,status,baseline,recovery,bound,board=verify_fallback(coordinator,work,operation)
    if status["status"] not in ("continuation_complete","released_at_three"):
        raise Conflict("All four never-started assignments must complete before releasing the future hold")
    completed=status["completed_job"]
    if completed["counts"]["unstarted"] or completed["status"]!="partial_failed":raise Conflict("Continuation is incomplete")
    final_receipt=Path(intent["recovery_operation"])/"reconciliation-final.private.json"
    if verify_reconciliation(work,final_receipt)!=verify_reconciliation(work,Path(intent["recovery_operation"])/"reconciliation.private.json"):
        raise Conflict("Final continuation changed the preserved interruptions")
    hold=read(Path(intent["capacity_operation"])/"hold.private.json");_validate_hold(hold)
    def change(current):
        remote=check_owner(current,bound,intent["board_identity"])
        if current["global_stop"] or remote["concurrency"]!=3:raise Conflict("STOP or reservation prevents release")
        if current["global_max_concurrency"]!=intent["global_max_concurrency"] or current["jobs"].get(completed["job_id"])!=completed:
            raise Conflict("Global capacity or completed continuation changed")
        if any(j["model"]==bound["model"] and j["status"] in ("claimed","running") for j in current["jobs"].values()):
            raise Conflict("An active job prevents release")
        item=current["jobs"][hold["held_job"]["job_id"]];events=current.setdefault("operational_events",[])
        prior=next((e for e in events if e.get("operation_id")==intent["operation_id"] and e.get("action")=="release_hold_at_validated_three"),None)
        if prior and item==hold["original_job"]:return
        if item!=hold["held_job"]:raise Conflict("Future administrative hold changed")
        current["jobs"][item["job_id"]]=deepcopy(hold["original_job"])
        events.append({"operation_id":intent["operation_id"],"action":"release_hold_at_validated_three", "at":now(),
                       "model":bound["model"],"intent_sha256":status["intent_sha256"],"concurrency":3,
                       "note":"Ten-way probes abandoned; original three-way readiness and four-ID continuation verified"})
        validate_board(current)
    coordinator._mutate("Release exact future hold after validated three-way fallback",change)
    capacity_path=Path(intent["capacity_operation"])/"capacity.private.json"
    capacity=read(capacity_path)
    if capacity!=intent["original_capacity_audit"] and capacity.get("fallback_intent_sha256")!=status["intent_sha256"]:
        raise Conflict("Capacity audit changed outside this fallback; remote release is recorded, inspect local audit")
    capacity.update(status="abandoned_after_catalog429_returned3",actual_concurrency=3,
                    abandoned_attempts=intent["abandoned_attempts"],fallback_intent_sha256=status["intent_sha256"],
                    fallback_at=now(),ten_way_validation_passed=False)
    atomic_json(capacity_path,capacity)
    return save_status(operation,"released_at_three",status["intent_sha256"],completed_job=completed,
                       concurrency=3,ten_way_validation_passed=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("work-dir","operation-dir"):p.add_argument("--"+name,required=True)
    p.add_argument("--stopped-pid",type=int,action="append",required=True)
    p.add_argument("--remote",default="https://github.com/dasnidm/llm-equivoque-experiments.git")
    p.add_argument("--branch",default="exp7/main-v2-coordination")
    p.add_argument("--result-branch",default="exp7/main-v2-results/gpt-6-astra")
    p.add_argument("--timeout",type=float,default=300)
    sub=p.add_subparsers(dest="command",required=True)
    down=sub.add_parser("downgrade")
    for name in ("capacity-operation-dir","recovery-operation-dir","calibration-01-receipt","calibration-02-receipt","freeze"):
        down.add_argument("--"+name,required=True)
    sub.add_parser("execute-four");sub.add_parser("release")
    args=p.parse_args(argv)
    try:
        work,operation=Path(args.work_dir).resolve(),Path(args.operation_dir).resolve()
        coordinator=GitCoordinator(args.remote,args.branch,operation/"coordination.git")
        with fallback_lock(work,operation,args.stopped_pid):
            coordinator.worker_storage_monitor=StorageMonitor([work,Path(os.environ.get("CODEX_HOME",Path.home()/".codex"))],coordinator)
            coordinator.worker_storage_monitor.check(force=True)
            if args.command=="downgrade":
                result=downgrade(coordinator,work,operation,args.capacity_operation_dir,args.recovery_operation_dir,
                    {"c10-01":args.calibration_01_receipt,"c10-02":args.calibration_02_receipt},args.freeze)
            elif args.command=="execute-four":
                publisher=ResultPublisher(args.remote,args.result_branch,operation/"results.git")
                result=execute_four(coordinator,publisher,work,operation,args.timeout)
            else:result=release(coordinator,work,operation)
        summary={k:result[k] for k in ("status","at","concurrency","ten_way_validation_passed","failed_ten_way_attempts") if k in result}
        if "completed_job" in result:summary.update(counts=result["completed_job"]["counts"],calls=result["completed_job"]["calls"])
        print(json.dumps(summary,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({"status":"blocked","error_type":type(exc).__name__,"message":str(exc)},ensure_ascii=False));return 1


if __name__=="__main__":raise SystemExit(main())
