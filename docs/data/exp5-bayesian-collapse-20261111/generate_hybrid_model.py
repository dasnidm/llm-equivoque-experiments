"""Exploratory hybrid: switch hypotheses, accumulated surprise, response model.

All modelling assumptions and limitations are documented in hybrid_model/README.md.
This script reads only experiment 5's published tables and makes no model calls.
"""
from pathlib import Path
import gzip,json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.model_selection import GroupKFold
from sklearn.metrics import log_loss,brier_score_loss

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables'
OUT=HERE/'hybrid_model'
OUT.mkdir(exist_ok=True)
ratings=pd.read_csv(BASE/'measurements.csv')
choices=pd.read_csv(BASE/'choices.csv')
assert not ratings.duplicated(['trial_id','round']).any()
assert choices.groupby(['trial_id','round']).size().eq(2).all()
assert choices.groupby(['trial_id','round']).route.nunique().eq(1).all()
assert choices.groupby(['trial_id','round']).target_position.nunique().eq(1).all()
choice=choices[choices.stage.eq(1)][['trial_id','round','route','target_position']]
df=ratings.merge(choice,on=['trial_id','round'],validate='one_to_one').sort_values(['trial_id','round'])
assert len(df)==25200 and df.trial_id.nunique()==2520
assert df.route.str.fullmatch('[KD]{2}').all()
assert df.groupby('trial_id').round.agg(list).apply(lambda v:v==list(range(1,11))).all()

# 20 K/D feedbacks, 19 potential switch boundaries.
# M=0 initial rule never switches; M=1 switches once; M=2..19 multiple.
# First K/D has 50:50 prior and becomes an anchor. Conditional on M,
# switch positions are sampled uniformly among the 19 boundaries.
n_boundaries=19
ms=np.arange(n_boundaries+1)
initial=np.zeros(n_boundaries+1)
initial[0]=.5;initial[1]=.25;initial[2:]=.25/(n_boundaries-1)
epsilon=.05
rows=[]
for _,g in df.groupby('trial_id',sort=False):
    w=initial.copy();prev=None;seen_boundaries=0;switches=0
    cum_bits=0.;cum_violation=0.;target_belief=np.full(4,.25);outcome_log_bf=0.
    had_event=False
    for r in g.itertuples(index=False):
        step_predictions=[];step_bits=[];step_violation=[];step_switch=[]
        for symbol in r.route:
            if prev is None:
                p=.5;switch=0;bits=0.;violation=0.  # first anchors; excluded from D
            else:
                remaining=n_boundaries-seen_boundaries
                q_m=np.clip((ms-switches)/remaining,0,1)
                q_switch=float(np.dot(w,q_m))
                switch=int(symbol != prev)
                p=q_switch if switch else 1-q_switch
                assert 0 < p <= 1
                bits=-np.log2(p)
                # Violation only if the observed label was strictly less likely
                # than its alternative; ties do not add asymmetric suspicion.
                violation=(1-p) if p<.5 else 0.
                w *= q_m if switch else (1-q_m)
                assert w.sum()>0
                w /= w.sum()
                switches += switch
                seen_boundaries += 1
            prev=symbol;cum_bits+=bits;cum_violation+=violation
            step_predictions.append(p);step_bits.append(bits)
            step_violation.append(violation);step_switch.append(switch)
        # Separate outcome-repeat evidence, never multiplied into D. Each
        # displayed final result equals target_position in this forced study;
        # fixed positions within a conversation make that outcome observable.
        result=int(r.target_position)-1
        assert 0<=result<4
        lik_fixed=(1-epsilon)*target_belief[result]+epsilon/4
        outcome_log_bf += np.log(lik_fixed/.25)
        evidence=np.full(4,epsilon/4);evidence[result]+=1-epsilon
        target_belief*=evidence;target_belief/=target_belief.sum()
        rows.append(dict(trial_id=r.trial_id,case_id=r.case_id,
            configuration_id=r.configuration_id,model=r.model,effort=r.effort,
            kind=r.kind,frame=r.frame,round=r.round,route=r.route,
            p_first=step_predictions[0],p_second=step_predictions[1],
            switch_first=step_switch[0],switch_second=step_switch[1],
            cumulative_switches=switches,
            surprise_first_bits=step_bits[0],surprise_second_bits=step_bits[1],
            round_surprise_bits=sum(step_bits),cumulative_surprise_bits=cum_bits,
            cumulative_violation=cum_violation,
            p_H0=w[0],p_H1=w[1],p_Hmulti=w[2:].sum(),
            final_position=result+1,outcome_log_bf=outcome_log_bf,
            freedom=int(r.freedom),impact=int(r.impact),counterfactual=r.counterfactual,
            joint=int(r.joint),first_event=bool(r.joint) and not had_event,
            already_event=had_event))
        had_event=had_event or bool(r.joint)
