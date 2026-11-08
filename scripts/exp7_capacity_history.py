"""Derive timing/token aggregates from preserved failed jobs, without answers."""
import argparse
import bisect
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--astra-work', required=True, type=Path)
    p.add_argument('--sol-research', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    paths = sorted((args.astra_work / 'jobs').glob('*/states/*.json'))
    sets = {'astra': [json.loads(x.read_text()) for x in paths],
            'sol56': [json.loads(x) for x in gzip.decompress(args.sol_research.read_bytes()).splitlines()]}
    results, combined_times, combined_minutes, token_minutes = {}, [], Counter(), defaultdict(Counter)
    for name, states in sets.items():
        times, minutes, tokens, successes, failures = [], Counter(), Counter(), 0, 0
        for state in states:
            for turn in state.get('turns', []):
                dt = datetime.fromisoformat(turn['requested_at'])
                times.append(dt.timestamp()); combined_times.append(dt.timestamp())
                minute = dt.strftime('%H:%M'); minutes[minute] += 1; combined_minutes[minute] += 1
                successes += turn.get('ok') is True; failures += turn.get('ok') is not True
                for key, value in turn.get('usage_last', {}).items():
                    if isinstance(value, (int, float)):
                        tokens[key] += value; token_minutes[minute][key] += value
        times.sort()
        results[name] = {'recorded_requests': len(times), 'success': successes, 'failed': failures,
            'checkpoint_starts_by_minute': dict(sorted(minutes.items())),
            'peak_rolling60_checkpoint_starts': max((i-bisect.bisect_right(times,t-60)+1 for i,t in enumerate(times)),default=0),
            'usage_last_summed': dict(tokens)}
    combined_times.sort()
    results['combined'] = {'checkpoint_starts_by_minute': dict(sorted(combined_minutes.items())),
        'peak_rolling60_checkpoint_starts': max((i-bisect.bisect_right(combined_times,t-60)+1 for i,t in enumerate(combined_times)),default=0),
        'tokens_by_minute': {k:dict(v) for k,v in sorted(token_minutes.items())}}
    results['sources'] = {'sol_public_ref':'26845606894746e70fed7ab36dbdb69d8063d846:results/equivoque-2026-11-08-exp7-persistent-v1/gpt-5.6-sol/model-02-job-0001.jsonl.gz',
        'sol_research_sha256':hashlib.sha256(args.sol_research.read_bytes()).hexdigest(),
        'astra_state_sha256':{str(x.relative_to(args.astra_work)):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}}
    results['note'] = 'Checkpoint times precede pacing; counts are not actual endpoint arrivals or internal HTTP requests.'
    args.output.write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results['combined']))


if __name__ == '__main__':
    main()
