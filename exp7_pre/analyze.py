"""Read-only Exp7-pre analysis of assigned sessions and durable states.

No inference calls. A valid prefix is required for a first-event claim. Repeats
are never counted as new case families in primary arm comparisons.
"""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .protocol import probe_policies

COMPARISONS=[('A','J'),('J','P'),('J','K'),('J','JS'),('JS','N'),('J','R'),('N','F')]
FIELDS=['first_feedback','second_feedback','final']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def status(parsed,key):
    s=parsed.get('_parse',{})
    if isinstance(s,dict):return s.get('fields',{}).get(key,'unparseable')
    return 'unparseable'
def rating(parsed):
    parsed=parsed if isinstance(parsed,dict) else {}
    f=parsed.get('freedom');i=parsed.get('impact');c=parsed.get('counterfactual')
    f=f if status(parsed,'freedom')=='valid' and type(f)==int and 1<=f<=100 else None
    i=i if status(parsed,'impact')=='valid' and type(i)==int and 1<=i<=100 else None
    c=c if status(parsed,'counterfactual')=='valid' and c in ('yes','no') else None
    j=int(i==1 and c=='no') if i is not None and c is not None else None
    return {'freedom':f,'impact':i,'counterfactual':c,'joint':j,
            'freedom_status':status(parsed,'freedom'),'impact_status':status(parsed,'impact'),'counterfactual_status':status(parsed,'counterfactual'),
            'format_compliant':parsed.get('_parse',{}).get('format_compliant') if isinstance(parsed.get('_parse',{}),dict) else None,
            'schema_valid':parsed.get('_parse',{}).get('schema_valid') if isinstance(parsed.get('_parse',{}),dict) else None,
            'parse_status':parsed.get('_parse',{}).get('status','unparseable') if isinstance(parsed.get('_parse',{}),dict) else 'unparseable'}

