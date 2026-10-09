"""Prespecified longitudinal analysis with ten shared case clusters."""
import argparse
import collections
import json
from pathlib import Path
import subprocess
import warnings

import numpy as np
import pandas as pd

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque2.audit import audit_worker
from equivoque2.protocol import CONFIG, FREEZE, frozen_hashes

MEASUREMENTS = (3, 6, 9, 10)
LABELS = ['Round 1', 'Round 2', 'Round 3', 'Disclosed']


def case_bootstrap(matrix, indices):
    """Rows are cases; columns are paired frames. Preserve missing endpoints."""
    matrix = np.asarray(matrix, dtype=float)
    contributing = int(np.any(np.isfinite(matrix), axis=1).sum())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        estimate = float(np.nanmean(matrix))
        replicates = np.nanmean(matrix[indices], axis=(1, 2))
    valid = np.isfinite(replicates)
    sufficient = contributing >= 5 and valid.mean() >= .95
    interval = np.quantile(replicates[valid], [.025, .975]) if sufficient else [np.nan, np.nan]
    return {'estimate': estimate, 'ci_low': float(interval[0]), 'ci_high': float(interval[1]),
        'n_cases': contributing, 'n_observations': int(np.isfinite(matrix).sum()),
        'valid_bootstrap_replicates': int(valid.sum()),
        'status': 'estimable' if sufficient else 'insufficient'}, replicates


