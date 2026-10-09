"""Prespecified analysis of audited native evaluation records, never calibration.

Run from the integration worktree after collection. No subject requests are made.
The frozen EXPERIMENT_PLAN.md is the authority for estimands and exclusions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equivoque.audit import audit_worker
from equivoque.core import digest, frozen_hashes, read_json, write_json

ROUTES = ('KK', 'DD', 'KD', 'DK')


def endpoints(state):
    """Use validated endpoints independently, including a valid pre-only trial."""
    result = {}
    for turn in state.get('turns', []):
        if turn.get('ok') and turn.get('turn') in (3, 4) and 'parsed' in turn:
            phase = 'pre' if turn['turn'] == 3 else 'post'
            result.update({f'{phase}_{k}': v for k, v in turn['parsed'].items()})
    return result


def load_records(root=ROOT, allow_incomplete=False):
    frozen_hashes()
    config = read_json(root / 'protocol/run.v1.json')
    run = config['run_id']
    scheduled = read_json(root / 'manifests' / run / 'schedule.json')
    records, turn_rows, audits = [], [], []
    seen_ids, sessions, calibration_sessions = set(), set(), set()
    runtime = root / 'preparation/current-runtime'
    resumes = []
    for number in (2, 3):
        resume_path = runtime / f'executor-assignments-{number:02d}.json'
        if resume_path.exists():
            resume = read_json(resume_path)
            ids = {trial_id for entry in resume['executors'].values()
                   for trial_id in entry['trial_ids']}
            gate = read_json(runtime / f'coordinator-launch-{number + 2:02d}.json')
            resumes.append((f'resume-{number:02d}', gate['released_at'], ids))
    def turn_epoch(trial_id, stamp, default):
        for name, released, ids in reversed(resumes):
            if trial_id in ids and stamp >= released:
                return name
        return default
    for path in runtime.glob('service-preflight-*/*.json'):
        session = read_json(path).get('session_id')
        if session:
            calibration_sessions.add(session)
    for path in runtime.glob('development-access-*.json'):
        data = read_json(path)
        session = data.get('session_id') or data.get('result', {}).get('session_id')
        if session:
            calibration_sessions.add(session)
    for worker in config['workers']:
        directory = root / 'results' / run / f'worker-{worker}'
        manifest_path = root / 'manifests' / run / f'worker-{worker}.json'
        manifest = read_json(manifest_path)
        if manifest['schedule_sha256'] != digest(root / 'manifests' / run / 'schedule.json'):
            raise ValueError('Manifest schedule hash mismatch')
        audit = audit_worker(manifest_path, directory)
        if not audit['integrity_ok']:
            raise ValueError(f'Worker {worker} audit failed: {audit["errors"]}')
        if not audit['collection_finished'] and not allow_incomplete:
            raise ValueError(f'Worker {worker} collection unfinished; no final analysis')
        audits.append(audit)
        for p in directory.glob('preflight*/native-session-check.json'):
            s = read_json(p).get('session_id')
            if s:
                calibration_sessions.add(s)
        executor_by_trial = {}
        for profile in directory.glob('executor-*-provenance.json'):
            metadata = read_json(profile)
            if metadata['logical_worker'] != worker:
                raise ValueError('Executor provenance changes logical ownership')
            manifest_ids = {t['trial_id'] for t in manifest['trials']}
            if not set(metadata['trial_ids']) <= manifest_ids:
                raise ValueError('Executor provenance lists unassigned trials')
            for trial_id in metadata['trial_ids']:
                if trial_id in executor_by_trial:
                    raise ValueError('Overlapping exclusive executor provenance')
                executor_by_trial[trial_id] = metadata['executor_id']
        states = {read_json(p)['trial']['trial_id']: read_json(p)
                  for p in (directory / 'trials').glob('*.json')}
        for path in (directory / 'trials').glob('*.json'):
            state = read_json(path)
            raw = [json.loads(line) for line in path.with_suffix('.journal.jsonl').read_text().splitlines()]
            responses = [x for x in raw if x.get('type') == 'response_checkpoint']
            for record, original in zip(state['turns'], responses):
                checkpoint = {k: v for k, v in original.items() if k != 'type'}
                parsed_record = {k: v for k, v in record.items() if k != 'parsed'}
                if checkpoint != parsed_record:
                    raise ValueError('Full raw response/checkpoint mismatch, including provider options')
        if states:
            provenance = read_json(directory / 'provenance.json')
            if provenance['manifest_sha256'] != digest(manifest_path) or (
                    provenance['freeze_sha256'] != digest(root / 'protocol/freeze.json')):
                raise ValueError('Worker provenance hash mismatch')
        for trial in manifest['trials']:
            if trial['trial_id'] in seen_ids:
                raise ValueError('Overlapping worker manifests')
            seen_ids.add(trial['trial_id'])
            state = states.get(trial['trial_id'], {})
            session = state.get('session_id')
            if session and session in sessions:
                raise ValueError('Native session reused across shards')
            if session:
                sessions.add(session)
            default_epoch = 'expanded-01' if trial['trial_id'] in executor_by_trial else 'initial-or-resume'
            epochs = list(dict.fromkeys(turn_epoch(trial['trial_id'], t['requested_at'], default_epoch)
                                        for t in state.get('turns', [])))
            epoch = (epochs[0] if len(epochs) == 1 else 'spans-' + '-'.join(epochs)) if epochs else default_epoch
            row = {**trial, 'actual_executor_id': executor_by_trial.get(trial['trial_id'], worker),
                   'execution_epoch': epoch,
                   'status': state.get('status', 'unattempted'),
                   'route': state.get('route', ''), 'session_id': session,
                   'started_at': state.get('started_at'),
                   'ended_at': state.get('ended_at'), 'error': state.get('error'),
                   'target_position': trial['order'].index(trial['target']) + 1,
                   'recorded_turn_seconds': (sum(t['duration_seconds'] for t in state.get('turns', []))
                       if all(t.get('duration_seconds') is not None for t in state.get('turns', []))
                       else np.nan),
                   **endpoints(state)}
            for turn in state.get('turns', []):
                usage = turn.get('usage') or {}
                turn_rows.append({
                    'trial_id': trial['trial_id'], 'case_id': trial['case_id'],
                    'configuration_id': trial['configuration_id'],
                    'worker_id': worker, 'actual_executor_id': executor_by_trial.get(trial['trial_id'], worker),
                    'execution_epoch': turn_epoch(trial['trial_id'], turn['requested_at'], default_epoch),
                    'frame': trial['frame'], 'turn': turn['turn'],
                    'ok': turn['ok'], 'duration_seconds': turn['duration_seconds'],
                    'input_tokens': usage.get('input_tokens'),
                    'cached_input_tokens': usage.get('cached_input_tokens'),
                    'output_tokens': usage.get('output_tokens'),
                    'requested_at': turn['requested_at'],
                    'received_at': turn['received_at'],
                    'timeout': turn.get('timeout'), 'exit_code': turn.get('exit_code'),
                    'requested_model': trial['model'], 'requested_effort': trial['effort'],
                    'observed_provider_model': None, 'billed_cost': None,
                })
                if turn.get('parsed') and turn['turn'] == 1:
                    row['first_selection'] = ','.join(turn['parsed']['selection'])
                if turn.get('parsed') and turn['turn'] == 2:
                    row['second_selection'] = turn['parsed']['selection']
            records.append(row)
    schedule_ids = {t['trial_id'] for t in scheduled['trials']}
    if seen_ids != schedule_ids or len(records) != config['total_trials']:
        raise ValueError('Worker union differs from complete scheduled roster')
    if sessions & calibration_sessions:
        raise ValueError('Evaluation reused a calibration session')
    df = pd.DataFrame(records)
    for phase in ('pre', 'post'):
        for metric in ('impact', 'freedom', 'counterfactual'):
            if f'{phase}_{metric}' not in df:
                df[f'{phase}_{metric}'] = np.nan
    if df['pre_impact'].notna().sum() == 0:
        raise ValueError('No valid evaluation outcomes; do not generate result figures')
    return config, df, pd.DataFrame(turn_rows), audits


class CaseBootstrap:
    """One shared draw matrix retains all frames/configurations of each case."""
    def __init__(self, cases, seed, replicates=2000):
        self.cases = tuple(sorted(cases))
        self.replicates = replicates
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, len(cases), size=(replicates, len(cases)))
        self.weights = np.zeros((replicates, len(cases)), dtype=int)
        for i, sample in enumerate(draws):
            self.weights[i] = np.bincount(sample, minlength=len(cases))

    def means(self, rows, value):
        valid = rows.dropna(subset=[value])
        stats = valid.groupby('case_id')[value].agg(['sum', 'count']).reindex(
            self.cases, fill_value=0)
        numerator = self.weights @ stats['sum'].to_numpy(dtype=float)
        denominator = self.weights @ stats['count'].to_numpy(dtype=float)
        samples = np.divide(numerator, denominator, out=np.full_like(numerator, np.nan),
                            where=denominator > 0)
        mean = valid[value].mean() if len(valid) else np.nan
        return mean, samples, len(valid), valid['case_id'].nunique()


def estimate_record(configuration, metric, point, samples, n, cases,
                    primary_eligible=True, **extra):
    valid = samples[np.isfinite(samples)]
    enough = primary_eligible and len(valid) >= .95 * len(samples) and n > 0
    interval = np.percentile(valid, [2.5, 97.5]) if enough else (np.nan, np.nan)
    return {'configuration_id': configuration, 'metric': metric,
            'estimate': point if primary_eligible and (
                metric != 'primary_route_association' or enough) else np.nan,
            'ci_low': interval[0], 'ci_high': interval[1],
            'n_trials': n, 'n_cases': cases, 'valid_bootstrap_replicates': len(valid),
            'bootstrap_replicates': len(samples),
            'status': 'estimable' if enough else 'insufficient', **extra}


def estimates(df, bootstrap):
    output = []
    for configuration, group in df.groupby('configuration_id', sort=True):
        route_means = {r: bootstrap.means(group[group.route == r], 'pre_impact')
                       for r in ROUTES}
        samples = (route_means['KK'][1] + route_means['DD'][1] -
                   route_means['KD'][1] - route_means['DK'][1]) / 2
        point = (route_means['KK'][0] + route_means['DD'][0] -
                 route_means['KD'][0] - route_means['DK'][0]) / 2
        valid_pre = group[group.pre_impact.notna()]
        counts = {f'n_{r}': route_means[r][2] for r in ROUTES}
        output.append(estimate_record(configuration, 'primary_route_association',
            point, samples, len(valid_pre), valid_pre.case_id.nunique(),
            primary_eligible=all(m[2] >= 10 for m in route_means.values()), **counts))
        for a, b in (('KK', 'DD'), ('KD', 'DK')):
            selected = valid_pre[valid_pre.route.isin([a, b])]
            output.append(estimate_record(configuration, f'route_{a}_minus_{b}',
                route_means[a][0] - route_means[b][0],
                route_means[a][1] - route_means[b][1],
                len(selected), selected.case_id.nunique()))
        for metric in ('impact', 'freedom'):
            paired = group.dropna(subset=[f'pre_{metric}', f'post_{metric}']).copy()
            paired['change'] = paired[f'post_{metric}'] - paired[f'pre_{metric}']
            output.append(estimate_record(configuration, f'disclosure_change_{metric}',
                                          *bootstrap.means(paired, 'change')))
            for phase in ('pre', 'post'):
                column = f'{phase}_{metric}'
                pivot = group.pivot(index='case_id', columns='frame', values=column)
                pivot['difference'] = pivot['cats'] - pivot['cards']
                matched = pivot.dropna(subset=['difference']).reset_index()
                point, samples, n_pairs, n_cases = bootstrap.means(matched, 'difference')
                output.append(estimate_record(configuration, f'cats_minus_cards_{column}',
                    point, samples, n_pairs * 2, n_cases, n_pairs=n_pairs))
                for frame in ('cards', 'cats'):
                    output.append(estimate_record(configuration, f'{frame}_{column}_mean',
                        *bootstrap.means(group[group.frame == frame], column)))
    return pd.DataFrame(output)


def write_tables(df, turns, summary, output):
    tables = output / 'tables'
    tables.mkdir(parents=True)
    export = df.copy()
    export['order'] = export['order'].map(lambda x: ','.join(x))
    export.to_csv(tables / 'trials.csv', index=False)
    turns.to_csv(tables / 'turns.csv', index=False)
    summary.to_csv(tables / 'estimates.csv', index=False)
    counts = df.groupby(['configuration_id', 'frame', 'status']).size().rename('count')
    counts.to_csv(tables / 'trial_status.csv')
    df[df.status.isin(['failed', 'interrupted'])].groupby(
        ['configuration_id', 'frame', 'error'], dropna=False).size().rename('count').to_csv(
            tables / 'failure_types.csv')
    routes = df[df.pre_impact.notna()].groupby(['configuration_id', 'frame', 'route']).size()
    index = pd.MultiIndex.from_product([sorted(df.configuration_id.unique()),
        ['cards', 'cats'], ROUTES], names=['configuration_id', 'frame', 'route'])
    routes.reindex(index, fill_value=0).rename('valid_pre_trials').to_csv(tables / 'routes.csv')
    transitions = df.dropna(subset=['pre_counterfactual', 'post_counterfactual']).groupby(
        ['configuration_id', 'frame', 'pre_counterfactual', 'post_counterfactual']).size()
    transition_index = pd.MultiIndex.from_product([sorted(df.configuration_id.unique()),
        ['cards', 'cats'], ['yes', 'no'], ['yes', 'no']],
        names=['configuration_id', 'frame', 'pre_counterfactual', 'post_counterfactual'])
    transitions.reindex(transition_index, fill_value=0).rename('count').to_csv(
        tables / 'counterfactual_transitions.csv')
    evidence = []
    missingness = []
    for (configuration, frame), g in df.groupby(['configuration_id', 'frame']):
        post = g[g.post_impact.notna()]
        evidence.append({'configuration_id': configuration, 'frame': frame,
            'assigned': len(g), 'valid_post': len(post),
            'counterfactual_no_count': (post.post_counterfactual == 'no').sum(),
            'counterfactual_no_rate': (post.post_counterfactual == 'no').mean(),
            'minimum_impact_count': (post.post_impact == 1).sum(),
            'minimum_impact_rate': (post.post_impact == 1).mean()})
        missingness.append({'configuration_id': configuration, 'frame': frame,
            'assigned': len(g), 'valid_pre': g.pre_impact.notna().sum(),
            'valid_post': g.post_impact.notna().sum(),
            'valid_pre_post_pairs': (g.pre_impact.notna() & g.post_impact.notna()).sum(),
            'failed': (g.status == 'failed').sum(),
            'interrupted': (g.status == 'interrupted').sum(),
            'unattempted': (g.status == 'unattempted').sum()})
    pd.DataFrame(evidence).to_csv(tables / 'post_evidence_consistency.csv', index=False)
    pd.DataFrame(missingness).to_csv(tables / 'missingness.csv', index=False)
    for factors, name in [(['configuration_id', 'frame', 'target', 'target_position'], 'target_position'),
                          (['configuration_id', 'frame', 'first_selection', 'second_selection'], 'choices'),
                          (['configuration_id', 'frame', 'worker_id'], 'worker'),
                          (['configuration_id', 'frame', 'actual_executor_id', 'execution_epoch'], 'executor')]:
        df.groupby(factors, dropna=False).agg(assigned=('trial_id', 'size'),
            valid_pre=('pre_impact', 'count'), pre_impact_mean=('pre_impact', 'mean'),
            valid_post=('post_impact', 'count'), post_impact_mean=('post_impact', 'mean')).to_csv(
                tables / f'descriptive_{name}.csv')
    technical = turns.groupby(['configuration_id', 'frame', 'worker_id']).agg(
        returned_invocations=('trial_id', 'size'),
        known_duration_turns=('duration_seconds', 'count'),
        known_exit_code_turns=('exit_code', 'count'),
        reported_usage_turns=('input_tokens', 'count'),
        timeout_turns=('timeout', 'sum'),
        latency_mean_seconds=('duration_seconds', 'mean'),
        latency_median_seconds=('duration_seconds', 'median'),
        latency_p95_seconds=('duration_seconds', lambda x: x.quantile(.95)),
        input_tokens=('input_tokens', lambda x: x.sum(min_count=1)),
        cached_input_tokens=('cached_input_tokens', lambda x: x.sum(min_count=1)),
        output_tokens=('output_tokens', lambda x: x.sum(min_count=1)))
    technical.to_csv(tables / 'technical.csv')
    turns.groupby(['actual_executor_id']).agg(
        returned_invocations=('trial_id', 'size'),
        known_duration_turns=('duration_seconds', 'count'),
        latency_mean_seconds=('duration_seconds', 'mean'),
        latency_median_seconds=('duration_seconds', 'median')).to_csv(tables / 'technical_executors.csv')
    timed = turns.copy()
    timed['hour_utc'] = pd.to_datetime(timed.requested_at).dt.floor('h')
    timed.groupby(['configuration_id', 'hour_utc']).agg(
        returned_invocations=('trial_id', 'size'),
        known_duration_turns=('duration_seconds', 'count'),
        latency_median_seconds=('duration_seconds', 'median')).to_csv(tables / 'descriptive_time.csv')


def figures(df, summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    folder = output / 'figures'
    folder.mkdir()
    configurations = sorted(df.configuration_id.unique())
    colors = {'cards': '#3b6fb6', 'cats': '#d27c32'}
    captions = {}

    def save(fig, name, caption):
        fig.savefig(folder / f'{name}.svg', bbox_inches='tight')
        fig.savefig(folder / f'{name}.png', dpi=180, bbox_inches='tight')
        plt.close(fig)
        captions[name] = caption

    fig, axes = plt.subplots(1, 2, figsize=(12, 10), sharey=True)
    for ax, frame in zip(axes, ('cards', 'cats')):
        g = df[(df.frame == frame) & df.pre_impact.notna()]
        counts = pd.crosstab(g.configuration_id, g.route).reindex(
            index=configurations, columns=ROUTES, fill_value=0).fillna(0)
        ax.imshow(counts, norm=Normalize(0, 50), cmap='Blues', aspect='auto')
        for y in range(len(counts)):
            for x in range(4):
                ax.text(x, y, str(int(counts.iloc[y, x])), ha='center', va='center',
                        color='white' if counts.iloc[y, x] > 30 else 'black')
        ax.set(xticks=range(4), xticklabels=ROUTES, title=frame.title(),
               yticks=range(len(configurations)), yticklabels=configurations)
    save(fig, 'route_counts', 'Counts among valid Turn 3 trials; zero and sparse cells are retained. Routes arise from choices, not randomized treatments.')
    fig, ax = plt.subplots(figsize=(11, 10))
    for y, c in enumerate(configurations):
        for offset, frame in [(-.18, 'cards'), (.18, 'cats')]:
            values = df[(df.configuration_id == c) & (df.frame == frame)].pre_impact.dropna()
            if len(values):
                b = ax.boxplot([values], positions=[y + offset], vert=False,
                    widths=.28, patch_artist=True, manage_ticks=False, showfliers=True)
                b['boxes'][0].set_facecolor(colors[frame])
    ax.set(xlim=(1, 100), xlabel='Pre-disclosure impact (1–100)',
           yticks=range(len(configurations)), yticklabels=configurations)
    save(fig, 'pre_impact_distributions', 'Blue: cards; orange: cats. Boxes show median and quartiles, whiskers 1.5 IQR, with outliers; only valid Turn 3 ratings contribute.')
    for name, metrics in [('primary_route_association', ['primary_route_association']),
        ('disclosure_changes', ['disclosure_change_impact', 'disclosure_change_freedom']),
        ('frame_differences', ['cats_minus_cards_pre_impact', 'cats_minus_cards_post_impact',
                             'cats_minus_cards_pre_freedom', 'cats_minus_cards_post_freedom'])]:
        fig, axes = plt.subplots(1, len(metrics), figsize=(6 * len(metrics), 10), sharey=True, squeeze=False)
        for ax, metric in zip(axes[0], metrics):
            s = summary[summary.metric == metric].set_index('configuration_id').reindex(configurations)
            for y, (_, r) in enumerate(s.iterrows()):
                if r.status == 'estimable':
                    ax.plot([r.ci_low, r.ci_high], [y, y], color='#3b6fb6')
                    ax.scatter(r.estimate, y, color='#3b6fb6')
                else:
                    ax.text(0, y, 'insufficient', ha='center', fontsize=8)
            ax.axvline(0, color='gray', linewidth=.7)
            ax.set(xlim=(-99, 99), yticks=range(len(configurations)), yticklabels=configurations,
                   title=metric.replace('_', ' '), xlabel='Rating difference (points)')
        save(fig, name, 'Nominal pointwise 95% percentile intervals from 2,000 paired-case cluster replicates. Primary associations require at least 10 trials per route and 95% estimable replicates. Changes use within-trial pairs; frame differences use within-case card/cat pairs. No confirmatory tests.')
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)
    for ax, phase in zip(axes, ('pre', 'post')):
        for frame in ('cards', 'cats'):
            g = df[df.frame == frame]
            ax.scatter(g[f'{phase}_freedom'], g[f'{phase}_impact'], alpha=.2,
                       s=12, color=colors[frame], label=frame)
        ax.set(xlim=(1, 100), ylim=(1, 100), xlabel='Freedom (1–100)',
               ylabel='Impact (1–100)', title=phase.title())
        ax.legend()
    save(fig, 'freedom_vs_impact', 'Valid ratings on the common 1–100 scales. Freedom to choose and influence on the final object are distinct judgments; high post freedom is not an error.')
    fig, ax = plt.subplots(figsize=(11, 10))
    for offset, endpoint in [(-.18, 'post_counterfactual'), (.18, 'post_impact')]:
        rates = df.groupby('configuration_id')[endpoint].apply(
            lambda x: (x.dropna() == ('no' if endpoint.endswith('counterfactual') else 1)).mean()).reindex(configurations)
        ax.barh(np.arange(len(configurations)) + offset, rates, height=.32,
                label='Counterfactual no' if endpoint.endswith('counterfactual') else 'Impact = 1')
    ax.set(xlim=(0, 1), xlabel='Rate among valid post-disclosure endpoints',
           yticks=range(len(configurations)), yticklabels=configurations)
    ax.legend()
    save(fig, 'post_evidence_consistency', 'Endpoint-specific valid Turn 4 denominators; post counterfactual no and impact 1 match the disclosed fixed-target evidence. The CSV retains counts and denominators.')
    fig, axes = plt.subplots(1, 2, figsize=(12, 10), sharey=True)
    transitions = [('yes', 'yes'), ('yes', 'no'), ('no', 'yes'), ('no', 'no')]
    for ax, frame in zip(axes, ('cards', 'cats')):
        values = np.zeros((len(configurations), 4), dtype=int)
        for y, c in enumerate(configurations):
            g = df[(df.configuration_id == c) & (df.frame == frame)]
            for x, (pre, post) in enumerate(transitions):
                values[y, x] = ((g.pre_counterfactual == pre) & (g.post_counterfactual == post)).sum()
        ax.imshow(values, norm=Normalize(0, 50), cmap='Blues', aspect='auto')
        for y in range(len(configurations)):
            for x in range(4):
                ax.text(x, y, str(values[y, x]), ha='center', va='center',
                        color='white' if values[y, x] > 30 else 'black')
        ax.set(xticks=range(4), xticklabels=['yes → yes', 'yes → no', 'no → yes', 'no → no'],
               yticks=range(len(configurations)), yticklabels=configurations, title=frame.title())
    save(fig, 'counterfactual_transitions', 'Counts of valid within-trial pre/post counterfactual pairs. Missing endpoints are excluded from transitions and remain visible in the missingness table. No is evidence-consistent after disclosure.')
    fig, axes = plt.subplots(1, 2, figsize=(13, 10), sharey=True)
    failures = df.assign(failed=df.status.isin(['failed', 'interrupted'])).groupby('configuration_id').failed.mean().reindex(configurations)
    axes[0].barh(range(len(configurations)), failures)
    axes[0].set(xlim=(0, 1), xlabel='Failed/interrupted / assigned trials',
                yticks=range(len(configurations)), yticklabels=configurations)
    durations = df[df.status == 'complete'].groupby('configuration_id').recorded_turn_seconds.median().reindex(configurations)
    axes[1].barh(range(len(configurations)), durations)
    axes[1].set(xlabel='Median sum of recorded turn durations, complete trials (seconds)')
    save(fig, 'technical_failures', 'Failures remain in the assigned denominator. Latency uses complete trials only; raw per-turn latencies, usage, and unattempted counts are retained separately in tables. Billing cost and actual HTTP attempt counts are unavailable.')
    write_json(output / 'figure_captions.json', captions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-incomplete', action='store_true',
                        help='Explicitly label aborted/partial collection; never treats it as final')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('Use a new analysis output directory; preserve previous analysis')
    config, df, turns, audits = load_records(allow_incomplete=args.allow_incomplete)
    bootstrap = CaseBootstrap(df.case_id.unique(), config['seeds']['bootstrap'])
    summary = estimates(df, bootstrap)
    output.mkdir(parents=True)
    write_tables(df, turns, summary, output)
    figures(df, summary, output)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    provenance = {'run_id': config['run_id'], 'integration_commit': revision,
        'protocol_sha256': digest(ROOT / 'protocol/prompts.v1.json'),
        'freeze_sha256': digest(ROOT / 'protocol/freeze.json'),
        'analysis_source_sha256': digest(Path(__file__)),
        'analysis_seed': config['seeds']['bootstrap'], 'bootstrap_replicates': 2000,
        'incomplete_collection': any(not a['collection_finished'] for a in audits),
        'assigned': len(df), 'status_counts': df.status.value_counts().to_dict(),
        'valid_pre': int(df.pre_impact.notna().sum()),
        'valid_post': int(df.post_impact.notna().sum()),
        'subject_invocations': sum(a['subject_invocations'] for a in audits),
        'unknown_duration_turns': int(turns.duration_seconds.isna().sum()),
        'unknown_exit_code_turns': int(turns.exit_code.isna().sum()),
        'actual_http_requests': None, 'billing_cost': None,
        'observed_provider_model': None,
        'native_versions_note': 'The CLI logs requested model/effort. Its public event stream does not independently identify backend model versions.',
        'library_versions': {'numpy': np.__version__, 'pandas': pd.__version__}}
    write_json(output / 'provenance.json', provenance)
    write_json(output / 'union_audit.json', {'integrity_ok': True, 'workers': audits})
    primary = summary[summary.metric == 'primary_route_association']
    def markdown_table(table, columns):
        def cell(value):
            if pd.isna(value):
                return '—'
            if isinstance(value, (float, np.floating)):
                return f'{value:.2f}'
            return str(value).replace('|', '\\|')
        return ['| ' + ' | '.join(columns) + ' |',
                '| ' + ' | '.join(['---'] * len(columns)) + ' |'] + [
            '| ' + ' | '.join(cell(row[k]) for k in columns) + ' |'
            for _, row in table.iterrows()]

    calibration = []
    for worker in config['workers']:
        for path in (ROOT / 'results' / config['run_id'] / f'worker-{worker}').glob('preflight*/readiness.json'):
            r = read_json(path)
            calibration.append({'worker_id': worker, 'executor_id': r.get('executor_id', worker), 'attempt': path.parent.name,
                'subject_invocations': r['subject_invocations'], 'ready': r['ready'],
                'base_commit': r['base_commit']})
    pd.DataFrame(calibration).to_csv(output / 'tables/calibration_attempts.csv', index=False)
    provenance['worker_calibration_invocations'] = sum(r['subject_invocations'] for r in calibration)
    provenance['development_invocations'] = sum(read_json(p).get('subject_invocations', 0)
        for p in (ROOT / 'preparation/current-runtime').glob('development-access-*.json'))
    service_calibration = []
    for path in (ROOT / 'preparation/current-runtime').glob('service-preflight-*/readiness.json'):
        readiness = read_json(path)
        service_calibration.append({'attempt': path.parent.name, 'ready': readiness['ready'],
            'subject_invocations': readiness['subject_invocations'],
            'base_commit': readiness['base_commit'], 'freeze_sha256': readiness['freeze_sha256']})
    pd.DataFrame(service_calibration).to_csv(output / 'tables/service_calibration_attempts.csv', index=False)
    provenance['shared_service_calibration_invocations'] = sum(r['subject_invocations'] for r in service_calibration)
    provenance['non_evaluation_invocations'] = (provenance['worker_calibration_invocations']
        + provenance['development_invocations'] + provenance['shared_service_calibration_invocations'])
    write_json(output / 'provenance.json', provenance)
    lines = ['# Equivoque evaluation report', '',
        f'Run: `{config["run_id"]}`. Integration revision: `{revision}`.',
        f'Protocol SHA-256: `{provenance["protocol_sha256"]}`.', '',
        '**Collection incomplete: interpret all outputs as partial.**' if provenance['incomplete_collection'] else '**Collection finished; raw-data integrity checks passed.**', '',
        f'{len(df)} assigned trials; {provenance["valid_pre"]} valid pre-disclosure endpoints and {provenance["valid_post"]} valid post-disclosure endpoints.',
        f'{int((primary.status == "estimable").sum())} of 21 primary route associations were estimable under the prespecified thresholds.', '',
        '## Primary route associations', '',
        'The primary estimate equally weights KK and DD versus KD and DK. Routes arise from model choices; contrasts are associations. Cases are shared across frames and configurations. The 2,000 bootstrap replicates resample all 50 paired starting cases together using the frozen seed. Intervals are nominal pointwise percentile 95% intervals, with no confirmatory significance claims.', '',
        *markdown_table(primary, ['configuration_id', 'estimate', 'ci_low', 'ci_high',
            'n_KK', 'n_DD', 'n_KD', 'n_DK', 'n_cases', 'valid_bootstrap_replicates', 'status']), '',
        '## Within-trial disclosure changes', '',
        *markdown_table(summary[summary.metric.str.startswith('disclosure_change')],
            ['configuration_id', 'metric', 'estimate', 'ci_low', 'ci_high', 'n_trials', 'n_cases', 'status']), '',
        '## Paired cats-minus-cards differences', '',
        *markdown_table(summary[summary.metric.str.startswith('cats_minus_cards')],
            ['configuration_id', 'metric', 'estimate', 'ci_low', 'ci_high', 'n_pairs', 'n_cases', 'status']), '',
        '## Post-disclosure evidence consistency and missingness', '',
        *markdown_table(pd.read_csv(output / 'tables/post_evidence_consistency.csv'),
            ['configuration_id', 'frame', 'assigned', 'valid_post', 'counterfactual_no_count',
             'counterfactual_no_rate', 'minimum_impact_count', 'minimum_impact_rate']), '',
        *markdown_table(pd.read_csv(output / 'tables/missingness.csv'),
            ['configuration_id', 'frame', 'assigned', 'valid_pre', 'valid_post',
             'valid_pre_post_pairs', 'failed', 'interrupted', 'unattempted']), '',
        '## Interpretation and technical limits', '',
        'Native CLI subjects also receive the documented empty-directory environment context. Its working-directory paths contain the repository/run name, including the word equivoque. This is a possible topic cue before disclosure, even though no repository files, worker instructions, assigned target, or invariant rule are supplied. The context is part of the frozen harness and common across conditions; results describe judgments under that context, not the canonical message text in isolation. The protocol was not changed and trials were not replaced after collection began.', '',
        'A runtime reattachment stopped the coordinator and worker parents during collection. Seven already-requested native turns finished in their CLI children and left final durable event streams. Each had one schema-valid response, one final turn.completed event, matching session/system/prompt/schema, and no tools or metadata fallback. The coordinator recovered those responses without a new model invocation. Their original process exit codes and monotonic latencies are unavailable and remain missing; endpoint responses and available usage are retained. Fresh live readiness checks preceded resumption, with no replacement trials.', '',
        'The user subsequently requested ten additional executor processes and immediate concurrency 17. Original A–G manifests, the 2,100-trial roster, canonical stimuli, models, efforts, targets, cases and subject paths remained unchanged. Only unstarted evaluation IDs were exclusively subdivided; existing partial trials stayed with their original executors. Ten helper native-session checks added 40 separately retained calibration invocations. Seven existing native requests drained before subdivision and were reconciled without replay. Their exit status 0 was observed from /proc, but original monotonic latencies remain missing. Changing concurrency and manifest subsequences is an operational scheduling amendment, not a randomized scaling experiment.', '',
        'Seven evaluation turns subsequently exceeded the frozen 300-second native deadline. These trials remain failed, with their timeout records and any valid earlier endpoints retained; no failed or uncertain request was replayed. New trial intake was paused. Ten other already-requested native responses finished within the deadline and were reconciled from their final streams with observed exit status 0; their monotonic durations remain missing. Eight safe partial sessions resumed only their next unrequested turn. Twenty-one shared live service checks passed before another launch gate. The same 17 executors resumed with fair whole-trial permits and measured concurrency increases from 2 to 4, 7, 10 and 17; longer pending responses reduce subsequent intake. This scheduling history is preserved as technical evidence, without causal claims about scaling or the cause of the slowdown.', '',
        'A second runtime reattachment stopped the collection parents with 17 turns pending in durable state. Each already-requested turn left one schema-valid final native response inside its unchanged deadline, with matching session/system/prompt/schema and no tools or model-metadata fallback. Their native event logs retain WebSocket 403 reconnect errors and the CLI transport switch to HTTPS before successful completion. All 17 responses were reconciled without new invocations. Original per-turn process exit codes and monotonic durations could not be uniquely recovered and remain missing. Four trials ended at Turn 4; thirteen continued only their next unrequested turn. Another shared 21-configuration live check passed before a separately numbered gate and measured concurrency ramp. No failed trial was repeated or replaced.', '',
        'Disclosure combines an explanation, exhaustive evidence, and a later measurement. Its change cannot isolate the effect of any one component. Card and cat wording also differs in names, action verbs, and removal terms. Frame differences do not isolate only object category. These are model-generated judgments in one task family, not human agency measures.', '',
        'Valid Turn 3 endpoints contribute even when Turn 4 fails. Within-trial changes and frame differences use endpoint-valid pairs. All assigned failures and unattempted trials remain in denominators; missing ratings are not imputed. Sparse route contrasts remain insufficient, without replacement trials.', '',
        'See tables/estimates.csv for point estimates, contributing cases/trials, valid bootstrap counts, intervals, and insufficient cells. tables/missingness.csv contains endpoint denominators. Other CSVs retain route counts, counterfactual transitions, evidence consistency, target/position, choices, worker/time descriptions, and technical summaries. Static SVG and PNG figures have captions in figure_captions.json.', '',
        f'Worker calibration requested {provenance["worker_calibration_invocations"]} subject invocations across preserved attempts; development requested {provenance["development_invocations"]} and shared service checks requested {provenance["shared_service_calibration_invocations"]} additional invocations, for {provenance["non_evaluation_invocations"]} non-evaluation invocations in total. These, loopback request inspections, simulations, and the previous pilot are excluded from evaluation. Shared service calls are counted once; inherited per-executor readiness adds no calls. CLI HTTP retries are not observable as a reliable total; no cost is inferred without billing evidence. Backend model versions are not independently exposed by the CLI event stream. Exact requested models, effort settings, commands, usage, raw responses, and failures are preserved in the raw records.', '']
    (output / 'REPORT.md').write_text('\n'.join(lines))
    # A portable artifact browser: no hosting, network calls, or external assets.
    import html
    captions = read_json(output / 'figure_captions.json')
    panels = ''.join(f'<article><h2>{html.escape(k.replace("_", " "))}</h2>'
        f'<img src="figures/{k}.svg" alt="{html.escape(caption)}">'
        f'<p>{html.escape(caption)}</p><a href="figures/{k}.png">PNG</a> · '
        f'<a href="figures/{k}.svg">SVG</a></article>' for k, caption in captions.items())
    links = ''.join(f'<li><a href="tables/{p.name}">{html.escape(p.name)}</a></li>'
                    for p in sorted((output / 'tables').glob('*.csv')))
    (output / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"><title>Equivoque results</title>'
        '<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem;line-height:1.5}'
        'img{max-width:100%;max-height:1000px}article{border-top:1px solid #ccc;padding:2rem 0}'
        'select{font:inherit;padding:.5rem}code{overflow-wrap:anywhere}</style>'
        f'<h1>Equivoque results</h1><p>Run: {config["run_id"]}</p><p>Integration: <code>{revision}</code></p>'
        '<p><a href="REPORT.md">English report</a> · <a href="provenance.json">Provenance</a></p>'
        '<label>Figure <select id="figure"><option value="all">All figures</option>'
        + ''.join(f'<option>{html.escape(k.replace("_", " "))}</option>' for k in captions)
        + '</select></label>' + panels + '<h2>Tables</h2><ul>' + links + '</ul>'
        '<script>document.querySelector("select").onchange=e=>document.querySelectorAll("article").forEach(a=>a.hidden=e.target.value!=="all"&&a.querySelector("h2").textContent!==e.target.value)</script></html>')
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    main()
