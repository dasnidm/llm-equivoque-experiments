"""Reprice retained token usage; no inference or billing calls."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
          'output_tokens', 'reasoning_output_tokens')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def new_group():
    return {'sessions': 0, 'turns': 0, **dict.fromkeys(FIELDS, 0)}


def read_cohort(paths, expected_turns, cumulative_only=False):
    groups, by_effort, hashes, ids = defaultdict(new_group), defaultdict(new_group), [], set()
    for path in sorted(paths):
        content = path.read_bytes()
        record = json.loads(content)
        turns, trial = record['turns'], record['trial']
        assert len(turns) == expected_turns and all(t['ok'] for t in turns), path
        identity = (trial['run_id'], trial['trial_id'])
        assert identity not in ids, identity
        ids.add(identity)
        usage = turns[-1]['usage']
        # Both transports report cumulative usage. Never sum those cumulative totals.
        for key in FIELDS:
            assert all(t['usage'][key] >= 0 for t in turns)
            assert all(b['usage'][key] >= a['usage'][key] for a, b in zip(turns, turns[1:])), (path, key)
            if not cumulative_only:
                assert sum(t['usage_last'][key] for t in turns) == usage[key], (path, key)
        assert usage['cached_input_tokens'] + usage['cache_write_input_tokens'] <= usage['input_tokens']
        assert usage['reasoning_output_tokens'] <= usage['output_tokens']
        for group in (groups[trial['model']], by_effort[trial['model'] + '/' + trial['effort']]):
            group['sessions'] += 1
            group['turns'] += len(turns)
            for key in FIELDS:
                group[key] += usage[key]
        hashes.append({'path': str(path), 'sha256': sha(content)})
    digest = sha(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode())
    return dict(groups), dict(by_effort), {'file_count': len(hashes), 'ordered_source_hashes_sha256': digest}


def price_projection(group, target_turns, prices):
    scale = target_turns / group['turns']
    i, c, w, o = (group[k] * scale for k in FIELDS[:4])
    # CLI records report zero writes here. Direct API cache-write allocation is unknown.
    assert w == 0
    ordinary = i - c
    input_cost = ordinary * prices['input'] / 1e6
    cached_cost = c * prices['cached_input'] / 1e6
    output_cost = o * prices['output'] / 1e6
    base = input_cost + cached_cost + output_cost
    return {
        'target_turns': target_turns,
        'projected_input_tokens': i,
        'projected_cached_input_tokens': c,
        'projected_output_tokens_including_reasoning': o,
        'ordinary_input_usd': input_cost, 'cached_input_usd': cached_cost,
        'output_usd': output_cost,
        'observed_cache_no_write_premium_usd': base,
        'observed_cache_all_noncached_as_30m_write_usd': base + input_cost * .25,
        'zero_cache_no_writes_usd': i * prices['input'] / 1e6 + output_cost,
        'zero_cache_all_input_as_30m_write_usd': i * prices['input'] * 1.25 / 1e6 + output_cost,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unpaced-root', type=Path, default=Path('/workspace/work/exp7-unpaced-retry-20261108-v1'))
    parser.add_argument('--eight-model-root', type=Path, default=Path('/workspace/work/exp7-cli-upgrade-20261108/stable-i-models8-rpm160-p8'))
    parser.add_argument('--output', type=Path, default=REPO / 'docs/data/exp7-api-cost-20261108')
    args = parser.parse_args()
    out = args.output
    prices_path = out / 'prices.json'
    prices = json.loads(prices_path.read_text())
    manifest_path = REPO / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/summary.json'
    manifest = json.loads(manifest_path.read_text())
    latest, latest_efforts, latest_hash = read_cohort(args.unpaced_root.glob('p*-unpaced/states/*.json'), 34)
    eight, eight_efforts, eight_hash = read_cohort((args.eight_model_root / 'states').glob('*.json'), 34)
    old_root = REPO / 'results/equivoque-2026-10-12-sequence-replication-v1'
    old, old_efforts, old_hash = read_cohort(old_root.glob('worker-*/trials/*.json'), 33, cumulative_only=True)
    assert sum(g['turns'] for g in latest.values()) == 2720
    assert sum(g['turns'] for g in eight.values()) == 272
    assert sum(g['turns'] for g in old.values()) == 83160
    selected = dict(eight)
    selected.update(latest)  # Prefer 40 fresh conversations for Astra and 5.6 Sol.
    model_rows = []
    for model, sessions in sorted(manifest['per_model'].items()):
        group = selected[model]
        row = {'model': model, 'planned_sessions': sessions, 'observed': group,
               'usage_source': 'unpaced_80_conversations' if model in latest else 'native_8_model_technical_check',
               'observed_cache_fraction': group['cached_input_tokens'] / group['input_tokens']}
        row.update(price_projection(group, sessions * 34, prices['models'][model]['usd_per_million_tokens']))
        model_rows.append(row)
    money_keys = [k for k in model_rows[0] if k.endswith('_usd')]
    totals = {key: sum(row[key] for row in model_rows) for key in money_keys}
    total_input = sum(row['projected_input_tokens'] for row in model_rows)
    total_output = sum(row['projected_output_tokens_including_reasoning'] for row in model_rows)
    # Historical cross-check: 7 observed models x 3 efforts; Terra 6.1 explicitly stays a current medium proxy.
    historical_rows = []
    for model, sessions in sorted(manifest['per_model'].items()):
        group = old.get(model, selected[model])
        historical_rows.append({'model': model, 'source': 'Exp5_all_three_efforts' if model in old else 'current_medium_proxy_no_Exp5_data',
                                **price_projection(group, sessions * 34, prices['models'][model]['usd_per_million_tokens'])})
    historical_totals = {key: sum(row[key] for row in historical_rows) for key in money_keys}
    result = {
        'date': '2026-11-08', 'new_model_calls': 0, 'actual_api_charges_created': 0,
        'planned_conversations': manifest['conversations'], 'planned_turns': manifest['calls'],
        'prices_sha256': sha(prices_path.read_bytes()),
        'manifest': str(manifest_path.relative_to(REPO)), 'manifest_sha256': sha(manifest_path.read_bytes()),
        'source_digests': {'unpaced': latest_hash, 'eight_model': eight_hash, 'exp5': old_hash},
        'model_rows': model_rows, 'totals_usd': totals,
        'projected_tokens': {'input': total_input, 'output_including_reasoning': total_output},
        'historical_crosscheck': {'models': historical_rows, 'totals_usd': historical_totals, 'exp5_observed_efforts': old_efforts},
        'credit_examples': {str(credit): {
            'fraction_of_full_plan_at_observed_cache': credit / totals['observed_cache_no_write_premium_usd'],
            'balanced_mix_conversations_equivalent': credit / totals['observed_cache_no_write_premium_usd'] * manifest['conversations']
        } for credit in (100, 200, 500)},
        'limitations': [
            'Scenario estimates, not a confidence interval or an API invoice.',
            'Current medium/en_schema/cards/seq token usage is extrapolated to all conditions and efforts; six models have one current conversation each.',
            'Historical cross-check covers seven models at low/medium/high, but different protocol/transport; Terra 6.1 has only the current medium proxy.',
            'Reasoning tokens are already part of output_tokens and are not added again.',
            'CLI cumulative usage is counted once per conversation; usage_last sums checked where available.',
            'Direct API cache-write allocation, cache hit rate, instruction overhead, and output distribution may differ.',
            'Standard short-context prices; no tax, regional uplift, Fast/Ultrafast, technical calls, failures, or price changes included.',
        ],
    }
    (out / 'estimate.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (out / 'model_costs.csv').open('w', newline='') as stream:
        columns = ['model', 'planned_sessions', 'observed_sessions', 'observed_turns', 'observed_cache_fraction'] + money_keys
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        for row in model_rows:
            writer.writerow({**{k: row[k] for k in columns if k in row},
                             'observed_sessions': row['observed']['sessions'], 'observed_turns': row['observed']['turns']})
    print(json.dumps({'current': totals, 'historical_crosscheck': historical_totals,
                      'projected_tokens': result['projected_tokens'], 'credits': result['credit_examples']}, indent=2))


if __name__ == '__main__':
    main()
