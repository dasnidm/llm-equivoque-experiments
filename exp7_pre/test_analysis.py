"""Offline fake data tests for outcome definition, missingness, and controls."""
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from .analyze import rating,extract,contrast_bootstrap,did_bootstrap,run
from .protocol import make_probe_policies,probe_policies


def trial(arm='J',kind='obj',case='c1',replicate=1):
    t={'trial_id':f'{arm}-{kind}-{case}-{replicate}','case_id':case,'configuration_id':'fake-high','model':'fake','effort':'high','arm':arm,'kind':kind,'frame':'cards','replicate':replicate,'probe_arm':'neutral','prompt_variant':'p1','n_rounds':10,'order':['A','B','C','D'],'probe_policies':make_probe_policies(['A','B','C','D'],7)}
    if kind=='unforced':t['stage_rule']='KK'
    else:t['targets']=['A']*10
    return t

def rat(i,c,freedom=100):
    return {'freedom':freedom,'impact':i,'counterfactual':c,'_parse':{'status':'valid','fields':{'freedom':'valid','impact':'valid','counterfactual':'valid'},'format_compliant':True,'schema_valid':True}}

def state(t,ratings,compaction=False,probe=True):
    turns=[]
    for i,p in enumerate(ratings,1):
        if p is not None:turns.append({'turn':3*i,'parsed':p,'compaction_events':int(compaction and i==4)})
    if probe:
        fields={};parsed={}
        for i,policy in enumerate(probe_policies(t),1):
            key=f'policy_{i}';parsed[key]=dict(policy['gold'])
            fields.update({key+'.'+k:'valid' for k in policy['gold']})
        parsed['_parse']={'status':'valid','fields':fields};turns.append({'turn':32,'parsed':parsed,'ok':True})
    turns += [{'turn':33,'parsed':rat(1,'no')},{'turn':34,'parsed':rat(1,'no')}]
    return {'trial':t,'status':'complete','turns':turns,'rounds':[{'final':'A','selections':[['A','B'],['A']]} for _ in range(10)]}

