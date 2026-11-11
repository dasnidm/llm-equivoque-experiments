"""Exploratory belief update: no response threshold, no fitted parameters.

Task-specific hypotheses and likelihoods are discussed in the chat. Run after
experiment 5's archived choices/measurements have been made available locally.
The varying-target hypothesis is iid uniform, not the actual balanced schedule.
"""
import numpy as np
import pandas as pd
import os
from pathlib import Path

folder = Path(__file__).resolve().parent
root = folder.parents[2]
base = root / 'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables'
out = folder
choices = pd.read_csv(base / 'choices.csv')
measures = pd.read_csv(base / 'measurements.csv')
assert choices.groupby(['trial_id', 'round']).size().eq(2).all()
assert choices.groupby(['trial_id', 'round']).route.nunique().eq(1).all()
assert choices.groupby(['trial_id', 'round']).target_position.nunique().eq(1).all()
route = choices[choices.stage.eq(1)][['trial_id','round','route','target_position']]
df = measures.merge(route, on=['trial_id','round'], validate='one_to_one').sort_values(['trial_id','round'])
assert df.groupby('trial_id').round.agg(list).apply(lambda x: x == list(range(1,11))).all()
assert df.route.str.fullmatch('[KD]{2}').all()

rows = []
epsilon = float(os.environ.get('EXP7_EPSILON','0.05'))
suffix = os.environ.get('EXP7_SUFFIX','')
for _, group in df.groupby('trial_id', sort=False):
    # Model priors: equal prior weights for constant target, uniform variable
    # target, and selection-dependent K/D with learned transitions.
    weights = np.array([1.,1.,1.]) / 3
    target_belief = np.full(4, 0.25)
    # Rows: stage 1 depends on last round's stage-1 K/D; stage 2 depends
    # on current round's stage-1 K/D. Each context has Beta(1,1) prior.
    counts = {(stage, previous): np.array([1., 1.])
              for stage in (1,2) for previous in ('K','D')}
    previous_first = None
    seen_first = False
    for r in group.itertuples(index=False):
        target = int(r.target_position) - 1
        assert 0 <= target < 4
        first, second = r.route
        first_p = .5 if previous_first is None else counts[(1,previous_first)][0] / counts[(1,previous_first)].sum()
        second_p = counts[(2,first)][0] / counts[(2,first)].sum()
        h_stable = (first_p if first == 'K' else 1-first_p) * (second_p if second == 'K' else 1-second_p)
        # The observed stage choices and K/D feedback determine the final item;
        # consequently one must not multiply a second outcome likelihood.
        h_obj = (1-epsilon)*target_belief[target] + epsilon/4
        h_seq = .25
        weights *= np.array([h_obj, h_seq, h_stable])
        weights /= weights.sum()
        evidence = np.full(4,epsilon/4)
        evidence[target] += 1-epsilon
        target_belief *= evidence
        target_belief /= target_belief.sum()
        if previous_first is not None:
            counts[(1,previous_first)][0 if first == 'K' else 1] += 1
        counts[(2,first)][0 if second == 'K' else 1] += 1
        previous_first = first
        rows.append(dict(trial_id=r.trial_id, case_id=r.case_id,
                         configuration_id=r.configuration_id, frame=r.frame,
                         kind=r.kind, round=r.round, route=r.route,
                         final_position=target+1, joint=int(r.joint),
                         previously_joint=seen_first,
                         p_obj=weights[0], p_seq=weights[1], p_stable=weights[2],
                         p_forced=weights[0]+weights[1],
                         likelihood_obj=h_obj, likelihood_seq=h_seq,
                         likelihood_stable=h_stable))
        seen_first |= bool(r.joint)

res = pd.DataFrame(rows)
assert np.allclose(res[['p_obj','p_seq','p_stable']].sum(axis=1),1)
res.to_csv(out/f'bayesian_posterior_by_round{suffix}.csv',index=False)
print('rows',len(res),'conversations',res.trial_id.nunique())
for kind in ['obj','seq']:
 for t in [1,3,5,10]:
  x=res[(res.kind==kind)&(res['round']==t)]
  print(kind,t,'p_obj median',round(x.p_obj.median(),4),'mean',round(x.p_obj.mean(),4),'p_forced median',round(x.p_forced.median(),4),'joint n',int(x.joint.sum()))
print('epsilon',epsilon,'equal priors','K/D transition probabilities independently Beta(1,1)')
