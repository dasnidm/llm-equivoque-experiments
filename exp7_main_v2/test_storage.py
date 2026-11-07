"""Storage failure/recovery fixtures only; no historical data or model calls."""
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import storage


def sha(data):
    return hashlib.sha256(data).hexdigest()


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / 'jobs' / 'job-001'
        self.archives = self.root / 'archives'
        self.job.mkdir(parents=True)
        self.ids = ['trial-001', 'trial-002']
        claim = {'job_id':'job-001','owner':'vm-test','model':'model-test',
                 'claim_token':'claim-test','model_token':'model-token','trial_ids':self.ids}
        self.write_json(self.job/'claim.private.json', claim)
        self.public = gzip.compress(b'{"synthetic":true}\n', mtime=0)
        (self.job/'public.jsonl.gz').write_bytes(self.public)
        self.write_json(self.job/'budget.json', {'used':35,'limit':68})
        self.write_json(self.job/'progress.json', {'finished':2})
        self.completion = {**claim, 'status':'partial_failed',
                           'counts':{'complete':1,'failed':1,'interrupted':0,'unstarted':0},
                           'result_ref':'commit:results/job-001.jsonl.gz', 'result_sha256':sha(self.public)}
        for n, trial_id in enumerate(self.ids, 1):
            scratch = str(n)*32
            raw = self.job/'native'/scratch
            files = {'subject-system.txt': b'Fixture system.',
                     'turn-01/prompt.txt':b'Fixture prompt.',
                     'turn-01/events.jsonl':b'{"fixture":true}\n',
                     'turn-01/stderr.txt':b'',
                     'turn-01/schema.json':b'{"type":"object"}\n'}
            refs = []
            for relative, data in files.items():
                path = raw/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                refs.append({'path':str(path), 'sha256':sha(data)})
            state = {'trial':{'trial_id':trial_id},'status':'complete' if n==1 else 'failed',
                     'pending_turn':None,'scratch_id':scratch,
                     'turns':[{'turn':1,'raw_files':refs}]}
            self.write_json(self.job/'states'/(trial_id+'.json'), state)
            (self.job/'states'/(trial_id+'.json.lock')).write_bytes(b'')
            (self.job/'states'/(trial_id+'.journal.jsonl')).write_bytes(b'{"fixture_checkpoint":true}\n')
        self.original = self.loose_bytes()
        self.outside = {p.name:p.read_bytes() for p in self.job.iterdir() if p.is_file()}

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data,sort_keys=True)+'\n')

    def loose_bytes(self):
        return {p.relative_to(self.job).as_posix():p.read_bytes()
                for name in ('states','native') if (self.job/name).exists()
                for p in (self.job/name).rglob('*') if p.is_file() and not p.is_symlink()}

    def archive(self, **kwargs):
        return storage.archive_completed_job(self.job,self.archives,completion=self.completion,
                                             expected_trial_ids=self.ids,**kwargs)

    def assert_outside_preserved(self):
        for name, content in self.outside.items():
            self.assertEqual((self.job/name).read_bytes(), content)

    def test_archive_verify_prune_restore_and_idempotent_second_call(self):
        result = self.archive()
        self.assertTrue(result['verified'])
        self.assertEqual(result['file_count'], len(self.original))
        self.assertEqual(result['pruned_files'], len(self.original))
        self.assertEqual(result['remaining_loose_files'], 0)
        self.assertFalse((self.job/'states').exists())
        self.assertFalse((self.job/'native').exists())
        marker = json.loads((self.job/'archive-receipt.private.json').read_text())
        self.assertEqual(marker['claim_token'],self.completion['claim_token'])
        self.assertEqual(marker['manifest_sha256'],sha(Path(result['manifest']).read_bytes()))
        index = storage.verify_archive(result['archive'],result['manifest'])
        restored = self.root/'restored'
        storage.restore_archive(result['archive'],result['manifest'],restored)
        self.assertEqual({p.relative_to(restored).as_posix():p.read_bytes() for p in restored.rglob('*') if p.is_file()},self.original)
        second = self.archive()
        self.assertEqual(second['pruned_files'],0)
        self.assertEqual(second['archive'],result['archive'])
        self.assertEqual(index,storage.verify_archive(result['archive'],result['manifest']))
        self.assert_outside_preserved()

    def test_verified_archive_can_be_kept_without_pruning(self):
        result = self.archive(prune=False)
        self.assertEqual(result['pruned_files'],0)
        self.assertEqual(self.loose_bytes(),self.original)
        self.assertTrue((self.job/'archive-receipt.private.json').exists())
        self.assertEqual(self.archive()['pruned_files'],len(self.original))

    def test_archive_directory_cannot_hide_inside_loose_tree_via_dotdot(self):
        with self.assertRaises(storage.StorageError):
            storage.archive_completed_job(self.job, self.job/'native'/'not-created'/'..'/'archives',
                                          completion=self.completion,expected_trial_ids=self.ids)
        self.assertEqual(self.loose_bytes(),self.original)

    def test_corrupted_existing_archive_never_deletes_loose_files(self):
        result = self.archive(prune=False)
        path = Path(result['archive'])
        path.write_bytes(path.read_bytes()+b'corruption')
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertEqual(self.loose_bytes(),self.original)

    def test_truncation_detected_even_if_compressed_digest_is_updated(self):
        result = self.archive(prune=False)
        path, manifest = Path(result['archive']),Path(result['manifest'])
        data = path.read_bytes()
        path.write_bytes(data[:-8])  # Remove gzip CRC/length footer.
        index = json.loads(manifest.read_text())
        index.update(archive_sha256=sha(path.read_bytes()),archive_bytes=path.stat().st_size)
        self.write_json(manifest,index)
        with self.assertRaises(storage.StorageError):
            storage.verify_archive(path,manifest)
        self.assertEqual(self.loose_bytes(),self.original)

    def test_per_member_corruption_is_detected_after_recompression(self):
        result = self.archive(prune=False)
        path, manifest = Path(result['archive']),Path(result['manifest'])
        unpacked = gzip.decompress(path.read_bytes())
        self.assertIn(b'Fixture prompt.',unpacked)
        path.write_bytes(gzip.compress(unpacked.replace(b'Fixture prompt.',b'Changed prompt.',1),mtime=0))
        index = json.loads(manifest.read_text())
        index.update(archive_sha256=sha(path.read_bytes()),archive_bytes=path.stat().st_size)
        self.write_json(manifest,index)
        with self.assertRaisesRegex(storage.StorageError,'digest'):
            storage.verify_archive(path,manifest)
        self.assertEqual(self.loose_bytes(),self.original)

    def test_unknown_files_and_empty_directories_block_archiving(self):
        unknown = self.job/'native'/'untracked-note.txt'
        unknown.write_bytes(b'unknown evidence')
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertEqual(unknown.read_bytes(),b'unknown evidence')
        unknown.unlink()
        unknown_dir = self.job/'native'/'unknown-empty-directory'
        unknown_dir.mkdir()
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertTrue(unknown_dir.exists())
        self.assertEqual(self.loose_bytes(),self.original)

    def test_symlinks_hardlinks_and_live_locks_are_preserved(self):
        link = self.job/'states'/'unknown-link'
        link.symlink_to(self.job/'public.jsonl.gz')
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertTrue(link.is_symlink())
        link.unlink()
        os.link(self.job/'public.jsonl.gz',link)
        with self.assertRaises(storage.StorageError):
            self.archive()
        link.unlink()
        lock_path = self.job/'states'/(self.ids[0]+'.json.lock')
        with lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(storage.StorageError):
                self.archive()
        self.assertEqual(self.loose_bytes(),self.original)
        self.assert_outside_preserved()

    def test_active_interrupted_and_pending_states_never_archive(self):
        path = self.job/'states'/(self.ids[0]+'.json')
        original = json.loads(path.read_text())
        for status,pending in [('active',None),('interrupted',None),('failed',{'turn':2}),('complete',{})]:
            self.write_json(path,{**original,'status':status,'pending_turn':pending})
            with self.assertRaises(storage.StorageError):
                self.archive()
            self.assertTrue(path.exists())
        self.write_json(path,original)
        self.assertEqual(self.loose_bytes(),self.original)

    def test_receipt_identity_and_public_result_are_required(self):
        for change in [{'owner':'another-vm'},{'status':'running'},
                       {'counts':{'complete':1,'failed':0,'interrupted':1,'unstarted':0}},
                       {'result_sha256':'0'*64},{'trial_ids':[self.ids[0]]}]:
            with self.assertRaises(storage.StorageError):
                storage.archive_completed_job(self.job,self.archives,completion={**self.completion,**change},expected_trial_ids=self.ids)
        self.assertEqual(self.loose_bytes(),self.original)

    def test_crash_after_archive_commit_before_manifest_recovers_safely(self):
        atomic = storage._atomic_json
        def crash(path,value):
            if str(path).endswith('.manifest.json'):
                raise RuntimeError('simulated crash before index commit')
            return atomic(path,value)
        with patch.object(storage,'_atomic_json',side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.archive()
        self.assertTrue((self.archives/'job-001.tar.gz').exists())
        self.assertFalse((self.archives/'job-001.manifest.json').exists())
        self.assertEqual(self.loose_bytes(),self.original)
        self.assertEqual(self.archive()['remaining_loose_files'],0)

    def test_differing_orphan_archive_is_never_overwritten(self):
        self.archives.mkdir()
        orphan = self.archives/'job-001.tar.gz'
        orphan.write_bytes(b'unknown existing archive, preserve exactly')
        before = orphan.read_bytes()
        with self.assertRaisesRegex(storage.StorageError,'orphan'):
            self.archive()
        self.assertEqual(orphan.read_bytes(),before)
        self.assertFalse((self.archives/'job-001.manifest.json').exists())
        self.assertFalse((self.job/'archive-receipt.private.json').exists())
        self.assertEqual(self.loose_bytes(),self.original)

    def test_crash_before_tombstone_cannot_prune_and_recovers(self):
        atomic = storage._atomic_json
        def crash(path,value):
            if str(path).endswith('archive-receipt.private.json'):
                raise RuntimeError('simulated crash before tombstone commit')
            return atomic(path,value)
        with patch.object(storage,'_atomic_json',side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.archive()
        self.assertTrue((self.archives/'job-001.manifest.json').exists())
        self.assertEqual(self.loose_bytes(),self.original)
        self.assertEqual(self.archive()['remaining_loose_files'],0)

    def test_crash_during_prune_resumes_from_verified_archive(self):
        unlink = Path.unlink
        removed = []
        def crash(path,*args,**kwargs):
            if path.is_relative_to(self.job/'states') or path.is_relative_to(self.job/'native'):
                self.assertTrue((self.job/'archive-receipt.private.json').exists())
                if len(removed) == 3:
                    raise RuntimeError('simulated crash during deletion')
                removed.append(str(path))
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',crash):
            with self.assertRaises(RuntimeError):
                self.archive()
        self.assertEqual(len(self.loose_bytes()),len(self.original)-3)
        result = self.archive()
        self.assertEqual(result['pruned_files'],len(self.original)-3)
        restored = self.root/'restored-after-crash'
        storage.restore_archive(result['archive'],result['manifest'],restored)
        self.assertEqual({p.relative_to(restored).as_posix():p.read_bytes() for p in restored.rglob('*') if p.is_file()},self.original)

    def test_changed_or_new_loose_files_after_archive_block_all_pruning(self):
        self.archive(prune=False)
        path = self.job/'states'/(self.ids[0]+'.journal.jsonl')
        path.write_bytes(path.read_bytes()+b'new event')
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertEqual(len(self.loose_bytes()),len(self.original))
        path.write_bytes(self.original[path.relative_to(self.job).as_posix()])
        unknown = self.job/'native'/'new-file'
        unknown.write_bytes(b'preserve me')
        with self.assertRaises(storage.StorageError):
            self.archive()
        self.assertEqual(unknown.read_bytes(),b'preserve me')

    def test_restore_refuses_nonempty_destination_and_unsafe_paths(self):
        result = self.archive(prune=False)
        destination = self.root/'restore-target'
        destination.mkdir()
        (destination/'existing').write_bytes(b'preserve')
        with self.assertRaises(storage.StorageError):
            storage.restore_archive(result['archive'],result['manifest'],destination)
        self.assertEqual((destination/'existing').read_bytes(),b'preserve')
        manifest = Path(result['manifest'])
        index = json.loads(manifest.read_text())
        first = next(iter(index['files']))
        index['files']['../escape'] = index['files'].pop(first)
        self.write_json(manifest,index)
        with self.assertRaises(storage.StorageError):
            storage.restore_archive(result['archive'],manifest,self.root/'unsafe-restore')
        self.assertFalse((self.root/'escape').exists())

    def test_restore_never_follows_tar_symlink(self):
        result = self.archive(prune=False)
        path,manifest = Path(result['archive']),Path(result['manifest'])
        with tarfile.open(path,'w:gz') as archive:
            member = tarfile.TarInfo('states/link')
            member.type = tarfile.SYMTYPE
            member.linkname = '../outside'
            archive.addfile(member)
        index = json.loads(manifest.read_text())
        index.update(archive_sha256=sha(path.read_bytes()),archive_bytes=path.stat().st_size,
                     files={'states/link':{'size':0,'sha256':sha(b''),'mode':0o644}})
        self.write_json(manifest,index)
        with self.assertRaises(storage.StorageError):
            storage.restore_archive(path,manifest,self.root/'link-restore')
        self.assertFalse((self.root/'link-restore').exists())

    def test_disk_guard_has_exact_floor_is_readonly_and_rejects_relaxation(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        values = SimpleNamespace(f_bavail=5*1024**3,f_frsize=1,f_favail=100000,f_blocks=10*1024**3,f_files=200000)
        with patch.object(storage.os,'statvfs',return_value=values):
            self.assertTrue(storage.disk_guard(self.job/'not-created')['ok'])
            values.f_favail = 99999
            with self.assertRaises(storage.InsufficientStorage) as failure:
                storage.disk_guard(self.job)
            self.assertEqual(failure.exception.metrics['free_inodes'],99999)
            values.f_favail = 100000
            values.f_bavail -= 1
            with self.assertRaises(storage.InsufficientStorage):
                storage.disk_guard(self.job)
        with self.assertRaises(storage.StorageError):
            storage.disk_guard(self.job,{**storage.DEFAULT_STORAGE_POLICY,'min_free_inodes':0})
        self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))


if __name__ == '__main__':
    unittest.main()