class AnalysisTests(unittest.TestCase):
    def test_joint_does_not_require_freedom(self):
        p=rat(1,'no');p['_parse']['fields']['freedom']='unparseable';p['freedom']=None
        r=rating(p);self.assertEqual(r['joint'],1);self.assertIsNone(r['freedom'])
        p['_parse']['fields']['counterfactual']='uncertain';p['counterfactual']=None;self.assertIsNone(rating(p)['joint'])
    def test_onset_requires_prior_observation_and_r_is_undefined(self):
        t=trial(); ratings=[rat(100,'yes')]*3+[None]+[rat(1,'no')]+[rat(100,'yes')]*5
        a,rows,_=extract(t,state(t,ratings));self.assertIsNone(a['first_onset_round']);self.assertFalse(rows[4]['first_risk_eligible']);self.assertFalse(a['first_onset_identifiable'])
        t=trial(arm='R');a,rows,_=extract(t,state(t,[None]*9+[rat(1,'no')]));self.assertIsNone(a['first_onset_round']);self.assertFalse(rows[-1]['first_risk_eligible']);self.assertTrue(rows[0]['structural_unmeasured'])
    def test_onset_stays_identified_if_missing_after_event(self):
        t=trial();ratings=[rat(100,'yes')]*2+[rat(1,'no')]+[None]+[rat(100,'yes')]*6
        a,rows,_=extract(t,state(t,ratings));self.assertEqual(a['first_onset_round'],3);self.assertTrue(a['first_onset_identifiable']);self.assertFalse(rows[4]['reversal'])
    def test_r_ack_is_received_but_structurally_not_a_rating(self):
        t=trial(arm='R');ack={'ack':'ok','_parse':{'status':'valid','fields':{'ack':'valid'},'format_compliant':True,'schema_valid':True}}
        a,rows,_=extract(t,state(t,[ack]*9+[rat(100,'yes')]))
        self.assertTrue(rows[0]['turn_received']);self.assertFalse(rows[0]['rating_received']);self.assertTrue(rows[0]['structural_unmeasured'])
        self.assertEqual(rows[0]['impact_status'],'structural_unmeasured');self.assertEqual(rows[0]['counterfactual_status'],'structural_unmeasured');self.assertIsNone(rows[0]['joint'])
        self.assertTrue(rows[-1]['rating_received']);self.assertEqual(rows[-1]['joint'],0);self.assertIsNone(a['first_onset_round'])
    def test_unforced_uses_actual_stage_rule_gold_and_counts_uncertainty(self):
        t=trial(kind='unforced');s=state(t,[rat(100,'yes')]*10);parsed=[z for z in s['turns'] if z['turn']==32][0]['parsed'];parsed['policy_1']['first_feedback']='uncertain';parsed['_parse']['fields']['policy_1.first_feedback']='uncertain'
        a,_,checks=extract(t,s);self.assertEqual(len(checks),12);self.assertEqual(sum(c['status']=='uncertain' for c in checks),1);self.assertTrue(all(c['status']=='match' for c in checks[1:]));self.assertTrue(all(c['gold'] in 'ABCD' for c in checks if c['component']=='final'))
        finals=[c for c in checks if c['component']=='final'];self.assertGreater(len(set(c['gold'] for c in finals)),1)
    def test_paired_contrasts_exclude_repeats_and_missing(self):
        rows=[]
        for case in ['c1','c2']:
            for kind in ['obj','seq']:
                for arm in ['J','P']:
                    y=int(arm=='P' and kind=='obj');rows.append({'replicate':1,'r10_joint':y,'configuration_id':'fake','kind':kind,'arm':arm,'case_id':case})
        rows.append({'replicate':2,'r10_joint':0,'configuration_id':'fake','kind':'obj','arm':'P','case_id':'c1'})
        t=pd.DataFrame(rows);x=contrast_bootstrap(t,n_boot=10);z=x[(x.comparison=='P minus J')&(x.kind=='obj')].iloc[0];self.assertEqual(z.matched_case_families,2);self.assertEqual(z.difference,1)
        d=did_bootstrap(t,n_boot=10);z=d[d.comparison.eq('P minus J')].iloc[0];self.assertEqual(z.matched_case_families,2);self.assertEqual(z.difference_in_fixed_minus_sequence,1)
    def test_integration_counts_unstarted_parse_and_explicit_compaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);trials=[trial(),trial(arm='R'),trial(arm='P',case='c2')];(root/'states').mkdir();(root/'manifest.json').write_text(json.dumps({'run_id':'fake','trials':trials}))
            (root/'states'/f"{trials[0]['trial_id']}.json").write_text(json.dumps(state(trials[0],[rat(100,'yes')]*10,compaction=True)))
            (root/'states'/f"{trials[1]['trial_id']}.json").write_text(json.dumps(state(trials[1],[None]*9+[rat(100,'yes')])))
            result=run(root/'manifest.json',root/'states',root/'out');self.assertEqual((result['assigned'],result['complete'],result['unstarted']),(3,2,1));self.assertEqual(result['compaction_events'],1)
            summary=pd.read_csv(root/'out/profile_arm_condition.csv');self.assertEqual(int(summary.loc[summary.arm.eq('J'),'r10_parse_fail'].iloc[0]),0);self.assertEqual(int(summary.loc[summary.arm.eq('P'),'unstarted'].iloc[0]),1)
            rr=pd.read_csv(root/'out/round_outcomes.csv');self.assertEqual(int(rr.loc[rr.arm.eq('R'),'risk_rows'].sum()),0)
            self.assertEqual(int(summary.loc[summary.arm.eq('P'),'r10_unreceived'].iloc[0]),1);self.assertEqual(int(summary.loc[summary.arm.eq('P'),'r10_parse_fail'].iloc[0]),0)
            pp=pd.read_csv(root/'out/probe_components.csv');unknown=pp[pp.arm.eq('P')];self.assertEqual(len(unknown),12);self.assertTrue(unknown.status.eq('missing').all());self.assertEqual(unknown.baseline_matches.count(),0)
            self.assertTrue((root/'out/03_probe_components.png').is_file());self.assertTrue((root/'out/REPORT.ko.md').is_file())
    def test_calibration_requires_explicit_separate_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').write_text(json.dumps({'run_id':'test-calibration','trials':[trial()]}));(root/'states').mkdir()
            with self.assertRaisesRegex(ValueError,'Calibration'):run(root/'manifest.json',root/'states',root/'out')
    def test_recovered_native_transport_retained_and_filtered_only_in_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=trial(arm='J');b=trial(arm='P');(root/'states').mkdir();(root/'manifest.json').write_text(json.dumps({'run_id':'test-v4','trials':[a,b]}))
            sa=state(a,[rat(1,'no')]*10);sa['turns'][0].update({'https_fallback':True,'recovered_transport_events':5,'duration_seconds':3.5})
            sb=state(b,[rat(100,'yes')]*10);sb['turns'][0].update({'https_fallback':False,'recovered_transport_events':0,'duration_seconds':1.25})
            for tr,st in [(a,sa),(b,sb)]: (root/'states'/f"{tr['trial_id']}.json").write_text(json.dumps(st))
            result=run(root/'manifest.json',root/'states',root/'out');self.assertEqual(result['recovered_transport_turns'],1);self.assertEqual(result['recovered_transport_events'],5);self.assertEqual(result['sessions_with_recovery'],1);self.assertEqual(result['duration_observed_calls'],2);self.assertAlmostEqual(result['duration_seconds_total'],4.75)
            sensitivity=pd.read_csv(root/'out/r10_recovery_sensitivity.csv');all_rows=sensitivity[sensitivity.analysis_scope.eq('all_assigned')];filtered=sensitivity[sensitivity.analysis_scope.eq('no_recovered_transport')]
            self.assertEqual(set(all_rows.arm),{'J','P'});self.assertEqual(set(filtered.arm),{'P'});self.assertEqual(all_rows.loc[all_rows.arm.eq('J'),'joint_yes'].iloc[0],1)

if __name__=='__main__':unittest.main()
