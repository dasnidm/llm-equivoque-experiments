"""One chronological K/D stream with Bayesian transition learning per dialogue.

Every transition context has Beta(1,1) prior. Round boundaries never reset the
state. The outcome repetition and a response threshold are not modelled here.
"""
from pathlib import Path
import gzip,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables'
OUT=HERE/'temporal_kd_model';OUT.mkdir(exist_ok=True)
ratings=pd.read_csv(BASE/'measurements.csv')
choices=pd.read_csv(BASE/'choices.csv')
assert choices.groupby(['trial_id','round']).size().eq(2).all()
assert choices.groupby(['trial_id','round']).route.nunique().eq(1).all()
choice=choices[choices.stage.eq(1)][['trial_id','round','route','target_position']]
df=ratings.merge(choice,on=['trial_id','round'],validate='one_to_one').sort_values(['trial_id','round'])
assert len(df)==25200 and df.trial_id.nunique()==2520
assert df.route.str.fullmatch('[KD]{2}').all()
assert df.groupby('trial_id').round.agg(list).apply(lambda v:v==list(range(1,11))).all()

def step(previous,symbol,counts):
    """Predict before observing label, then update the previous-label row."""
    if previous is None:
        return .5,0.,0.,0
    k,d=counts[previous]['K'],counts[previous]['D']
    probability=(1+counts[previous][symbol])/(2+k+d)
    surprise=-np.log2(probability)
    # Optional alternative: penalties only for strictly less expected labels.
    violation=(1-probability) if probability < .5 else 0.
    switch=int(previous!=symbol)
    counts[previous][symbol]+=1
    return probability,surprise,violation,switch

def check_example():
    counts={a:{b:0 for b in 'KD'} for a in 'KD'}
    prev=None;probabilities=[];switches=0;D=0.
    for label in 'KKDDDD':
        p,s,v,sw=step(prev,label,counts); probabilities.append(p);switches+=sw;D+=s;prev=label
    assert np.allclose(probabilities,[.5,.5,1/3,.5,2/3,3/4])
    assert switches==1 and np.isclose(D,4.584962500721156)
    assert np.isclose((1+counts['D']['D'])/(2+sum(counts['D'].values())),.8)
check_example()

records=[]
for _,g in df.groupby('trial_id',sort=False):
    counts={a:{b:0 for b in 'KD'} for a in 'KD'}
    prev=None;switches=0;D=0.;V=0.;had_event=False
    for r in g.itertuples(index=False):
        probs=[];surprises=[];violations=[];switch_steps=[]
        for symbol in r.route:
            p,s,v,sw=step(prev,symbol,counts)
            probs.append(p);surprises.append(s);violations.append(v);switch_steps.append(sw)
            D+=s;V+=v;switches+=sw;prev=symbol
        pk_after_k=(1+counts['K']['K'])/(2+sum(counts['K'].values()))
        pd_after_d=(1+counts['D']['D'])/(2+sum(counts['D'].values()))
        records.append(dict(trial_id=r.trial_id,case_id=r.case_id,
            configuration_id=r.configuration_id,model=r.model,effort=r.effort,
            kind=r.kind,frame=r.frame,round=r.round,route=r.route,
            p_first=probs[0],p_second=probs[1],
            surprise_first_bits=surprises[0],surprise_second_bits=surprises[1],
            cumulative_surprise_bits=D,cumulative_violation=V,
            switch_first=switch_steps[0],switch_second=switch_steps[1],cumulative_switches=switches,
            count_KK=counts['K']['K'],count_KD=counts['K']['D'],
            count_DK=counts['D']['K'],count_DD=counts['D']['D'],
            p_K_given_K=pk_after_k,p_D_given_D=pd_after_d,
            final_position=int(r.target_position),
            freedom=int(r.freedom),impact=int(r.impact),counterfactual=r.counterfactual,
            joint=int(r.joint),first_event=bool(r.joint) and not had_event,already_event=had_event))
        had_event=had_event or bool(r.joint)
data=pd.DataFrame(records)
assert len(data)==25200 and data.first_event.sum()==342
assert data.groupby(['configuration_id','kind','frame']).trial_id.nunique().eq(30).all()
assert data.groupby('trial_id').cumulative_surprise_bits.diff().dropna().ge(-1e-12).all()
with (OUT/'temporal_kd_rounds.csv.gz').open('wb') as f:
    with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:
        z.write(data.to_csv(index=False,lineterminator='\n').encode())
stats={'conversations':int(data.trial_id.nunique()),'rounds':len(data),
       'first_events':int(data.first_event.sum()),
       'max_surprisal_bits':float(data.cumulative_surprise_bits.max()),
       'max_violation':float(data.cumulative_violation.max()),
       'switch_count_kkdddd':1,'kkdddd_D_bits':4.584962500721156,
       'kkdddd_next_D_probability':.8}
(OUT/'summary.json').write_text(json.dumps(stats,indent=2)+'\n',encoding='utf-8')
print(json.dumps(stats,indent=2))