def extract(trial,state):
    meta={k:trial.get(k) for k in ['trial_id','case_id','configuration_id','model','effort','arm','kind','frame','replicate','probe_arm','prompt_variant']}
    if state is None:
        state={'trial':trial,'status':'unstarted','turns':[],'rounds':[{'final':None,'selections':[]} for _ in range(trial['n_rounds'])]}
    if state.get('trial')!=trial:raise ValueError(f"State metadata mismatch for {trial['trial_id']}")
    turns={t['turn']:t for t in state.get('turns',[])};n=trial['n_rounds'];rounds=[];prefix_valid=True;ever=False;first=None;prev=None
    for r in range(1,n+1):
        t=turns.get(3*r);structural=trial['arm']=='R' and r<n
        p=(t or {}).get('parsed',{});v=rating(p)
        if structural:
            # An acknowledgement was requested here, not a rating. Keep the
            # call receipt separate from the intentionally absent measurement.
            v={**v,'freedom':None,'impact':None,'counterfactual':None,'joint':None,
               'freedom_status':'structural_unmeasured','impact_status':'structural_unmeasured',
               'counterfactual_status':'structural_unmeasured','parse_status':'structural_unmeasured',
               'format_compliant':None,'schema_valid':None}
        j=v['joint']; observed=j is not None and not structural
        risk=bool(prefix_valid and not ever and observed and not structural)
        onset=bool(risk and j==1)
        reversion=bool(prev==1 and observed and j==0)
        reentry=bool(ever and prev==0 and observed and j==1)
        if onset:first=r
        row={**meta,'round':r,'structural_unmeasured':structural,'turn_received':t is not None,'rating_received':t is not None and not structural,
             'prior_prefix_complete':prefix_valid,'first_risk_eligible':risk,'first_onset':onset,
             'first_already_seen':ever,'reversal':reversion,'reentry':reentry,**v}
        rounds.append(row)
        if structural or not observed:prefix_valid=False
        if observed and j==1:ever=True
        prev=j if observed else None
    last=rounds[-1]; terminal=turns.get(3*n+2); rerate=turns.get(3*n+3); disclosed=turns.get(3*n+4)
    terminal_available=terminal is not None and terminal.get('ok',False)
    pred=terminal.get('parsed',{}) if terminal else {}; checks=[]
    visited=set()
    for rec in state.get('rounds',[]):
        sels=rec.get('selections',[])
        if len(sels)==2 and isinstance(sels[1],list) and len(sels[1])==1:
            visited.add((tuple(sorted(sels[0])),sels[1][0]))
    outcome=state.get('rounds',[{}]*n)[-1].get('final')
    for i,pol in enumerate(probe_policies(trial),1):
        key='policy_'+str(i);item=pred.get(key,{}) if isinstance(pred,dict) else {}
        path=(tuple(sorted(pol['first'])),pol['second']); seen=path in visited
        for field in FIELDS:
            ans=item.get(field);fs=status(pred,key+'.'+field)
            if not terminal_available:category='missing'
            elif fs=='uncertain':category='uncertain'
            elif fs=='ambiguous':category='ambiguous'
            elif fs!='valid':category='unparseable'
            else:category='match' if ans==pol['gold'][field] else 'mismatch'
            # Simple baselines ignore any inferred trick. They are compared only
            # against generator labels, including uncertainty/missing separately.
            baseline='keep_selected' if field!='final' else outcome
            checks.append({**meta,'policy':i,'component':field,'answer':ans,'status':category,
                           'gold':pol['gold'][field],'observed_path':seen,
                           'baseline_name':'always_keep' if field!='final' else 'repeat_last_outcome',
                           'baseline_answer':baseline,'baseline_matches':int(baseline==pol['gold'][field]) if terminal_available and baseline is not None else None})
    rv=rating((rerate or {}).get('parsed',{}));dv=rating((disclosed or {}).get('parsed',{}))
    response=state.get('turns',[])
    recovered_turns=sum(bool(v.get('https_fallback',False)) or int(v.get('recovered_transport_events',0) or 0)>0 for v in response)
    recovered_events=sum(int(v.get('recovered_transport_events',0) or 0) for v in response)
    fallback_calls=sum(bool(v.get('https_fallback',False)) for v in response)
    durations=[float(v['duration_seconds']) for v in response if isinstance(v.get('duration_seconds'),(int,float)) and not isinstance(v.get('duration_seconds'),bool) and np.isfinite(v['duration_seconds']) and v['duration_seconds']>=0]
    return {**meta,'status':state.get('status','unknown'),'calls_received':len(response),'compaction_events':sum(int(v.get('compaction_events',0) or 0) for v in response),
            'recovered_transport_turns':recovered_turns,'recovered_transport_events':recovered_events,'https_fallback_calls':fallback_calls,'has_recovered_transport':recovered_turns>0,
            'recovery_metadata_missing_turns':sum('https_fallback' not in v or 'recovered_transport_events' not in v for v in response),
            'duration_observed_calls':len(durations),'duration_seconds_total':sum(durations),
            'pending':state.get('pending_turn') is not None,'r10_joint':last['joint'],
            'r10_impact':last['impact'],'r10_freedom':last['freedom'],'r10_cf':last['counterfactual'],
            'r10_received':last['rating_received'],'r10_parse_status':last['parse_status'],'r10_format_compliant':last['format_compliant'],'first_onset_round':first,
            'first_onset_identifiable':trial['arm']!='R' and (first is not None or all(x['joint'] is not None for x in rounds)),
            'first_risk_rows':sum(x['first_risk_eligible'] for x in rounds),
            'reversals':sum(x['reversal'] for x in rounds),'reentries':sum(x['reentry'] for x in rounds),
            'pre_disclosure_rerate_joint':rv['joint'],'post_disclosure_joint':dv['joint'],
            'terminal_received':terminal is not None,'terminal_parse_status':pred.get('_parse',{}).get('status','unparseable') if isinstance(pred,dict) and isinstance(pred.get('_parse',{}),dict) else 'unparseable'},rounds,checks

