"""Read-only scope/round-length scenarios, not an executable study allocation."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/data/exp7-english-curve-resources-20261108'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/assignments.jsonl.gz'
    counts = Counter()
    with gzip.open(manifest, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            counts[(row['arm'], row['model'])] += 1
    english = sum(n for (arm, _), n in counts.items() if arm in ('en_schema', 'en_natural'))
    r_sessions = sum(n for (arm, _), n in counts.items() if arm == 'R_A')
    assert english == 34560 and r_sessions == 8736
    prices_path = ROOT / 'docs/data/exp7-api-cost-20261108/prices.json'
    prices = json.loads(prices_path.read_text())['models']
    paths = list(Path('/workspace/work/exp7-unpaced-retry-20261108-v1').glob('p*-unpaced/states/*.json'))
    eight = Path('/workspace/work/exp7-cli-upgrade-20261108/stable-i-models8-rpm160-p8/states')
    paths += [p for p in eight.glob('*.json')
              if json.loads(p.read_text())['trial']['model'] not in ('gpt-6-astra', 'gpt-5.6-sol')]
    samples = defaultdict(list)
    for path in paths:
        row = json.loads(path.read_text())
        assert len(row['turns']) == 34 and all(t['ok'] for t in row['turns'])
        samples[row['trial']['model']].append(row)
    credit_models = {}
    for model, rows in samples.items():
        rates = prices[model]['usd_per_million_tokens']
        n = len(rows)
        round_inputs, round_outputs = np.zeros(10), np.zeros(10)
        inputs = cached = outputs = 0
        for row in rows:
            for key in ('input_tokens', 'cached_input_tokens', 'output_tokens'):
                assert sum(t['usage_last'][key] for t in row['turns']) == row['turns'][-1]['usage'][key]
            for turn in row['turns']:
                usage = turn['usage_last']
                inputs += usage['input_tokens']; cached += usage['cached_input_tokens']; outputs += usage['output_tokens']
                if turn['turn'] <= 30:
                    index = (turn['turn'] - 1) // 3
                    round_inputs[index] += usage['input_tokens'] / n
                    round_outputs[index] += usage['output_tokens'] / n
        slope = max(0., float(np.polyfit(np.arange(1, 11), round_inputs, 1)[0]))
        hit_rate = cached / inputs
        effective_input_price = (1-hit_rate)*rates['input'] + hit_rate*rates['cached_input']
        # These models' observed Standard credit rates equal 25 times the USD token rates.
        # This is rate-card arithmetic, not conversion/transfer of the user's balance.
        base = ((inputs-cached)*rates['input'] + cached*rates['cached_input'] + outputs*rates['output']) / n / 1e6 * 25
        projections = {}
        for rounds in (10, 15, 20):
            extra_inputs = sum(float(round_inputs[-1]) + slope*j for j in range(1, rounds-9))
            # Four final responses are delayed; add the mean per-call history growth.
            extra_inputs += 4 / 3 * slope * (rounds - 10)
            extra_outputs = (rounds - 10) * float(round_outputs.mean())
            projections[str(rounds)] = {
                'constant_cost_per_call_credits': base * (3*rounds+4) / 34,
                'linear_history_growth_credits': base + (extra_inputs*effective_input_price + extra_outputs*rates['output'])/1e6*25,
            }
        credit_models[model] = {'observed_conversations': n, 'observed_cache_fraction': hit_rate,
                                'round_input_token_slope': slope, 'projections_per_conversation': projections}
    scenarios = []
    for rounds, core_n in ((10,120), (15,120), (20,120), (10,200)):
        # 8 models x 3 efforts x 2 frames x 2 formats; 2 core games and 4 controls.
        main_n = 8*3*2*2*(2*core_n+4*30)
        total_n = main_n + r_sessions
        calls = total_n * (3*rounds+4)
        credits = {key: sum(v['projections_per_conversation'][str(rounds)][key] for v in credit_models.values()) * (total_n/8)
                   for key in ('constant_cost_per_call_credits','linear_history_growth_credits')}
        scenarios.append({'rounds': rounds, 'core_n_per_cell': core_n, 'fixed_rule_n_per_cell':30,
                          'main_conversations': main_n, 'R_conversations': r_sessions, 'total_conversations': total_n,
                          'calls_per_conversation':3*rounds+4, 'calls_with_R': calls,
                          'calls_without_R': main_n*(3*rounds+4),
                          'days_at_100_with_R':calls/144000, 'days_at_100_without_R': main_n*(3*rounds+4)/144000,
                          'days_at_80_percent_uptime_with_R':calls/115200,
                          'standard_codex_credit_scenarios_excluding_included_allowance':credits})
    events = defaultdict(Counter)
    for path in (ROOT/'results/equivoque-2026-10-12-sequence-replication-v1').glob('worker-*/trials/*.json'):
        record = json.loads(path.read_text())
        ratings = [t['parsed'] for t in record['turns'][:30] if t['local_turn']==3]
        assert len(ratings)==10
        group = events[record['trial']['kind']]; group['conversations'] += 1
        valid = all(type(x.get('impact')) is int and 1<=x['impact']<=100 and x.get('counterfactual') in ('yes','no') for x in ratings)
        if not valid:
            group['invalid_prefix'] += 1
            continue
        flags = [x['impact']==1 and x['counterfactual']=='no' for x in ratings]
        group['round10_joint'] += flags[-1]
        if any(flags):
            first = flags.index(True)+1
            group['ever_joint'] += 1; group['first_round_'+str(first)] += 1
            group['first_round_8_to_10'] += first>=8
        else:
            group['none_by_round10'] += 1
    old_cost = ROOT/'docs/data/exp7-api-cost-20261108/estimate.json'
    old_sources = json.loads(old_cost.read_text())['source_digests']
    result = {'status':'proposal_and_resource_estimate_only', 'new_model_calls':0,
              'new_manifest_created':False, 'frozen_design_changed':False,
              'manifest_sha256':digest(manifest), 'prices_sha256':digest(prices_path),
              'previous_token_source_digests':old_sources,
              'credit_rate_source':'https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing',
              'scenarios':scenarios, 'credit_projection_models':credit_models, 'Exp5_first_joint_reports':events,
              'assumptions':[
                  'R remains the existing single English/schema condition; its final rating moves to the proposed endpoint. It is not duplicated for English natural language.',
                  'Each proposed control and R conversation has the same round length as the main conversations.',
                  '100 successful calls/minute includes retry waits; 80% uptime adds other operational downtime.',
                  'Throughput for all efforts and rounds 11+ is not measured. Same-account VMs are not assumed to multiply capacity.',
                  'Credit scenarios are not confidence bounds. Current English/schema/medium usage is a proxy for all profiles/formats/games.',
                  'History-growth sensitivity extrapolates round-input slope, fixes cache fraction and mean output per added round, and shifts four final turns.',
                  'Codex cache writes are free under the cited card. Included plan allowance, future resets and other work are excluded.',
                  'Changing rounds requires new protocol, target schedule, allocation, analysis contract and freeze; current frozen source rejects rounds other than 10.',
              ]}
    (OUT/'scenarios.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'scenarios':scenarios,'first_joint_reports':events},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
