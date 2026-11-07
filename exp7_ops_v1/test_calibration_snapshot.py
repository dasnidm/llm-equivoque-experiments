"""Technical STOP snapshot tests using temporary evidence only."""
import json
import hashlib
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

    def exact_incident(self,attempt='c10-01'):
        work=self.work/('exact-incident-'+attempt);work.mkdir()
        (work/'identity.private.json').write_bytes((self.work/'identity.private.json').read_bytes())
        (work/'worker.lock').write_bytes(b'')
        directory=work/'calibration'/('attempt-'+attempt);(directory/'states').mkdir(parents=True)
        op=work/'ops-v1'/attempt;op.mkdir(parents=True)
        for name in self.receipts:(op/name).write_bytes((self.op/name).read_bytes())
        ids=[tid.replace('c10-01',attempt) for tid in self.ids]
        for i,tid in enumerate(ids[:10]):
            scratch=f'{i+100:032x}';records=[]
            for t in range(1,11):
                event=directory/'native'/scratch/f'turn-{t:02d}'/'events.jsonl'
                event.parent.mkdir(parents=True,exist_ok=True);event.write_bytes(b'{"synthetic_success":true}\n')
                records.append({'turn':t,'ok':True,'budget_ticket':i*10+t,
                                'raw_files':[{'path':str(event),'sha256':hashlib.sha256(event.read_bytes()).hexdigest()}]})
            state={'trial':{'trial_id':tid,'model':'model-test','cohort':'technical_calibration'},
                   'freeze_sha256':self.board['freeze_sha256'],'status':'interrupted','scratch_id':scratch,
                   'turns':records,'pending_turn':{'turn':11,'budget_ticket':101+i}}
            (directory/'states'/(tid+'.json')).write_text(json.dumps(state))
            (directory/'states'/(tid+'.json.lock')).write_bytes(b'')
        (directory/'budget.json').write_text(json.dumps({'run_id':'incident','used':110,'limit':612}))
        (directory/'budget.json.lock').write_bytes(b'')
        (directory/'progress.json').write_text('{"finished":10,"assigned":18}')
        result=calibration.snapshot_stopped_calibration(work,attempt,op,op/'technical-stop-snapshot',
            expected_trial_ids=ids,stopped_pids=[99901,99902],confirmed_board=self.board,operator_receipts=self.receipts)
        return work,directory,result

    def test_exact_incident_receipt_excludes_only_ten_unchanged_states(self):
        work,directory,result=self.exact_incident()
        before={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        paths=calibration.verify_stopped_calibration_receipt(work,result['manifest'])
        self.assertEqual(paths,{directory/'states'/(tid+'.json') for tid in self.ids[:10]})
        self.assertEqual(before,{p:p.read_bytes() for p in directory.rglob('*') if p.is_file()})
        state_path=next(iter(paths));original=state_path.read_bytes();state=json.loads(original)
        state['pending_turn']['budget_ticket']=999;state_path.write_text(json.dumps(state))
        with self.assertRaises(calibration.StorageError):calibration.verify_stopped_calibration_receipt(work,result['manifest'])
        state_path.write_bytes(original)
        native=directory/'native'/state['scratch_id']/'turn-11';native.mkdir()
        with self.assertRaises(calibration.StorageError):calibration.verify_stopped_calibration_receipt(work,result['manifest'])

    def test_generic_technical_snapshot_cannot_exclude_arbitrary_interruptions(self):
        result=self.make()
        with self.assertRaises(calibration.StorageError):
            calibration.verify_stopped_calibration_receipt(self.work,result['manifest'])

    def test_fallback_proof_preserves_calibration_strictness_and_original_guard(self):
        for attempt in ('c10-01','c10-02'):
            work,directory,result=self.exact_incident(attempt)
            kwargs={'expected_attempt':attempt,'expected_freeze_sha256':self.board['freeze_sha256']}
            paths=calibration.verify_terminal_calibration_snapshot(work,result['manifest'],**kwargs)
            self.assertEqual(len(paths),10)
            with self.assertRaises(calibration.StorageError):
                calibration.verify_terminal_calibration_snapshot(work,result['manifest'],**{**kwargs,'expected_freeze_sha256':'0'*64})
            operator_log=work/'ops-v1'/attempt/self.receipts[1]
            operator_log.write_bytes(operator_log.read_bytes()+b'Later audited capacity change.\n')
            self.assertEqual(calibration.verify_terminal_calibration_snapshot(work,result['manifest'],**kwargs),paths)
            with self.assertRaises(calibration.StorageError):
                calibration.verify_stopped_calibration_receipt(work,result['manifest'])
            state=next(iter(paths));state.write_bytes(state.read_bytes()+b' ')
            with self.assertRaises(calibration.StorageError):
                calibration.verify_terminal_calibration_snapshot(work,result['manifest'],**kwargs)

    def test_second_stopped_attempt_has_separate_scope_without_weakening_first_guard(self):
        old_directory=self.directory
        self.attempt='c10-02';self.directory=old_directory.with_name('attempt-c10-02')
        old_directory.rename(self.directory)
        old_ids=self.ids;self.ids=[tid.replace('c10-01','c10-02') for tid in old_ids]
        for old,tid in zip(old_ids[:2],self.ids[:2]):
            path=self.directory/'states'/(old+'.json');state=json.loads(path.read_text())
            state['trial']['trial_id']=tid
            refs=[raw for record in state['turns'] for raw in record['raw_files']]+state.get('pending_raw_files',[])
            for raw in refs:raw['path']=raw['path'].replace(str(old_directory),str(self.directory))
            path.write_text(json.dumps(state))
            for suffix in ('.json','.json.lock','.journal.jsonl'):
                (self.directory/'states'/(old+suffix)).rename(self.directory/'states'/(tid+suffix))
        self.op=self.work/'ops-v1'/'c10-02';self.op.mkdir()
        self.receipts=['status.private.json','launch.private.json','supervisor.log',
                       'resume.private.json','resume-intent.private.json',
                       'independent-wrapper-audit.private.json','readonly-metrics-first-terminal.json',
                       'catalog-invocations.private.jsonl']
        for name in self.receipts:(self.op/name).write_bytes(b'{"synthetic_operator_evidence":true}\n')
        self.output=self.op/'stop-snapshot';before=self.source_bytes()
        result=self.make();index=calibration.verify_calibration_snapshot(result['archive'],result['manifest'])
        self.assertEqual(index['attempt'],'c10-02')
        self.assertEqual(index['attempt_relative'],'calibration/attempt-c10-02')
        self.assertTrue(all(not tid.startswith('cal-c10-01-') for tid in index['expected_trial_ids']))
        for name in self.receipts:self.assertIn('ops-v1/c10-02/'+name,index['files'])
        self.assertEqual(self.source_bytes(),before)
        with self.assertRaises(calibration.StorageError):
            calibration.verify_stopped_calibration_receipt(self.work,result['manifest'])


if __name__=='__main__':unittest.main()