def summarized_rows(trials):
    rows=[]
    for key,g in trials.groupby(['configuration_id','kind','arm'],dropna=False):
        valid=g.r10_joint.notna();iv=g.r10_impact.notna();cv=g.r10_cf.notna();fv=g.r10_freedom.notna()
        rows.append(dict(zip(['configuration_id','kind','arm'],key))|{'assigned':len(g),'complete':int(g.status.eq('complete').sum()),'unstarted':int(g.status.eq('unstarted').sum()),'calls_received':int(g.calls_received.sum()),'compaction_events':int(g.compaction_events.sum()),'sessions_with_detected_compaction':int(g.compaction_events.gt(0).sum()),'pending':int(g.pending.sum()),'joint_valid':int(valid.sum()),'joint_yes':int(g.loc[valid,'r10_joint'].sum()),'joint_rate':g.loc[valid,'r10_joint'].mean(),'impact_valid':int(iv.sum()),'impact1':int(g.loc[iv,'r10_impact'].eq(1).sum()),'impact_mean':g.loc[iv,'r10_impact'].mean(),'cf_valid':int(cv.sum()),'cf_no':int(g.loc[cv,'r10_cf'].eq('no').sum()),'freedom_valid':int(fv.sum()),'freedom_mean':g.loc[fv,'r10_freedom'].mean(),'first_time_observable':int(g.first_onset_identifiable.fillna(False).sum()),'first_events':int(g.first_onset_round.notna().sum()),'reversals':int(g.reversals.fillna(0).sum()),'r10_unreceived':int((~g.r10_received).sum()),'r10_parse_fail':int((g.r10_received & g.r10_parse_status.ne('valid')).sum()),'r10_format_noncompliant':int(g.r10_format_compliant.eq(False).sum())})
    return pd.DataFrame(rows)

def contrast_bootstrap(trials,n_boot=5000,seed=1030):
    x=trials[(trials.replicate==1)&trials.r10_joint.notna()].copy();out=[];rng=np.random.default_rng(seed)
    for (cfg,kind),q in x.groupby(['configuration_id','kind']):
        for a,b in COMPARISONS:
            aa=q[q.arm.eq(a)].set_index('case_id').r10_joint;bb=q[q.arm.eq(b)].set_index('case_id').r10_joint
            z=pd.concat([aa.rename('a'),bb.rename('b')],axis=1).dropna();n=len(z)
            if n>=1:
                d=(z.b-z.a).to_numpy();mean=float(d.mean())
                if n>=2:draw=d[rng.integers(0,n,(n_boot,n))].mean(axis=1);lo,hi=np.quantile(draw,[.025,.975])
                else:lo=hi=np.nan
            else:mean=lo=hi=np.nan
            out.append({'configuration_id':cfg,'kind':kind,'comparison':b+' minus '+a,'matched_case_families':n,'difference':mean,'ci_low':lo,'ci_high':hi})
    return pd.DataFrame(out,columns=['configuration_id','kind','comparison','matched_case_families','difference','ci_low','ci_high'])

def did_bootstrap(trials,n_boot=5000,seed=1031):
    x=trials[(trials.replicate==1)&trials.r10_joint.notna()&trials.kind.isin(['obj','seq'])];out=[];rng=np.random.default_rng(seed)
    for cfg,q in x.groupby('configuration_id'):
        p=q.pivot(index='case_id',columns=['arm','kind'],values='r10_joint')
        for a,b in COMPARISONS:
            keys=[(a,'obj'),(a,'seq'),(b,'obj'),(b,'seq')]
            if not all(k in p.columns for k in keys):n=0
            else:z=p[keys].dropna();n=len(z)
            if n>=1:
                d=((z[(b,'obj')]-z[(b,'seq')])-(z[(a,'obj')]-z[(a,'seq')])).to_numpy();mean=d.mean()
                if n>=2:boot=d[rng.integers(0,n,(n_boot,n))].mean(axis=1);lo,hi=np.quantile(boot,[.025,.975])
                else:lo=hi=np.nan
            else:mean=lo=hi=np.nan
            out.append({'configuration_id':cfg,'comparison':b+' minus '+a,'matched_case_families':n,'difference_in_fixed_minus_sequence':mean,'ci_low':lo,'ci_high':hi})
    return pd.DataFrame(out,columns=['configuration_id','comparison','matched_case_families','difference_in_fixed_minus_sequence','ci_low','ci_high'])