data=pd.DataFrame(rows)
assert len(data)==25200 and data.first_event.sum()==342
assert np.allclose(data[['p_H0','p_H1','p_Hmulti']].sum(axis=1),1)
assert data.groupby(['configuration_id','kind','frame']).trial_id.nunique().eq(30).all()
assert data.groupby('trial_id').cumulative_surprise_bits.diff().dropna().ge(-1e-12).all()

# Observation model: first report hazard = sigmoid[k(D-theta)]. This is a
# statistical link to a binary *report*, not a measured subjective SoA.
# Fit positive k; theta is the report model's 50% crossing, not a neural value.
risk=data[~data.already_event].copy().reset_index(drop=True)
folds=list(GroupKFold(5).split(risk,risk.first_event,risk.case_id))

def fit(d,y):
    d=np.asarray(d,float);y=np.asarray(y,float)
    # Fit the convex logit a+k*D; theta=-a/k. The nonlinear (k,theta)
    # parametrisation can get stuck and silently invent spurious thresholds.
    def objective(v):
        a,k=v;z=a+k*d;error=expit(z)-y
        return (float(np.mean(np.logaddexp(0,z)-y*z)),
                np.array([np.mean(error),np.mean(error*d)]))
    result=minimize(objective,[-4.2,.05],jac=True,method='L-BFGS-B',
                    bounds=[(-50,0),(0,10)],options={'ftol':1e-13,'gtol':1e-9,'maxiter':2000})
    if not result.success:raise RuntimeError(result.message)
    a,k=result.x
    return float(a),float(k)

metrics={}
for cov in ['cumulative_surprise_bits','cumulative_violation']:
    pred=np.zeros(len(risk));fold_params=[]
    for tr,te in folds:
        a,k=fit(risk[cov].iloc[tr],risk.first_event.iloc[tr])
        pred[te]=expit(a+k*risk[cov].iloc[te].to_numpy())
        fold_params.append({'intercept':a,'k':k,'theta':float(-a/k) if k>1e-8 else None})
    a,k=fit(risk[cov],risk.first_event)
    risk['pred_'+cov]=pred
    metrics[cov]={'intercept_full_sample':a,'k_full_sample':k,
        'theta_full_sample':float(-a/k) if k>1e-8 else None,
        'folds':fold_params,'heldout_log_loss':float(log_loss(risk.first_event,pred,labels=[0,1])),
        'heldout_brier':float(brier_score_loss(risk.first_event,pred)),
        'observed_range':[float(risk[cov].min()),float(risk[cov].max())]}
    for kind in ['obj','seq']:
        sub=risk.kind.eq(kind)
        metrics[cov][kind]={'rows':int(sub.sum()),'events':int(risk.loc[sub,'first_event'].sum()),
            'heldout_log_loss':float(log_loss(risk.loc[sub,'first_event'],pred[sub],labels=[0,1]))}

pred_round=np.zeros(len(risk));pred_null=np.zeros(len(risk))
for tr,te in folds:
    a,k=fit(risk['round'].iloc[tr],risk.first_event.iloc[tr])
    pred_round[te]=expit(a+k*risk['round'].iloc[te].to_numpy())
    pred_null[te]=risk.first_event.iloc[tr].mean()
metrics['baseline']={'round_only_heldout_log_loss':float(log_loss(risk.first_event,pred_round,labels=[0,1])),
                     'constant_heldout_log_loss':float(log_loss(risk.first_event,pred_null,labels=[0,1]))}

with (OUT/'hybrid_rounds.csv.gz').open('wb') as f:
    with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:
        z.write(data.to_csv(index=False,lineterminator='\n').encode())
with (OUT/'hazard_crossvalidated.csv.gz').open('wb') as f:
    with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:
        z.write(risk[['trial_id','case_id','configuration_id','kind','frame','round','first_event',
                      'pred_cumulative_surprise_bits','pred_cumulative_violation']].to_csv(index=False,lineterminator='\n').encode())
(OUT/'fit_results.json').write_text(json.dumps(metrics,indent=2)+'\n',encoding='utf-8')
print('observations',len(data),'conversations',data.trial_id.nunique(),
      'risk_rows',len(risk),'events',int(data.first_event.sum()))
print(json.dumps(metrics,indent=2))
