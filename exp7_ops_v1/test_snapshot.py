"""Offline fixtures for STOP snapshots; all original bytes remain untouched."""
import fcntl
import hashlib
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from exp7_main_v2 import test_storage as storage_fixtures
from . import snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        fixture = storage_fixtures.StorageTests('test_verified_archive_can_be_kept_without_pruning')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.work, self.job = fixture.root, fixture.job
        self.output = self.work/'ops-v1'/'c10-01'/'stop-snapshot'
        self.ids = fixture.ids+['trial-003']
        claim = json.loads((self.job/'claim.private.json').read_text())
        claim['trial_ids'] = self.ids
        fixture.write_json(self.job/'claim.private.json',claim)
        for trial_id in fixture.ids:
            path=self.job/'states'/(trial_id+'.json')
            state=json.loads(path.read_text())
            state['trial']['model']='model-test'
            if trial_id == 'trial-002':
                state['status']='interrupted'
                state['pending_turn']={'turn':2,'prompt':'Saved pending request; never replay.'}
                raw=self.job/'native'/state['scratch_id']/'turn-02'/'prompt.txt'
                raw.parent.mkdir()
                raw.write_bytes(b'Uncertain request evidence')
                # Raw evidence can exist before the response checkpoint.
                state['pending_raw_files']=[{'path':str(raw),'sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}]
            fixture.write_json(path,state)
        (self.job/'budget.json.lock').write_bytes(b'')
        (self.work/'worker.lock').write_bytes(b'')
        (self.work/'launch-v1').mkdir()
        (self.work/'launch-v1'/'launcher.lock').write_bytes(b'')
        fixture.write_json(self.work/'identity.private.json',{'model':'model-test','owner':'vm-test','model_token':'model-token','run_id':'run-test'})
        remote={**claim,'status':'blocked','counts':{'complete':1,'failed':0,'interrupted':1,'unstarted':1},
                'result_ref':'commit:result.jsonl.gz','result_sha256':hashlib.sha256((self.job/'public.jsonl.gz').read_bytes()).hexdigest()}
        self.board={'run_id':'run-test','manifest_sha256':'a'*64,'freeze_sha256':'b'*64,'source_commit':'c'*40,
                    'global_stop':True,'models':{'model-test':{'owner':'vm-test','model_token':'model-token'}},
                    'jobs':{'job-001':remote}}
        self.before=self.source_bytes()
        mocked=patch.object(snapshot,'process_alive',return_value=False)
        mocked.start();self.addCleanup(mocked.stop)

    def source_bytes(self):
        return {p.relative_to(self.job).as_posix():p.read_bytes() for p in self.job.rglob('*') if p.is_file() and not p.is_symlink()}

    def make(self):
        return snapshot.snapshot_stopped_job(self.work,'job-001',self.output,stopped_pids=[99901,99902],confirmed_board=self.board)

    def test_preserves_pending_and_original_bytes_and_is_idempotent(self):
        result=self.make()
        self.assertTrue(result['non_pruning'])
        self.assertEqual(result['pending_checkpoint_trials'],['trial-002'])
        self.assertEqual(result['state_counts']['unstarted'],1)
        self.assertEqual(result['state_counts']['interrupted'],1)
        index=snapshot.verify_snapshot(result['archive'],result['manifest'])
        self.assertTrue(all(not Path(p).is_absolute() and not p.endswith('.lock') for p in index['files']))
        self.assertEqual(self.source_bytes(),self.before)
        with tarfile.open(result['archive'],'r:gz') as archive:
            extracted={m.name:archive.extractfile(m).read() for m in archive}
        self.assertEqual(extracted,{p:b for p,b in self.before.items() if not p.endswith('.lock')})
        state=json.loads(extracted['states/trial-002.json'])
        self.assertEqual(state['status'],'interrupted')
        self.assertEqual(state['pending_turn']['turn'],2)
        initial={k:Path(result[k]).read_bytes() for k in ('archive','manifest')}
        self.assertEqual(self.make(),result)
        self.assertEqual(initial,{k:Path(result[k]).read_bytes() for k in initial})
        self.assertEqual(self.source_bytes(),self.before)

    def test_alive_worker_or_busy_lock_blocks_without_source_change(self):
        with patch.object(snapshot,'process_alive',return_value=True):
            with self.assertRaises(snapshot.StorageError):self.make()
        with (self.work/'worker.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(snapshot.StorageError):self.make()
        with (self.job/'states'/'trial-002.json.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(self.source_bytes(),self.before)
        self.assertFalse(self.output.exists())

    def test_remote_stop_owner_and_local_counts_must_match(self):
        self.board['global_stop']=False
        with self.assertRaises(snapshot.StorageError):self.make()
        self.board['global_stop']=True
        self.board['jobs']['job-001']['owner']='another-vm'
        with self.assertRaises(snapshot.StorageError):self.make()
        self.board['jobs']['job-001']['owner']='vm-test'
        self.board['jobs']['job-001']['counts']['complete']=2
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(self.source_bytes(),self.before)

    def test_unknown_source_files_and_symlinks_are_never_included(self):
        unknown=self.job/'credentials.env'
        unknown.write_bytes(b'unknown local file')
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(unknown.read_bytes(),b'unknown local file')
        unknown.unlink()
        unknown.symlink_to(self.work/'identity.private.json')
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertTrue(unknown.is_symlink())
        unknown.unlink()
        self.assertEqual(self.source_bytes(),self.before)

    def test_corrupted_archive_blocks_idempotent_call_without_touching_sources(self):
        result=self.make()
        path=Path(result['archive'])
        path.write_bytes(path.read_bytes()[:-8])
        with self.assertRaises(snapshot.StorageError):snapshot.verify_snapshot(path,result['manifest'])
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(self.source_bytes(),self.before)

    def test_source_change_cannot_overwrite_old_snapshot(self):
        result=self.make()
        archive_before=Path(result['archive']).read_bytes()
        path=self.job/'states'/'trial-001.journal.jsonl'
        path.write_bytes(path.read_bytes()+b'new source evidence')
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(Path(result['archive']).read_bytes(),archive_before)
        self.assertTrue(path.read_bytes().endswith(b'new source evidence'))

    def test_different_orphan_snapshot_and_unsafe_member_are_rejected(self):
        self.output.mkdir(parents=True)
        orphan=self.output/'job-001.stopped.tar.gz'
        orphan.write_bytes(b'preserve unknown existing archive')
        with self.assertRaises(snapshot.StorageError):self.make()
        self.assertEqual(orphan.read_bytes(),b'preserve unknown existing archive')
        self.assertEqual(self.source_bytes(),self.before)
        for path in ('../secret','/tmp/secret','native/../identity.private.json','budget.json.lock'):
            with self.assertRaises(snapshot.StorageError):snapshot._relative(path)


if __name__=='__main__':
    unittest.main()
