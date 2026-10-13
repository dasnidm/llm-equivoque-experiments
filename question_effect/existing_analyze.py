"""Reproducible existing-data analysis; semantic coding limited to 97 accounts."""
import csv,json,re,hashlib,collections,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

MATCHING_TARGET_IDS={1,2,5,6,9,10,11,13,14,16,17,20,21,23,26,33,34,35,40,41,43,45,46,47,51,52,54,60,62,63,65,70,73,74,76,78,81,82,87,93}
SCREENED_MAPPING_IDS={3,5,9,11,12,15,16,18,20,21,23,24,25,26,32,36,41,42,45,46,47,49,52,56,58,59,65,66,72,75,76,77,78,83,85,88,89,96,99,101,102,105,106,108,109,110,111,112,118,119,120,122,125,129,131,132,133}

def save_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    root=Path(__file__).resolve().parents[1]
    old=root/'work/existing-inputs'
    if not (old/'trials.csv').exists():
        old=Path('/workspace/work/equivoque-recovery/work/integration-trees/equivoque-2026-10-12-sequence-replication-v1/analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables')
    out=root/'analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01'
    fig=out/'figures';fig.mkdir(parents=True,exist_ok=True)
    load=lambda name:list(csv.DictReader((old/(name+'.csv')).open()))
    ts=[r for r in load('trials') if r['kind']=='seq']
    ps=[r for r in load('predictions') if r['kind']=='seq']
    rs=[r for r in load('rules') if r['kind']=='seq']
    models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
    summary=[]
    for m in models:
        group=[r for r in ts if r['model']==m];pred=[r for r in ps if r['model']==m]
        counts=collections.Counter('uncertain' if r['uncertain']=='1' else 'match' if r['matches_generator']=='1' else 'mismatch' for r in pred)
        summary.append({'model':m,'sessions':len(group),'perfect_12':sum(r['prediction_matches']=='12' for r in group),'mean_matches':statistics.mean(float(r['prediction_matches']) for r in group),'all_12_uncertain':sum(r['prediction_uncertain']=='12' for r in group),'any_uncertain':sum(float(r['prediction_uncertain'])>0 for r in group),'component_total':len(pred),**{k:counts[k] for k in ['match','mismatch','uncertain']}})
    save_csv(out/'tables/existing_prediction_by_model.csv',summary)
    component=[]
    for m in models:
        for c in ['first_feedback','second_feedback','final']:
            pred=[r for r in ps if r['model']==m and r['component']==c]
            counts=collections.Counter('uncertain' if r['uncertain']=='1' else 'match' if r['matches_generator']=='1' else 'mismatch' for r in pred)
            component.append({'model':m,'component':c,'n':len(pred),**{k:counts[k] for k in ['match','mismatch','uncertain']}})
    save_csv(out/'tables/existing_prediction_by_component.csv',component)
    # Text search is explicitly descriptive, not semantic or blinded coding.
    lexical=[]
    for r in rs:
        text=r['rule'].lower()
        lexical.append({**r,'target_word':int(bool(re.search(r'\btarget\b|preselect|predetermin|intended|desired|forcing|force a|forced',text))),
                        'uncertainty_word':int(bool(re.search(r'insufficient|cannot|can.t|unclear|unknown|not reveal|no clear|no consistent|no fixed|no stable|no single|not establish|not infer|not determin|not identifiable|unobserved|not evident',text)))})
    save_csv(out/'tables/existing_rule_text_features.csv',lexical)
    features=[]
    for m in models:
        group=[r for r in lexical if r['model']==m]
        features.append({'model':m,'n':len(group),'target_word':sum(r['target_word'] for r in group),'uncertainty_word':sum(r['uncertainty_word'] for r in group),'both_words':sum(r['target_word'] and r['uncertainty_word'] for r in group)})
    save_csv(out/'tables/existing_rule_feature_by_model.csv',features)
    blind=json.loads((root/'work/existing-analysis/blind-97.json').read_text())
    key=json.loads((root/'work/existing-analysis/blind-key.json').read_text());by={r['trial_id']:r for r in ts}
    coded=[]
    for r in blind:
        t=by[key[r['id']]]
        coded.append({'masked_id':r['id'],'trial_id':t['trial_id'],'model':t['model'],'effort':t['effort'],'frame':t['frame'],
                      'target_preserving_mapping_in_account':int(int(r['id'][1:]) in MATCHING_TARGET_IDS),
                      'round10_impact':t['round10_impact'],'round10_counterfactual':t['round10_counterfactual'],'rule':r['rule']})
    assert len(coded)==97 and sum(r['target_preserving_mapping_in_account'] for r in coded)==40
    assert all(r['round10_impact']=='100' and r['round10_counterfactual']=='yes' for r in coded)
    save_csv(out/'tables/existing_97_account_coding.csv',coded)
    candidates=json.loads((root/'work/existing-analysis/target-candidates.json').read_text())
    candidate_key=json.loads((root/'work/existing-analysis/target-key.json').read_text())
    candidate_coding=[]
    for r in candidates:
        t=by[candidate_key[r['id']]]
        candidate_coding.append({'masked_id':r['id'],'trial_id':t['trial_id'],'model':t['model'],'effort':t['effort'],'frame':t['frame'],
                                 'target_preserving_mapping_in_account':int(int(r['id'][1:]) in SCREENED_MAPPING_IDS),
                                 'prediction_matches':t['prediction_matches'],'prediction_uncertain':t['prediction_uncertain'],'rule':r['rule']})
    candidate_by_id={r['trial_id']:r for r in candidate_coding}
    for r in coded:
        if r['trial_id'] in candidate_by_id:
            assert r['target_preserving_mapping_in_account']==candidate_by_id[r['trial_id']]['target_preserving_mapping_in_account']
    save_csv(out/'tables/existing_screened_account_coding.csv',candidate_coding)
    rubric={'scope':'Only the 97 sequence sessions with all12 components matching the generator. Other1260 accounts receive transparent lexical features only.',
            'criterion':'Code1 if the account explicitly links conditional keep/discard or choosing the surviving side to preserving an intended/preselected/hidden target. A qualified possibility is sufficient; certainty about target selection is not required. Generic varying keep/discard alone, or target mention alone, is code0.',
            'coder':'Single coordinator manual review of all97 texts displayed with randomized masked IDs; model/effort/trial labels omitted during reading. Coordinator already knew aggregate results and selected the subset; not independent blinded validation.',
            'interpretation':'Code0 means no explicit target-preserving mapping in this answer; not proof of absent mechanism knowledge. Code1 may be a qualified compatible hypothesis, not proven knowledge.',
            'mapping_present':40,'other_accounts':57,'all97_round10_impact100_counterfactual_yes':True,
            'source_run':'equivoque-2026-10-12-sequence-replication-v1','source_files_sha256':{str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in [old/'trials.csv',old/'predictions.csv',old/'rules.csv']}}
    rubric['additional_screen']={'candidate_selection':'133 of1260 accounts with target/predetermined/force/intended/desired lexical flag; all133 manually reviewed with randomized masked IDs under the same mapping criterion.',
                                'negative_spotcheck':'First five lexical-negative accounts per model (35 total) inspected; none explicitly linked keep/discard to preserving a chosen outcome. Remaining lexical negatives not manually coded.',
                                'mapping_accounts':sum(r['target_preserving_mapping_in_account'] for r in candidate_coding),
                                'mapping_by_model':dict(collections.Counter(r['model'] for r in candidate_coding if r['target_preserving_mapping_in_account'])),
                                'limitation':'Screen is not guaranteed exhaustive; do not infer absent knowledge from nonselection. Possible or qualified target-steering hypotheses count; not a certainty score.'}
    (out/'existing-analysis-method.json').write_text(json.dumps(rubric,indent=2)+'\n')
    plt.rcParams.update({'font.size':10,'figure.dpi':150})
    fig1,ax=plt.subplots(figsize=(9,4.8));left=np.zeros(7)
    for k,color,label in [('match','#298c79','Matches generator'),('mismatch','#df785a','Confident mismatch'),('uncertain','#c4cad1','Uncertain')]:
        vals=np.array([r[k]/r['component_total']*100 for r in summary]);ax.barh(models,vals,left=left,label=label,color=color);left+=vals
    ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xlabel('Percent of 2,160 prediction components per model');ax.set_title('Existing sequence predictions: uncertainty is separate from mismatch');ax.legend(loc='upper center',bbox_to_anchor=(.5,-.16),ncol=3);fig1.tight_layout();fig1.savefig(fig/'01_existing_prediction_components.png',bbox_inches='tight');plt.close(fig1)
    fig2,axes=plt.subplots(1,2,figsize=(9,4));axes[0].bar(['Explicit target-preserving\naccount','Other account'],[40,57],color=['#298c79','#c4cad1']);axes[0].set_ylim(0,100);axes[0].set_title('97 complete prediction matches: account review')
    for i,n in enumerate([40,57]):axes[0].text(i,n+2,str(n),ha='center')
    axes[1].bar(['Impact100 + Yes\nat round10','Other report'],[97,0],color=['#df785a','#c4cad1']);axes[1].set_ylim(0,110);axes[1].set_title('Their immediately preceding self-reports');axes[1].text(0,99,'97',ha='center');fig2.tight_layout();fig2.savefig(fig/'02_existing_97_accounts.png');plt.close(fig2)
    print(json.dumps({'sequence_sessions':len(ts),'prediction_components':len(ps),'manual97_mapping':40,'output':str(out)}))

if __name__=='__main__':main()
