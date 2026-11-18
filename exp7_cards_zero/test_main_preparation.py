"""Verify wave allocation and reversible private backups without model calls."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from .main_backup import archive_conversation, PrivateGitBackup, restore_archive, sha
from .main_schedule import audit, build, load, save
from .main_status import Dashboard, StatusDB, render


class MainPreparationTests(unittest.TestCase):
    def test_two_waves_are_disjoint_and_balanced(self):
        rows=build()
        self.assertEqual(audit(rows)['wave_sessions'],4200)
        self.assertTrue(all(t['stage']=='wave-1' for t in rows[:4200]))
        self.assertTrue(all(t['stage']=='wave-2' for t in rows[4200:]))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'assignments.gz'
            info=save(path)
            self.assertEqual(load(path,info['sha256']),rows)
            with self.assertRaises(ValueError): load(path,'0'*64)

    def test_private_backup_pushes_verified_archives(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); work=root/'run'; (work/'states').mkdir(parents=True)
            scratch='a'*32; (work/'native'/scratch).mkdir(parents=True)
            (work/'native'/scratch/'raw.txt').write_text('raw evidence')
            (work/'states'/'sample.json').write_text(json.dumps({'status':'complete'}))
            (work/'states'/'sample.journal.jsonl').write_text('{}\n')
            item=archive_conversation(work,'sample',scratch)
            self.assertEqual(sha(item['archive']),item['sha256'])
            restored=root/'restored'
            self.assertGreater(restore_archive(item['archive'],restored,item['sha256'])['files'],0)
            self.assertEqual((restored/'native'/scratch/'raw.txt').read_text(),'raw evidence')
            with tarfile.open(item['archive'],'r:gz') as archive:
                names=set(archive.getnames())
                self.assertIn('states/sample.json',names)
                self.assertIn('native/'+scratch+'/raw.txt',names)
                self.assertNotIn('sqlite',names)
            remote=root/'remote.git';subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            backup=PrivateGitBackup(root/'local.git',str(remote),'raw/test')
            first=backup.upload([item]); self.assertTrue(first)
            listing=subprocess.check_output(['git','--git-dir',str(remote),'ls-tree','-r','--name-only',first],text=True)
            self.assertIn('archives/sample.tar.gz',listing)
            (work/'states'/'sample2.json').write_text(json.dumps({'status':'complete'}))
            (work/'states'/'sample2.journal.jsonl').write_text('{}\n')
            second_item=archive_conversation(work,'sample2',scratch)
            second=backup.upload([second_item])
            listing=subprocess.check_output(['git','--git-dir',str(remote),'ls-tree','-r','--name-only',second],text=True)
            self.assertIn('archives/sample.tar.gz',listing)
            self.assertIn('archives/sample2.tar.gz',listing)
            with self.assertRaises(FileExistsError): archive_conversation(work,'sample',scratch)

    def test_backup_reconciles_a_lost_push_ack_without_rewriting(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); work=root/'run'; (work/'states').mkdir(parents=True)
            scratch='b'*32;(work/'native'/scratch).mkdir(parents=True)
            (work/'native'/scratch/'raw.txt').write_text('raw')
            (work/'states'/'sample.json').write_text(json.dumps({'status':'complete'}))
            (work/'states'/'sample.journal.jsonl').write_text('{}\n')
            item=archive_conversation(work,'sample',scratch)
            remote=root/'remote.git';subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            backup=PrivateGitBackup(root/'local.git',str(remote),'raw/test')
            original=backup.git
            def lost_ack(*args,**kwargs):
                result=original(*args,**kwargs)
                if args[0]=='push':raise RuntimeError('simulated lost acknowledgement')
                return result
            with patch.object(backup,'git',side_effect=lost_ack):
                with self.assertRaises(RuntimeError):backup.upload([item])
            pending=backup.pending['commit']
            self.assertTrue(subprocess.check_output(['git','--git-dir',str(remote),'rev-parse','refs/heads/raw/test'],text=True).strip()==pending)
            self.assertEqual(backup.upload([item]),pending)
            self.assertIsNone(backup.pending)

    def test_backup_retries_the_same_commit_if_push_was_not_sent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'run';(work/'states').mkdir(parents=True)
            scratch='c'*32;(work/'native'/scratch).mkdir(parents=True)
            (work/'native'/scratch/'raw').write_text('raw')
            (work/'states'/'sample.json').write_text('{}')
            (work/'states'/'sample.journal.jsonl').write_text('{}\n')
            item=archive_conversation(work,'sample',scratch)
            remote=root/'remote.git';subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            backup=PrivateGitBackup(root/'local.git',str(remote),'raw/test')
            original=backup.git
            def rejected_before_push(*args,**kwargs):
                if args[0]=='push':raise RuntimeError('simulated disconnected push')
                return original(*args,**kwargs)
            with patch.object(backup,'git',side_effect=rejected_before_push):
                with self.assertRaises(RuntimeError):backup.upload([item])
            pending=backup.pending['commit']
            self.assertEqual(backup.upload([item]),pending)
            self.assertIsNone(backup.pending)

    def test_dashboard_does_not_count_pending_backup_as_complete(self):
        class Transport:
            attempt_counts={'success':34,'rpc_429':2,'requeued':2}
        with tempfile.TemporaryDirectory() as d:
            rows=build();db=StatusDB(Path(d)/'status.sqlite',rows)
            trial=rows[0]
            db.update(trial['trial_id'],'complete_pending_backup',turns=34)
            view=render(db,Transport(),'1차 수집 중')
            self.assertIn('**0 / 8,400**',view)
            self.assertIn('| 백업 대기 | 1 |',view)
            db.update(trial['trial_id'],'complete')
            self.assertIn('**1 / 8,400**',render(db,Transport(),'1차 수집 중'))

    def test_dashboard_syncs_only_its_own_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);remote=root/'remote.git';repo=root/'board'
            subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            subprocess.run(['git','init','-q','-b','board/test',str(repo)],check=True)
            def git(*args):
                subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
            git('config','user.name','test');git('config','user.email','test@example.invalid')
            (repo/'README.md').write_text('initial\n')
            git('add','README.md');git('commit','-q','-m','initial')
            git('remote','add','origin',str(remote));git('push','-qu','origin','HEAD')
            Dashboard(repo).sync()

    @unittest.skipUnless(os.environ.get('CODEX_TEST_BINARY') and os.environ.get('EXP7_TEST_CATALOG'),
                         'Explicit loopback CLI fixture required')
    def test_full_cli_session_then_private_archive(self):
        from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
        from exp7_cards.queued_retry_transport import QueuedRetryTransport
        from exp7_cards.queued_retry_runner import run_trial
        from exp7_cards.queued_retry_audit import audit_queued_trial
        from exp7_pre.runner import CallBudget
        from .main_controller import make_wrapper, sqlite_for
        from .protocol import ZeroCardProtocol
        with tempfile.TemporaryDirectory() as d, LocalResponses(schema_answers=True) as service:
            root=Path(d);(root/'states').mkdir();(root/'native').mkdir()
            fixture=make_cli_wrapper(root,os.environ['CODEX_TEST_BINARY'],service.base_url)
            wrapper=make_wrapper(root,str(fixture))
            transport=QueuedRetryTransport(timeout=30,codex_binary=str(wrapper),
                                           catalog_path=os.environ['EXP7_TEST_CATALOG'])
            transport.before_send=lambda:None
            trial=build()[0]; protocol=ZeroCardProtocol(); path=root/'states'/(trial['trial_id']+'.json')
            try:
                state=run_trial(trial,protocol,transport,path,root/'native',
                                CallBudget(root/'budget.json','loopback',34),'a'*64)
            finally:
                if not transport.held_processes:transport.close()
            self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertEqual(len(state['turns']),34)
            self.assertTrue(audit_queued_trial(trial,protocol,path,'a'*64)['integrity_ok'])
            sqlite=sqlite_for(root,root/'native'/state['scratch_id'])
            self.assertTrue(sqlite.exists())
            item=archive_conversation(root,trial['trial_id'],state['scratch_id'])
            with tarfile.open(item['archive'],'r:gz') as archive:
                self.assertIn('states/'+trial['trial_id']+'.json',archive.getnames())
                self.assertFalse(any(name.startswith('sqlite/') for name in archive.getnames()))


if __name__=='__main__':unittest.main()
