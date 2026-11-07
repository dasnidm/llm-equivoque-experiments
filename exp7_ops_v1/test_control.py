"""Real local-Git operation checks; no external writes or inference."""
from copy import deepcopy
import fcntl
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from exp7_main_v2.coordination import GitCoordinator, new_board, Conflict, NoCapacity, OwnershipError
from exp7_ops_v1.control import (
    _validate_hold, atomic_json, read, reserve_target, resize_local, release_hold,
    verify_capacity_evidence,
)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-ops-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        self.coord = GitCoordinator(str(remote), "test", self.root / "cache.git")
        jobs = [{"job_id":"j1","model":"m1","trial_ids":["t1"]},
                {"job_id":"j2","model":"m2","trial_ids":["t2"]},
                {"job_id":"j3","model":"m1","trial_ids":["t3"]}]
        self.coord.bootstrap(new_board("run", "a"*64, "b"*40, jobs,
            freeze_sha256="c"*64, global_stop=False, global_max_concurrency=10))
        self.token = self.coord.claim_model("m1","owner",concurrency=3)
        self.job = self.coord.claim_job("m1","owner",self.token)
        self.coord.mark_running("m1","owner",self.token,"j1",self.job["claim_token"])
        self.work = self.root / "work"
        self.work.mkdir()
        self.op = self.work / "ops-v1" / "c10-01"
        self.op.mkdir(parents=True)
        self.bound = {"model":"m1","owner":"owner","model_token":self.token,
                      "run_id":"run","concurrency":3,"created_at":"2026-01-01T00:00:00+00:00"}
        atomic_json(self.work / "identity.private.json", self.bound)
        original = self.coord.status()["jobs"]["j3"]
        held = deepcopy(original)
        held.update(status="blocked",owner="operator-hold-c10-01",claim_token="hold-token",
                    ops_hold={"operation_id":"test-operation","non_inference":True})
        self.hold = {"schema_version":1,"status":"confirmed","operation_id":"test-operation",
                     "run_id":"run","model":"m1","owner":"owner","model_token":self.token,
                     "hold_token":"hold-token","original_job":original,"held_job":held}
        atomic_json(self.op / "hold.private.json",self.hold)
        self.coord._mutate("Test operator hold",lambda board: board["jobs"].update(j3=held))

    def finish(self):
        self.coord.complete_job("m1","owner",self.token,"j1",self.job["claim_token"],
            counts={"complete":1,"failed":0,"interrupted":0,"unstarted":0},calls=34,
            result_ref="d"*40+":results/j1.gz",result_sha256="e"*64)

    def resized(self):
        reserve_target(self.coord,self.work,self.op)
        self.finish()
        with patch("exp7_ops_v1.control.process_alive",return_value=False):
            return resize_local(self.coord,self.work,self.op,100001,100002)

    def release(self, passed=True):
        ready = self.work / "calibration" / "attempt-c10-01" / "readiness.json"
        ready.parent.mkdir(parents=True,exist_ok=True)
        self.synthetic_capacity(ready)
        with patch("exp7_ops_v1.control.process_alive",return_value=False), \
             patch("exp7_main_v2.worker.verify_freeze",return_value=({"run_id":"run","bundle":"fixture"},"c"*64)), \
             patch("exp7_main_v2.schedule.load_bundle",return_value={"trials":[]}), \
             patch("exp7_main_v2.worker.verify_readiness",side_effect=None if passed else ValueError("Invalid calibration")) as verify:
            result = release_hold(self.coord,self.work,self.op,100001,100002,"c10-01",self.root/"freeze.json")
            verify.assert_called_once_with(ready,"m1","c"*64,[],"owner")
            return result

    def synthetic_capacity(self, ready, peak=10, attempt="c10-01"):
        start=datetime.now(timezone.utc)+timedelta(seconds=1)
        entries=[]
        for i in range(18):
            trial_start=start+timedelta(seconds=100*(i//peak))
            state={"status":"complete","pending_turn":None,"started_at":trial_start.isoformat(),
                   "turns":[{"requested_at":(trial_start+timedelta(seconds=2*t)).isoformat(),
                             "received_at":(trial_start+timedelta(seconds=2*t+1)).isoformat()}
                            for t in range(34)]}
            relative=f"states/c{i}.json"
            atomic_json(ready.parent/relative,state)
            entries.append({"path":relative})
        atomic_json(ready,{"created_at":(start+timedelta(seconds=1000)).isoformat(),
                          "attempt":attempt,"calibration_call_cap":612,"states":entries})

    def test_reservation_leaves_current_pool_and_permission_unchanged(self):
        first = reserve_target(self.coord,self.work,self.op)
        second = reserve_target(self.coord,self.work,self.op)
        self.assertEqual(first["target_concurrency"],10)
        self.assertEqual(second["status"],"reserved")
        self.assertEqual(read(self.work/"identity.private.json"),self.bound)
        board=self.coord.status()
        self.assertEqual(board["models"]["m1"]["concurrency"],10)
        self.assertFalse(board["global_stop"])
        self.coord.assert_permission("m1","owner",self.token,"j1",self.job["claim_token"])
        self.coord.heartbeat("m1","owner",self.token,"j1",self.job["claim_token"])
        self.finish()
        with self.assertRaises(Conflict):
            self.coord.claim_job("m1","owner",self.token)
        with self.assertRaises(NoCapacity):
            self.coord.claim_model("m2","other",1)
        events=[e for e in self.coord.status()["operational_events"] if e["action"]=="reserve_capacity"]
        self.assertEqual(len(events),1)

    def test_reservation_respects_other_model_capacity(self):
        self.coord.claim_model("m2","other",1)
        with self.assertRaises(Conflict):
            reserve_target(self.coord,self.work,self.op)
        self.assertEqual(self.coord.status()["models"]["m1"]["concurrency"],3)
        self.assertEqual(read(self.work/"identity.private.json"),self.bound)

    def test_changed_or_non_operator_hold_rejected(self):
        invalid=deepcopy(self.hold)
        invalid["held_job"]["owner"]="arbitrary"
        with self.assertRaises(Conflict):
            _validate_hold(invalid)
        self.coord._mutate("Changed hold",lambda b:b["jobs"]["j3"].update(claim_token="changed"))
        with self.assertRaises(Conflict):
            reserve_target(self.coord,self.work,self.op)
        self.assertFalse((self.op/"capacity.private.json").exists())

    def test_resize_waits_for_processes_and_remote_active_job(self):
        reserve_target(self.coord,self.work,self.op)
        with patch("exp7_ops_v1.control.process_alive",return_value=True),self.assertRaises(Conflict):
            resize_local(self.coord,self.work,self.op,100001,100002)
        with patch("exp7_ops_v1.control.process_alive",return_value=False),self.assertRaises(Conflict):
            resize_local(self.coord,self.work,self.op,100001,100002)
        self.assertEqual(read(self.work/"identity.private.json"),self.bound)

    def test_resize_waits_for_locks_and_uncertain_requests(self):
        reserve_target(self.coord,self.work,self.op)
        self.finish()
        with (self.work/"worker.lock").open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch("exp7_ops_v1.control.process_alive",return_value=False),self.assertRaises(BlockingIOError):
                resize_local(self.coord,self.work,self.op,100001,100002)
        state=self.work/"jobs"/"j1"/"states"/"t1.json"
        state.parent.mkdir(parents=True)
        atomic_json(state,{"status":"interrupted","pending_turn":{"turn":1}})
        with patch("exp7_ops_v1.control.process_alive",return_value=False),self.assertRaises(Conflict):
            resize_local(self.coord,self.work,self.op,100001,100002)

    def test_resize_preserves_identity_and_is_restartable(self):
        first=self.resized()
        with patch("exp7_ops_v1.control.process_alive",return_value=False):
            second=resize_local(self.coord,self.work,self.op,100001,100002)
        self.assertEqual(first["status"],"local_resized")
        self.assertEqual(second["status"],"local_resized")
        self.assertEqual(first["resized_at"],second["resized_at"])
        self.assertEqual(read(self.work/"identity.private.json"),dict(self.bound,concurrency=10))
        self.assertEqual(self.coord.status()["jobs"]["j3"],self.hold["held_job"])

    def test_release_requires_successful_fresh_calibration(self):
        self.resized()
        with self.assertRaises(ValueError):
            self.release(passed=False)
        self.assertEqual(self.coord.status()["jobs"]["j3"],self.hold["held_job"])
        with self.assertRaises(ValueError):
            release_hold(self.coord,self.work,self.op,100001,100002,"01",self.root/"freeze.json")

    def test_release_refuses_global_stop(self):
        self.resized()
        self.coord.set_stop(True,"Failed capacity diagnostics")
        with self.assertRaises(Conflict):
            self.release()
        self.assertEqual(self.coord.status()["jobs"]["j3"],self.hold["held_job"])

    def test_release_rejects_substituted_local_identity_before_validating_readiness(self):
        self.resized()
        identity_path=self.work/"identity.private.json"
        original=read(identity_path)
        for field in ("run_id","model","owner","model_token"):
            with self.subTest(field=field):
                atomic_json(identity_path,{**original,field:"different-"+field})
                with patch("exp7_ops_v1.control.process_alive",return_value=False), \
                     patch("exp7_main_v2.worker.verify_freeze") as freeze, \
                     patch("exp7_main_v2.worker.verify_readiness") as readiness:
                    with self.assertRaises(OwnershipError):
                        release_hold(self.coord,self.work,self.op,100001,100002,
                                     "c10-01",self.root/"freeze.json")
                    freeze.assert_not_called()
                    readiness.assert_not_called()
                self.assertEqual(self.coord.status()["jobs"]["j3"],self.hold["held_job"])
                self.assertFalse(any(e.get("action")=="release_queue_hold"
                                     for e in self.coord.status()["operational_events"]))
        atomic_json(identity_path,original)

    def test_capacity_evidence_rejects_prior_attempt_and_insufficient_overlap(self):
        audit=self.resized()
        ready=self.work/"calibration"/"attempt-c10-01"/"readiness.json"
        ready.parent.mkdir(parents=True)
        self.synthetic_capacity(ready,peak=3)
        with self.assertRaises(Conflict):
            verify_capacity_evidence(ready,"c10-01",audit)
        self.synthetic_capacity(ready,peak=10,attempt="01")
        with self.assertRaises(Conflict):
            verify_capacity_evidence(ready,"c10-01",audit)
        self.synthetic_capacity(ready)
        self.assertEqual(verify_capacity_evidence(ready,"c10-01",audit)["observed_local_pending_peak"],10)
        state=ready.parent/"states"/"c0.json"
        data=read(state)
        data["started_at"]="2000-01-01T00:00:00+00:00"
        atomic_json(state,data)
        with self.assertRaises(Conflict):
            verify_capacity_evidence(ready,"c10-01",audit)

    def test_successful_release_restores_exact_job_and_preserves_claims(self):
        self.resized()
        self.assertEqual(self.release()["status"],"released")
        self.assertEqual(self.release()["status"],"released")
        board=self.coord.status()
        self.assertEqual(board["jobs"]["j3"],self.hold["original_job"])
        self.assertEqual(board["models"]["m1"]["model_token"],self.token)
        claimed=self.coord.claim_job("m1","owner",self.token)
        self.assertEqual(claimed["job_id"],"j3")


if __name__=="__main__":
    unittest.main()
