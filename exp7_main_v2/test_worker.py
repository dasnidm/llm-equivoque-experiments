"""Worker failure, privacy, and Git-publication tests; no external calls."""
from copy import deepcopy
import gzip
import importlib.metadata
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from .coordination import GitCoordinator, OwnershipError, new_board
from .protocol import MainProtocol
from .runner import CallBudget, run_trial
from exp7_main.test_protocol import example
from exp7_main.test_runner import FakeTransport
from .worker import (PermissionGate, ResultPublisher, bind_model, calibration_trials,
                     calibration_valid, execute_job, export_job, job_identity, public_state,
                     sha, verify_freeze, StorageMonitor, heartbeat_due, finalize_job, archive_backlog,
                     transport_profile, verify_transport_profile, verify_readiness, source_paths,
                     GatedTransport)
from exp7_pre.runner import atomic_json


class FakeCoordinator:
    def __init__(self):
        self.board = {"run_id": "test", "manifest_sha256": "a"*64,
                      "freeze_sha256": "b"*64, "source_commit": "c"*40,
                      "global_stop": False,
                      "models": {"fake": {"owner": "vm", "model_token": "token", "concurrency": 1}},
                      "jobs": {"j": {"model": "fake", "owner": "vm", "claim_token": "claim", "status": "running"}}}
        self.worker_expected_identity = {k: self.board[k] for k in ("run_id", "manifest_sha256", "freeze_sha256", "source_commit")}
        self.reads = 0
        self.fail = False

    def status(self):
        self.reads += 1
        if self.fail:
            raise RuntimeError("Network unavailable")
        return deepcopy(self.board)

    def set_stop(self, value, reason):
        self.board["global_stop"] = value


