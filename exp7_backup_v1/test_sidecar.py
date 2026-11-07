"""Offline private-backup tests; only synthetic archives and local bare Git."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from exp7_main_v2 import test_storage as storage_fixtures
from exp7_main_v2.worker import ResultPublisher
from exp7_pre.runner import atomic_json
from .sidecar import (BackupError, BackupTransient, backup_job, once, sha,
                      sidecar_lock, verify_private_repository, entrypoint)


class SidecarTests(unittest.TestCase):
    def setUp(self):
        fixture=storage_fixtures.StorageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.work=fixture.root
        self.identity={"run_id":"test-run-v2","model":"model-test","owner":"vm-test","model_token":"model-token"}
        atomic_json(self.work/"identity.private.json",self.identity)
        atomic_json(self.work/"calibration/attempt-01/readiness.json",{
            "passed":True,"model":"model-test","worker_owner":"vm-test","freeze_sha256":"a"*64})
        for path in (fixture.job/"states").glob("*.json"):
            state=json.loads(path.read_text())
            state["trial"].update(run_id=self.identity["run_id"],model=self.identity["model"])
            state["freeze_sha256"]="a"*64
            atomic_json(path,state)
        result=fixture.archive()
        self.archive=Path(result["archive"])
        self.manifest=Path(result["manifest"])
        self.marker=fixture.job/"archive-receipt.private.json"
        self.before={p:p.read_bytes() for p in (self.archive,self.manifest,self.marker)}
        self.state=self.work/"backup-v1"
        self.state.mkdir()
        self.remote=self.work/"private-fixture.git"
        subprocess.run(["git","init","--bare",str(self.remote)],check=True,capture_output=True)
        self.repo={"id":123,"full_name":"fixture/private","private":True,"visibility":"private",
                   "archived":False,"disabled":False,"permissions":{"push":True}}
        self.branch="raw/test-run-v2/model-test"
        self.publisher=ResultPublisher(str(self.remote),self.branch,self.state/"publication.git")

    def upload(self,publisher=None,checker=None,reverify=False):
        return backup_job(self.work,self.identity,"job-001",self.repo,publisher or self.publisher,
                          self.state,checker or (lambda:deepcopy(self.repo)),reverify)

    def assert_sources_preserved(self):
        for path,content in self.before.items():
            self.assertEqual(path.read_bytes(),content)

    def test_private_write_access_checks_reject_public_or_read_only(self):
        for update in ({},{"private":False,"visibility":"public"},{"permissions":{"push":False}}):
            data={**self.repo,**update}
            with patch("exp7_backup_v1.sidecar.subprocess.run",return_value=SimpleNamespace(stdout=json.dumps(data))):
                if update:
                    with self.assertRaises(BackupError):verify_private_repository("fixture/private")
                else:
                    self.assertEqual(verify_private_repository("fixture/private")["id"],123)
        with patch("exp7_backup_v1.sidecar.subprocess.run",side_effect=subprocess.TimeoutExpired("gh",30)):
            with self.assertRaises(BackupTransient):verify_private_repository("fixture/private")

    def test_real_git_backup_readback_receipt_and_cached_idempotence(self):
        result=self.upload()
        self.assertEqual(result["status"],"verified")
        receipt=json.loads((self.state/"receipts/job-001.json").read_text())
        self.assertEqual(receipt["repository_id"],123)
        self.assertEqual(receipt["freeze_sha256"],"a"*64)
        self.assertEqual(len(receipt["files"]),3)
        for target,entry in receipt["files"].items():
            data=subprocess.check_output(["git","--git-dir",str(self.remote),"show",receipt["remote_commit"]+":"+target])
            import hashlib
            self.assertEqual(hashlib.sha256(data).hexdigest(),entry["sha256"])
        self.assert_sources_preserved()
        with patch("exp7_backup_v1.sidecar.verify_archive",side_effect=AssertionError("unnecessary full read")), \
             patch("exp7_backup_v1.sidecar._remote_readback",side_effect=AssertionError("unnecessary remote read")):
            self.assertEqual(self.upload()["status"],"already_verified")
        before=subprocess.check_output(["git","--git-dir",str(self.remote),"rev-list","--count",self.branch])
        self.assertEqual(self.upload(reverify=True)["status"],"verified")
        after=subprocess.check_output(["git","--git-dir",str(self.remote),"rev-list","--count",self.branch])
        self.assertEqual(before,after)
        self.assert_sources_preserved()

    def test_corrupted_archive_is_blocked_without_publication(self):
        self.archive.write_bytes(self.archive.read_bytes()+b"corruption")
        with patch.object(self.publisher,"publish") as publish:
            with self.assertRaises(Exception):self.upload()
            publish.assert_not_called()
        self.assertFalse((self.state/"receipts/job-001.json").exists())

    def test_foreign_claim_or_freeze_never_uploads(self):
        claim_path=self.work/"jobs/job-001/claim.private.json"
        claim=json.loads(claim_path.read_text())
        atomic_json(claim_path,{**claim,"owner":"another-vm"})
        with patch.object(self.publisher,"publish") as publish:
            with self.assertRaisesRegex(BackupError,"belong"):self.upload()
            publish.assert_not_called()
        atomic_json(claim_path,claim)
        ready=self.work/"calibration/attempt-01/readiness.json"
        data=json.loads(ready.read_text());data["freeze_sha256"]="b"*64;atomic_json(ready,data)
        with patch.object(self.publisher,"publish") as publish:
            with self.assertRaisesRegex(BackupError,"freeze"):self.upload()
            publish.assert_not_called()

    def test_partial_network_failure_is_idempotently_recovered(self):
        original=self.publisher.publish
        calls=[]
        def fail_second(*args):
            calls.append(args)
            if len(calls)==2:raise RuntimeError("network unavailable")
            return original(*args)
        with patch.object(self.publisher,"publish",side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.upload()
        self.assertFalse((self.state/"receipts/job-001.json").exists())
        self.assert_sources_preserved()
        self.assertEqual(self.upload()["status"],"verified")
        self.assert_sources_preserved()

    def test_remote_checksum_failure_never_writes_success_receipt(self):
        with patch("exp7_backup_v1.sidecar._remote_readback",side_effect=BackupTransient("remote_checksum","Mismatch")):
            with self.assertRaises(BackupTransient):self.upload()
        self.assertFalse((self.state/"receipts/job-001.json").exists())
        self.assert_sources_preserved()
        self.assertEqual(self.upload()["status"],"verified")

    def test_final_repository_identity_change_blocks_success(self):
        calls=[]
        def checker():
            calls.append(1)
            return {**self.repo,"id":456 if len(calls)==4 else 123}
        with self.assertRaisesRegex(BackupError,"ID changed"):
            self.upload(checker=checker)
        self.assertFalse((self.state/"receipts/job-001.json").exists())
        self.assert_sources_preserved()

    def test_unexpected_state_or_native_auth_member_rejected(self):
        original_index=self.manifest.read_bytes();original_marker=self.marker.read_bytes()
        for path in ("states/auth.json","native/"+"1"*32+"/turn-01/auth.json"):
            index=json.loads(original_index)
            index["files"][path]={"sha256":"b"*64,"size":1,"mode":0o600}
            atomic_json(self.manifest,index)
            marker=json.loads(original_marker);marker["manifest_sha256"]=sha(self.manifest);atomic_json(self.marker,marker)
            with patch.object(self.publisher,"publish") as publish:
                with self.assertRaises(BackupError):self.upload()
                publish.assert_not_called()

    def test_large_archive_and_symlink_are_blocked(self):
        with patch("exp7_backup_v1.sidecar.MAX_GIT_BLOB",1),patch.object(self.publisher,"publish") as publish:
            with self.assertRaisesRegex(BackupError,"blob limit"):self.upload()
            publish.assert_not_called()
        original=self.archive.with_suffix(".original")
        self.archive.rename(original);self.archive.symlink_to(original)
        with self.assertRaisesRegex(BackupError,"symlink"):self.upload()

    def test_once_status_waiting_identity_destination_and_completed(self):
        empty=self.work/"empty"
        with patch("exp7_backup_v1.sidecar.verify_private_repository",side_effect=AssertionError("No network before identity")):
            self.assertEqual(once(empty,"fixture/private")["status"],"waiting_identity")
        result=once(self.work,"fixture/private",repository_check=lambda:(_ for _ in ()).throw(BackupTransient("repository_unavailable","Missing")))
        self.assertEqual(result["status"],"waiting_destination")
        result=once(self.work,"fixture/private",repository_check=lambda:self.repo,
                    publisher_factory=lambda remote,branch,cache:self.publisher)
        self.assertEqual(result["status"],"up_to_date")
        self.assertEqual(result["verified"],1)

    def test_exclusive_sidecar_lock_and_clean_cli_error(self):
        with sidecar_lock(self.work):
            with self.assertRaises(BackupError):
                with sidecar_lock(self.work):pass
        with patch("exp7_backup_v1.sidecar.verify_private_repository",side_effect=BackupError("repository_not_private","Private required")), \
             patch("builtins.print") as output:
            self.assertEqual(entrypoint(["check","--repository","fixture/private"]),2)
            self.assertEqual(json.loads(output.call_args.args[0])["error"],"repository_not_private")


if __name__ == "__main__":
    unittest.main()
