"""Continuation snapshot/publication using synthetic inference and local Git."""
from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch

from exp7_main.test_runner import FakeTransport
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.worker import ResultPublisher
from . import test_recovery as recovery_fixtures
from . import snapshot
from . import revision_snapshot as revision


class NativeFixtureTransport(FakeTransport):
    """Synthetic raw artifacts, never a CLI/provider request."""
    def request(self,trial,prompt,schema,system,session_id,directory,turn):
        result=super().request(trial,prompt,schema,system,session_id,directory,turn)
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        system_path=directory/'subject-system.txt'
        if not system_path.exists():system_path.write_text(system)
        attempt=directory/f'turn-{turn:02d}';attempt.mkdir()
        (attempt/'prompt.txt').write_text(prompt)
        (attempt/'events.jsonl').write_text(json.dumps({'fixture_response':result['text']})+'\n')
        (attempt/'stderr.txt').write_text('')
        paths=[system_path,attempt/'prompt.txt',attempt/'events.jsonl',attempt/'stderr.txt']
        if schema is not None:
            (attempt/'schema.json').write_text(json.dumps(schema));paths.append(attempt/'schema.json')
        result['raw_files']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
        return result


class RevisionSnapshotTests(unittest.TestCase):
    def setUp(self):
        fixture=recovery_fixtures.RecoveryTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.work=fixture.work;self.job=fixture.dir
        fixture.op=self.work/'ops-v1'/'c10-01'/'continuation-01';fixture.op.mkdir(parents=True)
        self.op=fixture.op
        (self.op/'recovery.lock').write_bytes(b'')
        (self.work/'worker.lock').write_bytes(b'')
        (self.job/'progress.json').write_text('{"finished":2,"assigned":6}')
        for module in (snapshot,revision):
            mocked=patch.object(module,'process_alive',return_value=False);mocked.start();self.addCleanup(mocked.stop)
        fixture.c.set_stop(True,'Fixture STOP')
        self.old=snapshot.snapshot_stopped_job(self.work,'job',self.op.parent/'stop-snapshot',
            stopped_pids=[99901,99902],confirmed_board=fixture.c.status())
        self.old_bytes={key:Path(self.old[key]).read_bytes() for key in ('archive','manifest')}
        fixture.c.set_stop(False,'Fixture explicit resumption')
        self.intent=fixture.plan()
        fixture.transport=lambda:NativeFixtureTransport(MainProtocol())
        self.receipt=fixture.execute()
        self.output=self.op/'revision-snapshot'

    def make(self):
        return revision.snapshot_finalized_revision(self.work,self.op,self.output,
            stopped_pids=[99901,99902],confirmed_board=self.fixture.c.status(),
            prior_snapshot_archive=self.old['archive'],prior_snapshot_manifest=self.old['manifest'])

    def test_finalized_snapshot_contains_four_new_raw_sessions_and_original_pending(self):
        source_before={p:p.read_bytes() for p in self.job.rglob('*') if p.is_file()}
        result=self.make();index=revision.verify_revision_snapshot(result['archive'],result['manifest'])
        self.assertEqual(index['continued_ids'],['t2','t3','t4','t5'])
        self.assertEqual(index['state_counts']['complete'],5)
        self.assertEqual(index['state_counts']['interrupted'],1)
        self.assertEqual(index['pending_checkpoint_trials'],['t1'])
        self.assertIn('jobs/job/revisions/continuation-01/public.jsonl.gz',index['files'])
        self.assertIn('ops-v1/c10-01/continuation-01/reconciliation-final.private.json',index['files'])
        with tarfile.open(result['archive'],'r:gz') as archive:
            files={m.name:archive.extractfile(m).read() for m in archive}
        for tid in index['continued_ids']:
            state=json.loads(files['jobs/job/states/'+tid+'.json'])
            self.assertEqual(state['status'],'complete')
            raw_prefix='jobs/job/native/'+state['scratch_id']+'/'
            self.assertTrue(all(raw_prefix+f'turn-{t:02d}/events.jsonl' in files for t in range(1,35)))
        old_state=json.loads(files['jobs/job/states/t1.json'])
        self.assertEqual(old_state['status'],'interrupted');self.assertIsNotNone(old_state['pending_turn'])
        self.assertEqual(source_before,{p:p.read_bytes() for p in self.job.rglob('*') if p.is_file()})
        self.assertEqual(self.old_bytes,{k:Path(self.old[k]).read_bytes() for k in self.old_bytes})
        old_manifest=Path(result['manifest']).read_bytes()
        self.assertEqual(self.make(),result)
        self.assertEqual(Path(result['manifest']).read_bytes(),old_manifest)

    def test_unfinalized_receipt_or_changed_old_evidence_blocks(self):
        path=self.op/'status.private.json';original=path.read_bytes()
        value=json.loads(original);value['status']='planned';path.write_text(json.dumps(value))
        with self.assertRaises(Exception):self.make()
        path.write_bytes(original)
        old=self.job/'states'/'t1.json';data=old.read_bytes();old.write_bytes(data+b' ')
        with self.assertRaises(Exception):self.make()
        old.write_bytes(data)
        self.assertFalse(self.output.exists())

    def test_busy_worker_and_unknown_new_files_block_snapshot(self):
        with (self.work/'worker.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(revision.StorageError):self.make()
        unknown=self.job/'native'/'unknown';unknown.write_bytes(b'preserve')
        with self.assertRaises(revision.StorageError):self.make()
        self.assertEqual(unknown.read_bytes(),b'preserve')

    def private_fixture(self):
        remote=self.fixture.root/'private.git'
        subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
        repo={'id':123,'full_name':'fixture/private','private':True,'visibility':'private',
              'archived':False,'disabled':False,'permissions':{'push':True}}
        def factory(url,branch,cache):
            self.assertEqual(url,'https://github.com/fixture/private.git')
            return ResultPublisher(str(remote),branch,cache)
        return remote,repo,factory

    def test_private_publication_readback_idempotence_without_worker_lock(self):
        result=self.make();remote,repo,factory=self.private_fixture();folder=self.op/'private-snapshot-publication'
        with (self.work/'worker.lock').open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            receipt=revision.publish_revision_snapshot(result['archive'],result['manifest'],'fixture/private',folder,
                repository_check=lambda:deepcopy(repo),publisher_factory=factory)
        self.assertEqual(receipt['status'],'verified')
        self.assertTrue(receipt['local_archive_retained'])
        self.assertEqual(set(receipt['files']),{
            'snapshots/run/fake/job/continuation-01/archive.tar.gz',
            'snapshots/run/fake/job/continuation-01/manifest.json'})
        for target,expected in receipt['files'].items():
            content=subprocess.check_output(['git','--git-dir',str(remote),'show',receipt['remote_commit']+':'+target])
            self.assertEqual(hashlib.sha256(content).hexdigest(),expected['sha256'])
        again=revision.publish_revision_snapshot(result['archive'],result['manifest'],'fixture/private',folder,
            repository_check=lambda:deepcopy(repo),publisher_factory=factory)
        self.assertEqual(again,receipt)
        self.assertEqual(self.old_bytes,{k:Path(self.old[k]).read_bytes() for k in self.old_bytes})

    def test_public_repository_or_corrupt_archive_never_uploads(self):
        result=self.make();remote,repo,factory=self.private_fixture()
        with patch('exp7_main_v2.worker.ResultPublisher') as publisher:
            with self.assertRaises(Exception):
                revision.publish_revision_snapshot(result['archive'],result['manifest'],'fixture/private',self.op/'upload',
                    repository_check=lambda:{**repo,'private':False,'visibility':'public'})
            publisher.assert_not_called()
        Path(result['archive']).write_bytes(Path(result['archive']).read_bytes()[:-8])
        with patch('exp7_main_v2.worker.ResultPublisher') as publisher:
            with self.assertRaises(Exception):
                revision.publish_revision_snapshot(result['archive'],result['manifest'],'fixture/private',self.op/'upload',
                    repository_check=lambda:repo)
            publisher.assert_not_called()


if __name__=='__main__':unittest.main()