def available_trials():
    rows = []
    for effort in ("low", "medium", "high"):
        for game in ("obj", "seq", "KK", "KD", "DK", "DD"):
            for frame in ("cards", "cats"):
                for arm in ("en_schema", "en_natural", "ko_schema", "ko_natural", "R_A"):
                    rows.append(example(arm, game, frame, effort=effort,
                                        trial_id="-".join((effort,game,frame,arm)),
                                        fold=0, split="development", cohort="main"))
    return rows


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-worker-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def complete_state(self, arm="en_schema", game="seq"):
        trial = example(arm, game, trial_id="fixture-"+arm+"-"+game)
        protocol = MainProtocol()
        state = run_trial(trial, protocol, FakeTransport(protocol), self.root/(trial["trial_id"]+".json"),
                          self.root/"native", CallBudget(self.root/(trial["trial_id"]+"-budget.json"),"test",34),"a"*64)
        self.assertEqual(state["status"], "complete")
        return state

    def test_calibration_matrix_covers_every_arm_in_both_frames(self):
        rows = calibration_trials(available_trials(), "fake")
        self.assertEqual(len(rows),18)
        for effort in ("low","medium","high"):
            selected = [r for r in rows if r["effort"] == effort]
            self.assertEqual(len(selected),6)
            self.assertEqual({r["game"] for r in selected},{"obj","seq","KK","KD","DK","DD"})
            self.assertEqual({r["arm"] for r in selected},{"en_schema","en_natural","ko_schema","ko_natural","R_A"})
        for arm in {r["arm"] for r in rows}:
            self.assertEqual({r["frame"] for r in rows if r["arm"] == arm},{"cards","cats"})
        other = calibration_trials(available_trials(),"fake",attempt="02")
        self.assertFalse({r["trial_id"] for r in rows}&{r["trial_id"] for r in other})
        self.assertTrue(all(r["cohort"] == "technical_calibration" and r["fold"] is None for r in rows))

    def test_calibration_rejects_complete_but_missing_or_ambiguous_fields(self):
        state = self.complete_state()
        self.assertTrue(calibration_valid(state))
        for defect in ("missing", "ambiguous", "uncertain", "wrong_format", "no_summary"):
            bad = deepcopy(state)
            parsed = bad["turns"][2]["parsed"]
            if defect == "missing":
                parsed.update(freedom=None,impact=None,counterfactual=None)
            elif defect in ("ambiguous","uncertain"):
                parsed["_parse"]["fields"]["impact"] = defect
            elif defect == "wrong_format":
                parsed["_parse"]["format_compliant"] = False
            else:
                parsed.pop("_parse")
            self.assertFalse(calibration_valid(bad), defect)
        bad = deepcopy(state)
        bad["turns"][31]["parsed"]["_parse"]["fields"].pop("policy_4.final")
        self.assertFalse(calibration_valid(bad))

    def test_calibration_accepts_explicit_prediction_uncertainty_not_missingness(self):
        state = self.complete_state("ko_natural")
        self.assertTrue(calibration_valid(state))
        parsed = state["turns"][31]["parsed"]
        parsed["policy_1"]["final"] = "uncertain"
        parsed["_parse"]["fields"]["policy_1.final"] = "uncertain"
        self.assertTrue(calibration_valid(state))
        parsed["_parse"]["fields"]["policy_1.final"] = "unparseable"
        self.assertFalse(calibration_valid(state))
        r_state = self.complete_state("R_A")
        self.assertTrue(calibration_valid(r_state))
        r_state["turns"][2]["parsed"]["ack"] = None
        self.assertFalse(calibration_valid(r_state))

    def test_permission_cache_refresh_stop_and_identity_change(self):
        c = FakeCoordinator()
        gate = PermissionGate(c,"fake","vm","token",{"job_id":"j","claim_token":"claim"},ttl=10)
        with patch("exp7_main_v2.worker.time.monotonic",side_effect=[0,5,11]):
            gate.check()
            gate.check()
            c.board["global_stop"] = True
            with self.assertRaises(RuntimeError):
                gate.check()
        self.assertEqual(c.reads,2)
        c = FakeCoordinator()
        gate = PermissionGate(c,"fake","vm","token",ttl=0)
        c.board["freeze_sha256"] = "d"*64
        with self.assertRaisesRegex(RuntimeError,"identity"):
            gate.check()
        self.assertTrue(gate.stopped.is_set())

    def test_permission_network_failure_and_wrong_job_token_fail_closed(self):
        for failure in ("network","token"):
            c = FakeCoordinator()
            gate = PermissionGate(c,"fake","vm","token",{"job_id":"j","claim_token":"claim"},ttl=0)
            if failure == "network":
                c.fail = True
            else:
                c.board["jobs"]["j"]["claim_token"] = "other"
            with self.assertRaises(RuntimeError):
                gate.check()
            self.assertTrue(gate.stopped.is_set())

    def test_auth_and_capacity_diagnostics_stop_but_participant_text_does_not(self):
        for diagnostic in ("HTTP 429 Too many requests", "401 Unauthorized",
                           "Your access token could not be refreshed. Please sign in again."):
            c = FakeCoordinator()
            gate = PermissionGate(c,"fake","vm","token")
            gate.observe({"stderr":"", "events":[{"type":"error","message":diagnostic}]})
            self.assertTrue(gate.stopped.is_set())
            self.assertTrue(c.board["global_stop"])
        c = FakeCoordinator()
        gate = PermissionGate(c,"fake","vm","token")
        gate.observe({"text":"429 401 Unauthorized", "events":[{"type":"item.completed","item":{"type":"agent_message","text":"429"}}]})
        self.assertFalse(gate.stopped.is_set())

    def test_successful_catalog_429_preserves_response_and_cools_worker(self):
        c = FakeCoordinator()
        gate = PermissionGate(c, "fake", "vm", "token", allow_catalog_recovery=True)
        response = {"ok": True, "text": "preserved answer", "events": [],
                    "stderr": "ERROR codex_models_manager::manager: failed to refresh available models: 429 Too Many Requests",
                    "retry_after_seconds": 120}
        with patch("exp7_main_v2.worker.time.monotonic", return_value=10):
            gate.observe(response)
        self.assertFalse(gate.stopped.is_set())
        self.assertFalse(c.board["global_stop"])
        self.assertEqual(response["text"], "preserved answer")
        self.assertEqual(response["catalog_rate_limit"]["seconds"], 120)
        self.assertEqual(gate._cooldown_until, 130)
        # A remote stop must still be noticed before a delayed next request.
        c.board["global_stop"] = True
        with self.assertRaisesRegex(RuntimeError, "Permission stopped"):
            gate.check()

    def test_catalog_recovery_is_narrow_and_never_hides_response_or_auth_errors(self):
        catalog = "ERROR codex_models_manager::manager: failed to refresh available models: 429 Too Many Requests"
        variants = [
            {"ok": False, "stderr": catalog},
            {"ok": True, "stderr": catalog + "\n401 Unauthorized"},
            {"ok": True, "stderr": catalog + "\nresponses: 429 Too Many Requests"},
            {"ok": True, "stderr": catalog, "events": [{"type": "error", "message": "429 Too Many Requests"}]},
            {"ok": True, "stderr": "unclassified 429 Too Many Requests"},
        ]
        for response in variants:
            c = FakeCoordinator()
            gate = PermissionGate(c, "fake", "vm", "token", allow_catalog_recovery=True)
            gate.observe(response)
            self.assertTrue(gate.stopped.is_set(), response)
            self.assertTrue(c.board["global_stop"], response)
        c = FakeCoordinator()
        legacy = PermissionGate(c, "fake", "vm", "token")
        legacy.observe({"ok": True, "stderr": catalog})
        self.assertTrue(legacy.stopped.is_set())

    def test_catalog_cooldown_delays_even_forced_permission_checks(self):
        gate = PermissionGate(FakeCoordinator(), "fake", "vm", "token", allow_catalog_recovery=True)
        gate._cooldown_until = 130
        with patch.object(gate, "_check_permission") as permission:
            with patch.object(gate.stopped, "wait", return_value=False) as wait_for_stop:
                with patch("exp7_main_v2.worker.time.monotonic", side_effect=[10, 129, 130]):
                    gate.check(force=True)
        self.assertIsNone(gate._cooldown_until)
        self.assertEqual(wait_for_stop.call_count, 2)
        self.assertEqual(permission.call_count, 3)

    def test_transport_profile_binds_catalog_contents_and_blocks_old_freeze_switch(self):
        native = transport_profile()
        verify_transport_profile({}, native)
        catalog = self.root / "catalog.json"
        catalog.write_text('{"models": []}')
        selected = transport_profile("persistent", 0.5, catalog)
        with self.assertRaisesRegex(ValueError, "differ from freeze"):
            verify_transport_profile({}, selected)
        verify_transport_profile({"transport_profile": selected}, selected)
        copied = self.root / "catalog-copy.json"
        copied.write_bytes(catalog.read_bytes())
        verify_transport_profile({"transport_profile": selected}, transport_profile("persistent", 0.5, copied))
        catalog.write_text('{"models": ["changed"]}')
        with self.assertRaisesRegex(ValueError, "differ from freeze"):
            verify_transport_profile({"transport_profile": selected}, transport_profile("persistent", 0.5, catalog))
        for interval in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                transport_profile("persistent", interval)

    def test_persistent_sources_are_frozen_and_native_readiness_cannot_authorize_them(self):
        package = self.root / "exp7_persistent"
        package.mkdir()
        source = package / "transport.py"
        source.write_text("# source fixture\n")
        self.assertIn(source, source_paths(self.root))
        readiness = self.root / "readiness.json"
        atomic_json(readiness, {"passed": True, "model": "fake", "freeze_sha256": "a"*64})
        with self.assertRaisesRegex(ValueError, "different transport"):
            verify_readiness(readiness, "fake", "a"*64, available_trials(), transport="persistent")
        atomic_json(readiness, {"passed": True, "model": "fake", "freeze_sha256": "a"*64,
                               "transport": "codex-app-server-persistent-v1",
                               "transport_profile": transport_profile("persistent", 0.5)})
        with self.assertRaisesRegex(ValueError, "different transport settings"):
            verify_readiness(readiness, "fake", "a"*64, available_trials(), transport="persistent",
                             profile=transport_profile("persistent", 1.0))

    def test_persistent_readiness_requires_rpc_audit_after_hash_validation(self):
        state = self.complete_state()
        state["transport"] = "codex-app-server-persistent-v1"
        raw = self.root/"raw-fixture.jsonl"
        raw.write_text("{}\n")
        for turn in state["turns"]:
            turn["raw_files"] = [{"path":str(raw), "sha256":sha(raw)}]
        path = self.root/"persistent-state.json"
        atomic_json(path, state)
        evidence = {"passed":True, "model":"fake", "freeze_sha256":"a"*64,
                    "transport":state["transport"], "states":[{
                        "trial_id":state["trial"]["trial_id"], "path":path.name, "sha256":sha(path)}]}
        ready = self.root/"readiness.json"
        atomic_json(ready, evidence)
        with patch("exp7_main_v2.worker.calibration_trials", return_value=[state["trial"]]):
            with patch("exp7_persistent.audit.audit_trial", return_value={"integrity_ok":False,"errors":["PID changed"]}) as audit:
                with self.assertRaisesRegex(ValueError, "RPC/scientific audit failed.*PID changed"):
                    verify_readiness(ready,"fake","a"*64,[],transport="persistent")
                self.assertEqual(audit.call_args.args[0],state["trial"])
                self.assertEqual(audit.call_args.args[2],path)

    def test_export_excludes_session_command_paths_and_is_deterministic(self):
        state = self.complete_state()
        state["session_id"] = "private-session-secret"
        state["scratch_id"] = "private-scratch-secret"
        state["turns"][0].update(command=["secret-command"],session_id="private-session-secret",
                                  raw_files=[{"path":"/private/credentials/events.jsonl","sha256":"d"*64}])
        clean = public_state(state)
        text = json.dumps(clean)
        for token in ("private-session-secret","private-scratch-secret","secret-command","/private/credentials"):
            self.assertNotIn(token,text)
        self.assertEqual(clean["turns"][0]["text"],state["turns"][0]["text"])
        a,b = self.root/"a.gz",self.root/"b.gz"
        self.assertEqual(export_job([state],a),export_job([state],b))
        self.assertEqual(json.loads(gzip.decompress(a.read_bytes())),clean)
        self.assertEqual(export_job([state],a),sha(a))
        state["turns"][0]["text"] = "github_pat_" + "a"*30
        with self.assertRaises(ValueError):
            public_state(state)

    def test_result_publication_is_append_only_and_confirmed(self):
        remote = self.root/"remote.git"
        subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
        pub = ResultPublisher(str(remote),"exp7/results/fake",self.root/"publisher.git")
        first,second = self.root/"first.gz",self.root/"second.gz"
        first.write_bytes(b"first immutable result")
        second.write_bytes(b"second immutable result")
        ref = pub.publish(first,"results/job-1.jsonl.gz")
        self.assertEqual(pub.publish(first,"results/job-1.jsonl.gz"),ref)
        later = pub.publish(second,"results/job-2.jsonl.gz")
        self.assertNotEqual(later.split(":")[0],ref.split(":")[0])
        with self.assertRaises(ValueError):
            pub.publish(second,"results/job-1.jsonl.gz")
        with self.assertRaises(ValueError):
            pub.publish(first,"../unsafe")

    def test_verify_freeze_rejects_changed_bytes(self):
        (self.root/"plan").mkdir()
        (self.root/"plan/summary.json").write_text("{}")
        source = self.root/"source.py"
        source.write_text("version = 1\n")
        frozen = {"bundle":"plan", "manifest_sha256":sha(self.root/"plan/summary.json"),
                  "files":{"source.py":sha(source)},"cli_version":"test",
                  "dependencies":{"jsonschema":importlib.metadata.version("jsonschema")}}
        path = self.root/"freeze.json"
        atomic_json(path,frozen)
        verify_freeze(path,self.root,check_cli=False)
        source.write_text("version = 2\n")
        with self.assertRaises(ValueError):
            verify_freeze(path,self.root,check_cli=False)

    def test_bind_model_auto_claim_race_chooses_next_available_and_persists(self):
        class Race:
            def __init__(self):
                self.board={"run_id":"run","global_stop":False,"models":{
                    "m1":{"owner":None},"m2":{"owner":None}}}
            def status(self):
                return deepcopy(self.board)
            def claim_model(self,model,owner,concurrency):
                if model == "m1":
                    self.board["models"][model]={"owner":"another-vm","model_token":"other","concurrency":1}
                    raise OwnershipError("Lost race")
                self.board["models"][model]={"owner":owner,"model_token":"mine","concurrency":concurrency}
                return "mine"
        c=Race()
        bound=bind_model(c,self.root,"auto",["m1","m2"],1,owner="vm")
        self.assertEqual(bound["model"],"m2")
        self.assertEqual(bind_model(c,self.root,"auto",["m1","m2"],1),bound)
        with self.assertRaises(ValueError):
            bind_model(c,self.root,"m1",["m1","m2"],1)

    def test_saved_concurrency_must_match_flag_and_reservation(self):
        c = FakeCoordinator()
        c.board["models"]["fake"]["concurrency"] = 5
        saved = {"model": "fake", "owner": "vm", "model_token": "token", "concurrency": 3}
        atomic_json(self.root / "identity.private.json", saved)
        with self.assertRaisesRegex(ValueError, "Saved worker concurrency"):
            bind_model(c, self.root, "fake", ["fake"], 5)
        self.assertEqual(json.loads((self.root / "identity.private.json").read_text()), saved)

    def test_trial_scope_closes_after_followups_and_after_failure(self):
        class ScopedFake(FakeTransport):
            def __init__(self, protocol, fail_at=None):
                super().__init__(protocol, fail_at=fail_at)
                self.closed = []
            def close_trial(self, trial_id):
                self.closed.append(trial_id)
        for fail_at in (None, 2):
            trial = example(trial_id="scope-" + str(fail_at))
            protocol = MainProtocol()
            transport = ScopedFake(protocol, fail_at)
            state = run_trial(trial, protocol, transport, self.root/(trial["trial_id"]+".json"),
                              self.root/"native", CallBudget(self.root/(trial["trial_id"]+"-budget.json"),"test",34),"a"*64)
            self.assertEqual(len(state["turns"]), 34 if fail_at is None else 2)
            self.assertEqual(transport.closed, [trial["trial_id"]])

    def test_final_process_logs_are_bound_after_close_for_completed_and_pending_trials(self):
        class FinalizingFake(FakeTransport):
            def __init__(self, protocol, interrupted):
                super().__init__(protocol)
                self.interrupted = interrupted
            def request(self, trial, prompt, schema, system, session_id, directory, turn):
                self.directory = Path(directory)
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory/"process.stderr.log").write_text("running\n")
                if self.interrupted and turn == 2:
                    raise RuntimeError("Connection lost after send")
                return super().request(trial,prompt,schema,system,session_id,directory,turn)
            def close_trial(self, trial_id):
                paths = [self.directory/"process.stderr.log", self.directory/"close-diagnostics.json"]
                paths[0].write_text("running\nclosed\n")
                paths[1].write_text('{"closed":true}\n')
                return [{"path":str(p.resolve()),"sha256":sha(p)} for p in paths]
        for interrupted in (False, True):
            trial = example(trial_id="closed-"+str(interrupted))
            protocol = MainProtocol()
            path = self.root/(trial["trial_id"]+".json")
            transport = FinalizingFake(protocol, interrupted)
            state = run_trial(trial,protocol,transport,path,self.root/"native",
                              CallBudget(self.root/(trial["trial_id"]+"-budget.json"),"test",34),"a"*64)
            refs = state["pending_raw_files"] if interrupted else state["turns"][-1]["raw_files"]
            final = {Path(entry["path"]).name:entry for entry in refs}
            for name in ("process.stderr.log", "close-diagnostics.json"):
                self.assertEqual(final[name]["sha256"],sha(final[name]["path"]))
            self.assertEqual(json.loads(path.read_text()),state)
            journal = [json.loads(line) for line in path.with_suffix(".journal.jsonl").read_text().splitlines()]
            self.assertEqual(journal[-1]["type"],"transport_closed")

    def job_setup(self):
        trials=[example(trial_id="t1"),example("ko_natural","KD",trial_id="t2")]
        remote=self.root/"remote.git"
        subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
        c=GitCoordinator(str(remote),"coord",self.root/"coord.git")
        board=new_board("run","a"*64,"b"*40,[{"job_id":"job-1","model":"fake","trial_ids":["t1","t2"]}],global_stop=False)
        c.bootstrap(board)
        bound=bind_model(c,self.root,"fake",["fake"],1,owner="vm")
        job=c.claim_job("fake","vm",bound["model_token"])
        atomic_json(self.root/"jobs/job-1/claim.private.json",job_identity(job,bound))
        return trials,c,bound,job

    def test_execute_job_uses_disjoint_budget_and_preserves_all_response_records(self):
        trials,c,bound,job=self.job_setup()
        class MultiFake:
            name="offline-main-fixture"
            def __init__(self,timeout):
                self.sessions={}
            def request(self,trial,*args):
                return self.sessions.setdefault(trial["trial_id"],FakeTransport(MainProtocol())).request(trial,*args)
        with patch("exp7_main_v2.runner.NativeTransport",MultiFake):
            result=execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300)
        self.assertEqual(result["calls"],68)
        self.assertEqual(result["counts"],{"complete":2,"failed":0,"interrupted":0,"unstarted":0})
        rows=[json.loads(line) for line in gzip.decompress(Path(result["path"]).read_bytes()).splitlines()]
        self.assertEqual([r["trial"]["trial_id"] for r in rows],["t1","t2"])
        self.assertEqual([len(r["turns"]) for r in rows],[34,34])

    def test_persistent_job_uses_trial_scopes_and_closes_shared_transport(self):
        trials,c,bound,job=self.job_setup()
        class PersistentFake:
            name="codex-app-server-persistent-v1"
            def __init__(self):
                self.sessions = {}
                self.closed_trials = []
                self.closed = False
            def request(self, trial, *args):
                return self.sessions.setdefault(trial["trial_id"], FakeTransport(MainProtocol())).request(trial, *args)
            def close_trial(self, trial_id):
                self.closed_trials.append(trial_id)
            def close(self):
                self.closed = True
        native = PersistentFake()
        with patch("exp7_main_v2.worker.make_transport", return_value=native) as factory:
            result=execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300,
                               transport_kind="persistent", request_interval=0.5)
        factory.assert_called_once_with("persistent", 300, request_interval=0.5, model_catalog=None)
        self.assertEqual(result["calls"], 68)
        self.assertEqual(native.closed_trials, ["t1", "t2"])
        self.assertTrue(native.closed)
        rows=[json.loads(line) for line in gzip.decompress(Path(result["path"]).read_bytes()).splitlines()]
        self.assertTrue(all(r["transport"] == native.name for r in rows))

    def test_persistent_rechecks_stop_at_send_boundary_after_pacing(self):
        c = FakeCoordinator()
        gate = PermissionGate(c, "fake", "vm", "token", ttl=0)
        class Delayed:
            name = "codex-app-server-persistent-v1"
            before_send = None
            sent = False
            def request(self):
                c.board["global_stop"] = True
                self.before_send()
                self.sent = True
        native = Delayed()
        with self.assertRaisesRegex(RuntimeError, "Permission stopped"):
            GatedTransport(native, gate).request()
        self.assertFalse(native.sent)
        self.assertTrue(gate.stopped.is_set())

    def test_transport_exception_keeps_pending_and_halts_new_intake(self):
        trials,c,bound,job=self.job_setup()
        class Uncertain:
            name = "codex-app-server-persistent-v1"
            closed = False
            closed_trials = []
            def request(self, *args):
                raise RuntimeError("Connection lost after request write")
            def close_trial(self, trial_id):
                self.closed_trials.append(trial_id)
            def close(self):
                self.closed = True
        native = Uncertain()
        with patch("exp7_main_v2.worker.make_transport", return_value=native):
            result = execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300,
                                 transport_kind="persistent")
        self.assertTrue(result["stopped"])
        self.assertFalse(c.status()["global_stop"])
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["counts"], {"complete":0,"failed":0,"interrupted":1,"unstarted":1})
        state = json.loads((self.root/"jobs/job-1/states/t1.json").read_text())
        self.assertIsNotNone(state["pending_turn"])
        self.assertTrue(native.closed)
        self.assertEqual(native.closed_trials, ["t1"])

    def test_auth_exception_publishes_stop_before_rethrow(self):
        c = FakeCoordinator()
        gate = PermissionGate(c, "fake", "vm", "token")
        class AuthFailure:
            name = "codex-app-server-persistent-v1"
            def request(self):
                raise RuntimeError("401 Unauthorized")
        with self.assertRaisesRegex(RuntimeError, "401"):
            GatedTransport(AuthFailure(), gate).request()
        self.assertTrue(c.board["global_stop"])
        self.assertTrue(gate.stopped.is_set())

    def test_exception_stderr_and_post_close_tail_are_classified(self):
        for source in ("exception", "close"):
            c = FakeCoordinator()
            gate = PermissionGate(c,"fake","vm","token",allow_catalog_recovery=True)
            class Failure:
                name="codex-app-server-persistent-v1"
                def request(self):
                    error = RuntimeError("App-server exited")
                    error.transport_diagnostics = "401 Unauthorized"
                    raise error
                def close_trial(self, trial_id):
                    self.after_close({"ok":True,"stderr":"401 Unauthorized","events":[]})
                    return []
            wrapped = GatedTransport(Failure(),gate)
            if source == "exception":
                with self.assertRaisesRegex(RuntimeError,"App-server exited"):
                    wrapped.request()
            else:
                self.assertEqual(wrapped.close_trial("trial"),[])
            self.assertTrue(c.board["global_stop"])
            self.assertTrue(gate.stopped.is_set())

    def test_cleanup_failure_halts_and_retains_original_exception_context(self):
        c = FakeCoordinator()
        gate = PermissionGate(c,"fake","vm","token")
        class BrokenClose:
            name="codex-app-server-persistent-v1"
            def close(self):
                raise RuntimeError("Cleanup failed")
        with self.assertRaisesRegex(RuntimeError,"Cleanup failed") as caught:
            with GatedTransport(BrokenClose(),gate):
                raise ValueError("Original failure")
        self.assertIsInstance(caught.exception.__cause__,ValueError)
        self.assertTrue(gate.stopped.is_set())

    def test_rate_limit_stops_unstarted_assignment_and_preserves_partial(self):
        trials,c,bound,job=self.job_setup()
        class CapacityFailure:
            name="offline-main-fixture"
            def __init__(self,timeout):
                self.inner=FakeTransport(MainProtocol(),fail_at=2)
            def request(self,*args):
                result=self.inner.request(*args)
                if not result["ok"]:
                    result["stderr"]="HTTP 429 Too many requests"
                return result
        with patch("exp7_main_v2.runner.NativeTransport",CapacityFailure):
            result=execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300)
        self.assertEqual(result["calls"],2)
        self.assertEqual(result["counts"],{"complete":0,"failed":1,"interrupted":0,"unstarted":1})
        self.assertTrue(result["stopped"])
        self.assertTrue(c.status()["global_stop"])

    def test_storage_monitor_caches_checks_and_halts_on_low_capacity(self):
        c=FakeCoordinator()
        monitor=StorageMonitor([self.root],c,ttl=60)
        with patch("exp7_main_v2.storage.disk_guard",return_value={"free_bytes":10**10}) as check:
            with patch("exp7_main_v2.worker.time.monotonic",side_effect=[0,59,61,61]):
                monitor.check()
                monitor.check()
                monitor.check()
            self.assertEqual(check.call_count,2)
        with patch("exp7_main_v2.storage.disk_guard",side_effect=RuntimeError("insufficient inodes")):
            with self.assertRaises(RuntimeError):
                monitor.check(force=True)
        self.assertTrue(monitor.stopped.is_set())
        self.assertTrue(c.board["global_stop"])

    def test_permission_gate_invokes_storage_guard_before_provider_permission(self):
        c=FakeCoordinator()
        class BadStorage:
            def check(self):
                raise RuntimeError("insufficient space")
        c.worker_storage_monitor=BadStorage()
        gate=PermissionGate(c,"fake","vm","token")
        with self.assertRaisesRegex(RuntimeError,"space"):
            gate.check()
        self.assertEqual(c.reads,0)
        self.assertTrue(gate.stopped.is_set())
        c=FakeCoordinator()
        gate=PermissionGate(c,"fake","vm","token",ttl=10)
        gate.check()
        c.worker_storage_monitor=BadStorage()
        # Even a still-valid remote permission cache cannot bypass disk checks.
        with self.assertRaisesRegex(RuntimeError,"space"):
            gate.check()
        self.assertTrue(gate.stopped.is_set())

    def test_heartbeats_are_throttled_to_at_most_once_per_minute(self):
        class Heartbeats:
            def __init__(self):self.calls=[]
            def heartbeat(self,*args):self.calls.append(args)
        c=Heartbeats();bound={"model":"fake","owner":"vm","model_token":"token"}
        with patch("exp7_main_v2.worker.time.monotonic",side_effect=[0,30,59,60,61,120]):
            self.assertFalse(heartbeat_due(c,bound))
            self.assertFalse(heartbeat_due(c,bound))
            self.assertFalse(heartbeat_due(c,bound))
            self.assertTrue(heartbeat_due(c,bound))
            self.assertFalse(heartbeat_due(c,bound))
            self.assertTrue(heartbeat_due(c,bound))
        self.assertEqual(len(c.calls),2)

    def test_archive_requires_confirmed_remote_publication_and_completion(self):
        order=[]
        job={"job_id":"j","claim_token":"claim","trial_ids":["t1"]}
        bound={"model":"fake","owner":"vm","model_token":"token"}
        result={"path":"file.gz","sha256":"a"*64,"counts":{"complete":1,"failed":0,"interrupted":0,"unstarted":0},"calls":34}
        class Publisher:
            def publish(self,*args):order.append("publish");return "commit:path"
        class Coordinator:
            def complete_job(self,*args,**kwargs):
                self.kwargs=kwargs;order.append("confirmed_complete")
                return {**job,"status":"complete","result_ref":kwargs["result_ref"]}
        c=Coordinator()
        def archive(*args,**kwargs):
            self.assertEqual(order,["publish","confirmed_complete"])
            self.assertEqual(kwargs["completion"]["result_ref"],"commit:path")
            order.append("archive")
            atomic_json(self.root/"jobs/j/archive-receipt.private.json",{"archiver_receipt":True})
            return {"archive":"private.tar.gz","manifest":"private.manifest.json"}
        with patch("exp7_main_v2.storage.archive_completed_job",side_effect=archive):
            finished=finalize_job(job,bound,c,Publisher(),result,self.root,"run")
        self.assertEqual(order,["publish","confirmed_complete","archive"])
        self.assertIsNotNone(finished["archive"])
        self.assertTrue((self.root/"jobs/j/archive-receipt.private.json").exists())
        class FailedPublisher:
            def publish(self,*args):raise RuntimeError("Push not confirmed")
        with patch("exp7_main_v2.storage.archive_completed_job") as archive_mock:
            with self.assertRaises(RuntimeError):
                finalize_job(job,bound,c,FailedPublisher(),result,self.root,"run")
            archive_mock.assert_not_called()

    def test_archived_job_is_never_reexecuted_after_remote_reopening(self):
        trials,c,bound,job=self.job_setup()
        marker=self.root/"jobs/job-1/archive-receipt.private.json"
        atomic_json(marker,{"archived":True})
        with patch("exp7_main_v2.runner.NativeTransport") as native:
            with self.assertRaisesRegex(RuntimeError,"Archived job"):
                execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300)
            native.assert_not_called()

    def test_full_job_publication_archive_prune_and_exact_restore(self):
        from .storage import restore_archive, verify_archive
        trials,c,bound,job=self.job_setup()
        class RawFake:
            name="offline-main-fixture"
            def __init__(self,timeout):
                self.sessions={}
            def request(self,trial,prompt,schema,system,session_id,directory,turn):
                inner=self.sessions.setdefault(trial["trial_id"],FakeTransport(MainProtocol()))
                result=inner.request(trial,prompt,schema,system,session_id,directory,turn)
                directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
                system_path=directory/"subject-system.txt"
                if not system_path.exists():system_path.write_text(system)
                turn_dir=directory/f"turn-{turn:02d}";turn_dir.mkdir()
                content={"prompt.txt":prompt,"events.jsonl":json.dumps({"offline_fixture":True,"text":result["text"]})+"\n","stderr.txt":""}
                if schema is not None:content["schema.json"]=json.dumps(schema)
                paths=[system_path]
                for name,text in content.items():
                    p=turn_dir/name;p.write_text(text);paths.append(p)
                result["raw_files"]=[{"path":str(p.resolve()),"sha256":sha(p)} for p in paths]
                return result
        with patch("exp7_main_v2.runner.NativeTransport",RawFake):
            result=execute_job(job,bound,c,{t["trial_id"]:t for t in trials},self.root,"c"*64,300)
        directory=self.root/"jobs/job-1"
        original={str(p.relative_to(directory)):p.read_bytes() for folder in (directory/"states",directory/"native")
                  for p in folder.rglob("*") if p.is_file()}
        self.assertGreater(len(original),200)
        publisher=ResultPublisher(str(self.root/"remote.git"),"results/fake",self.root/"publisher.git")
        finished=finalize_job(job,bound,c,publisher,result,self.root,"run")
        self.assertEqual(c.status()["jobs"]["job-1"]["status"],"complete")
        self.assertFalse((directory/"states").exists())
        self.assertFalse((directory/"native").exists())
        self.assertTrue((directory/"archive-receipt.private.json").exists())
        archive=finished["archive"]
        verify_archive(archive["archive"],archive["manifest"])
        restored=self.root/"restored"
        restore_archive(archive["archive"],archive["manifest"],restored)
        self.assertEqual({str(p.relative_to(restored)):p.read_bytes() for p in restored.rglob("*") if p.is_file()},original)
        again=archive_backlog(c,bound,self.root)
        self.assertEqual(len(again),1)
        self.assertEqual(again[0]["pruned_files"],0)
        self.assertTrue((directory/"public.jsonl.gz").exists())


if __name__ == "__main__":
    unittest.main()
