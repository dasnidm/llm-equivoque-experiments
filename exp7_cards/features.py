"""Construct event-at-risk rows from an offline or collected runner state.

Features are descriptive candidate inputs, not an estimate of an LLM's belief.
Missing reports end the observable first-event interval and are never zeros.
This module makes no model calls and does not fit a statistical model.
"""
import math


def risk_rows(state):
    trial = state['trial']
    if trial.get('kind') not in ('obj', 'seq') or trial.get('n_rounds') != 10:
        raise ValueError('Expected a ten-round obj/seq trial')
    turns = {r['turn']: r for r in state['turns']}
    counts = {'KK': 0, 'KD': 0, 'DK': 0, 'DD': 0}
    previous = None
    previous_final = None
    cumulative = 0.0
    run_length = 0
    rows = []
    reason = 'ten_rounds_observed'
    for expected, rnd in enumerate(state['rounds'], 1):
        i = rnd['round']
        if i != expected or i > 10:
            raise ValueError('Rounds must be sequential and within the ten-round study')
        report = turns.get(3 * i, {}).get('parsed', {})
        if (len(rnd.get('route', '')) != 2 or any(x not in 'KD' for x in rnd['route'])
                or rnd.get('final') not in trial['order']
                or report.get('impact') not in range(1, 101)
                or isinstance(report.get('impact'), bool)
                or report.get('counterfactual') not in ('yes', 'no')):
            reason = 'missing_or_invalid_round'
            break
        surprises = []
        for symbol in rnd['route']:
            if previous is not None:
                total = counts[previous + 'K'] + counts[previous + 'D']
                p = (counts[previous + symbol] + 1) / (total + 2)
                surprises.append(-math.log2(p))
                cumulative += surprises[-1]
                counts[previous + symbol] += 1
            previous = symbol
        final = rnd['final']
        run_length = run_length + 1 if final == previous_final else 1
        previous_final = final
        event = int(report['impact'] == 1 and report['counterfactual'] == 'no')
        rows.append({'trial_id': trial['trial_id'], 'case_id': trial['case_id'],
                     'model': trial['model'], 'effort': trial['effort'],
                     'game': trial['game'], 'split': trial['split'], 'fold': trial['fold'],
                     'round': i, 'cumulative_kd_surprisal_bits': cumulative,
                     'round_kd_surprisal_bits': sum(surprises),
                     'same_result_run_length': run_length, 'first_joint_report': event})
        if event:
            reason = 'first_joint_report'
            break
    if reason == 'ten_rounds_observed' and len(rows) < 10:
        reason = 'missing_or_invalid_round'
    return rows, reason
