"""Read preserved records; distinguish VM count, admission caps and throughput."""
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import statistics

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / 'docs/data/exp7-exp5-throughput-reassessment-20261108'


def read(path):
    return json.loads(path.read_text())


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = REPO / 'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/turns.csv'
    old = list(csv.DictReader(path.open()))
    if not old or any(r['ok'] != 'True' for r in old):
        raise ValueError('Expected the preserved successful Exp5 turn table')
    release = read(REPO / 'sequence_replication/runtime/coordinator-launch-01.json')['released_at']
    end = read(REPO / 'sequence_replication/runtime/direct-progress.json')['at']
    elapsed = ts(end) - ts(release)
    points = sorted([(ts(r['requested_at']), 1) for r in old] + [(ts(r['received_at']), -1) for r in old])
    active = peak = 0
    for _, delta in points:
        active += delta; peak = max(peak, active)
    interval_sum = sum(ts(r['received_at']) - ts(r['requested_at']) for r in old)
    old_rate = len(old) / elapsed * 60
    exp5 = {'successful_retained_turns': len(old), 'release_at': release, 'final_status_at': end,
            'elapsed_seconds': elapsed, 'turns_per_minute': old_rate,
            'mean_adapter_seconds': statistics.mean(float(r['duration_seconds']) for r in old),
            'mean_checkpoint_interval_seconds': interval_sum / len(old),
            'mean_overlapping_retained_request_intervals': interval_sum / elapsed,
            'peak_overlapping_retained_request_intervals': peak,
            'interval_unit': 'Client execution/checkpoint intervals, not server-internal inference count',
            'mean_adapter_by_model_medium_cards_seq_first30': {model: statistics.mean(float(r['duration_seconds'])
                for r in old if r['model'] == model and r['effort'] == 'medium' and r['frame'] == 'cards'
                and r['kind'] == 'seq' and int(r['turn']) <= 30)
                for model in ('gpt-6-astra', 'gpt-5.6-sol')},
            'source': str(path.relative_to(REPO)), 'source_sha256': sha(path),
            'timing_sources': {str(p.relative_to(REPO)): sha(p) for p in (
                REPO / 'sequence_replication/runtime/coordinator-launch-01.json',
                REPO / 'sequence_replication/runtime/direct-progress.json')}}
    root = Path('/workspace/work/exp7-capacity-20261108')
    history = read(root / 'historical-summary.json')
    astra_root = Path('/workspace/work/exp7-persistent-v1-astra')
    astra = []
    for rel, expected in history['sources']['astra_state_sha256'].items():
        source = astra_root / rel
        if sha(source) != expected: raise ValueError('Historical Astra checkpoint changed')
        astra.append(read(source))
    sol_path = root / 'sol-research.jsonl.gz'
    if sha(sol_path) != history['sources']['sol_research_sha256']:
        raise ValueError('Historical Sol source changed')
    sol = [json.loads(line) for line in gzip.decompress(sol_path.read_bytes()).splitlines()]
    turns = {name: [t for state in states for t in state.get('turns', [])]
             for name, states in (('Astra_VM', astra), ('Sol_VM', sol))}
    ranges = {name: (min(ts(t['requested_at']) for t in rows), max(ts(t['received_at']) for t in rows))
              for name, rows in turns.items()}
    lo, hi = max(r[0] for r in ranges.values()), min(r[1] for r in ranges.values())
    workers = {}
    for name, rows in turns.items():
        good = [r for r in rows if r.get('ok')]
        duration = ranges[name][1] - ranges[name][0]
        workers[name] = {'retained_successful_turns': len(good), 'recorded_failures': len(rows) - len(good),
                         'span_seconds': duration, 'successes_per_minute_own_span': len(good) / duration * 60,
                         'mean_adapter_seconds': statistics.mean(r['duration_seconds'] for r in good),
                         'mean_checkpoint_interval_seconds': statistics.mean(ts(r['received_at']) - ts(r['requested_at']) for r in good),
                         'mean_pre_adapter_gap_seconds': statistics.mean(ts(r['received_at']) - ts(r['requested_at']) - r['duration_seconds'] for r in good),
                         'successes_completed_during_overlap': sum(lo <= ts(r['received_at']) < hi for r in good)}
    overlap_success = sum(w['successes_completed_during_overlap'] for w in workers.values())
    astra_before = [r for r in turns['Astra_VM'] if ts(r['received_at']) < lo and r.get('ok')]
    two_vm = {'workers': workers, 'overlap_start': datetime.fromtimestamp(lo, timezone.utc).isoformat(),
              'overlap_end': datetime.fromtimestamp(hi, timezone.utc).isoformat(), 'timezone': 'UTC',
              'overlap_seconds': hi - lo, 'overlap_successful_completions': overlap_success,
              'overlap_successful_turns_per_minute': overlap_success / (hi - lo) * 60,
              'Astra_before_overlap': {'successful_completions': len(astra_before),
                  'seconds': lo - ranges['Astra_VM'][0],
                  'turns_per_minute': len(astra_before) / (lo - ranges['Astra_VM'][0]) * 60},
              'illustrative_posthoc_window_start_offset_seconds': 20,
              'successes_in_complete_60second_window': {name: sum(lo + 20 <= ts(r['received_at']) < lo + 80 and r.get('ok')
                                                               for r in rows) for name, rows in turns.items()},
              'note': 'Short completion window; boundary carry-in, later failures and interruption prevent treating this as long-run capacity.',
              'source_reference': history['sources']['sol_public_ref'],
              'source_provenance': history['sources'],
              'source_hashes_checked': True}
    latest = read(REPO / 'analysis/exp7_retry_efficiency_20261108/results/metrics.json')
    fifo = read(REPO / 'analysis/exp7_retry_efficiency_20261108/results/fifo-v4/metrics.json')['stages'][0]
    current = {'physical_VM_count_measured': 1, 'model_count': 2, 'effort': 'medium',
               'imposed_account_physical_start_cap_per_minute': 100,
               'FIFO10_successful_turns_per_minute': fifo['successful_turns_per_minute'],
               '6worker_original_queue_turns_per_minute': latest['stages'][0]['successful_turns_per_minute'],
               'mean_adapter_by_model_medium_cards_seq_first30': {},
               'not_an_identified_provider_limit': True,
               'not_a_two_VM_benchmark': True}
    stage = Path('/workspace/work/exp7-retry-efficiency-20261108-v3-job30/comparison-p6-r100')
    states = [read(p) for p in (stage / 'states').glob('*.json')]
    for model in ('gpt-6-astra', 'gpt-5.6-sol'):
        rows = [t for s in states if s['trial']['model'] == model for t in s['turns'] if t['turn'] <= 30]
        current['mean_adapter_by_model_medium_cards_seq_first30'][model] = statistics.mean(r['duration_seconds'] for r in rows)
    result = {'analysis_only': True, 'new_model_requests': 0, 'original_records_changed': False,
              'exp5': exp5, 'historical_two_VM_main_attempt': two_vm, 'recent_capped_single_VM_benchmark': current,
              'configured_upper_bounds': {'two_original_workers_interval1_second_each': 120,
                                         'two_original_workers_with_one_extra_start_per34turn_trial': 120 * 34 / 35,
                                         'current_imposed_account_cap': 100},
              'arithmetic_not_causal_decomposition': {'exp5_rate_minus_current_cap': old_rate - 100,
                  'current_cap_minus_FIFO10_observed_rate': 100 - fifo['successful_turns_per_minute'],
                  'note': 'An admission cap below the old rate precludes matching it in this test; removing it is not proof the service would accept the old rate.'},
              'limitations': ['Different dates, transports, CLI versions, model mix, workloads and failure policies.',
                             'No matched uncapped multi-VM throughput estimate or fixed backend limit identified.',
                             'New retry policy was tested on one VM with two models, not two physical VMs.']}
    (OUT / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'exp5_rate': old_rate, 'exp5_mean_intervals': exp5['mean_overlapping_retained_request_intervals'],
                      'two_VM_overlap_rate': two_vm['overlap_successful_turns_per_minute'],
                      'two_VM_60sec_successes': two_vm['successes_in_complete_60second_window'],
                      'single_VM_imposed_cap': 100, 'output': str(OUT / 'summary.json')}))


if __name__ == '__main__': main()
