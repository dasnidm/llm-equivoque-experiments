"""Technical STOP snapshot tests using temporary evidence only."""
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from . import calibration_snapshot as calibration
from . import test_snapshot as snapshot_fixtures


class CalibrationSnapshotTests(unittest.TestCase):
    def setUp(self):
        fixture=snapshot_fixtures.SnapshotTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.work=fixture.work;self.board=fixture.board
        self.attempt='c10-01';self.op=self.work/'ops-v1'/'c10-01';self.op.mkdir(parents=True,exist_ok=True)
        self.directory=self.work/'calibration'/'attempt-c10-01';self.directory.mkdir(parents=True)
        for name in ('states','native'):(fixture.job/name).rename(self.directory/name)
        self.ids=[f'cal-c10-01-model-test-{effort}-{i:02d}' for effort in ('low','medium','high') for i in range(1,7)]
        for old_id,tid in zip(fixture.fixture.ids,self.ids[:2]):
            path=self.directory/'states'/(old_id+'.json');state=json.loads(path.read_text())
            state['trial'].update(trial_id=tid,cohort='technical_calibration')
            state['freeze_sha256']=self.board['freeze_sha256']
            for record in state['turns']:
                record['ok']=True
                for raw in record['raw_files']:raw['path']=raw['path'].replace(str(fixture.job),str(self.directory))
            for raw in state.get('pending_raw_files',[]):raw['path']=raw['path'].replace(str(fixture.job),str(self.directory))
            fixture.fixture.write_json(path,state)
            for suffix in ('.json','.json.lock','.journal.jsonl'):
                (self.directory/'states'/(old_id+suffix)).rename(self.directory/'states'/(tid+suffix))
        fixture.fixture.write_json(self.directory/'budget.json',{'run_id':'run-test-calibration-c10-01:model-test','used':3,'limit':612})
        fixture.fixture.write_json(self.directory/'progress.json',{'finished':2,'assigned':18})
        (self.directory/'budget.json.lock').write_bytes(b'')
        self.receipts=['bounded-probe-status.private.json','bounded-probe.log']
        (self.op/self.receipts[0]).write_text('{"stage":"stopped"}\n')
        (self.op/self.receipts[1]).write_text('Synthetic bounded probe log.\n')
        self.output=self.op/'technical-stop-snapshot'
        self.before=self.source_bytes()
        mocked=patch.object(calibration,'process_alive',return_value=False);mocked.start();self.addCleanup(mocked.stop)

    def source_bytes(self):
        paths=[p for p in self.directory.rglob('*') if p.is_file() and not p.is_symlink()]+[self.op/name for name in self.receipts]
        return {p.relative_to(self.work).as_posix():p.read_bytes() for p in paths}

    def make(self):
        return calibration.snapshot_stopped_calibration(self.work,self.attempt,self.op,self.output,
            expected_trial_ids=self.ids,stopped_pids=[99901,99902],confirmed_board=self.board,operator_receipts=self.receipts)

    def test_all_native_pending_receipts_preserved_and_snapshot_idempotent(self):
        result=self.make();self.assertTrue(result['non_pruning'])
        self.assertEqual(result['state_counts']['unstarted'],16)
        self.assertEqual(result['state_counts']['interrupted'],1)
        self.assertEqual(result['recorded_calls'],2);self.assertEqual(result['successful_calls'],2)
        self.assertEqual(result['reserved_calls'],3)
        index=calibration.verify_calibration_snapshot(result['archive'],result['manifest'])
        self.assertEqual(index['pending_checkpoint_trials'],[self.ids[1]])
        with tarfile.open(result['archive'],'r:gz') as archive:
            copied={m.name:archive.extractfile(m).read() for m in archive}
        self.assertEqual(copied,{k:v for k,v in self.before.items() if not k.endswith('.lock')})
        self.assertEqual(self.source_bytes(),self.before)
        old_manifest=Path(result['manifest']).read_bytes();old_archive=Path(result['archive']).read_bytes()
        self.assertEqual(self.make(),result)
        self.assertEqual(Path(result['manifest']).read_bytes(),old_manifest)
        self.assertEqual(Path(result['archive']).read_bytes(),old_archive)

    def test_stop_identity_and_exact_technical_panel_required(self):
        self.board['global_stop']=False
        with self.assertRaises(calibration.StorageError):self.make()
        self.board['global_stop']=True
        self.ids[-1]='unrelated-trial'
        with self.assertRaises(calibration.StorageError):self.make()
        self.assertEqual(self.source_bytes(),self.before)
        self.assertFalse(self.output.exists())

    def test_unknown_files_or_unapproved_operator_receipts_block(self):
        unknown=self.directory/'unrequested-auth.txt';unknown.write_bytes(b'not copied')
        with self.assertRaises(calibration.StorageError):self.make()
        self.assertEqual(unknown.read_bytes(),b'not copied');unknown.unlink()
        self.receipts.append('../../identity.private.json')
        with self.assertRaises(calibration.StorageError):self.make()
        self.receipts.pop()
        self.assertEqual(self.source_bytes(),self.before)

    def test_corruption_and_source_changes_cannot_overwrite_old_snapshot(self):
        result=self.make();archive=Path(result['archive']);original=archive.read_bytes()
        (self.op/self.receipts[1]).write_bytes(b'changed log')
        with self.assertRaises(calibration.StorageError):self.make()
        self.assertEqual(archive.read_bytes(),original)
        archive.write_bytes(original[:-8])
        with self.assertRaises(calibration.StorageError):calibration.verify_calibration_snapshot(archive,result['manifest'])

    def test_live_process_and_symlink_are_rejected(self):
        with patch.object(calibration,'process_alive',return_value=True):
            with self.assertRaises(calibration.StorageError):self.make()
        link=self.directory/'native'/'linked-secret';link.symlink_to(self.work/'identity.private.json')
        with self.assertRaises(calibration.StorageError):self.make()
        self.assertTrue(link.is_symlink());link.unlink()
        self.assertEqual(self.source_bytes(),self.before)


if __name__=='__main__':unittest.main()
