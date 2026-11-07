"""Offline original-budget continuation with real local Git publication."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from exp7_main.test_protocol import example
from exp7_main.test_runner import FakeTransport
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.runner import CallBudget, run_trial, atomic_json
from exp7_main_v2.coordination import GitCoordinator,new_board,Conflict
from exp7_main_v2.worker import ResultPublisher,export_job,job_identity,sha
from exp7_ops_v1.recovery import (
    prepare_recovery,execute_recovery,finalize_recovery,verify_reconciliation,read,
)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="exp7-recovery-")
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        remote=self.root/"remote.git"
        subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
        self.c=GitCoordinator(str(remote),"coordination",self.root/"coord.git")
        self.p=ResultPublisher(str(remote),"results",self.root/"results.git")
        size=getattr(self,"panel_size",4)
        total=size+2
        self.trials={f"t{i}":example(trial_id=f"t{i}",run_id="run") for i in range(total)}
        self.c.bootstrap(new_board("run","b"*64,"c"*40,[{"job_id":"job","model":"fake","trial_ids":list(self.trials)}],
            global_stop=False,global_max_concurrency=10,freeze_sha256="a"*64))
        token=self.c.claim_model("fake","owner",concurrency=3)
        self.job=self.c.claim_job("fake","owner",token)
        self.bound={"model":"fake","owner":"owner","model_token":token,"run_id":"run","concurrency":3}
        self.work=self.root/"work";self.dir=self.work/"jobs"/"job";self.dir.mkdir(parents=True)
        self.op=self.work/"ops-v1"/"continuation-01";self.op.mkdir(parents=True)
        atomic_json(self.work/"identity.private.json",self.bound)
        atomic_json(self.dir/"claim.private.json",job_identity(self.job,self.bound))
        budget=CallBudget(self.dir/"budget.json","run:job",34*total)
        states=[]
        for i in range(2):
            state=run_trial(self.trials[f"t{i}"],MainProtocol(),FakeTransport(MainProtocol(),raise_at=2 if i else None),
                self.dir/"states"/f"t{i}.json",self.dir/"native",budget,"a"*64)
            states.append(state)
        for i in range(2,total):
            states.append({"trial":self.trials[f"t{i}"],"status":"unstarted","freeze_sha256":"a"*64,
                           "turns":[],"rounds":[],"pending_turn":None})
        digest=export_job(states,self.dir/"public.jsonl.gz")
        ref=self.p.publish(self.dir/"public.jsonl.gz","results/original.jsonl.gz")
        self.c.complete_job("fake","owner",token,"job",self.job["claim_token"],
            counts={"complete":1,"failed":0,"interrupted":1,"unstarted":size},calls=36,result_ref=ref,result_sha256=digest)
        self.selected=[f"t{i}" for i in range(2,total)]
        self.calls=[]

    def plan(self):
        return prepare_recovery(self.c,self.p,self.work,self.op,self.trials,"a"*64,"job",self.selected,expected_count=len(self.selected))

    def transport(self):
        outer=self
        class Counting(FakeTransport):
            def request(self,trial,*args,**kwargs):
                outer.calls.append(trial["trial_id"])
                return super().request(trial,*args,**kwargs)
        return Counting(MainProtocol())

    def execute(self):
        return execute_recovery(self.c,self.p,self.work,self.op,self.trials,transport_factory=self.transport)

    def test_plan_receipt_preserves_pending_without_authorizing_replay(self):
        self.plan()
        paths=verify_reconciliation(self.work,self.op/"reconciliation.private.json")
        self.assertEqual(paths,{(self.dir/"states"/"t1.json").resolve()})
        self.assertEqual(self.calls,[])
        self.assertEqual(self.c.status()["jobs"]["job"]["status"],"blocked")

    def test_only_four_new_trials_run_and_old_publication_stays_immutable(self):
        intent=self.plan()
        # Capacity probe may have updated the local/remote reservation to ten;
        # continuation remains a pool of at most three with the original token.
        atomic_json(self.work/"identity.private.json",dict(self.bound,concurrency=10))
        self.c._mutate("Test capacity reservation",lambda b:b["models"]["fake"].update(concurrency=10))
        receipt=self.execute()
        self.assertEqual(len(self.calls),136)
        self.assertEqual(set(self.calls),set(self.selected))
        for relative,digest in intent["prior_files"].items():
            if relative!="budget.json": self.assertEqual(sha(self.dir/relative),digest)
        job=receipt["completed_job"]
        self.assertEqual(job["status"],"partial_failed")
        self.assertEqual(job["counts"],{"complete":5,"failed":0,"interrupted":1,"unstarted":0})
        self.assertEqual(job["calls"],172)
        self.assertEqual(read(self.dir/"budget.json")["limit"],204)
        self.assertTrue(job["result_ref"].endswith("job.continuation-01.jsonl.gz"))
        head=self.p._head()
        self.assertEqual(self.p._existing(head,"results/original.jsonl.gz"),(self.dir/"public.jsonl.gz").read_bytes())
        self.assertEqual(verify_reconciliation(self.work,self.op/"reconciliation-final.private.json"),
                         {(self.dir/"states"/"t1.json").resolve()})
        with self.assertRaises(Conflict): self.execute()
        self.assertEqual(len(self.calls),136)

    def test_wrong_ids_and_native_orphans_block_plan(self):
        self.selected=["t1","t3","t4","t5"]
        with self.assertRaises(Conflict): self.plan()
        self.selected=["t2","t3","t4","t5"]
        (self.dir/"native"/"orphan").mkdir(parents=True)
        with self.assertRaises(Conflict): self.plan()
        self.assertEqual(self.calls,[])

    def test_mismatched_budget_and_changed_old_state_fail_closed(self):
        budget=read(self.dir/"budget.json");budget["used"]+=1
        atomic_json(self.dir/"budget.json",budget)
        with self.assertRaises(Conflict): self.plan()
        budget["used"]-=1;atomic_json(self.dir/"budget.json",budget)
        self.plan()
        path=self.dir/"states"/"t1.json";state=read(path);state["pending_turn"]=None
        atomic_json(path,state)
        with self.assertRaises(Conflict): self.execute()
        with self.assertRaises(Conflict): verify_reconciliation(self.work,self.op/"reconciliation.private.json")
        self.assertEqual(self.calls,[])

    def test_stop_prevents_reopening_or_calls(self):
        self.plan();self.c.set_stop(True,"Synthetic external STOP")
        with self.assertRaises(Conflict): self.execute()
        self.assertEqual(self.calls,[])
        self.assertEqual(self.c.status()["jobs"]["job"]["status"],"blocked")
        self.assertEqual(read(self.op/"status.private.json")["status"],"planned")

    def test_reduced_remote_reservation_and_changed_budget_block(self):
        self.plan()
        self.c._mutate("Synthetic reservation mismatch",lambda b:b["models"]["fake"].update(concurrency=1))
        with self.assertRaises(Conflict): self.execute()
        self.assertEqual(self.calls,[])
        budget=read(self.dir/"budget.json");budget["limit"]+=1
        atomic_json(self.dir/"budget.json",budget)
        with self.assertRaises(Conflict):
            verify_reconciliation(self.work,self.op/"reconciliation.private.json")

    def test_finalize_retry_never_performs_inference(self):
        self.plan();first=self.execute()
        extra=self.root/"later.json";extra.write_text("later unrelated result")
        self.p.publish(extra,"results/later.json")
        second=finalize_recovery(self.c,self.p,self.work,self.op,self.trials)
        self.assertEqual(first["completed_job"],second["completed_job"])
        self.assertEqual(len(self.calls),136)

    def test_finalize_before_execution_cannot_publish_or_close_job(self):
        self.plan();head=self.p._head()
        with self.assertRaises(Conflict):
            finalize_recovery(self.c,self.p,self.work,self.op,self.trials)
        self.assertEqual(self.p._head(),head)
        self.assertEqual(self.c.status()["jobs"]["job"]["status"],"blocked")


if __name__=="__main__":
    unittest.main()


class LargerPanelTests(unittest.TestCase):
    def test_27_untouched_assignments_keep_original_budget_and_prior_states(self):
        fixture=RecoveryTests()
        fixture.panel_size=27
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        intent=fixture.plan()
        receipt=fixture.execute()
        self.assertEqual(len(fixture.calls),918)
        self.assertEqual(set(fixture.calls),set(fixture.selected))
        self.assertEqual(receipt['completed_job']['counts'],dict(complete=28,failed=0,interrupted=1,unstarted=0))
        self.assertEqual(receipt['completed_job']['calls'],954)
        for relative,digest in intent['prior_files'].items():
            if relative!='budget.json':self.assertEqual(sha(fixture.dir/relative),digest)
