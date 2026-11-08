"""Read local evidence; report retry-inclusive throughput without model calls."""
import argparse
import csv
import json
from pathlib import Path
import datetime
import hashlib
import re
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('/workspace/work/exp7-retry-efficiency-20261108-v2'))
    p.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'results')
    p.add_argument('--no-config', action='store_true')
    p.add_argument('--decision-file', type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in args.root.glob('*/summary.json'):
        if not path.parent.name.startswith(('comparison-', 'confirmation-')):
            continue
        row = read(path)
        profile = read(path.parent / 'profile.json')
        row.update(stage=path.parent.name, profile=profile['profile'], source_commit=profile['source_commit'],
                   source_sha256=profile['source_sha256'], cli_version=profile['cli_version'],
                   binary_sha256=profile['binary_sha256'],
                   models=profile['models'], effort=profile['effort'])
        states = [read(p) for p in (path.parent / 'states').glob('*.json')]
        by_model = {}
        for model in profile['models']:
            turns = [turn for state in states if state['trial']['model'] == model for turn in state['turns'] if turn.get('ok')]
            usage = [turn['usage_last'] for turn in turns if turn.get('usage_last')]
            by_model[model] = {'successful_turns': len(turns),
                               'mean_last_turn_input_tokens': sum(u['input_tokens'] for u in usage) / len(usage) if usage else None,
                               'mean_last_turn_output_tokens': sum(u['output_tokens'] for u in usage) / len(usage) if usage else None}
        row['model_token_diagnostics'] = by_model
        intervals = []
        for state in states:
            for turn in state['turns']:
                intervals.extend((datetime.datetime.fromisoformat(turn[key]).timestamp(), delta)
                                 for key, delta in (('requested_at', 1), ('received_at', -1)))
        active = peak = 0
        for _, delta in sorted(intervals):
            active += delta; peak = max(peak, active)
        row['actual_peak_active_logical_turns'] = peak
        attempts = [json.loads(line) for line in (path.parent / 'http-attempts.jsonl').read_text().splitlines()]
        physical_latencies = sorted(r['duration_seconds'] for r in attempts if r.get('status') == 200)
        row['physical_HTTP_roundtrip_p95_seconds'] = statistics.quantiles(physical_latencies, n=100, method='inclusive')[94]
        admissions = [json.loads(line) for line in (path.parent / 'admission.jsonl').read_text().splitlines()]
        direct_waits = [r['queue_wait_seconds'] for r in admissions if r['kind'] == 'admit' and 'queue_wait_seconds' in r]
        row['measured_admission_wait_p95_seconds'] = statistics.quantiles(direct_waits, n=100, method='inclusive')[94] if len(direct_waits) > 1 else None
        row['measured_admission_wait_max_seconds'] = max(direct_waits) if direct_waits else None
        outer = [json.loads(line) for line in (path.parent / 'http-responses.jsonl').read_text().splitlines()]
        hashes = {}
        for attempt in attempts: hashes.setdefault(attempt['request_body_sha256'], []).append(attempt)
        approx_waits = []
        for response in outer:
            group = hashes.get(response['request_body_sha256'], [])
            if len({entry['logical_id'] for entry in group}) == 1:
                approx_waits.append(response['duration_seconds'] - sum(entry['duration_seconds'] for entry in group)
                                    - sum(entry.get('required_delay_seconds', 0) for entry in group))
        row['approximate_local_admission_wait_p95_seconds'] = statistics.quantiles(approx_waits, n=100, method='inclusive')[94] if len(approx_waits) > 1 else None
        row['approximate_local_admission_wait_max_seconds'] = max(approx_waits) if approx_waits else None
        first_attempt = min(r['started_monotonic'] for r in attempts) if attempts else None
        last_end = max(r['ended_monotonic'] for r in attempts) if attempts else None
        if first_attempt is not None and last_end - first_attempt >= 180:
            common_success = sum(r.get('status') == 200 and first_attempt + 60 <= r['ended_monotonic'] < first_attempt + 180 for r in attempts)
            row['secondary_post60_to180s_successful_turns'] = common_success
            row['secondary_post60_to180s_turns_per_minute'] = common_success / 2
        else:
            row['secondary_post60_to180s_turns_per_minute'] = None
        if first_attempt is not None and last_end - first_attempt >= 480:
            long_success = sum(r.get('status') == 200 and first_attempt + 60 <= r['ended_monotonic'] < first_attempt + 480 for r in attempts)
            row['secondary_post60_to480s_turns_per_minute'] = long_success / 7
        else:
            row['secondary_post60_to480s_turns_per_minute'] = None
        events = sorted([(r['started_monotonic'], 1) for r in attempts] + [(r['ended_monotonic'], -1) for r in attempts])
        active = 0; above_pool_seconds = 0.; previous = events[0][0] if events else 0
        for time, delta in events:
            if active > row['pool']: above_pool_seconds += time - previous
            active += delta; previous = time
        row['HTTP_close_overlap_above_conversation_pool_seconds'] = above_pool_seconds
        row['request_content_encodings'] = sorted({r.get('request_content_encoding') for r in attempts})
        native = read(path.parent / 'native-retry-audit.json')
        row['native_429_retry_warning_records'] = native['native_429_retry_log_records']
        row['native_other_retry_warning_records'] = native['other_native_retry_log_records']
        catalog = other = 0
        pattern = re.compile(r'status[: =]+429\b|\b429 Too Many Requests\b|status code 429\b', re.I)
        for log in (path.parent / 'native').rglob('process.stderr.log'):
            for line in log.read_text(errors='replace').splitlines():
                if pattern.search(line):
                    if re.search(r'models_manager|/models|model catalog', line, re.I): catalog += 1
                    else: other += 1
        row['catalog_429_log_lines'] = catalog
        row['other_native_429_log_lines'] = other
        receipt = args.root / 'backups' / path.parent.name / 'receipt.json'
        row['private_backup_receipt'] = read(receipt) if receipt.exists() else None
        rows.append(row)
    rows.sort(key=lambda r: r['ended_at'])
    historical_root = Path('/workspace/work/exp7-cli-upgrade-20261108')
    previous_audit = read(Path(__file__).resolve().parents[1] / 'exp7_cli_upgrade_20261108/results/metrics.json')
    audited_stages = {row['stage']: row for row in previous_audit['stages']}
    historical = []
    for name in ('stable-i-rpm100-p6', 'stable-i-models2-rpm110-p8', 'stable-i-models8-rpm160-p8', 'stable-i-models8-rpm200-p10'):
        summary = read(historical_root / name / 'summary.json')
        native = audited_stages[name]['native_retry_audit']
        historical.append({'stage': name, 'successful_turns': summary['successful_turns'],
                           'complete_conversations': summary['sessions_complete'],
                           'planned_conversations': summary['sessions_planned'],
                           'duration_seconds': summary['duration_seconds'],
                           'successful_turns_per_minute_including_native_retries': summary['successful_turns_per_minute'],
                           'native_429_retry_warning_records': native['native_429_retry_log_records'],
                           'complete_session_audits_ok': summary['complete_session_audits_ok'],
                           'censored_incomplete_stage': summary['sessions_complete'] != summary['sessions_planned']})
    decision_path = args.decision_file or args.root / 'decision.json'
    decision = read(decision_path) if decision_path.exists() else None
    result = {'role': 'Technical operational comparison; no main samples',
              'study_root': str(args.root), 'decision': decision, 'stages': rows,
              'prior_WS_derived_retry_inclusive_metrics': historical,
              'runtime_sources_identical_across_new_stages': len({json.dumps(row['source_sha256'], sort_keys=True) for row in rows}) == 1 if rows else None,
              'limitations': ['Sequential short stages, not randomized causal comparisons.',
                             'Two models, medium effort, one VM; no all-model/high-effort capacity guarantee.',
                             'HTTP/SSE profile differs from retired WS profile; no response-distribution equivalence claim.',
                             'Pool and physical start rate are compared jointly.',
                             'RPC/native and byte-identical retry audits do not prove provider-internal exactly-once execution.']}
    write(args.out / 'metrics.json', result)
    fields = ['stage', 'pool', 'physical_start_ceiling_per_minute', 'sessions_complete', 'sessions_planned',
              'successful_turns', 'duration_seconds_including_retries', 'successful_turns_per_minute',
              'secondary_post60_to180s_turns_per_minute',
              'secondary_post60_to480s_turns_per_minute',
              'physical_attempts', 'explicit_capacity_429', 'recovered_logical_requests',
              'actual_peak_inflight_http', 'p95_turn_seconds', 'complete_session_audits_ok']
    with (args.out / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    if rows:
        labels = [('Confirm ' if r['stage'].startswith('confirmation') else '') + f"pool {r['pool']}\ncap {r['physical_start_ceiling_per_minute']}/min" for r in rows]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
        rates = [r['successful_turns_per_minute'] for r in rows]
        x = list(range(len(rows)))
        long_window = all(r['secondary_post60_to480s_turns_per_minute'] is not None for r in rows)
        secondary_key = 'secondary_post60_to480s_turns_per_minute' if long_window else 'secondary_post60_to180s_turns_per_minute'
        secondary = [r[secondary_key] or 0 for r in rows]
        bars = axes[0].bar([i - .2 for i in x], rates, width=.38, color='#198576', label='Whole allocation')
        axes[0].bar_label(bars, labels=[f'{v:.1f}' for v in rates], padding=3)
        warm = axes[0].bar([i + .2 for i in x], secondary, width=.38, color='#7997bb', label='Secondary: seconds 60-480' if long_window else 'Secondary: seconds 60-180')
        axes[0].bar_label(warm, labels=[f'{v:.1f}' for v in secondary], padding=3)
        axes[0].set_xticks(x, labels)
        axes[0].set(ylabel='Successful turns / minute', title='Retry-inclusive throughput', ylim=(0, max(rates + secondary) * 1.2))
        if not args.no_config:
            axes[0].axhline(rates[0] * 1.05, color='#b05d39', linestyle='--', label='Baseline + 5%')
        axes[0].legend(fontsize=8)
        latency = [r['p95_turn_seconds'] or 0 for r in rows]
        bars = axes[1].bar(labels, latency, color='#b88b5b')
        axes[1].bar_label(bars, labels=[f'{v:.2f}s' for v in latency], padding=3)
        axes[1].set(ylabel='p95 logical turn seconds', title='Includes shared admission / cooldown', ylim=(0, max(latency) * 1.2))
        for ax in axes: ax.grid(axis='y', alpha=.2)
        fig.savefig(args.out / 'throughput_and_latency.png', dpi=170); plt.close(fig)
        fig, axes = plt.subplots(len(rows), 1, figsize=(10, 2.7 * len(rows)), constrained_layout=True, squeeze=False)
        for ax, row in zip(axes[:, 0], rows):
            stage = args.root / row['stage']
            attempts = sorted((json.loads(line) for line in (stage / 'http-attempts.jsonl').read_text().splitlines()), key=lambda r: r['started_monotonic'])
            first = attempts[0]['started_monotonic']
            good = sorted(r['ended_monotonic'] - first for r in attempts if r.get('status') == 200)
            starts = [r['started_monotonic'] - first for r in attempts]
            ax.step([0] + starts, [0] + list(range(1, len(starts) + 1)), where='post', color='#3b6aa8', label='Physical starts')
            ax.step([0] + good, [0] + list(range(1, len(good) + 1)), where='post', color='#198576', label='Successful turns')
            admissions = [json.loads(line) for line in (stage / 'admission.jsonl').read_text().splitlines()]
            for event in admissions:
                if event['kind'] == 'cooldown':
                    ax.axvspan(event['monotonic'] - first, event['until_monotonic'] - first, alpha=.12, color='#c74646')
            ax.set(title=f"{row['stage']}: {row['successful_turns_per_minute']:.1f} successful turns/min, {row['explicit_capacity_429']} HTTP 429", ylabel='Cumulative count', xlabel='Seconds since first physical attempt')
            ax.grid(alpha=.2); ax.legend(loc='upper left', fontsize=8)
        fig.savefig(args.out / 'retry_timelines.png', dpi=150); plt.close(fig)
    if decision and not args.no_config:
        selected = next(row for row in rows if row['stage'] == 'comparison-' + decision['selected_profile'])
        config = {'schema_version': 1, 'status': 'selected_for_fresh_execution_profile',
                  'main_collection_enabled': False, 'retired_main_STOP_preserved': True,
                  'selected_strategy': decision['selected_profile'], 'selection_validation_passed': decision['confirmed'],
                  'validation_kind': decision.get('validation_kind', 'Original short-batch screening and conditional repeat'),
                  'global_pool': selected['pool'], 'physical_starts_per_minute_global': selected['physical_start_ceiling_per_minute'],
                  'pool_unit': 'Concurrent conversation/CLI worker slots, not provider-internal inference count',
                  'observed_HTTP_stream_interval_peak': selected['actual_peak_inflight_http'],
                  'observed_active_logical_turn_peak': selected['actual_peak_active_logical_turns'],
                  'scope': 'One shared admission/cooldown controller; never multiply these limits by VM count',
                  'cli_version': '0.167.0', 'transport': 'persistent CLI HTTP/SSE',
                  'binary_sha256': selected['binary_sha256'],
                  'original_scientific_freeze_sha256': selected['main_freeze_sha256'],
                  'model_catalog_sha256': hashlib.sha256((Path(__file__).resolve().parents[2] / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/model-catalog.json').read_bytes()).hexdigest(),
                  'CLI_local_min_start_interval_seconds': 0,
                  'physical_admission_owner': 'One shared controller; avoid a second independent per-model pacer',
                  'native_request_max_retries': 0, 'native_stream_max_retries': 0,
                  'sqlite_isolation': 'Child-only CODEX_SQLITE_HOME; serial migration before pool launch; native auth home retained',
                  'native_retry_warning_visibility': 'Child RUST_LOG appends codex_core::responses_retry=warn',
                  'retry_only': {'status': 429, 'error_type': 'rate_limit_error', 'error_code': 'turn_rate_limit_exceeded', 'before_stream': True},
                  'max_retries_per_logical_request': 4,
                  'max_elapsed_plus_next_wait_for_retry_scheduling_seconds': 240,
                  'CLI_logical_turn_timeout_seconds': 360,
                  'respect_retry_after': True, 'shared_cooldown': True, 'jitter_seconds': [.1, .4],
                  'retry_changes_request_bytes': False, 'retry_adds_turn_start_or_user_message': False,
                  'automatic_uncertain_completion_replay': False, 'automatic_STOP_release': False,
                  'verified_models': selected['models'], 'verified_effort': 'medium',
                  'scientific_allocation_changed': False,
                  'fresh_main_requirements': ['New execution ID and freeze, full original allocation preserved.',
                                              'Exact-profile model/effort readiness and raw audit.',
                                              'All VM physical attempts, retries and concurrency share one account budget.'],
                  'selection_evidence': decision,
                  'source_commit': selected['source_commit'], 'source_sha256': selected['source_sha256']}
        write(args.out / 'recommended_execution_profile.json', config)
    print(json.dumps({'stages': len(rows), 'decision_available': bool(decision), 'output': str(args.out)}))


if __name__ == '__main__': main()
