"""Offline illustrative recovery check using legal choices and forced targets.

This is a narrow feasibility check, not a sample-size guarantee. No inference
or empirical response data are used. Development/holdout stays case-disjoint.
"""
import json
import math
import random
import numpy as np
from scipy.special import expit
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from exp7_pre.protocol import operate_step
from .features import risk_rows
from .schedule import build


def trajectories(seed=2026111502):
    _, trials = build()
    rng = random.Random(seed)
    rows = []
    for t in trials:
        rounds, turns = [], []
        for i in range(1, 11):
            first = rng.sample(t['order'], 2)
            remain, a = operate_step(t, i, 1, t['order'], first)
            second = rng.choice(remain)
            final, b = operate_step(t, i, 2, remain, [second])
            rounds.append({'round': i, 'route': a+b, 'final': final[0]})
            turns.append({'turn': 3*i, 'parsed': {'impact': 100, 'counterfactual': 'yes'}})
        generated, reason = risk_rows({'trial': t, 'rounds': rounds, 'turns': turns})
        if reason != 'ten_rounds_observed':
            raise ValueError('Generated invalid trajectory')
        rows.extend(generated)
    return rows


def run(seed=2026111503):
    rows = trajectories()
    category = np.array([[f"{r['model']}|{r['effort']}|{r['game']}"] for r in rows], dtype=object)
    games = np.array([r['game'] for r in rows])
    numeric = np.array([[r['round'], r['cumulative_kd_surprisal_bits'],
                         r['same_result_run_length']] for r in rows], dtype=float)
    holdout = np.array([r['split'] == 'holdout' for r in rows])
    trial_ids = np.array([r['trial_id'] for r in rows])
    out = []
    scenarios = [('time_only', 0.0, 0.0), ('kd_signal', 1.0, 0.0),
                 ('repeat_signal', 0.0, 0.7), ('combined_signal', 1.0, 0.7)]
    for scenario, beta, repeat_beta in scenarios:
        rng = np.random.default_rng(seed)
        logit = np.where(games == 'obj', -3.2, -6.8)
        logit += 0.15 * (numeric[:, 0] - 5.5) / 2.9
        logit += beta * (numeric[:, 1] - 10.0) / 5.0
        logit += repeat_beta * (numeric[:, 2] - 1.0) / 3.0
        draws = rng.random(len(rows)) < expit(logit)
        active = np.ones(len(rows), dtype=bool)
        seen = set()
        for i, (ident, event) in enumerate(zip(trial_ids, draws)):
            if ident in seen:
                active[i] = False
            elif event:
                seen.add(ident)
        encoder = OneHotEncoder(handle_unknown='ignore')
        cat_train = encoder.fit_transform(category[active & ~holdout])
        cat_test = encoder.transform(category[active & holdout])
        scaler = StandardScaler().fit(numeric[active & ~holdout])
        train_num = scaler.transform(numeric[active & ~holdout])
        test_num = scaler.transform(numeric[active & holdout])
        y_train, y_test = draws[active & ~holdout], draws[active & holdout]
        losses = {}
        for name, cols in [('time', [0]), ('kd', [0, 1]),
                           ('repeat', [0, 2]), ('combined', [0, 1, 2])]:
            model = LogisticRegression(C=1, solver='liblinear', max_iter=1000)
            model.fit(hstack([cat_train, csr_matrix(train_num[:, cols])]), y_train)
            p = model.predict_proba(hstack([cat_test, csr_matrix(test_num[:, cols])]))[:, 1]
            losses[name] = log_loss(y_test, p, labels=[False, True])
        seq_test = games[active & holdout] == 'seq'
        out.append({'scenario': scenario, 'kd_logit_coefficient_on_prespecified_scale': beta,
                    'repeat_logit_coefficient_on_prespecified_scale': repeat_beta,
                    'training_events': int(y_train.sum()), 'holdout_events': int(y_test.sum()),
                    'holdout_seq_events': int(y_test[seq_test].sum()),
                    'holdout_log_loss': losses,
                    'improvement_kd_over_time': losses['time']-losses['kd']})
    return {'seed': seed, 'trajectory_seed': 2026111502, 'sessions': len(rows)//10,
            'scope': 'one synthetic draw per scenario, random legal choices, not a power estimate',
            'results': out}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
