"""Audit completed native sessions and export paired intervention estimates."""
import csv,json,collections,statistics,hashlib,html
from pathlib import Path
import numpy as np
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from equivoque.core import digest,read_json,write_json
from equivoque.transport import provider_schema
from question_effect.protocol import QuestionProtocol
from question_effect.existing_analyze import save_csv

def paired_interval(values,draws):
    values=np.asarray(values,dtype=float)
    boot=values[draws].mean(axis=1)
    return float(values.mean()),float(np.quantile(boot,.025)),float(np.quantile(boot,.975))

def wilson_interval(successes,n):
    z=1.959963984540054;p=successes/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.,center-radius),min(1.,center+radius)

def export(root):
    root=Path(root);design=read_json(root/'question_effect/design.json');run=design['run_id']
    out=root/'analysis/results'/run/'attempt-01';fig=out/'figures';fig.mkdir(parents=True,exist_ok=True)
    assignments=read_json(root/'question_effect/assignments.json');expected={t['trial_id']:t for ts in assignments.values() for t in ts}
    for name,expected_hash in read_json(root/'question_effect/freeze.json')['files'].items():
        assert digest(root/name)==expected_hash,('Frozen source changed',name)
    import sequence_replication.audit as audit_module
    audit_module.SequenceProtocol=QuestionProtocol
    audits=[];work=root/'work/audit-manifests';work.mkdir(parents=True,exist_ok=True)
    for w,ts in assignments.items():
        manifest=work/(w+'.json');write_json(manifest,{'run_id':run,'worker_id':w,'trials':ts})
        a=audit_module.audit_worker(manifest,root/'results'/run/('worker-'+w))
        audits.append(a)
    errors=[e for a in audits for e in a['errors']]
    sessions=[s for a in audits for s in a['session_ids']]
    counts=collections.Counter();[counts.update(a['counts']) for a in audits]
    assert not errors,errors[:10]
    assert counts=={'complete':180} and len(sessions)==len(set(sessions))==180
    assert sum(a['subject_invocations'] for a in audits)==5940
    states=sorted([read_json(p) for p in (root/'results'/run).glob('worker-*/trials/*.json')],key=lambda s:s['trial']['trial_id'])
    trial_rows=[];measurements=[];predictions=[];accounts=[];ledger=[]
    for s in states:
        t=s['trial'];assert t==expected[t['trial_id']]
        assert len(s['turns'])==33 and not s['pending_turn']
        b={k:t[k] for k in ['trial_id','case_id','model','effort','arm','worker_id']}
        for turn in s['turns']:
            assert turn['provider_schema']==provider_schema(turn['schema'])
            ledger.append({**b,'scratch_id':s['scratch_id'],'session_id':s['session_id'],'turn':turn['turn'],'requested_at':turn['requested_at'],'received_at':turn['received_at'],'duration_seconds':turn['duration_seconds'],'ok':turn['ok']})
        for r in range(1,11):measurements.append({**b,'phase':'game','round':r,**s['turns'][3*r-1]['parsed']})
        pre=s['turns'][29]['parsed'];post=s['turns'][31]['parsed'];disclosed=s['turns'][32]['parsed']
        joint=lambda v:int(v['impact']==1 and v['counterfactual']=='no')
        row={**b,'session_id':s['session_id'],'pre_impact':pre['impact'],'post_impact':post['impact'],'impact_change':post['impact']-pre['impact'],
             'pre_joint':joint(pre),'post_joint':joint(post),'joint_change':joint(post)-joint(pre),'pre_cf_no':int(pre['counterfactual']=='no'),
             'post_cf_no':int(post['counterfactual']=='no'),'pre_freedom':pre['freedom'],'post_freedom':post['freedom'],
             'disclosed_joint':joint(disclosed),'prediction_matches':'','prediction_uncertain':'','prediction_mismatch':''}
        for label,value in [('rerating',post),('disclosed',disclosed)]:measurements.append({**b,'phase':label,'round':10,**value})
        if t['arm']=='prediction':
            from sequence_replication.protocol import probe_policies
            match=uncertain=wrong=0
            for i,policy in enumerate(probe_policies(t),1):
                answers=s['turns'][30]['parsed'][f'policy_{i}']
                for component,answer in answers.items():
                    state='uncertain' if answer=='uncertain' else 'match' if answer==policy['gold'][component] else 'mismatch'
                    match+=state=='match';uncertain+=state=='uncertain';wrong+=state=='mismatch'
                    predictions.append({**b,'policy':i,'component':component,'answer':answer,'generator_value':policy['gold'][component],'state':state})
            row.update(prediction_matches=match,prediction_uncertain=uncertain,prediction_mismatch=wrong)
        elif t['arm']=='explanation':accounts.append({**b,'rule':s['turns'][30]['parsed']['rule'],'category':'uncoded'})
        trial_rows.append(row)
    for name,rows in [('intervention_trials',trial_rows),('intervention_measurements',measurements),('intervention_predictions',predictions),('intervention_accounts',accounts),('evaluation_invocation_ledger',ledger)]:save_csv(out/'tables'/(name+'.csv'),rows)
    draws=np.random.default_rng(2026101302).integers(0,30,size=(2000,30))
    summaries=[];effects=[];by={(r['model'],r['arm'],r['case_id']):r for r in trial_rows}
    case_ids=sorted({r['case_id'] for r in trial_rows});assert len(case_ids)==30
    for m in design['models']:
        for arm in design['arms']:
            group=[by[m,arm,c] for c in case_ids];assert len(group)==30
            post_count=sum(r['post_joint'] for r in group);wl,wh=wilson_interval(post_count,30)
            summaries.append({'model':m,'arm':arm,'n':30,'pre_joint':sum(r['pre_joint'] for r in group),'post_joint':post_count,'post_joint_wilson95_low':wl,'post_joint_wilson95_high':wh,
                              'new_joint':sum(r['post_joint']==1 and r['pre_joint']==0 for r in group),'lost_joint':sum(r['post_joint']==0 and r['pre_joint']==1 for r in group),
                              'pre_impact_mean':statistics.mean(r['pre_impact'] for r in group),'post_impact_mean':statistics.mean(r['post_impact'] for r in group),
                              'pre_cf_no':sum(r['pre_cf_no'] for r in group),'post_cf_no':sum(r['post_cf_no'] for r in group),
                              'disclosed_joint':sum(r['disclosed_joint'] for r in group),'perfect_predictions':sum(r['prediction_matches']==12 for r in group) if arm=='prediction' else '',
                              'prediction_mean_matches':statistics.mean(r['prediction_matches'] for r in group) if arm=='prediction' else ''})
        for arm in ['explanation','prediction']:
            for endpoint,field in [('joint_report_change','joint_change'),('impact_change','impact_change'),('counterfactual_no_change',None)]:
                def value(r):return r[field] if field else r['post_cf_no']-r['pre_cf_no']
                paired=[value(by[m,arm,c])-value(by[m,'control',c]) for c in case_ids]
                point,lo,hi=paired_interval(paired,draws)
                effects.append({'model':m,'treatment':arm,'reference':'control','endpoint':endpoint,'matched_cases':30,'estimate':point,'ci_low':lo,'ci_high':hi,'bootstrap_replicates':2000,'interval':'nominal pointwise paired case percentile95%'})
    save_csv(out/'tables/intervention_summary.csv',summaries);save_csv(out/'tables/intervention_effects.csv',effects)
    audit={'run_id':run,'integrity_ok':True,'complete':180,'cells':6,'per_cell':30,'unique_sessions':180,'game_rounds':1800,'evaluation_calls':5940,
           'compaction_events':[e for a in audits for e in a['compaction_events']],'worker_audits':audits,'first_requested_at':min(r['requested_at'] for r in ledger),'last_received_at':max(r['received_at'] for r in ledger),'errors':[]}
    recoveries_path=root/'question_effect/runtime/recoveries.json'
    recoveries=read_json(recoveries_path) if recoveries_path.exists() else []
    physical=[{'scope':'evaluation',**r} for r in ledger]
    excluded_audits=[]
    for path in sorted((root/'results'/run/'excluded').glob('*/worker-*/trials/*.json')):
        s=read_json(path);t=s['trial'];assert t==expected[t['trial_id']]
        manifest=work/(s['scratch_id']+'.json');write_json(manifest,{'run_id':run,'worker_id':t['worker_id'],'trials':[t]})
        ea=audit_module.audit_worker(manifest,path.parent.parent);assert ea['integrity_ok'],ea['errors'];excluded_audits.append(ea)
        for turn in s['turns']:
            physical.append({'scope':'excluded_capacity',**{k:t[k] for k in ['trial_id','case_id','model','effort','arm','worker_id']},'scratch_id':s['scratch_id'],'session_id':s['session_id'],'turn':turn['turn'],'requested_at':turn['requested_at'],'received_at':turn['received_at'],'duration_seconds':turn['duration_seconds'],'ok':turn['ok']})
    for path in sorted((root/'work/preflight').glob('*/trials/calibration.json')):
        s=read_json(path);t=s['trial'];assert s['status']=='complete' and len(s['turns'])==6
        for turn in s['turns']:
            physical.append({'scope':'calibration',**{k:t[k] for k in ['trial_id','case_id','model','effort','arm','worker_id']},'scratch_id':s['scratch_id'],'session_id':s['session_id'],'turn':turn['turn'],'requested_at':turn['requested_at'],'received_at':turn['received_at'],'duration_seconds':turn['duration_seconds'],'ok':turn['ok']})
    assert len({(r['scratch_id'],r['turn']) for r in physical})==len(physical)
    scopes=dict(collections.Counter(r['scope'] for r in physical));assert scopes.get('calibration')==12
    assert len(excluded_audits)==len(recoveries)
    audit.update(excluded_attempts=len(recoveries),excluded_audits=excluded_audits,physical_invocation_scopes=scopes,physical_invocation_rows=len(physical))
    save_csv(out/'tables/physical_invocation_ledger.csv',physical)
    write_json(out/'audit.json',audit);write_json(out/'results.json',{'design':design,'summary':summaries,'effects':effects})
    plt.rcParams.update({'font.size':10,'figure.dpi':150})
    f,axes=plt.subplots(1,2,figsize=(10,4.5),sharey=True)
    for ax,m in zip(axes,design['models']):
        group=[r for r in summaries if r['model']==m];x=np.arange(3)
        ax.bar(x-.18,[r['pre_joint'] for r in group],width=.36,color='#b8c4cf',label='Before question')
        ax.bar(x+.18,[r['post_joint'] for r in group],width=.36,color='#298c79',label='After question, before disclosure')
        for i,r in enumerate(group):
            ax.text(i-.18,r['pre_joint']+.5,str(r['pre_joint']),ha='center');ax.text(i+.18,r['post_joint']+.5,str(r['post_joint']),ha='center')
        ax.set_xticks(x,design['arms']);ax.set_ylim(0,34);ax.set_title(m+' / high');ax.set_ylabel('Joint impact1 + counterfactual no / 30')
    axes[1].legend(loc='upper right',fontsize=8);f.suptitle('Question intervention: immediate judgment changes');f.tight_layout();f.savefig(fig/'03_intervention_joint_reports.png');plt.close(f)
    f,axes=plt.subplots(1,2,figsize=(10,4.5))
    for ax,m in zip(axes,design['models']):
        group=[r for r in effects if r['model']==m and r['endpoint']=='joint_report_change'];y=np.arange(2)
        pts=np.array([r['estimate'] for r in group])*100;lo=np.array([r['ci_low'] for r in group])*100;hi=np.array([r['ci_high'] for r in group])*100
        ax.errorbar(pts,y,xerr=[pts-lo,hi-pts],fmt='o',color='#298c79',capsize=5);ax.axvline(0,color='#777',lw=1);ax.set_yticks(y,[r['treatment']+' vs control' for r in group]);ax.set_title(m+' / high');ax.set_xlabel('Difference in pre/post change (percentage points)');ax.grid(axis='x',alpha=.2)
    f.suptitle('Paired case contrasts; nominal pointwise95% bootstrap intervals');f.tight_layout();f.savefig(fig/'04_intervention_effects.png');plt.close(f)
    f,axes=plt.subplots(1,2,figsize=(10,4.5))
    for ax,m in zip(axes,design['models']):
        group=[r for r in trial_rows if r['model']==m and r['arm']=='prediction']
        count=collections.Counter((r['prediction_matches'],r['post_joint']) for r in group)
        for (matches,joint),n in count.items():ax.scatter(matches,joint,s=45*n,alpha=.65,color='#298c79' if joint else '#df785a');ax.text(matches,joint,str(n),ha='center',va='center',fontsize=9)
        ax.set_xlim(-.7,12.7);ax.set_ylim(-.4,1.4);ax.set_xticks(range(0,13,2));ax.set_yticks([0,1],['Other report','Impact1 + No']);ax.set_xlabel('Prediction components matching generator /12');ax.set_title(m+' / high')
    f.suptitle('Prediction-only arm: forecast matches vs immediate rerating (counts)');f.tight_layout();f.savefig(fig/'05_predictions_and_rerating.png');plt.close(f)
    f,axes=plt.subplots(1,2,figsize=(10,4.5),sharey=True)
    for ax,m in zip(axes,design['models']):
        group=[r for r in summaries if r['model']==m];x=np.arange(3)
        ax.bar(x-.18,[r['pre_impact_mean'] for r in group],width=.36,color='#b8c4cf',label='Before question')
        ax.bar(x+.18,[r['post_impact_mean'] for r in group],width=.36,color='#298c79',label='After question')
        for i,r in enumerate(group):
            ax.text(i-.18,r['pre_impact_mean']+1.5,f"{r['pre_impact_mean']:.1f}",ha='center',fontsize=9)
            ax.text(i+.18,r['post_impact_mean']+1.5,f"{r['post_impact_mean']:.1f}",ha='center',fontsize=9)
        ax.set_xticks(x,design['arms']);ax.set_ylim(0,114);ax.set_ylabel('Mean reported impact (1=no effect;100=control)');ax.set_title(m+' / high')
    axes[1].legend(fontsize=8,loc='upper center',bbox_to_anchor=(.5,-.13),ncol=2);f.suptitle('Impact ratings: changes hidden by the strict joint endpoint');f.tight_layout();f.savefig(fig/'06_intervention_impact_ratings.png');plt.close(f)
    print(json.dumps({'complete':180,'audit_ok':True,'summary':summaries,'primary_effects':[r for r in effects if r['endpoint']=='joint_report_change']}))
    return audit

if __name__=='__main__':export(Path(__file__).resolve().parents[1])
