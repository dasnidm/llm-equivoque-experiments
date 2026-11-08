"""Summarize the unpaced technical sweep without reading answer content."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

REPO = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def summarize(root):
    sweep = load(root / 'sweep.json')
    rows = []
    for stage in sweep['stages']:
        path = root / stage['profile']
        states = [load(p) for p in (path / 'states').glob('*.json')]
        turns = [t for state in states for t in state.get('turns', [])]
        good = [t for t in turns if t.get('ok')]
        attempts = lines(path / 'http-attempts.jsonl')
        first = min((ts(t['requested_at']) for t in turns), default=None)
        last = max((ts(t['received_at']) for t in turns), default=None)
        closed = (path / 'summary.json').exists()
        end = last if closed else datetime.now(timezone.utc).timestamp()
        elapsed = end - first if first is not None and end is not None else 0
        row = {'profile': stage['profile'], 'pool': int(stage['profile'].split('-')[0][1:]),
               'VMs_measured': 1, 'sessions_planned': stage['sessions'],
               'sessions_started': len(states), 'sessions_complete': sum(s['status'] == 'complete' for s in states),
               'successful_turns': len(good), 'elapsed_seconds': elapsed,
               'successful_turns_per_minute': len(good) / elapsed * 60 if elapsed else None,
               'capacity_429': sum(r.get('explicit_capacity_429', False) for r in attempts),
               'physical_attempts_finished': len(attempts),
               'HTTP_status_counts': dict(Counter(str(r.get('status', 'exception')) for r in attempts)),
               'STOP': (path / 'STOP.json').exists(), 'closed': closed}
        active = peak = 0
        events = sorted([(ts(t['requested_at']), 1) for t in turns] + [(ts(t['received_at']), -1) for t in turns])
        for _, delta in events:
            active += delta
            peak = max(peak, active)
        row['actual_peak_logical_checkpoint_intervals'] = peak
        waits = [a['required_delay_seconds'] for a in attempts if a.get('retry_scheduled')]
        row['summed_required_retry_wait_seconds_not_wall_time'] = sum(waits)
        row['mean_required_retry_wait_seconds'] = statistics.mean(waits) if waits else 0
        physical_success_times = [a['duration_seconds'] for a in attempts if a.get('status') == 200]
        row['mean_successful_physical_HTTP_seconds'] = statistics.mean(physical_success_times) if physical_success_times else None
        gaps = [ts(t['received_at']) - ts(t['requested_at']) - t['duration_seconds'] for t in good]
        row['mean_pre_adapter_gap_seconds'] = statistics.mean(gaps) if gaps else None
        row['post_completion_HTTP_close_diagnostics'] = sum(bool(a.get('post_completion_HTTP_close_error')) for a in attempts)
        groups = defaultdict(list)
        for attempt in attempts:
            groups[attempt['logical_id']].append(attempt)
        row['recovered_logical_requests'] = sum(len(g) > 1 and any(r.get('status') == 200 for r in g) for g in groups.values())
        row['backoff_wait_violations'] = 0
        for group in groups.values():
            group.sort(key=lambda r: r['attempt'])
            for previous, current in zip(group, group[1:]):
                required = previous.get('required_delay_seconds', 0)
                if current['started_monotonic'] - previous['ended_monotonic'] + .01 < required:
                    row['backoff_wait_violations'] += 1
        if elapsed >= 180:
            completed = sum(first + 60 <= ts(t['received_at']) < first + 180 for t in good)
            row['illustrative_60_to_180_seconds_successes'] = completed
            row['illustrative_60_to_180_seconds_turns_per_minute'] = completed / 2
        if row['closed']:
            summary = load(path / 'summary.json')
            profile = load(path / 'profile.json')
            row.update(p95_turn_seconds=summary['p95_turn_seconds'],
                       actual_peak_inflight_http=summary['actual_peak_inflight_http'],
                       rolling_60s_start_peak=summary['rolling_60s_start_peak'],
                       audit_ok=summary['complete_session_audits_ok'],
                       credential_scan_clean=summary['credential_scan_clean'],
                       tool_events=summary['actual_tool_events'],
                       source_commit=profile['source_commit'],
                       physical_start_ceiling_per_minute=profile['physical_start_ceiling_per_minute'],
                       request_interval_seconds=profile['physical_start_interval_seconds'],
                       shared_cooldown=profile['retry_policy']['shared_cooldown_all_models'])
            row['valid_complete_stage'] = bool(stage.get('exit_code') == 0 and row['audit_ok']
                and row['credential_scan_clean'] and row['sessions_complete'] == row['sessions_planned']
                and not row['STOP'] and not row['backoff_wait_violations'])
        rows.append(row)
    valid = [r for r in rows if r.get('valid_complete_stage')]
    return {'study_id': sweep['run_id'], 'main_samples': 0, 'VMs_measured': 1,
            'rate_cap': None, 'retry_wait_scope': 'request', 'stages': rows,
            'best_observed_complete_stage': max(valid, key=lambda r: r['successful_turns_per_minute'])['profile'] if valid else None,
            'interpretation': 'Exploratory comparison, different finite job sizes and tails; no account-wide absolute maximum identified.'}


def plot(result, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows = [r for r in result['stages'] if r.get('valid_complete_stage')]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    labels = [str(r['pool']) for r in rows]
    rates = [r['successful_turns_per_minute'] for r in rows]
    axes[0].bar(labels, rates, color='#247ba0')
    axes[0].axhline(126.73178195262251, linestyle='--', color='#666666', label='Exp5 historical average')
    for i, value in enumerate(rates):
        axes[0].text(i, value + 2, f'{value:.1f}', ha='center')
    axes[0].set_ylabel('Successful logical turns / minute')
    axes[0].set_title('Whole job, including retries and tails')
    axes[0].set_ylim(0, max([140] + [r * 1.2 for r in rates]))
    axes[0].legend(fontsize=8)
    failures = [100 * r['capacity_429'] / r['successful_turns'] for r in rows]
    axes[1].bar(labels, failures, color='#e28e2c')
    for i, value in enumerate(failures):
        axes[1].text(i, value + .2, f'{value:.1f}', ha='center')
    axes[1].set_ylabel('Capacity 429s per 100 successful turns')
    axes[1].set_title('Rejected attempts are retried unchanged')
    axes[1].set_ylim(0, max([12] + [r * 1.2 for r in failures]))
    for axis in axes:
        axis.set_xlabel('Concurrent conversation workers')
        axis.spines[['top', 'right']].set_visible(False)
    fig.suptitle('Unpaced CLI test: one VM, two models, medium effort; no RPM cap', fontsize=11)
    fig.tight_layout()
    fig.savefig(output / 'throughput.png', dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--plot', action='store_true')
    args = p.parse_args()
    result = summarize(args.root)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        fields = ['pool', 'sessions_planned', 'successful_turns', 'elapsed_seconds',
                  'successful_turns_per_minute', 'capacity_429', 'physical_attempts_finished',
                  'p95_turn_seconds', 'actual_peak_logical_checkpoint_intervals',
                  'actual_peak_inflight_http', 'valid_complete_stage']
        with (args.output / 'metrics.csv').open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
            writer.writeheader()
            writer.writerows(result['stages'])
        if args.plot:
            plot(result, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
