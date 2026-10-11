import collections
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from equivoque.core import ROOT, LABELS, read_json, write_json
from equivoque.transport import provider_schema
from .protocol import CONFIG, PilotProtocol, apply_rule, paths
from .runner import run_task
from .analyze import estimate
from .audit import audit_worker


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.p=PilotProtocol(); self.c=read_json(CONFIG)
        self.schedule=read_json(ROOT/'manifests'/self.c['run_id']/'schedule.json')

    def test_exhaustive_rules_and_renaming_covariance(self):
        for order in itertools.permutations(LABELS):
            for target in LABELS:
                for proc in ('fixed_target','keep_selected'):
                    rows=paths(order,target,proc)
                    self.assertEqual(len(rows),12)
                    self.assertEqual(collections.Counter(r['final'] for r in rows),{target:12} if proc=='fixed_target' else dict.fromkeys(LABELS,3))
                    for mapping_values in itertools.permutations(LABELS):
                        mapping=dict(zip(LABELS,mapping_values))
                        for r in rows:
                            _,final=apply_rule([mapping[x] for x in order],[mapping[x] for x in r['first']],mapping[r['second']],mapping[target],proc)
                            self.assertEqual(final,mapping[r['final']])

    def test_exact_disjoint_schedule_and_balanced_cases(self):
        trials=self.schedule['trials']; self.assertEqual(len(trials),2016)
        ids=[t['trial_id'] for t in trials]; self.assertEqual(len(set(ids)),2016)
        shards=[read_json(ROOT/'manifests'/self.c['run_id']/f'worker-{w}.json') for w in self.c['workers']]
        self.assertEqual(sorted(len(m['trials']) for m in shards),[100]*4+[101]*16)
        self.assertEqual(collections.Counter(t['configuration_id'] for t in trials),dict.fromkeys([c['configuration_id'] for c in self.c['configurations']],96))
        self.assertEqual({t['trial_id'] for m in shards for t in m['trials']},set(ids))
        self.assertEqual(collections.Counter(c['target'] for c in self.schedule['cases']),dict.fromkeys(LABELS,2))
        self.assertEqual(collections.Counter(c['target_position'] for c in self.schedule['cases']),dict.fromkeys(range(4),2))
        evaluation={(tuple(c['order']),c['target']) for c in self.schedule['cases']}
        development=read_json(ROOT/'experiment3/protocol/development-cases.json')['cases']
        self.assertFalse(evaluation & {(tuple(c['order']),c['target']) for c in development})

    def test_claim_changes_only_host_statement(self):
        t=self.schedule['trials'][0]
        versions=[self.p.prompt({**t,'claim':c}) for c in ('neutral','congruent','conflicting')]
        stripped=[v.split('\n\nHost statement:')[0]+v.split('\n\nHost statement:')[1].split('\n\n',1)[1] for v in versions]
        self.assertEqual(len(set(stripped)),1)
        self.assertEqual(len({json.dumps(self.p.oracle({**t,'claim':c}),sort_keys=True) for c in ('neutral','congruent','conflicting')}),1)

    def test_frames_schema_and_all_feasible_queries(self):
        for t in self.schedule['trials']:
            response=self.p.oracle(t)
            self.assertEqual(self.p.parse(json.dumps(response),t['frame']),response)
            self.assertTrue(all(self.p.score(t,response).values()))
            prompt=self.p.prompt(t)
            if t['frame']=='cards':
                self.assertNotIn('A is renamed',prompt)
                self.assertNotIn('"A"',json.dumps(self.p.schema(frame='cards')))
            self.assertEqual(response['counterfactual']=='yes',t['procedure']=='keep_selected')
            self.assertNotEqual(response['counterfactual'],response['changed_counterfactual'])

    def test_strict_response_validation(self):
        t=self.schedule['trials'][0]; r=self.p.oracle(t)
        for invalid in [{**r,'extra':1},{**r,'counterfactual':'maybe'},{**r,'new_arrangement':None}]:
            with self.assertRaises(ValueError): self.p.parse(json.dumps(invalid),t['frame'])
        with self.assertRaises(ValueError):self.p.parse('{"counterfactual":"yes","counterfactual":"no"}',t['frame'])

    def test_no_replay_and_failure_preservation(self):
        trial=self.schedule['trials'][0]; protocol=self.p
        class Mock:
            name='mock'; calls=0
            def request(self,*args):
                self.calls+=1
                return {'ok':True,'text':json.dumps(protocol.oracle(trial)),'session_id':str(uuid.uuid4())}
        mock=Mock()
        with tempfile.TemporaryDirectory() as d:
            s=run_task(trial,Path(d),Path(d)/'scratch',mock)
            self.assertEqual(s['status'],'complete')
            run_task(trial,Path(d),Path(d)/'scratch',mock);self.assertEqual(mock.calls,1)
            path=next((Path(d)/'trials').glob('*.json'))
            s['status']='active';path.write_text(json.dumps(s))
            self.assertEqual(run_task(trial,Path(d),Path(d)/'scratch',mock)['status'],'interrupted')
            self.assertEqual(mock.calls,1)

    def test_primary_excludes_lookup_and_pairs_missingness(self):
        tasks=[t for t in self.schedule['trials'] if t['configuration_id']==self.c['configurations'][0]['configuration_id']]
        states=[]
        for t in tasks:
            correct={k:True for k in self.p.oracle(t)};correct['table_lookup']=False
            states.append({'trial':t,'status':'complete','correct':correct,'response':self.p.oracle(t),'result':{}})
        rows,cells,pairs,contrasts=estimate(states)
        self.assertTrue(all(r['transfer_accuracy']==1 for r in rows))
        self.assertEqual(contrasts[0]['difference'],0)
        selected=next(s for s in states if s['trial']['claim']=='neutral');selected['status']='failed'
        rows,cells,pairs,contrasts=estimate(states)
        self.assertEqual(contrasts[0]['paired_valid'],31)
        self.assertEqual(contrasts[0]['paired_assigned'],32)
        self.assertEqual(contrasts[0]['difference'],0)

    def test_full_simulation_audit_and_native_tampering(self):
        protocol=self.p
        class MockNative:
            name='codex-native'
            calls=0
            def request(self,t,prompt,schema,session,directory,attempt):
                self.calls+=1
                directory=Path(directory);directory.mkdir(parents=True)
                sid=str(uuid.uuid4());text=json.dumps(protocol.oracle(t))
                events=[{'type':'thread.started','thread_id':sid}, {'type':'item.completed','item':{'type':'agent_message','text':text}}, {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
                (directory/'subject-system.txt').write_text(protocol.data['system'])
                (directory/'turn-01.events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
                (directory/'turn-01.stderr.txt').write_text('')
                write_json(directory/'turn-01.schema.json',provider_schema(schema))
                return {'ok':True,'text':text,'session_id':sid,'events':events,'stderr':'',
                        'provider_schema':provider_schema(schema),'usage':events[-1]['usage'], 'timeout':False,
                        'tool_events':[],'metadata_fallback':False,'duration_seconds':.01,
                        'command':['codex','exec','--model',t['model'],'-c','model_reasoning_effort='+json.dumps(t['effort'])]}
        mock=MockNative()
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            for w in self.c['workers']:
                manifest=read_json(ROOT/'manifests'/self.c['run_id']/f'worker-{w}.json')
                directory=base/w
                for t in manifest['trials']:
                    self.assertEqual(run_task(t,directory,base/'scratch',mock)['status'],'complete')
                audit,_=audit_worker(manifest,directory)
                self.assertEqual(audit['counts'],{'complete':len(manifest['trials'])})
            self.assertEqual(mock.calls,2016)
            target=next((base/'a'/'native-raw').glob('*/turn-01.stderr.txt'))
            target.write_text('tampered')
            manifest=read_json(ROOT/'manifests'/self.c['run_id']/'worker-a.json')
            with self.assertRaises(ValueError):audit_worker(manifest,base/'a')


if __name__=='__main__':unittest.main()
