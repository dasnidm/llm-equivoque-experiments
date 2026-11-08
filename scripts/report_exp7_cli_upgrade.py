"""Read-only derived report for independent CLI upgrade technical stages."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def percentile(values, p):
    values = sorted(values)
    return values[math.ceil(len(values) * p) - 1] if values else None


def rolling_peak(records):
    queue, peak = deque(), 0
    for item in records:
        t = item['monotonic']
        while queue and queue[0] <= t - 60:
            queue.popleft()
        queue.append(t)
        peak = max(peak, len(queue))
    return peak


def collect(root):
    stages = []
    exclusions = {}
    for path in root.glob('operator-*.json'):
        item = read(path)
        if item.get('excluded_from_matched_speed_comparison'):
            exclusions[item['stage']] = item['exclusion_reason']
    for path in sorted(root.glob('*/summary.json')):
        directory = path.parent
        external_profile = root / (directory.name + '.comparison-profile.json')
        if not external_profile.is_file():
            continue
        summary, profile = read(path), read(external_profile)
        states = [read(p) for p in sorted((directory / 'states').glob('*.json'))]
        records = [json.loads(line) for line in (directory / 'meter.jsonl').read_text().splitlines()]
        sends = [r for r in records if r['kind'] == 'send']
        turns = [t for s in states for t in s.get('turns', []) if t.get('ok')]
        model_metrics = {}
        for model in profile['models']:
            sample = [t for s in states if s['trial']['model'] == model for t in s.get('turns', []) if t.get('ok')]
            usages = [t['usage_last'] for t in sample if t.get('usage_last')]
            model_metrics[model] = {
                'successful_turns': len(sample),
                'complete_conversations': sum(s['trial']['model'] == model and s['status'] == 'complete' for s in states),
                'p95_adapter_seconds': percentile([t['duration_seconds'] for t in sample], .95),
                'mean_input_tokens': sum(u['input_tokens'] for u in usages) / len(usages) if usages else None,
                'cached_input_fraction': sum(u['cached_input_tokens'] for u in usages) / sum(u['input_tokens'] for u in usages) if usages else None,
            }
        start_times = {}
        wire_latencies = []
        for record in records:
            key = (record.get('pid'), record.get('thread_id'))
            if record['kind'] == 'send':
                start_times[key] = record['monotonic']
            elif record['kind'] == 'turn/completed' and key in start_times:
                wire_latencies.append(record['monotonic'] - start_times.pop(key))
        startup_errors = []
        for stderr in (directory / 'native').rglob('process.stderr.log'):
            text = stderr.read_text(errors='replace')
            if 'failed to initialize sqlite state runtime' in text:
                startup_errors.append('local_sqlite_initialization')
        valid = (summary['sessions_complete'] == summary['sessions_planned']
                 and summary['complete_session_audits_ok'] and not summary['stop_reason']
                 and not any(summary['diagnostics'].values()))
        receipt = root / 'backups' / directory.name / 'receipt.json'
        stages.append({
            **summary, 'version': profile['version'], 'sqlite_isolation': profile.get('sqlite_isolation', False),
            'valid_complete_stage': valid,
            'matched_speed_comparison_exclusion': exclusions.get(directory.name),
            'stable_throughput_estimate': summary['successful_turns_per_minute'] if valid else None,
            'request_ceiling_per_minute': 60 / profile['account_interval_seconds'] if profile['account_interval_seconds'] else None,
            'actual_rolling_60_second_send_peak': rolling_peak(sends),
            'p95_send_to_complete_seconds': percentile(wire_latencies, .95),
            'p99_adapter_seconds': percentile([t['duration_seconds'] for t in turns], .99),
            'max_adapter_seconds': max((t['duration_seconds'] for t in turns), default=None),
            'model_metrics': model_metrics, 'startup_error_types': dict(Counter(startup_errors)),
            'profile_sha256': hashlib.sha256(external_profile.read_bytes()).hexdigest(),
            'summary_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'backup': read(receipt) if receipt.is_file() else None,
        })
    return stages


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    stages = collect(args.root)
    versions = []
    for version in ('0.159.0-alpha.3', '0.167.0', '0.169.0-alpha.3'):
        group = [s for s in stages if s['version'] == version and s['sqlite_isolation']
                 and s['valid_complete_stage'] and s['pool'] == 4 and s['request_ceiling_per_minute'] == 80
                 and len(s['model_metrics']) == 2 and not s['matched_speed_comparison_exclusion']]
        if group:
            versions.append({'version': version, 'blocks': len(group),
                             'conversations': sum(s['sessions_complete'] for s in group),
                             'successful_turns': sum(s['successful_turns'] for s in group),
                             'successful_turns_per_minute': sum(s['successful_turns'] for s in group) / sum(s['duration_seconds'] for s in group) * 60})
    offline = {p.name: read(p) for p in sorted(args.root.glob('*.offline-summary.json'))}
    stop_path = args.root / 'main-stop-verification.json'
    stop_verification = read(stop_path) if stop_path.is_file() else None
    result = {'sample_inclusion': False,
              'main_run_remains_stopped': stop_verification.get('global_stop') if stop_verification else None,
              'main_stop_verification': stop_verification, 'stages': stages,
              'matched_profile_version_summary': versions, 'offline_checks': offline,
              'limitations': ['Descriptive small-sample sequential stages; no causal estimate of binary-only effect.',
                             'CLI versions differ in advertised additional tool definitions despite the same scientific questions.',
                             'No exact provider limit or internal HTTP retry count inferred from logical turn/start sends.',
                             'Finite successful load does not demonstrate long-run stability for all model-effort combinations.']}
    (args.output / 'metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# CLI version technical comparison', '', 'All observations are technical and excluded from the scientific sample.', '',
             '| Stage | CLI | Pool | Models | Completed conversations | Successful turns/min | p95 adapter seconds | Result |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for s in stages:
        speed = f"{s['successful_turns_per_minute']:.1f}" if s['valid_complete_stage'] else 'not estimable'
        latency = f"{s['p95_response_seconds']:.2f}" if s['p95_response_seconds'] is not None else '—'
        result_label = ('integrity pass; operator pause, excluded from speed comparison'
                        if s['matched_speed_comparison_exclusion'] else
                        ('pass' if s['valid_complete_stage'] else s['stop_reason']))
        lines.append(f"| {s['stage']} | {s['version']} | {s['pool']} | {len(s['model_metrics'])} | {s['sessions_complete']}/{s['sessions_planned']} | {speed} | {latency} | {result_label} |")
    (args.output / 'TABLE.md').write_text('\n'.join(lines) + '\n')
    if versions:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        figure, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
        labels = [v['version'] for v in versions]
        rates = [v['successful_turns_per_minute'] for v in versions]
        bars = axes[0].bar(labels, rates, color=['#637a93', '#228b91', '#a078bb'][:len(versions)])
        axes[0].bar_label(bars, labels=[f'{n:.1f}' for n in rates], padding=4)
        axes[0].set(ylabel='Successful turns / minute', title='Matched load: 2 models, pool 4, ceiling 80/min', ylim=(0, max(rates) * 1.25))
        axes[0].tick_params(axis='x', labelrotation=12)
        others = [s for s in stages if s['pool'] != 4 or len(s['model_metrics']) != 2]
        if others:
            for i, s in enumerate(others):
                if s['valid_complete_stage']:
                    axes[1].bar(i, s['successful_turns_per_minute'], color='#228b91')
                    axes[1].text(i, s['successful_turns_per_minute'] + 3, f"{s['successful_turns_per_minute']:.1f}", ha='center')
                else:
                    axes[1].scatter([i], [0], color='#c44e52', marker='x', s=90)
                    axes[1].text(i, 5, 'Stopped\nNo valid rate', ha='center', color='#a23638')
            axes[1].set_xticks(range(len(others)), [f"{len(s['model_metrics'])} models\npool {s['pool']}\nceiling {s['request_ceiling_per_minute']:.0f}/min" for s in others])
            axes[1].set(ylabel='Successful turns / minute', title='Separate load profiles; not a matched CLI comparison')
            axes[1].set_ylim(bottom=-5)
        else:
            axes[1].axis('off')
            axes[1].text(.03, .5, 'No additional closed load stages yet.', transform=axes[1].transAxes)
        figure.suptitle('Experiment 7: independent CLI upgrade checks\nTechnical conversations only; failed partial stages are not throughput estimates', fontsize=12)
        figure.savefig(args.output / 'comparison.png', dpi=170)
        plt.close(figure)
    print(json.dumps({'stages': len(stages), 'version_summary': versions, 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
