import collections
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import uuid
from equivoque.core import ROOT,branches,read_json,write_json
from equivoque.transport import provider_schema
from .protocol import CONFIG,SequenceProtocol,phase,probe_policies
from .schedule import build
from .runner import run_trial
from .audit import audit_worker


class SimulationTransport:
    name='simulation-only'
    def __init__(self,fail_at=None,native=False):
        self.calls=0;self.fail_at=fail_at;self.native=native
        if native:self.name='codex-native'
    def request(self,trial,prompt,schema,session_id,directory,attempt):
        self.calls+=1;session_id=session_id or str(uuid.uuid4());r,local=phase(trial,attempt)
        if local==1:answer={'selection':schema['properties']['selection']['items']['enum'][:2]}
        elif local==2:answer={'selection':schema['properties']['selection']['enum'][0]}
        elif local in (3,6):answer={'freedom':100,'impact':1 if r>=4 or local==6 else 100,'counterfactual':'no' if r>=4 or local==6 else 'yes'}
        elif local==4:answer={'rule':'SIMULATION ONLY: keep the group containing the predetermined target.'}
        else:
            p=SequenceProtocol();names=p.choice_names(trial['frame'])
            answer={f'policy_{i}':{**policy['gold'],'final':names[policy['gold']['final']]} for i,policy in enumerate(probe_policies(trial),1)}
        text=json.dumps(answer);events=[{'type':'thread.started','thread_id':session_id},
              {'type':'item.completed','item':{'type':'agent_message','text':text}},
              {'type':'turn.completed','usage':{'input_tokens':0,'output_tokens':0}}]
        result={'ok':attempt!=self.fail_at,'session_id':session_id,'text':text,'events':events,
                'tool_events':[],'metadata_fallback':False,'duration_seconds':0.001,
                'provider_schema':provider_schema(schema),'stderr':'SIMULATION ONLY\n','usage':{'input_tokens':0,'output_tokens':0}}
        if self.native:
            d=Path(directory);d.mkdir(parents=True,exist_ok=True)
            (d/'subject-system.txt').write_text(SequenceProtocol().data['system'])
            (d/f'turn-{attempt:02d}.schema.json').write_text(json.dumps(provider_schema(schema)))
            (d/f'turn-{attempt:02d}.events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            (d/f'turn-{attempt:02d}.stderr.txt').write_text(result['stderr'])
        return result


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.c=read_json(CONFIG);self.p=SequenceProtocol();self.positions,self.assigned=build(self.c)
        self.trials=[t for group in self.assigned.values() for t in group]
    def test_shared_positions_and_four_labels(self):
        self.assertEqual((self.positions,self.assigned),build(self.c))
        self.assertEqual(sorted(collections.Counter(self.positions).values()),[7,7,8,8])
        self.assertEqual(len({t['trial_id'] for t in self.trials}),28)
        self.assertEqual(collections.Counter(len(g) for g in self.assigned.values()),{1:12,2:8})
        for c in self.c['configurations']:
            group=[t for t in self.trials if t['configuration_id']==c['configuration_id']]
            self.assertEqual(len(group),4)
            self.assertEqual({t['effort'] for t in group},{'low'})
            for t in group:
                expected=self.positions if t['kind']=='seq' else [self.positions[0]]*30
                self.assertEqual(t['positions'],expected)
                self.assertEqual(t['targets'],[t['order'][i-1] for i in expected])
                self.assertEqual(t['order'],list('ABDC' if t['frame']=='cards' else 'ABCD'))
    def test_base_wording_and_no_early_disclosure(self):
        self.assertEqual(self.p.data,read_json(ROOT/'protocol/prompts.v1.json'))
        for t in self.trials:
            for turn in range(1,94):
                r,local=phase(t,turn)
                text=self.p.prompt(t,turn,'K',t['order'][:2])
                if t['frame']=='cards':self.assertIsNone(re.search(r'\b[A-D]\b',text))
                if local==3:self.assertTrue(text.endswith(self.p.data['frames'][t['frame']]['evaluation']))
                self.assertEqual('was fixed' in text or 'were fixed' in text or 'was fixed according' in text,turn==93)
                if turn<=90:self.assertNotIn('predetermined',text)
            self.assertIn('ace of spades, ace of clubs, ace of hearts, ace of diamonds' if t['frame']=='cards' else 'A, B, C, D',self.p.prompt(t,1))
    def test_all_targets_all_legal_paths_and_probe_legality(self):
        for t in self.trials:
            for target in set(t['targets']):
                rows=branches(t['order'],target)
                self.assertEqual(len(rows),12)
                self.assertEqual({r['final'] for r in rows},{target})
            policies=probe_policies(t)
            self.assertEqual({(p['gold']['first_feedback'],p['gold']['second_feedback']) for p in policies},
                {('keep_selected','keep_selected'),('keep_selected','discard_selected'),('discard_selected','keep_selected'),('discard_selected','discard_selected')})
    def test_full_simulation_2604_invocations(self):
        transport=SimulationTransport();sessions=set()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for w,trials in self.assigned.items():
                manifest=root/f'{w}.json';write_json(manifest,{'run_id':self.c['run_id'],'worker_id':w,'trials':trials})
                for t in trials:
                    path=root/w/'trials'/(t['trial_id'].replace('/','__')+'.json')
                    s=run_trial(t,self.p,transport,path,root/'scratch')
                    self.assertEqual(s['status'],'complete');self.assertEqual(len(s['turns']),93)
                    self.assertNotIn(s['session_id'],sessions);sessions.add(s['session_id'])
                    for r in s['rounds']:self.assertEqual(r['remaining'],[r['target']])
                audit=audit_worker(manifest,root/w,allow_simulation=True)
                self.assertTrue(audit['integrity_ok'],audit['errors'][:2])
                self.assertEqual(audit['valid_measurements'],len(trials)*30)
                self.assertFalse(audit_worker(manifest,root/w)['integrity_ok'])
            self.assertEqual(transport.calls,2604)
            run_trial(t,self.p,transport,path,root/'scratch');self.assertEqual(transport.calls,2604)
    def test_failures_and_uncertain_pending_never_replayed(self):
        t=self.trials[0]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trials/t.json';tr=SimulationTransport(fail_at=11)
            s=run_trial(t,self.p,tr,path,tmp);self.assertEqual(s['status'],'failed')
            self.assertEqual(len(s['turns']),11);run_trial(t,self.p,tr,path,tmp);self.assertEqual(tr.calls,11)
            s.update(status='active',pending_turn={'turn':12});write_json(path,s)
            s=run_trial(t,self.p,tr,path,tmp);self.assertEqual(s['status'],'interrupted');self.assertEqual(tr.calls,11)
    def test_native_archive_tampering_detected(self):
        t=self.trials[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'manifest.json'
            write_json(manifest,{'run_id':self.c['run_id'],'worker_id':t['worker_id'],'trials':[t]})
            run_trial(t,self.p,SimulationTransport(native=True),root/'trials/t.json',root/'scratch')
            audit=audit_worker(manifest,root);self.assertTrue(audit['integrity_ok'],audit['errors'][:2])
            next((root/'native-raw').glob('*/turn-01.stderr.txt')).write_text('TAMPERED')
            self.assertFalse(audit_worker(manifest,root)['integrity_ok'])
    def test_analysis_preserves_rounds_excludes_disclosure_and_exports_graphs(self):
        from .analyze import export
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=self.c['run_id']
            for w,trials in self.assigned.items():
                write_json(root/'manifests'/run/f'worker-{w}.json',{'run_id':run,'worker_id':w,'trials':trials})
                for t in trials:
                    if t['configuration_id']!=self.c['configurations'][0]['configuration_id']:continue
                    path=root/'results'/run/f'worker-{w}'/'trials'/(t['trial_id'].replace('/','__')+'.json')
                    run_trial(t,self.p,SimulationTransport(native=True),path,root/'scratch')
            with patch('experiment7.analyze.frozen_hashes',return_value={}):audit=export(root,root/'analysis')
            self.assertEqual(audit['attempted'],4);self.assertEqual(audit['valid_measurements'],120)
            with (root/'analysis/tables/trials.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual({r['first_impact_1'] for r in rows},{'4'})
            self.assertEqual({r['prediction_generator_matches'] for r in rows},{'12'})
            self.assertEqual(len(list((root/'analysis/figures').glob('*.png'))),5)
            self.assertIn('120 valid pre-disclosure ratings', (root/'analysis/REPORT.md').read_text())
            self.assertIn('uncertainty or a plausible alternative', (root/'analysis/REPORT.md').read_text())
            self.assertEqual(len(read_json(root/'analysis/artifact-manifest.json')['files']),21)


if __name__=='__main__':unittest.main()
