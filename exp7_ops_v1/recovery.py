"""Explicit once-only continuation of proven never-started assignments.

Existing terminal conversations, uncertain requests and prior public results
are immutable. This operator action never clears STOP and never replays a trial.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re

from exp7_main_v2.coordination import GitCoordinator, Conflict, OwnershipError, validate_board
from exp7_main_v2.worker import (
    ROOT, PermissionGate, GatedTransport, StorageMonitor, ResultPublisher,
    export_job, job_identity, sha, verify_freeze, verify_readiness, heartbeat_due,
)
from exp7_main_v2.runner import CallBudget, NativeTransport, run_trial, atomic_json, now, TERMINAL
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.schedule import load_bundle
from .control import read, board_identity, process_alive


@contextmanager
def recovery_lock(work_dir, operation_dir, old_worker_pid, old_supervisor_pid):
    if process_alive(old_worker_pid) or process_alive(old_supervisor_pid):
        raise Conflict("Previous worker/supervisor is still alive")
    work_dir, operation_dir=Path(work_dir).resolve(),Path(operation_dir).resolve()
    operation_dir.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        paths=[operation_dir/"recovery.lock",work_dir/"worker.lock"]
        if (work_dir/"launch-v1").exists():
            paths.append(work_dir/"launch-v1"/"launcher.lock")
        for path in paths:
            handle=stack.enter_context(path.open("a"))
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def inventory(directory):
    """Hash regular evidence files; reject links and unexpected ownership."""
    result={}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink():
            raise Conflict("Linked evidence is not eligible for continuation")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise Conflict("Hard-linked evidence is not eligible for continuation")
            result[path.relative_to(directory).as_posix()]=sha(path)
    return result


def check_binding(board,bound,identity,job=None):
    if board_identity(board)!=identity or bound["run_id"]!=identity["run_id"]:
        raise Conflict("Frozen experiment identity changed")
    entry=board["models"][bound["model"]]
    if entry.get("owner")!=bound["owner"] or entry.get("model_token")!=bound["model_token"]:
        raise OwnershipError("Model ownership changed")
    if job is not None and (job["model"]!=bound["model"] or job["owner"]!=bound["owner"]):
        raise OwnershipError("Job belongs to another worker")


def verify_publication(publisher,job,local_path):
    if sha(local_path)!=job["result_sha256"]:
        raise Conflict("Prior public result differs from its remote receipt")
    commit,target=job["result_ref"].split(":",1)
    with (publisher.cache/"publisher.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        head=publisher._head()
        content=Path(local_path).read_bytes()
        if publisher._existing(commit,target)!=content or publisher._existing(head,target)!=content:
            raise Conflict("Prior public result is not intact on its result branch")


def inspect_unstarted(directory,job,trials,freeze_digest,selected,expected_count=4):
    if expected_count < 1 or len(selected)!=expected_count or len(set(selected))!=expected_count:
        raise Conflict("This continuation requires the explicit number of distinct never-started IDs")
    if not set(selected).issubset(job["trial_ids"]):
        raise Conflict("Selected IDs are outside the original job")
    if job["call_cap"]!=34*len(job["trial_ids"]):
        raise Conflict("Original call cap differs from the frozen job size")
    existing,missing,tickets,journal_tickets,scratch_ids=[],[],[],[],set()
    for tid in job["trial_ids"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+",tid):
            raise Conflict("Unsafe trial ID")
        if trials[tid].get("trial_id")!=tid or trials[tid].get("model")!=job["model"]:
            raise Conflict("Original job contains a cross-model or mismatched assignment")
        path=directory/"states"/(tid+".json")
        if not path.exists():
            missing.append(tid)
            if any((directory/"states"/(tid+suffix)).exists() for suffix in (".journal.jsonl",".json.lock")):
                raise Conflict("Never-started ID has a prior journal/lock artifact")
            continue
        state=read(path)
        if state["trial"]!=trials[tid] or state["freeze_sha256"]!=freeze_digest or state["status"] not in TERMINAL:
            raise Conflict("Prior state is active or differs from the original frozen assignment")
        existing.append(state)
        scratch_ids.add(state["scratch_id"])
        tickets.extend(r["budget_ticket"] for r in state["turns"])
        if state.get("pending_turn") is not None:
            if state["status"]!="interrupted":
                raise Conflict("Only terminal interrupted uncertainty can be preserved")
            tickets.append(state["pending_turn"]["budget_ticket"])
        journal=path.with_suffix(".journal.jsonl")
        for line in journal.read_text().splitlines():
            row=json.loads(line)
            if row["type"]=="request_checkpoint":
                journal_tickets.append(row["budget_ticket"])
    if set(missing)!=set(selected):
        raise Conflict("Explicit continuation IDs do not exactly match all proven never-started IDs")
    allowed={tid+suffix for tid in job["trial_ids"] for suffix in (".json",".journal.jsonl",".json.lock")}
    if any(p.name not in allowed or not p.is_file() for p in (directory/"states").iterdir()):
        raise Conflict("Unexpected prior state artifact")
    if (directory/"native").exists() and any(p.name not in scratch_ids or not p.is_dir()
                                             for p in (directory/"native").iterdir()):
        raise Conflict("Orphan native evidence prevents proving the four IDs untouched")
    budget=read(directory/"budget.json")
    if budget["run_id"]!=trials[job["trial_ids"][0]]["run_id"]+":"+job["job_id"] or budget["limit"]!=job["call_cap"]:
        raise Conflict("Budget identity/cap differs")
    expected=list(range(1,budget["used"]+1))
    if sorted(tickets)!=expected or sorted(journal_tickets)!=expected or budget["used"]!=job["calls"]:
        raise Conflict("State/journal tickets do not reconcile exactly with spent calls")
    counts=Counter({"complete":0,"failed":0,"interrupted":0,"unstarted":len(missing)})
    for state in existing:
        counts["interrupted" if state["status"]=="budget_exhausted" else state["status"]]+=1
    if dict(counts)!=job["counts"] or budget["used"]+34*len(selected)>job["call_cap"]:
        raise Conflict("Prior job counts or remaining immutable budget disagree")
    return existing,budget


def prepare_recovery(coordinator,publisher,work_dir,operation_dir,trials,freeze_digest,job_id,selected,expected_count=4):
    """Write a durable intent only; caller holds recovery/worker locks."""
    work_dir,operation_dir=Path(work_dir).resolve(),Path(operation_dir).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+",operation_dir.name):
        raise Conflict("Invalid operation ID")
    path=operation_dir/"intent.private.json"
    if path.exists():
        raise Conflict("Existing recovery intent must be reviewed; do not replace or re-plan")
    board=coordinator.status();bound=read(work_dir/"identity.private.json");job=board["jobs"][job_id]
    identity=board_identity(board)
    check_binding(board,bound,identity,job)
    if identity["freeze_sha256"]!=freeze_digest or job["status"]!="blocked":
        raise Conflict("Expected this frozen blocked job")
    if any(j["model"]==bound["model"] and j["status"] in ("claimed","running") for j in board["jobs"].values()):
        raise Conflict("Another job is still active")
    directory=work_dir/"jobs"/job_id
    if (directory/"archive-receipt.private.json").exists():
        raise Conflict("Archived jobs cannot be reopened")
    if read(directory/"claim.private.json")!=job_identity(job,bound):
        raise OwnershipError("Durable original job claim differs")
    existing,budget=inspect_unstarted(directory,job,trials,freeze_digest,selected,expected_count)
    verify_publication(publisher,job,directory/"public.jsonl.gz")
    files=inventory(directory)
    intent={"schema_version":1,"operation_id":operation_dir.name,"created_at":now(),
            "action":"continue_only_never_started_assignments","bound":bound,"board_identity":identity,
            "original_job":job,"selected_ids":[tid for tid in job["trial_ids"] if tid in selected],
            "original_budget":budget,"maximum_additional_calls":34*len(selected),"prior_files":files,
            "excluded_interrupted_ids":[s["trial"]["trial_id"] for s in existing if s["status"]=="interrupted"],
            "revision_target":f"results/{bound['run_id']}/{bound['model']}/{job_id}.{operation_dir.name}.jsonl.gz"}
    atomic_json(path,intent);os.chmod(path,0o600)
    atomic_json(operation_dir/"status.private.json",{"status":"planned","intent_sha256":sha(path),"at":now()})
    atomic_json(operation_dir/"reconciliation.private.json",{
        "schema_version":1,"phase":"preserved_before_continuation","operation_id":intent["operation_id"],
        "intent_path":str(path.resolve()),"intent_sha256":sha(path),"original_job":job,
        "excluded_interrupted_ids":intent["excluded_interrupted_ids"],"created_at":now(),
        "policy":"Terminal uncertainty is preserved byte-for-byte and never executable; only quiescence exclusion"})
    return intent


def verify_prior(work_dir,intent,allow_budget_change=False):
    directory=Path(work_dir)/"jobs"/intent["original_job"]["job_id"]
    for relative,digest in intent["prior_files"].items():
        if allow_budget_change and relative=="budget.json":
            continue
        path=directory/relative
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1 or sha(path)!=digest:
            raise Conflict("Prior immutable evidence changed: "+relative)
    if allow_budget_change:
        original=intent["original_budget"];budget=read(directory/"budget.json")
        if (budget["run_id"]!=original["run_id"] or budget["limit"]!=original["limit"]
                or not original["used"]<=budget["used"]<=original["used"]+intent["maximum_additional_calls"]):
            raise Conflict("Preserved budget identity/cap changed or continuation exceeded its allowance")
    return directory


def finalize_recovery(coordinator,publisher,work_dir,operation_dir,trials):
    """Publish a distinct result revision; never perform inference on retry."""
    operation_dir=Path(operation_dir);intent=read(operation_dir/"intent.private.json")
    directory=verify_prior(work_dir,intent,allow_budget_change=True)
    bound=intent["bound"];job=intent["original_job"]
    status=read(operation_dir/"status.private.json")
    if status.get("intent_sha256")!=sha(operation_dir/"intent.private.json"):
        raise Conflict("Recovery intent changed")
    if status.get("status") not in ("inference_admitted_once","finalized"):
        raise Conflict("Continuation was never admitted; do not publish a premature revision")
    output=[];counts=Counter({"complete":0,"failed":0,"interrupted":0,"unstarted":0})
    for tid in job["trial_ids"]:
        path=directory/"states"/(tid+".json")
        if path.exists():
            state=read(path)
            if state["trial"]!=trials[tid] or state["freeze_sha256"]!=intent["board_identity"]["freeze_sha256"] or state["status"] not in TERMINAL:
                raise Conflict("Continuation state is active or changed assignment")
            counts["interrupted" if state["status"]=="budget_exhausted" else state["status"]]+=1
        else:
            counts["unstarted"]+=1
            state={"trial":trials[tid],"status":"unstarted","freeze_sha256":intent["board_identity"]["freeze_sha256"],
                   "rounds":[],"turns":[],"pending_turn":None}
        output.append(state)
    budget=read(directory/"budget.json")
    original=intent["original_budget"]
    if budget["run_id"]!=original["run_id"] or budget["limit"]!=original["limit"] or not original["used"]<=budget["used"]<=original["used"]+intent["maximum_additional_calls"]:
        raise Conflict("Original immutable call budget changed or continuation overspent")
    verify_publication(publisher,job,directory/"public.jsonl.gz")
    path=directory/"revisions"/intent["operation_id"]/"public.jsonl.gz"
    digest=export_job(output,path)
    result_ref=publisher.publish(path,intent["revision_target"])
    board=coordinator.status();check_binding(board,bound,intent["board_identity"])
    current=board["jobs"][job["job_id"]]
    if (current.get("result_sha256")==digest and current["status"] in ("partial_failed","blocked","complete")
            and current.get("result_ref","").partition(":")[2]==intent["revision_target"]
            and current.get("counts")==dict(counts) and current.get("calls")==budget["used"]
            and current.get("ops_continuation",{}).get("intent_sha256")==status["intent_sha256"]):
        completed=current
        result_ref=current["result_ref"]
    else:
        if current.get("ops_continuation",{}).get("intent_sha256")!=status["intent_sha256"]:
            raise Conflict("Remote job lacks this explicit continuation transaction")
        completed=coordinator.complete_job(bound["model"],bound["owner"],bound["model_token"],job["job_id"],job["claim_token"],
            counts=dict(counts),calls=budget["used"],result_ref=result_ref,result_sha256=digest)
    verify_prior(work_dir,intent,allow_budget_change=True)
    receipt={"schema_version":1,"phase":"finalized","operation_id":intent["operation_id"],"intent_path":str((operation_dir/"intent.private.json").resolve()),
             "intent_sha256":status["intent_sha256"],"completed_job":completed,"created_at":now(),
             "excluded_interrupted_ids":intent["excluded_interrupted_ids"],
             "policy":"Original interrupted states are terminal exclusions; never resume or replay them"}
    receipt_path=operation_dir/"reconciliation-final.private.json"
    if not receipt_path.exists():
        atomic_json(receipt_path,receipt)
    atomic_json(operation_dir/"status.private.json",{"status":"finalized","intent_sha256":status["intent_sha256"],"at":now(),
                "result_ref":result_ref,"counts":dict(counts),"calls":budget["used"]})
    return receipt


def execute_recovery(coordinator,publisher,work_dir,operation_dir,trials,timeout=300,transport_factory=None):
    """Execute an intent at most once. Interrupted execution requires finalize/review."""
    work_dir,operation_dir=Path(work_dir).resolve(),Path(operation_dir).resolve()
    intent=read(operation_dir/"intent.private.json");status=read(operation_dir/"status.private.json")
    if status["status"]!="planned" or status["intent_sha256"]!=sha(operation_dir/"intent.private.json"):
        raise Conflict("Inference has already been admitted or intent changed; never replay this recovery")
    bound=intent["bound"];job=intent["original_job"]
    local=read(work_dir/"identity.private.json")
    if any(local.get(k)!=bound.get(k) for k in ("model","owner","model_token","run_id")):
        raise Conflict("Original local ownership changed")
    pool_size=min(3,local["concurrency"])
    if pool_size<1:
        raise Conflict("No local request capacity")
    directory=verify_prior(work_dir,intent)
    inspect_unstarted(directory,job,trials,intent["board_identity"]["freeze_sha256"],intent["selected_ids"],len(intent["selected_ids"]))
    board=coordinator.status();check_binding(board,bound,intent["board_identity"],job)
    if board["models"][bound["model"]]["concurrency"]!=local["concurrency"]:
        raise Conflict("Remote request reservation differs from the local pool")
    if board["global_stop"] or board["jobs"][job["job_id"]]!=job:
        raise Conflict("STOP remains active or the blocked job changed")
    verify_publication(publisher,job,directory/"public.jsonl.gz")
    atomic_json(operation_dir/"status.private.json",{"status":"inference_admitted_once","intent_sha256":status["intent_sha256"],"at":now()})
    def reopen(current):
        check_binding(current,bound,intent["board_identity"],job)
        if current["models"][bound["model"]]["concurrency"]!=local["concurrency"]:
            raise Conflict("Request reservation changed before continuation")
        if current["global_stop"] or current["jobs"][job["job_id"]]!=job:
            raise Conflict("STOP/job changed before explicit continuation")
        if any(j["model"]==bound["model"] and j["status"] in ("claimed","running") for j in current["jobs"].values()):
            raise Conflict("Another job became active")
        current["jobs"][job["job_id"]]["status"]="running"
        current["jobs"][job["job_id"]]["ops_continuation"]={"operation_id":intent["operation_id"],
            "intent_sha256":status["intent_sha256"],"selected_ids":intent["selected_ids"],
            "prior_result_ref":job["result_ref"],"maximum_additional_calls":intent["maximum_additional_calls"],"at":now()}
        validate_board(current)
    coordinator._mutate("Explicit never-started-only continuation",reopen)
    coordinator.worker_expected_identity=intent["board_identity"]
    gate=PermissionGate(coordinator,bound["model"],bound["owner"],bound["model_token"],job)
    budget=CallBudget(directory/"budget.json",intent["original_budget"]["run_id"],job["call_cap"])
    iterator=iter(intent["selected_ids"])
    def perform(tid):
        # A distinct transport per conversation also makes offline fixtures deterministic.
        transport=transport_factory() if transport_factory else NativeTransport(timeout=timeout)
        return run_trial(trials[tid],MainProtocol(),GatedTransport(transport,gate),directory/"states"/(tid+".json"),
                         directory/"native",budget,intent["board_identity"]["freeze_sha256"])
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        pending={}
        def submit():
            if gate.stopped.is_set(): return
            tid=next(iterator,None)
            if tid is not None:
                gate.check();pending[pool.submit(perform,tid)]=tid
        for _ in range(pool_size): submit()
        while pending:
            finished,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future);future.result()
            verify_prior(work_dir,intent,allow_budget_change=True)
            heartbeat_due(coordinator,bound,job)
            for _ in finished: submit()
    return finalize_recovery(coordinator,publisher,work_dir,operation_dir,trials)


def verify_reconciliation(work_dir,receipt_path):
    """Return ONLY hash-bound old terminal interruptions; never execute them."""
    receipt=read(receipt_path);intent_path=Path(receipt["intent_path"])
    if sha(intent_path)!=receipt["intent_sha256"]:
        raise Conflict("Reconciliation intent changed")
    intent=read(intent_path)
    if receipt["operation_id"]!=intent["operation_id"] or receipt["excluded_interrupted_ids"]!=intent["excluded_interrupted_ids"]:
        raise Conflict("Reconciliation exclusions changed")
    if receipt.get("phase")=="preserved_before_continuation":
        if receipt["original_job"]!=intent["original_job"] or receipt["original_job"]["status"]!="blocked":
            raise Conflict("Preserved terminal-state receipt differs from the blocked job")
    elif receipt.get("phase")=="finalized":
        job=receipt["completed_job"]
        if job["status"]!="partial_failed" or job["counts"]["unstarted"] or job["job_id"]!=intent["original_job"]["job_id"]:
            raise Conflict("Continuation is not fully reconciled")
        if job.get("ops_continuation",{}).get("intent_sha256")!=receipt["intent_sha256"]:
            raise Conflict("Completion does not bind this continuation")
    else:
        raise Conflict("Unknown reconciliation phase")
    directory=verify_prior(work_dir,intent,allow_budget_change=True)
    bound=read(Path(work_dir)/"identity.private.json")
    if any(bound[k]!=intent["bound"][k] for k in ("model","owner","model_token","run_id")):
        raise OwnershipError("Reconciliation belongs to another local worker")
    paths=set()
    for tid in receipt["excluded_interrupted_ids"]:
        path=directory/"states"/(tid+".json")
        if read(path)["status"]!="interrupted" or tid in intent["selected_ids"]:
            raise Conflict("Only original immutable interrupted trials may be excluded")
        paths.add(path.resolve())
    return paths


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-dir",required=True);p.add_argument("--operation-dir",required=True)
    p.add_argument("--freeze",required=True);p.add_argument("--old-worker-pid",type=int,required=True)
    p.add_argument("--old-supervisor-pid",type=int,required=True)
    p.add_argument("--remote",default="https://github.com/dasnidm/llm-equivoque-experiments.git")
    p.add_argument("--branch",default="exp7/main-v2-coordination")
    p.add_argument("--result-branch",required=True)
    p.add_argument("--timeout",type=float,default=300)
    p.add_argument("--calibration-attempt",default="01")
    p.add_argument("--capacity-operation-dir")
    sub=p.add_subparsers(dest="command",required=True)
    plan=sub.add_parser("plan");plan.add_argument("--job-id",required=True);plan.add_argument("--trial-id",action="append",required=True)
    sub.add_parser("execute");sub.add_parser("finalize")
    args=p.parse_args(argv)
    try:
        work=Path(args.work_dir).resolve();op=Path(args.operation_dir).resolve()
        frozen,digest=verify_freeze(args.freeze)
        schedule=load_bundle(ROOT/frozen["bundle"]);trials={t["trial_id"]:t for t in schedule["trials"]}
        coordinator=GitCoordinator(args.remote,args.branch,op/"coordination.git")
        publisher=ResultPublisher(args.remote,args.result_branch,op/"results.git")
        with recovery_lock(work,op,args.old_worker_pid,args.old_supervisor_pid):
            bound=read(work/"identity.private.json")
            ready=work/"calibration"/("attempt-"+args.calibration_attempt)/"readiness.json"
            verify_readiness(ready,bound["model"],digest,schedule["trials"],bound["owner"])
            if args.command=="execute":
                from .control import verify_capacity_evidence
                if args.calibration_attempt=="01" or not args.capacity_operation_dir:
                    raise Conflict("Continuation requires the fresh capacity probe and its audited resize")
                capacity=read(Path(args.capacity_operation_dir)/"capacity.private.json")
                if capacity.get("status")!="local_resized" or capacity.get("board_identity",{}).get("freeze_sha256")!=digest:
                    raise Conflict("Capacity operation does not bind this frozen experiment")
                if (capacity.get("model")!=bound["model"] or capacity.get("owner")!=bound["owner"]
                        or capacity.get("target_concurrency")!=10 or bound["concurrency"]!=10):
                    raise OwnershipError("Capacity readiness belongs to another worker or pool size")
                verify_capacity_evidence(ready,args.calibration_attempt,capacity)
            coordinator.worker_storage_monitor=StorageMonitor([work,Path(os.environ.get("CODEX_HOME",Path.home()/".codex"))],coordinator)
            coordinator.worker_storage_monitor.check(force=True)
            if args.command=="plan":
                result=prepare_recovery(coordinator,publisher,work,op,trials,digest,args.job_id,args.trial_id)
                summary={"status":"planned","selected_ids":result["selected_ids"],"preserved_interrupted_ids":result["excluded_interrupted_ids"],
                         "original_calls":result["original_budget"]["used"],"maximum_additional_calls":136}
            else:
                if args.command=="execute":
                    result=execute_recovery(coordinator,publisher,work,op,trials,args.timeout)
                else:
                    result=finalize_recovery(coordinator,publisher,work,op,trials)
                summary={"status":result["completed_job"]["status"],"counts":result["completed_job"]["counts"],
                         "calls":result["completed_job"]["calls"],"result_ref":result["completed_job"]["result_ref"]}
        print(json.dumps(summary,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({"status":"blocked","error_type":type(exc).__name__,"message":str(exc)},ensure_ascii=False));return 1


if __name__=="__main__":
    raise SystemExit(main())
