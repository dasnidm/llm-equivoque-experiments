"""Read-only diagnosis of archived throughput and retry-window structure."""
import argparse
import csv
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import statistics

REPO = Path(__file__).resolve().parents[1]
RAW = Path('/workspace/work/exp7-unpaced-retry-20261108-v1')
OUT = REPO / 'docs/data/exp7-throttle-diagnosis-20261108'


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path, default=RAW)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    raw, out = args.raw_root, args.output
    out.mkdir(parents=True, exist_ok=True)
    old_path = REPO / 'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/turns.csv'
    with old_path.open() as stream:
        old = list(csv.DictReader(stream))
    assert len(old) == 83160 and all(row['ok'] == 'True' for row in old)
    start, end = min(ts(r['received_at']) for r in old), max(ts(r['received_at']) for r in old)
    minute_counts = Counter(int((ts(r['received_at']) - start) // 60) for r in old)
    full_minutes = [minute_counts[i] for i in range(int((end - start) // 60))]
    release_path = REPO / 'sequence_replication/runtime/coordinator-launch-01.json'
    final_path = REPO / 'sequence_replication/runtime/direct-progress.json'
    release = json.loads(release_path.read_text())['released_at']
    final = json.loads(final_path.read_text())['at']
    old_rate = len(old) / (ts(final) - ts(release)) * 60
    old_result = {'successful_turns': len(old), 'overall_turns_per_minute': old_rate,
                  'full_60s_bins': len(full_minutes), 'full_bin_median': statistics.median(full_minutes),
                  'full_bins_over100': sum(n > 100 for n in full_minutes),
                  'fraction_full_bins_over100': sum(n > 100 for n in full_minutes) / len(full_minutes),
                  'bin_origin': 'First retained successful completion; final partial minute excluded',
                  'source': str(old_path.relative_to(REPO)), 'source_sha256': sha(old_path),
                  'interval_sources': [{'path': str(p.relative_to(REPO)), 'sha256': sha(p)}
                                       for p in (release_path, final_path)],
                  'released_at': release, 'final_status_at': final}
    stages, plot_records = [], []
    for stage in ('p10-unpaced', 'p20-unpaced', 'p40-unpaced'):
        source = raw / stage / 'http-attempts.jsonl'
        rows = sorted([json.loads(s) for s in source.read_text().splitlines()], key=lambda r: r['started_monotonic'])
        good = [r for r in rows if r.get('status') == 200]
        rejected = [r for r in rows if r.get('status') == 429]
        groups = [[]]
        for row in good:
            if groups[-1] and row['started_monotonic'] - groups[-1][-1]['started_monotonic'] > 10:
                groups.append([])
            groups[-1].append(row)
        counts = [len(g) for g in groups]
        gaps = [groups[i+1][0]['started_monotonic'] - groups[i][0]['started_monotonic']
                for i in range(len(groups)-1) if len(groups[i]) == len(groups[i+1]) == 100]
        summary_path = raw / stage / 'summary.json'
        summary = json.loads(summary_path.read_text())
        assert len(good) == summary['successful_turns']
        assert len(good) + len(rejected) == len(rows)
        assert all(r['error'].get('code') == 'turn_rate_limit_exceeded' for r in rejected)
        planned_wait = sum(r.get('required_delay_seconds', 0) for r in rejected if r.get('retry_scheduled'))
        slot_seconds = summary['pool'] * summary['duration_seconds_including_retries']
        # This is worker-slot time, not a causal fraction of elapsed wall time.
        samples = []
        for row in rejected[:2]:
            headers = row['headers']
            reset = parsedate_to_datetime(headers['date']).timestamp() + float(headers['retry-after'])
            samples.append({'local_headers_at': row['headers_at'], 'server_date': headers['date'],
                            'retry_after_seconds': float(headers['retry-after']),
                            'server_advised_retry_epoch': reset,
                            'request_id': headers.get('x-oai-request-id'),
                            'error_type': row['error'].get('type'), 'error_code': row['error'].get('code')})
        stages.append({'stage': stage, 'pool': summary['pool'],
                       'successful_turns': summary['successful_turns'],
                       'successful_turns_per_minute': summary['successful_turns_per_minute'],
                       'success_burst_threshold_seconds': 10, 'success_burst_counts': counts,
                       'consecutive_100_burst_start_gaps_seconds': gaps,
                       'median_100_burst_start_gap_seconds': statistics.median(gaps) if gaps else None,
                       'sum_required_backoff_seconds': planned_wait,
                       'available_worker_slot_seconds': slot_seconds,
                       'lower_bound_slot_fraction_required_backoff': planned_wait / slot_seconds,
                       'backoff_fraction_note': 'Overlapping waits are summed across different worker slots; not an estimate of causal wall-time savings.',
                       'retained_429_examples_for_support': samples,
                       'source': str(source), 'source_sha256': sha(source),
                       'summary_source': str(summary_path), 'summary_source_sha256': sha(summary_path)})
        if stage == 'p40-unpaced':
            origin = rows[0]['started_monotonic']
            plot_records = [(r['started_monotonic'] - origin, i+1) for i,r in enumerate(good)]
    data = {'new_model_calls': 0, 'exp5': old_result, 'stages': stages,
            'burst_method': 'Exploratory: split chronologically ordered successful HTTP start times at gaps over 10 seconds. Not a preregistered hypothesis test or a provider-declared quota.',
            'inference': 'Approximately 100 successful admissions per roughly 60-second cycle on this account/path; exact scope and provider policy remain unidentified.',
            'full_plan_turns': 2647104,
            'days_at_100_per_minute': 2647104 / 100 / 60 / 24,
            'days_at_exp5_average': 2647104 / old_rate / 60 / 24,
            'required_turns_per_minute_for_three_days': 2647104 / 3 / 24 / 60}
    (out / 'diagnosis.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    with (out / 'exp5_minute_completions.csv').open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['minute_from_first_completion', 'successful_completions'])
        writer.writerows(enumerate(full_minutes))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.3))
    axes[0].hist(full_minutes, bins=range(0, 181, 10), color='#247ba0')
    axes[0].axvline(100, color='#cf5c36', linestyle='--')
    axes[0].set(xlabel='Successful completions in a 60-second bin', ylabel='Number of bins',
                title='Exp5: 560 of 655 full bins exceed 100')
    x, y = zip(*plot_records)
    axes[1].step(x, y, where='post', color='#247ba0', label='Successful HTTP attempts')
    axes[1].plot([0, max(x)], [0, max(x)*100/60], '--', color='#777777', label='100 per minute reference')
    axes[1].set(xlabel='Seconds from first physical start', ylabel='Cumulative successful attempts',
                title='Current 40 workers: recurring batches of 100')
    axes[1].legend(fontsize=8)
    waits = [r['lower_bound_slot_fraction_required_backoff']*100 for r in stages]
    axes[2].bar(['10', '20', '40'], waits, color='#e28e2c')
    for i,v in enumerate(waits): axes[2].text(i, v+2, f'{v:.1f}%', ha='center')
    axes[2].set(xlabel='Conversation workers', ylabel='Percent of available worker-slot time', ylim=(0,100),
                title='Minimum slot time spent in 429 backoff')
    for ax in axes: ax.spines[['top','right']].set_visible(False)
    fig.tight_layout(); fig.savefig(out / 'diagnosis.png', dpi=180); plt.close(fig)
    print(json.dumps({'exp5': old_result, 'stages': [{k:r[k] for k in ('pool','success_burst_counts','median_100_burst_start_gap_seconds','lower_bound_slot_fraction_required_backoff')} for r in stages]},ensure_ascii=False))


if __name__ == '__main__': main()