def load(output):
    config = read_json(CONFIG)
    trials, measurements, turns, audits, sessions = [], [], [], [], set()
    seen = set()
    for w in config['workers']:
        manifest_path = ROOT / 'manifests' / config['run_id'] / f'worker-{w}.json'
        manifest = read_json(manifest_path)
        directory = ROOT / 'results' / config['run_id'] / f'worker-{w}'
        audit = audit_worker(manifest_path, directory)
        audits.append(audit)
        if not audit['integrity_ok'] or not audit['collection_finished']:
            raise ValueError('Worker collection/audit incomplete: ' + w)
        for session in audit['session_ids']:
            if session in sessions:
                raise ValueError('Native session reused across workers')
            sessions.add(session)
        for t in manifest['trials']:
            if t['trial_id'] in seen:
                raise ValueError('Duplicate trial ID')
            seen.add(t['trial_id'])
            state = read_json(directory / 'trials' / (t['trial_id'].replace('/', '__') + '.json'))
            row = {**t, 'round_orders': json.dumps(t['round_orders']), 'status': state['status'],
                   'session_id': state['session_id'], 'error': state.get('error'),
                   'started_at': state['started_at'], 'ended_at': state.get('ended_at')}
            row['recorded_turn_seconds'] = sum(r['duration_seconds'] for r in state['turns']) if all(
                r.get('duration_seconds') is not None for r in state['turns']) else np.nan
            for m, turn in enumerate(MEASUREMENTS, 1):
                parsed = state['turns'][turn - 1].get('parsed', {}) if len(state['turns']) >= turn else {}
                for key in ('freedom', 'impact', 'counterfactual'):
                    row[f'm{m}_{key}'] = parsed.get(key)
                measurements.append({'trial_id': t['trial_id'], 'case_id': t['case_id'],
                    'configuration_id': t['configuration_id'], 'frame': t['frame'], 'measurement': m,
                    'phase': LABELS[m - 1], 'valid': bool(parsed), **parsed})
            row['counterfactual_trajectory'] = ''.join(
                '?' if row[f'm{m}_counterfactual'] is None else 'Y' if row[f'm{m}_counterfactual'] == 'yes' else 'N'
                for m in range(1, 5))
            row['first_observed_pre_no'] = next((str(m) for m in range(1, 4)
                if row[f'm{m}_counterfactual'] == 'no'), 'none_observed')
            row['pre_measurements_complete'] = all(row[f'm{m}_counterfactual'] is not None for m in range(1, 4))
            for r in state['rounds']:
                row[f"r{r['round']}_route"] = r['route']
            trials.append(row)
            for r in state['turns']:
                usage = r.get('usage') or {}
                turns.append({'trial_id': t['trial_id'], 'case_id': t['case_id'],
                    'configuration_id': t['configuration_id'], 'frame': t['frame'], 'worker': w,
                    'turn': r['turn'], 'round': r['round'], 'local_turn': r['local_turn'],
                    'ok': r['ok'], 'duration_seconds': r.get('duration_seconds'),
                    'timeout': r.get('timeout'), 'exit_code': r.get('exit_code'),
                    'requested_at': r['requested_at'], 'received_at': r['received_at'],
                    **{k: usage.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')}})
    if len(seen) != 420:
        raise ValueError('Integrated roster does not contain 420 unique trials')
    write_json(output / 'union_audit.json', {'integrity_ok': True, 'trials': len(seen),
        'unique_sessions': len(sessions), 'raw_files_verified': sum(a['raw_files_verified'] for a in audits), 'workers': audits})
    return config, pd.DataFrame(trials), pd.DataFrame(measurements), pd.DataFrame(turns)


def estimates(config, df):
    cases = sorted(df.case_id.unique())
    configurations = [c['configuration_id'] for c in config['configurations']]
    indices = np.random.default_rng(config['seeds']['bootstrap']).integers(0, len(cases), (2000, len(cases)))
    rows, primary_replicates, primary_matrices = [], [], []
    for cid in configurations:
        part = df[df.configuration_id == cid].set_index(['case_id', 'frame'])
        def matrix(column):
            return part[column].unstack('frame').reindex(index=cases, columns=['cards', 'cats']).to_numpy(dtype=float)
        values = {(key, m): matrix(f'm{m}_{key}') for key in ('impact', 'freedom') for m in range(1, 5)}
        for key in ('impact', 'freedom'):
            for m in range(1, 5):
                result, _ = case_bootstrap(values[key, m], indices)
                rows.append({'configuration_id': cid, 'metric': f'm{m}_{key}', **result})
                frame_diff = (values[key, m][:, 1] - values[key, m][:, 0])[:, None]
                result, _ = case_bootstrap(frame_diff, indices)
                rows.append({'configuration_id': cid, 'metric': f'cats_minus_cards_m{m}_{key}', **result})
            for first, last in ((1, 2), (2, 3), (1, 3), (3, 4), (1, 4)):
                result, replicates = case_bootstrap(values[key, last] - values[key, first], indices)
                metric = f'm{last}_minus_m{first}_{key}'
                rows.append({'configuration_id': cid, 'metric': metric, **result})
                if metric == 'm3_minus_m1_impact':
                    primary_replicates.append(replicates)
                    primary_matrices.append(values[key, last] - values[key, first])
        for m in range(1, 5):
            cf = part[f'm{m}_counterfactual'].map({'yes': 1., 'no': 0.})
            mat = cf.unstack('frame').reindex(index=cases, columns=['cards', 'cats']).to_numpy(dtype=float)
            result, _ = case_bootstrap(mat, indices)
            rows.append({'configuration_id': cid, 'metric': f'm{m}_counterfactual_yes', **result})
    primary = [r for r in rows if r['metric'] == 'm3_minus_m1_impact']
    combined = np.mean(np.array(primary_replicates), axis=0)
    valid = np.isfinite(combined)
    sufficient = all(r['status'] == 'estimable' for r in primary) and valid.mean() >= .95
    ci = np.quantile(combined[valid], [.025, .975]) if sufficient else [np.nan, np.nan]
    rows.append({'configuration_id': 'ALL_EQUAL_CONFIGURATIONS', 'metric': 'm3_minus_m1_impact',
        'estimate': np.mean([r['estimate'] for r in primary]), 'ci_low': ci[0], 'ci_high': ci[1],
        'n_cases': int(np.any(np.isfinite(np.array(primary_matrices)), axis=(0, 2)).sum()),
        'n_observations': sum(r['n_observations'] for r in primary),
        'valid_bootstrap_replicates': int(valid.sum()), 'status': 'estimable' if sufficient else 'insufficient'})
    return pd.DataFrame(rows)


def tables(df, measures, turns, summary, output):
    output.mkdir(parents=True, exist_ok=True)
    for name, frame in [('trials', df), ('measurements', measures), ('turns', turns), ('estimates', summary)]:
        frame.to_csv(output / (name + '.csv'), index=False)
    df.groupby(['configuration_id', 'frame', 'status']).size().rename('count').to_csv(output / 'trial_status.csv')
    measures.groupby(['configuration_id', 'frame', 'measurement']).agg(
        assigned=('trial_id', 'size'), valid=('valid', 'sum'), mean_impact=('impact', 'mean'),
        mean_freedom=('freedom', 'mean')).to_csv(output / 'missingness.csv')
    measures.groupby(['configuration_id', 'frame', 'measurement', 'impact'], dropna=False).size().rename('count').to_csv(output / 'impact_distribution.csv')
    measures.groupby(['configuration_id', 'frame', 'measurement', 'freedom'], dropna=False).size().rename('count').to_csv(output / 'freedom_distribution.csv')
    df.groupby(['configuration_id', 'frame', 'counterfactual_trajectory']).size().rename('count').to_csv(output / 'counterfactual_trajectories.csv')
    df.groupby(['configuration_id', 'frame', 'first_observed_pre_no', 'pre_measurements_complete']).size().rename('count').to_csv(output / 'first_observed_pre_no.csv')
    transitions = []
    for (cid, frame), part in df.groupby(['configuration_id', 'frame']):
        for first, last in ((1, 2), (2, 3), (3, 4), (1, 3), (1, 4)):
            pair = part[[f'm{first}_counterfactual', f'm{last}_counterfactual']].dropna()
            for a in ('yes', 'no'):
                for b in ('yes', 'no'):
                    count = ((pair.iloc[:, 0] == a) & (pair.iloc[:, 1] == b)).sum()
                    transitions.append({'configuration_id': cid, 'frame': frame, 'first': first,
                        'last': last, 'from': a, 'to': b, 'count': int(count), 'valid_pairs': len(pair)})
    pd.DataFrame(transitions).to_csv(output / 'counterfactual_transitions.csv', index=False)
    routes = []
    for r in (1, 2, 3):
        valid = df[df[f'm{r}_impact'].notna()]
        for key, count in valid.groupby(['configuration_id', 'frame', f'r{r}_route']).size().items():
            routes.append({'configuration_id': key[0], 'frame': key[1], 'round': r, 'route': key[2], 'count': count})
    pd.DataFrame(routes).to_csv(output / 'routes.csv', index=False)
    consistency = []
    for (cid, frame), part in df.groupby(['configuration_id', 'frame']):
        valid = part.m4_impact.notna()
        consistency.append({'configuration_id': cid, 'frame': frame, 'assigned': len(part),
            'valid_post': int(valid.sum()), 'counterfactual_no': int((part.m4_counterfactual == 'no').sum()),
            'impact_1': int((part.m4_impact == 1).sum())})
    pd.DataFrame(consistency).to_csv(output / 'post_evidence_consistency.csv', index=False)
    turns.groupby(['configuration_id']).agg(invocations=('trial_id', 'size'),
        known_durations=('duration_seconds', 'count'), median_turn_seconds=('duration_seconds', 'median'),
        timeouts=('timeout', 'sum'), input_tokens=('input_tokens', 'sum'),
        output_tokens=('output_tokens', 'sum')).to_csv(output / 'technical.csv')


def figures(config, df, measures, summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output.mkdir(parents=True, exist_ok=True)
    names, captions = [], {}
    def save(fig, name, caption):
        fig.tight_layout()
        for extension in ('svg', 'png'):
            fig.savefig(output / (name + '.' + extension), dpi=150, bbox_inches='tight')
        plt.close(fig)
        names.append(name)
        captions[name] = caption
    models = list(dict.fromkeys(c['model'] for c in config['configurations']))
    for metric in ('impact', 'freedom', 'counterfactual_yes'):
        fig, axes = plt.subplots(3, 3, figsize=(14, 10), sharex=True, sharey=True)
        for model, ax in zip(models, axes.flat):
            for effort in ('low', 'medium', 'high'):
                cid = model + '-' + effort
                rows = summary[(summary.configuration_id == cid) & summary.metric.isin([f'm{m}_{metric}' for m in range(1, 5)])].set_index('metric')
                rows = rows.reindex([f'm{m}_{metric}' for m in range(1, 5)])
                ax.plot(range(1, 5), rows.estimate, marker='o', label=effort, alpha=.85)
            ax.set_title(model)
            ax.set(xticks=range(1, 5), xticklabels=['R1', 'R2', 'R3', 'Post'],
                   ylim=(-.04, 1.04) if metric == 'counterfactual_yes' else (-4, 104))
            ax.grid(alpha=.2)
        for ax in list(axes.flat)[len(models):]:
            ax.set_visible(False)
        axes.flat[0].legend()
        fig.suptitle(metric.replace('_', ' ').title() + ' across measurements')
        save(fig, metric + '_trajectories', 'Endpoint-valid configuration means; lines connect measurement occasions, not independent samples. R1/R2/R3 are before disclosure. Axis margins preserve boundary points. Pointwise case-cluster intervals are in estimates.csv.')
    configs = sorted(df.configuration_id.unique())
    def intervals(ax, metric, include_overall=False):
        order = configs + (['ALL_EQUAL_CONFIGURATIONS'] if include_overall else [])
        part = summary[summary.metric == metric].set_index('configuration_id').reindex(order)
        ax.hlines(range(len(order)), part.ci_low, part.ci_high, color='#356db4')
        ax.scatter(part.estimate, range(len(order)), color='#356db4', zorder=3)
        ax.axvline(0, color='gray', lw=1)
        finite = np.r_[part.estimate, part.ci_low, part.ci_high, 0.]
        finite = finite[np.isfinite(finite)]
        low, high = finite.min(), finite.max()
        margin = max(1., (high - low) * .08)
        ax.set(xlim=(low - margin, high + margin), yticks=range(len(order)), yticklabels=order,
               xlabel='Rating difference (points)', title=metric.replace('_', ' '))
    fig, ax = plt.subplots(figsize=(10, 10))
    intervals(ax, 'm3_minus_m1_impact', True)
    save(fig, 'primary_repeat_changes', 'Primary within-trial Round 3 minus Round 1 impact; overall equally weights all 21 configurations. Nominal pointwise 95% intervals resample ten shared cases, 2,000 times. Associations over repeated experience; no unrepeated control.')
    fig, axes = plt.subplots(1, 2, figsize=(15, 10))
    for ax, key in zip(axes, ('impact', 'freedom')):
        intervals(ax, 'm4_minus_m3_' + key)
    save(fig, 'disclosure_changes', 'Within-trial post-disclosure minus Round 3 judgments. Nominal pointwise case-cluster intervals. Panel axes adapt independently; explanation, evidence, and later measurement are bundled.')
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    bins, labels = [0, 1, 24, 49, 74, 99, 100], ['1', '2–24', '25–49', '50–74', '75–99', '100']
    for ax, key in zip(axes, ('impact', 'freedom')):
        bottoms = np.zeros(4)
        for lo, hi, label in zip(bins[:-1], bins[1:], labels):
            values = np.array([((part[key] > lo) & (part[key] <= hi)).sum() / part[key].count()
                if part[key].count() else 0 for m in range(1, 5)
                for part in [measures[measures.measurement == m]]])
            ax.bar(range(1, 5), values, bottom=bottoms, label=label)
            bottoms += values
        ax.set(xticks=range(1, 5), xticklabels=LABELS, ylim=(0, 1.05), title=key.title(), ylabel='Fraction among valid ratings')
    axes[-1].legend(title='Rating', bbox_to_anchor=(1.02, 1))
    save(fig, 'rating_distributions', 'Frequency-aware pooled rating bins; exact 1 and 100 boundaries are separate categories. Valid endpoint denominators can differ; distributions pool configurations descriptively.')
    transitions = pd.read_csv(output.parent / 'tables/counterfactual_transitions.csv')
    matrix = np.array([[transitions[(transitions['first'] == first) & (transitions['last'] == last) &
        (transitions['from'] == a) & (transitions['to'] == b)]['count'].sum()
        for first, last in ((1, 2), (2, 3), (3, 4))]
        for a, b in (('yes', 'yes'), ('yes', 'no'), ('no', 'yes'), ('no', 'no'))])
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.imshow(matrix, cmap='Blues')
    for i in range(4):
        for j in range(3):
            ax.text(j, i, str(matrix[i, j]), ha='center', va='center', color='white' if matrix[i, j] > matrix.max() / 2 else 'black')
    ax.set(xticks=range(3), xticklabels=['R1→R2', 'R2→R3', 'R3→Post'],
           yticks=range(4), yticklabels=['yes→yes', 'yes→no', 'no→yes', 'no→no'])
    save(fig, 'counterfactual_transitions', 'Pooled counts of valid within-trial adjacent counterfactual pairs. Missing pairs excluded and retained in missingness tables. Individual complete/incomplete trajectories remain in CSV.')
    fig, axes = plt.subplots(2, 4, figsize=(24, 15))
    for row, key in enumerate(('impact', 'freedom')):
        for m in range(1, 5):
            intervals(axes[row, m - 1], f'cats_minus_cards_m{m}_{key}')
    save(fig, 'frame_differences', 'Cats minus cards within the same case/configuration at each occasion. Nominal pointwise 95% case-cluster intervals. Frame wording changes nouns, names, and verbs together; no isolated object-category effect.')
    fig, axes = plt.subplots(1, 2, figsize=(15, 10))
    failures = df.assign(failed=df.status.isin(['failed', 'interrupted'])).groupby('configuration_id').failed.mean().reindex(configs)
    axes[0].barh(range(len(configs)), failures)
    axes[0].set(yticks=range(len(configs)), yticklabels=configs, xlim=(0, max(.02, failures.max() * 1.25)), xlabel='Failed/interrupted / assigned trials')
    latency = df[df.status == 'complete'].groupby('configuration_id').recorded_turn_seconds.median().reindex(configs)
    axes[1].barh(range(len(configs)), latency)
    axes[1].set(yticks=range(len(configs)), yticklabels=configs, xlabel='Median sum of ten recorded turn durations (seconds)')
    save(fig, 'technical_failures', 'Assigned denominator for failures; latency includes only complete trials with all ten durations known. Operational concurrency and service state vary, so this is not a controlled speed ranking.')
    write_json(output.parent / 'figure_captions.json', captions)
    return names, captions


def markdown_table(frame):
    columns = list(frame.columns)
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    for row in frame.itertuples(index=False, name=None):
        lines.append('| ' + ' | '.join(f'{v:.3f}' if isinstance(v, (float, np.floating)) else str(v) for v in row) + ' |')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    frozen_hashes()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    config, df, measures, turns = load(output)
    summary = estimates(config, df)
    tables(df, measures, turns, summary, output / 'tables')
    names, captions = figures(config, df, measures, summary, output / 'figures')
    aggregate = measures.groupby('measurement').agg(valid=('valid', 'sum'),
        mean_impact=('impact', 'mean'), mean_freedom=('freedom', 'mean'),
        yes=('counterfactual', lambda s: (s == 'yes').sum()), no=('counterfactual', lambda s: (s == 'no').sum())).reset_index()
    primary = summary[summary.metric == 'm3_minus_m1_impact']
    overall = primary[primary.configuration_id == 'ALL_EQUAL_CONFIGURATIONS'].iloc[0]
    provenance = {'run_id': config['run_id'], 'integration_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'freeze_sha256': digest(FREEZE), 'analysis_source_sha256': digest(Path(__file__)),
        'assigned': len(df), 'status_counts': df.status.value_counts().to_dict(),
        'evaluation_invocations': int(sum(a['subject_invocations'] for a in read_json(output / 'union_audit.json')['workers'])),
        'valid_measurements': {f'm{int(r.measurement)}': int(r.valid) for r in aggregate.itertuples()},
        'bootstrap_seed': config['seeds']['bootstrap'], 'bootstrap_replicates': 2000, 'shared_case_clusters': 10,
        'unknown_duration_turns': int(turns.duration_seconds.isna().sum()),
        'actual_http_attempts': None, 'backend_versions': None, 'billing_cost': None}
    write_json(output / 'provenance.json', provenance)
    post = df[df.m4_impact.notna()]
    report = f'''# Experiment 2: Three repeated equivoque rounds

Run `{config['run_id']}`. Collection finished and raw integrity checks passed.
420 assigned native trial sessions, ten shared starting cases, three rounds per
trial, four measurements, and {provenance['evaluation_invocations']} evaluation invocations.
Terminal statuses: {json.dumps(provenance['status_counts'])}.

## Observed longitudinal results

The equally weighted 21-configuration mean within-trial Round 3 minus Round 1
impact was {overall.estimate:.3f} points (nominal pointwise 95% case-cluster
interval {overall.ci_low:.3f} to {overall.ci_high:.3f}; {overall.status}). This
describes change before explicit disclosure, rather than an isolated causal
effect of repetition. Endpoint means and answer counts are below.

{markdown_table(aggregate)}

Among {len(post)} valid post-disclosure endpoints, {(post.m4_counterfactual == 'no').sum()}
counterfactual answers were no and {(post.m4_impact == 1).sum()} impact ratings were 1.
Freedom to choose and influence on the final object are distinct judgments;
high post-disclosure freedom is not an error.

## Primary configuration estimates

{markdown_table(primary[['configuration_id', 'estimate', 'ci_low', 'ci_high', 'n_cases', 'n_observations', 'status']])}

## Analysis and interpretation

Every interval resamples the same ten shared cases across frames, configurations,
and occasions, with 2,000 replicates and the frozen seed. Contrasts use only valid
pairs; missing endpoints are not imputed. Require five contributing cases and
95% estimable replicates; overall estimates require all 21 configurations.
Intervals are nominal pointwise 95%, without confirmatory multiple-comparison or
model-ranking claims. Boundary ratings can make bootstrap intervals degenerate;
this does not prove exact equality outside the recorded task.

Three repetitions bundle additional choices, repeated final labels, repeated
questions, and a longer conversation; there is no unrepeated randomized control.
The disclosure combines explanation, exhaustive evidence, and later measurement.
Card/cat wording changes nouns, names, and verbs together. Routes arise from model
choices. Pre-disclosure no responses are observed judgments, not proof the subject
identified the hidden procedure. Results concern these frozen English prompts and
native context, not human subjective experience or general reasoning accuracy.

The native empty working-directory context can contain the run/repository name.
Subjects receive no repository files, worker brief, hidden assignments, or tools.
Requested model/effort settings are retained; backend versions, actual HTTP attempt
counts, and billing cost are unknown. Operational latency excludes failed trials
and trials with unknown durations; changing concurrency is not a controlled
model speed comparison. Earlier valid endpoints in failures remain included.

Experiment 1 remains separate and is not a randomized control. See the prospective
EXPERIMENT_2_PLAN.md, provenance.json, union_audit.json, tidy tables, and figure
captions for exact definitions, denominators, records, and technical limitations.
'''
    (output / 'REPORT.md').write_text(report)
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Experiment 2 results</title><style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:16px system-ui;color:#18232d}figure{margin:32px 0}svg{width:100%;height:auto}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd}figcaption{color:#526171}</style><h1>Experiment 2: Three repeated rounds</h1><p>420 assigned trials; ten shared case clusters; three rounds before final disclosure.</p><p>Primary mean R3−R1 impact: ' + f'{overall.estimate:.3f} points; 95% interval {overall.ci_low:.3f} to {overall.ci_high:.3f}.' + '</p>' + aggregate.to_html(index=False)
    for name in names:
        svg = (output / 'figures' / (name + '.svg')).read_text()
        svg = svg[svg.index('<svg'):]
        html += '<figure>' + svg + '<figcaption>' + captions[name] + '</figcaption></figure>'
    html += '<p>Nominal pointwise intervals; descriptive longitudinal associations. No unrepeated randomized control. Full exact tables and report accompany this standalone visualization.</p></html>'
    (output / 'index.html').write_text(html)
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    main()