def run(manifest,states,out,allow_calibration=False):
    configuration=json.loads(Path(manifest).read_text());run_id=configuration.get('run_id','')
    if 'calibration' in run_id.lower() and not allow_calibration:
        raise ValueError('Calibration data require --allow-calibration and separate output; never merge with primary analysis')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);assigned=configuration['trials'];
    if len({x['trial_id'] for x in assigned})!=len(assigned):raise ValueError('Duplicate trial IDs')
    rows=[];rounds=[];probes=[];hashes={};freezes=set()
    for trial in assigned:
        path=Path(states)/(trial['trial_id']+'.json');state=json.loads(path.read_text()) if path.exists() else None
        if state is not None:
            hashes[path.name]=sha(path)
            if state.get('freeze_sha256'):freezes.add(state['freeze_sha256'])
        a,b,c=extract(trial,state);rows.append(a);rounds.extend(b);probes.extend(c)
    if len(freezes)>1:raise ValueError('Multiple frozen configurations in one analysis; investigate before reporting')
    t=pd.DataFrame(rows);r=pd.DataFrame(rounds);p=pd.DataFrame(probes)
    t.to_csv(out/'trial_summary.csv',index=False);r.to_csv(out/'round_level.csv',index=False);p.to_csv(out/'probe_components.csv',index=False)
    primary=t[t.replicate.eq(1)];summarized_rows(primary).to_csv(out/'profile_arm_condition.csv',index=False)
    # Recovery is recorded, not treated as an experimental condition.  The
    # primary analysis retains it; the filter below is descriptive sensitivity.
    no_recovery=primary[primary.calls_received.gt(0)&~primary.has_recovered_transport]
    all_summary=summarized_rows(primary).assign(analysis_scope='all_assigned')
    if no_recovery.empty:
        sensitivity=all_summary
    else:
        sensitivity=pd.concat([all_summary,summarized_rows(no_recovery).assign(analysis_scope='no_recovered_transport')],ignore_index=True)
    sensitivity.to_csv(out/'r10_recovery_sensitivity.csv',index=False)
    transport_summary=primary.groupby(['configuration_id','arm','kind'],dropna=False).agg(assigned=('trial_id','size'),calls_received=('calls_received','sum'),recovered_transport_turns=('recovered_transport_turns','sum'),recovered_transport_events=('recovered_transport_events','sum'),https_fallback_calls=('https_fallback_calls','sum'),sessions_with_recovery=('has_recovered_transport','sum'),recovery_metadata_missing_turns=('recovery_metadata_missing_turns','sum'),duration_observed_calls=('duration_observed_calls','sum'),duration_seconds_total=('duration_seconds_total','sum')).reset_index()
    transport_summary['recovered_turn_rate']=transport_summary.recovered_transport_turns/transport_summary.calls_received.replace(0,np.nan)
    transport_summary['mean_recorded_call_seconds']=transport_summary.duration_seconds_total/transport_summary.duration_observed_calls.replace(0,np.nan)
    transport_summary.to_csv(out/'transport_recovery_by_profile_arm_condition.csv',index=False)
    contrast_bootstrap(primary).to_csv(out/'arm_paired_contrasts.csv',index=False);did_bootstrap(primary).to_csv(out/'arm_difference_in_differences.csv',index=False)
    if not r.empty:
        r=r[r.replicate.eq(1)];r.groupby(['configuration_id','arm','kind','round'],dropna=False).agg(rating_received=('rating_received','sum'),joint_valid=('joint','count'),joint_positive=('joint','sum'),risk_rows=('first_risk_eligible','sum'),first_onsets=('first_onset','sum'),reversals=('reversal','sum'),reentries=('reentry','sum')).reset_index().to_csv(out/'round_outcomes.csv',index=False)
        coverage_fields=r.melt(id_vars=['configuration_id','arm','kind','round','structural_unmeasured'],value_vars=['freedom_status','impact_status','counterfactual_status'],var_name='field',value_name='field_status');coverage_fields.groupby(['configuration_id','arm','kind','round','structural_unmeasured','field','field_status'],dropna=False).size().rename('n').reset_index().to_csv(out/'field_parse_coverage.csv',index=False)
    if not p.empty:
        # observed_path means the same pair+single occurred in any previous
        # round; a sequence may give that path a different target/feedback.
        p=p[p.replicate.eq(1)];p.groupby(['configuration_id','arm','kind','component','observed_path','status'],dropna=False).size().rename('components').reset_index().to_csv(out/'probe_status.csv',index=False)
        p.groupby(['configuration_id','arm','kind','component'],dropna=False).agg(components=('status','size'),match=('status',lambda s:s.eq('match').sum()),mismatch=('status',lambda s:s.eq('mismatch').sum()),uncertain=('status',lambda s:s.eq('uncertain').sum()),unparseable=('status',lambda s:s.isin(['unparseable','ambiguous']).sum()),missing=('status',lambda s:s.eq('missing').sum()),baseline_eligible=('baseline_matches','count'),baseline_matches=('baseline_matches','sum')).reset_index().to_csv(out/'probe_comparison_baselines.csv',index=False)
        pt=p.groupby('trial_id').status.agg(matches=lambda s:s.eq('match').sum(),mismatches=lambda s:s.eq('mismatch').sum(),uncertain=lambda s:s.eq('uncertain').sum(),unparseable=lambda s:s.isin(['ambiguous','unparseable']).sum(),missing=lambda s:s.eq('missing').sum()).reset_index()
        pt=pt.merge(primary[['trial_id','configuration_id','kind','arm','probe_arm','r10_joint','pre_disclosure_rerate_joint']],on='trial_id',validate='one_to_one');pt['all12_match']=pt.matches.eq(12);pt['all12_determinate']=(pt.matches+pt.mismatches).eq(12);pt.to_csv(out/'probe_trial_outcomes.csv',index=False)
        pt.groupby(['configuration_id','kind','arm','probe_arm','r10_joint'],dropna=False).agg(conversations=('trial_id','size'),all12_match=('all12_match','sum'),all12_determinate=('all12_determinate','sum'),any_uncertain=('uncertain',lambda s:s.gt(0).sum()),any_unparseable=('unparseable',lambda s:s.gt(0).sum()),any_missing=('missing',lambda s:s.gt(0).sum())).reset_index().to_csv(out/'probe_by_prior_joint_and_arm.csv',index=False)
    if 'pre_disclosure_rerate_joint' in primary.columns:
        primary.groupby(['configuration_id','kind','arm','probe_arm','r10_joint','pre_disclosure_rerate_joint'],dropna=False).size().rename('conversations').reset_index().to_csv(out/'terminal_rerating.csv',index=False)
    # Prespecified same-case A-arm additional runs: preserve case and session, and
    # never count pairwise comparisons as independent case families.
    rep=t[t.arm.eq('A')].groupby(['configuration_id','kind','case_id'],dropna=False).filter(lambda q:q.replicate.nunique()>1)
    if not rep.empty:
        repeated=rep.groupby(['configuration_id','kind','case_id'],dropna=False).agg(sessions=('trial_id','size'),valid_joint=('r10_joint','count'),joint_yes=('r10_joint','sum'),joint_min=('r10_joint','min'),joint_max=('r10_joint','max')).reset_index();repeated['joint_discordance']=np.where(repeated.valid_joint.ge(2),repeated.joint_min.ne(repeated.joint_max),np.nan);repeated.to_csv(out/'same_case_repeats.csv',index=False)
    coverage=primary.groupby(['configuration_id','arm','kind','status'],dropna=False).agg(n=('trial_id','size'),received_calls=('calls_received','sum'),pending=('pending','sum'),compaction_events=('compaction_events','sum'),sessions_with_detected_compaction=('compaction_events',lambda s:s.gt(0).sum())).reset_index();coverage.to_csv(out/'completion_coverage.csv',index=False)
    # Plot only data actually observed, never synthesize zero observations.
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    sm=summarized_rows(primary);fig,axs=plt.subplots(1,3,figsize=(15,4.7),layout='constrained',sharey=True)
    for ax,kind in zip(axs,['obj','seq','unforced']):
        q=sm[sm.kind.eq(kind)];
        for cfg,g in q.groupby('configuration_id'):
            g=g.set_index('arm').reindex(['A','J','P','K','JS','N','R','F']);ax.plot(range(8),100*g.joint_rate,marker='o',label=cfg)
        ax.set_xticks(range(8),['A','J','P','K','JS','N','R','F']);ax.set_title(kind);ax.set_ylim(0,100);ax.set_xlabel('Arm')
    axs[0].set_ylabel('Round-10 1/no (%) among interpretable reports');h,l=axs[0].get_legend_handles_labels();fig.legend(h,l,loc='outside lower center',ncol=2,frameon=False);fig.suptitle('Exploratory: 12 cases/cell; missing values excluded, see coverage',fontsize=11);fig.savefig(out/'01_round10_arms.png',dpi=150);plt.close(fig)
    if not r.empty:
        fig,axs=plt.subplots(1,3,figsize=(15,4.7),layout='constrained',sharey=True)
        for ax,kind in zip(axs,['obj','seq','unforced']):
            q=r[r.kind.eq(kind)&r.arm.eq('J')].groupby(['configuration_id','round']).agg(risk=('first_risk_eligible','sum'),events=('first_onset','sum')).reset_index()
            for cfg,g in q.groupby('configuration_id'):ax.plot(g['round'],100*g.events/g.risk.replace(0,np.nan),marker='o',label=cfg)
            ax.set_title(kind);ax.set_xlabel('Round');ax.set_xticks([1,3,5,7,10]);ax.set_ylim(0,100)
        axs[0].set_ylabel('First 1/no risk (%) among complete observed prefixes');h,l=axs[0].get_legend_handles_labels();fig.legend(h,l,loc='outside lower center',ncol=2,frameon=False);fig.suptitle('Neutral JSON arm J; changing risk set; no R onset estimate',fontsize=11);fig.savefig(out/'02_first_onset.png',dpi=150);plt.close(fig)
    if not p.empty:
        q=p.groupby(['kind','component','status']).size().unstack(fill_value=0);fig,axs=plt.subplots(1,3,figsize=(13,4.5),layout='constrained',sharey=True)
        colors={'match':'#377ea5','mismatch':'#d86743','uncertain':'#e5ac3d','unparseable':'#858585','ambiguous':'#b49bbf','missing':'#dddddd'}
        for ax,kind in zip(axs,['obj','seq','unforced']):
            if kind not in q.index.get_level_values(0):continue
            z=q.loc[kind].reindex(FIELDS).fillna(0);bottom=np.zeros(len(z));total=z.sum(axis=1).replace(0,np.nan)
            for category,color in colors.items():
                v=100*z.get(category,0)/total;ax.bar(np.arange(len(z)),v,bottom=bottom,label=category,color=color);bottom+=v.fillna(0).to_numpy()
            ax.set_xticks(range(3),['First\nfeedback','Second\nfeedback','Final\nobject']);ax.set_title(kind);ax.set_ylim(0,100)
        axs[0].set_ylabel('Components (%) — repeated components within session');h,l=axs[0].get_legend_handles_labels();fig.legend(h,l,loc='outside lower center',ncol=3,frameon=False);fig.suptitle('Generator agreement after explanation OR neutral prompt',fontsize=11);fig.savefig(out/'03_probe_components.png',dpi=150);plt.close(fig)
    contrasts=contrast_bootstrap(primary); contrasts=contrasts[contrasts.matched_case_families.gt(0)]
    if not contrasts.empty:
        contrasts=contrasts.assign(group=contrasts.configuration_id+' | '+contrasts.kind)
        matrix=contrasts.pivot(index='group',columns='comparison',values='difference');counts=contrasts.pivot(index='group',columns='comparison',values='matched_case_families').reindex_like(matrix)
        fig,ax=plt.subplots(figsize=(12,max(4,.42*len(matrix))),layout='constrained');im=ax.imshow(matrix,aspect='auto',vmin=-1,vmax=1,cmap='RdBu_r');ax.set_xticks(range(len(matrix.columns)),matrix.columns,rotation=25,ha='right');ax.set_yticks(range(len(matrix)),matrix.index)
        for i in range(len(matrix)):
            for j in range(len(matrix.columns)):
                v=matrix.iloc[i,j];n=counts.iloc[i,j]
                if pd.notna(v):ax.text(j,i,f'{v:+.2f}\nn={int(n)}',ha='center',va='center',fontsize=7)
        fig.colorbar(im,ax=ax,label='Difference in joint-report rate');ax.set_title('Paired-arm difference, valid matched case families; exploratory',loc='left',weight='bold');fig.savefig(out/'04_paired_contrasts.png',dpi=150);plt.close(fig)
    md={'run_id':run_id,'manifest_sha256':sha(manifest),'analysis_script_sha256':sha(__file__),'protocol_sha256':sha(Path(__file__).with_name('protocol.py')),'prompts_sha256':sha(Path(__file__).with_name('prompts.json')),'state_sha256':hashes,'freeze_sha256':next(iter(freezes),None),'assigned':len(assigned),'complete':int(t.status.eq('complete').sum()),'unstarted':int(t.status.eq('unstarted').sum()),'primary_assigned':len(primary),'repeat_assigned':int(t.replicate.ne(1).sum()),'received_native_calls':int(t.calls_received.sum()),'pending_reservations':int(t.pending.sum()),'compaction_events':int(t.compaction_events.sum()),'sessions_with_detected_compaction':int(t.compaction_events.gt(0).sum()),'recovered_transport_turns':int(t.recovered_transport_turns.sum()),'recovered_transport_events':int(t.recovered_transport_events.sum()),'https_fallback_calls':int(t.https_fallback_calls.sum()),'sessions_with_recovery':int(t.has_recovered_transport.sum()),'recovery_metadata_missing_turns':int(t.recovery_metadata_missing_turns.sum()),'duration_observed_calls':int(t.duration_observed_calls.sum()),'duration_seconds_total':float(t.duration_seconds_total.sum()),'transport_limitation':'Recovery counts and duration derive from recorded calls only; missing recovery fields default to false but are separately counted, pending attempts are excluded, and billing/provider requests cannot be inferred. No-recovery sensitivity is descriptive and conditions on a postassignment event.','compaction_limitation':'Only explicitly reported native event types containing compact are counted; absent events do not prove that all history was retained.','no_model_calls':True,'bootstrap':'5000 case-family paired bootstrap, pointwise exploratory, no inference of equivalence or complete data; valid matched cases only','first_onset':'requires all previous rounds measured and no earlier 1/no; R is structurally undefined; unknown cannot be bridged','probe':'policy assigned before target exposure; backend gold uses actual generator; 12 components repeated within conversation','interpretation':'1/no is a report, not direct SOA or model knowledge. Explanation question changes subsequent prediction. Small sample/prompt panel, no generalization or equivalence claim.','versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__}}
    (out/'analysis_manifest.json').write_text(json.dumps(md,indent=2,ensure_ascii=False)+'\n')
    base=sm[(sm.arm.eq('J')) & sm.joint_valid.gt(0)]
    basic='\n'.join(f"| {v.configuration_id} | {v.kind} | {int(v.joint_yes)}/{int(v.joint_valid)} | {int(v.assigned)} |" for v in base.itertuples())
    if not basic:basic='| 아직 관측 없음 | — | — | — |'
    report=f"# 실험 7-pre: 탐색적 분석\n\n배정 {len(t)}대화 중 complete {md['complete']}, unstarted {md['unstarted']}, 기록된 수신 호출 {md['received_native_calls']}이다. 명시적 compaction 이벤트 {md['compaction_events']}회, 영향을 받은 대화 {md['sessions_with_detected_compaction']}개다. 기록된 이벤트가 없더라도 전체 과거 문맥이 온전히 유지됐다고 보장하지 않는다. 재시도/미확인 예약은 별도 상태·예산 원본에서 확인한다. 본 분석은 모델을 호출하지 않았다.\n\n## 기본 J 팔 10라운드\n\n| 모델×effort | 조건 | 1/no / 판독 가능 | 배정 |\n|---|---|---:|---:|\n{basic}\n\n`profile_arm_condition.csv`는 나머지 팔·세 지표 및 유효분모, `arm_paired_contrasts.csv`와 `arm_difference_in_differences.csv`는 같은 case family 짝 비교다. 12 case/cell의 5,000회 사례군 bootstrap 구간은 탐색적 pointwise 구간이며 동등성을 보여주지 않는다. 특히 관측된 차이가 모두 0이면 구간이 [0,0]으로 퇴화할 수 있으나 차이 없음의 증거가 아니다. 결측을 0으로 넣지 않았다.\n\n`round_outcomes.csv`는 동일 대화의 라운드 반복이며 첫 사건 위험집합은 모든 이전 라운드가 관측되었고 사건이 없을 때만 구성한다. R의 1–9라운드는 구조적 미측정으로 첫 사건 시점은 정의되지 않는다. 중립 확인 호출의 수신은 판단 응답의 수신이 아니다.\n\n`probe_components.csv`는 generator 일치/명시 불일치/불확실/모호/판독불가/미수신을 따로 기록한다. `observed_path`는 같은 pair와 single이 이전 어느 라운드에서라도 선택되었음을 뜻하며, 변화 시퀀스에서 같은 feedback이나 목표가 관측됐다는 의미는 아니다. 12성분은 대화 안에 반복되고 설명 질문은 후속 평가를 변화시킬 수 있다. `probe_comparison_baselines.csv`의 항상 keep 및 이전 최종 결과 반복은 단순 베이스라인이다. 그 `baseline_eligible`은 성공적으로 예측 호출을 받은 성분을 기준으로 하며 실제 답이 uncertain 또는 판독불가인 성분도 포함할 수 있으므로 모델 유효답 분모와 구분한다. 특히 강제 조건에서 최종 결과 4개를 맞혀도 규칙 이해를 입증하지 않는다. `same_case_repeats.csv`는 재실행 변동을 기술하고 새로운 case family로 세지 않는다.\n\n이 연구는 일부 프로파일·프롬프트에서의 보고와 예측에 관한 것이다. 실험적 조건·선택의 상호작용과 소표본 때문에 주관적 SoA, 내부 신념, 24개 전체 조합 일반화 또는 0차이 동등성을 주장하지 않는다.\n"
    report+=f"\n명시적으로 복구된 native 호출은 {md['recovered_transport_turns']}회, 관찰된 해당 이벤트는 {md['recovered_transport_events']}개, 복구가 있었던 세션은 {md['sessions_with_recovery']}개다. 복구 메타데이터가 없는 기록 턴은 {md['recovery_metadata_missing_turns']}개이며 예전 기록은 복구 없음으로 기본 처리하되 미기록 수를 별도 표시했다. `transport_recovery_by_profile_arm_condition.csv`에 기록된 native 호출만의 지연시간·비율을 저장했다. `r10_recovery_sensitivity.csv`는 전체와 복구 호출이 관측된 세션을 제외한 10라운드 기술 통계를 별도 표시한다. 후자는 배정 후 발생한 사유에 따른 선택이라 인과 효과가 아니며 1차 전체 결과를 대체하지 않는다. provider 재시도 횟수나 과금은 유추할 수 없다.\n"
    (out/'REPORT.ko.md').write_text(report)
    return md

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--manifest',required=True);a.add_argument('--states',required=True);a.add_argument('--output',required=True);a.add_argument('--allow-calibration',action='store_true');args=a.parse_args();print(json.dumps(run(args.manifest,args.states,args.output,args.allow_calibration),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
