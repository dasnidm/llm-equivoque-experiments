"""Paired case-cluster estimates; numeric judgments and raw accounts stay separate."""
import argparse
import collections
import csv
import json
from pathlib import Path
import tarfile
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, FREEZE, PROMPTS, frozen_hashes, probe_policies
from .audit import audit_worker


def csv_out(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resolve_results(root, run):
    direct = root / 'results' / run
    if any(direct.glob('worker-*/trials/*.json')):
        return direct
    cache = root / 'work/extracted-results' / run
    for path in sorted((direct / 'raw-archives').glob('worker-*.tar.gz')):
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:
                    raise ValueError('Unsafe archive member')
            archive.extractall(cache, filter='data')
    return cache


def paired_estimate(left, right, case_ids, resamples, minimum=5, fraction=.95):
    values = np.array([left.get(c, np.nan) - right.get(c, np.nan) for c in case_ids], float)
    valid = np.isfinite(values)
    estimate = float(values[valid].mean()) if valid.any() else None
    draws = values[resamples]
    denom = np.isfinite(draws).sum(axis=1)
    boot = np.divide(np.nansum(draws, axis=1), denom, where=denom > 0,
                     out=np.full(len(denom), np.nan))
    available = boot[np.isfinite(boot)]
    estimable = int(valid.sum()) >= minimum and len(available) >= len(boot) * fraction
    low, high = np.percentile(available, [2.5, 97.5]) if estimable else (None, None)
    return {'estimate': estimate, 'ci_low': low, 'ci_high': high, 'paired_cases': int(valid.sum()),
            'valid_bootstrap_replicates': len(available), 'status': 'estimable' if estimable else 'insufficient'}


def export(root, out):
    frozen_hashes()
    root, out = Path(root), Path(out)
    config = read_json(CONFIG)
    run = config['run_id']
    if out.exists():
        raise ValueError('Preserve an existing analysis attempt')
    out.mkdir(parents=True)
    data = resolve_results(root, run)
    states, audits, ids, sessions = [], [], set(), set()
    for w in config['workers']:
        audit = audit_worker(root / 'manifests' / run / f'worker-{w}.json', data / f'worker-{w}')
        if not audit['integrity_ok']:
            raise ValueError(str(audit['errors'][:3]))
        audits.append(audit)
        for path in sorted((data / f'worker-{w}' / 'trials').glob('*.json')):
            s = read_json(path)
            if s['trial']['trial_id'] in ids or s.get('session_id') in sessions:
                raise ValueError('Duplicate trial or native session')
            ids.add(s['trial']['trial_id'])
            if s.get('session_id'):
                sessions.add(s['session_id'])
            states.append(s)
    union = {'run_id': run, 'integrity_ok': True, 'assigned': config['sessions'],
             'attempted': len(states), 'unique_native_sessions': len(sessions),
             'unattempted': config['sessions'] - len(states),
             'counts': dict(collections.Counter(s['status'] for s in states)),
             'evaluation_invocations': sum(a['subject_invocations'] for a in audits),
             'valid_measurements': sum(a['valid_measurements'] for a in audits),
             'compaction_events': [x for a in audits for x in a['compaction_events']], 'workers': audits}
    write_json(out / 'union_audit.json', union)
    trial_rows, measurements, turns, choices, rules, predictions = [], [], [], [], [], []
    common = ['trial_id', 'case_id', 'configuration_id', 'model', 'effort', 'frame', 'kind', 'worker_id']
    for s in states:
        t = s['trial']
        base = {k: t[k] for k in common}
        pre, post, rule, predicted = [], None, None, None
        for record in s['turns']:
            local, r = record['local_turn'], record['round']
            turns.append({**base, **{k: record.get(k) for k in ['turn', 'round', 'local_turn', 'ok',
                'duration_seconds', 'requested_at', 'received_at', 'session_id']}})
            value = record.get('parsed')
            if value is None:
                continue
            if local == 3:
                row = {**base, 'round': r, **value, 'joint': int(value['impact'] == 1 and value['counterfactual'] == 'no')}
                pre.append(row)
                measurements.append(row)
            elif local == 4:
                rule = value['rule']
                rules.append({**base, 'rule': rule, 'category': 'uncoded'})
            elif local == 5:
                predicted = value
            elif local == 6:
                post = value
            else:
                choices.append({**base, 'round': r, 'stage': local, 'selection': json.dumps(value['selection']),
                                'route': s['rounds'][r-1]['route'], 'target_position': t['positions'][r-1]})
        pre.sort(key=lambda x: x['round'])
        first = next((r['round'] for r in pre if r['joint']), None)
        final = next((r for r in pre if r['round'] == 10), None)
        match = uncertain = 0
        if predicted:
            for i, policy in enumerate(probe_policies(t), 1):
                for component, gold in policy['gold'].items():
                    answer = predicted[f'policy_{i}'][component]
                    match += answer == gold
                    uncertain += answer == 'uncertain'
                    predictions.append({**base, 'policy': i, 'component': component, 'answer': answer,
                        'generator_value': gold, 'matches_generator': int(answer == gold),
                        'uncertain': int(answer == 'uncertain')})
        trial_rows.append({**base, 'status': s['status'], 'valid_rounds': len(pre), 'calls': len(s['turns']),
            'first_joint': first, 'initial_joint': int(bool(pre) and pre[0]['round'] == 1 and pre[0]['joint']),
            'joint_reversals': sum(a['joint'] and not b['joint'] for a, b in zip(pre, pre[1:])),
            'persistent_to_round10': int(first is not None and all(r['joint'] for r in pre if r['round'] >= first)) if len(pre) == 10 else None,
            'round10_joint': final['joint'] if final else None,
            'round10_freedom': final['freedom'] if final else None,
            'round10_impact': final['impact'] if final else None,
            'round10_counterfactual': final['counterfactual'] if final else None,
            'prediction_matches': match if predicted else None, 'prediction_uncertain': uncertain if predicted else None,
            'post_freedom': post['freedom'] if post else None, 'post_impact': post['impact'] if post else None,
            'post_counterfactual': post['counterfactual'] if post else None, 'error': s.get('error')})
    tables = {'trials': trial_rows, 'measurements': measurements, 'turns': turns,
              'choices': choices, 'rules': rules, 'predictions': predictions}
    extras = {'trials': ['status'], 'measurements': ['round', 'freedom', 'impact', 'counterfactual', 'joint'],
              'turns': ['turn'], 'choices': ['round', 'stage'], 'rules': ['rule', 'category'], 'predictions': ['policy', 'component']}
    for name, rows in tables.items():
        csv_out(out / 'tables' / (name + '.csv'), rows, list(rows[0]) if rows else common + extras[name])
    blinded = sorted(rules, key=lambda r: digest_text(r['trial_id']))
    csv_out(out / 'tables/blinded_rule_accounts.csv',
            [{'coding_id': digest_text(r['trial_id'])[:16], 'rule': r['rule'], 'category': ''} for r in blinded],
            ['coding_id', 'rule', 'category'])
    write_json(out / 'rule-coding-key.json', {digest_text(r['trial_id'])[:16]: r['trial_id'] for r in rules})
    cell_rows, curves, cells = [], [], {}
    settings = config['configurations']
    for c in settings:
        for frame in ('cards', 'cats'):
            for kind in ('obj', 'seq'):
                group = [t for t in trial_rows if t['configuration_id'] == c['configuration_id'] and t['frame'] == frame and t['kind'] == kind]
                valid = [t for t in group if t['round10_joint'] is not None]
                cells[c['configuration_id'], frame, kind] = {t['case_id']: t['round10_joint'] for t in valid}
                base = {**c, 'frame': frame, 'kind': kind}
                cell_rows.append({**base, 'assigned': 30, 'attempted': len(group),
                    'complete': sum(t['status'] == 'complete' for t in group), 'valid_round10': len(valid),
                    'joint_round10': sum(t['round10_joint'] for t in valid),
                    'joint_rate': statistics.mean(t['round10_joint'] for t in valid) if valid else None,
                    'first_joint_by10': sum(t['first_joint'] is not None for t in valid),
                    'joint_reversals': sum(t['joint_reversals'] for t in group)})
                for n in range(1, 11):
                    rs = [r for r in measurements if r['configuration_id'] == c['configuration_id'] and r['frame'] == frame and r['kind'] == kind and r['round'] == n]
                    curves.append({**base, 'round': n, 'valid': len(rs),
                        'joint_rate': statistics.mean(r['joint'] for r in rs) if rs else None,
                        'mean_impact': statistics.mean(r['impact'] for r in rs) if rs else None,
                        'mean_freedom': statistics.mean(r['freedom'] for r in rs) if rs else None})
    csv_out(out / 'tables/cell_summary.csv', cell_rows, list(cell_rows[0]))
    csv_out(out / 'tables/round_summary.csv', curves, list(curves[0]))
    case_ids = [f'case-{i:03d}' for i in range(1, 31)]
    samples = np.random.default_rng(config['seeds']['bootstrap']).integers(0, 30, (config['analysis']['bootstrap_replicates'], 30))
    estimates = []
    def contrast(label, c, frame, kind, left, right):
        estimates.append({'contrast': label, 'configuration_id': c, 'frame': frame, 'kind': kind,
            **paired_estimate(left, right, case_ids, samples, config['analysis']['minimum_cases'],
                              config['analysis']['minimum_valid_bootstrap_fraction'])})
    for c in settings:
        cid = c['configuration_id']
        for frame in ('cards', 'cats'):
            contrast('constant_minus_varying', cid, frame, 'both', cells[cid, frame, 'obj'], cells[cid, frame, 'seq'])
        for kind in ('obj', 'seq'):
            contrast('cats_minus_cards', cid, 'both', kind, cells[cid, 'cats', kind], cells[cid, 'cards', kind])
        if c['effort'] != 'low':
            low = c['model'] + '-low'
            for frame in ('cards', 'cats'):
                for kind in ('obj', 'seq'):
                    contrast(c['effort'] + '_minus_low', cid, frame, kind, cells[cid, frame, kind], cells[low, frame, kind])
    csv_out(out / 'tables/estimates.csv', estimates, list(estimates[0]))
    draw_figures(config, out, curves, cell_rows, trial_rows)
    lines = ['# Ten-round sequence replication', '',
        f"Assigned {config['sessions']} sessions in 84 cells; attempted {len(states)}, terminal counts {union['counts']}.",
        f"Valid pre-disclosure round reports: {len(measurements)}. Evaluation runner invocations: {union['evaluation_invocations']}.", '',
        'Primary endpoint is the joint report impact=1 and counterfactual=no at round ten. It is not proof of privately inferred mechanism knowledge.', '',
        '| Configuration | Frame | Schedule | Valid round ten | Joint reports | Rate |', '| --- | --- | --- | ---: | ---: | ---: |']
    for row in cell_rows:
        rate = f"{100 * row['joint_rate']:.1f}%" if row['joint_rate'] is not None else 'NA'
        lines.append(f"| {row['configuration_id']} | {row['frame']} | {row['kind']} | {row['valid_round10']} | {row['joint_round10']} | {rate} |")
    lines.extend(['', 'Each of thirty shared case families is resampled together across conditions and settings. Intervals are nominal pointwise 95%; sparse estimates remain insufficient. See estimates.csv for paired denominators.', '',
        'Earlier valid endpoints remain included after later failures. Calibration, simulations and all older studies are excluded. No failures are replaced. No event by ten is right-censored observation.', '',
        'Terminal rule questions may prompt new deductions. Prediction matches measure compatibility with the hidden generator; uncertainty is distinct from a wrong prediction. Raw accounts and a blinded coding sheet are retained; uncoded accounts are not scored as failures.', '',
        'Layouts and fixed targets vary across families; varying targets can change feedback routes. Reports concern the frozen native task and do not establish human feelings, general model rankings or private backend versions. Token counters are not billing estimates.'])
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    write_json(out / 'provenance.json', {'run_id': run, 'freeze_sha256': digest(FREEZE),
        'protocol_sha256': digest(PROMPTS), 'analysis_sha256': digest(ROOT / 'sequence_replication/analyze.py'),
        'raw_audit_sha256': digest(out / 'union_audit.json'), 'configurations': settings})
    (out / 'explorer.html').write_text('<!doctype html><meta charset="utf-8"><title>Sequence replication</title>'
        '<style>body{font:16px system-ui;max-width:1200px;margin:30px auto}img{max-width:100%}</style>'
        '<h1>Ten-round sequence replication</h1><p>Thirty matched families. Joint judgment reports are separate from mechanism knowledge. Calibration excluded.</p>'
        + ''.join('<h2>' + p.stem + '</h2><img src="figures/' + p.name + '">' for p in sorted((out / 'figures').glob('*.png'))))
    write_json(out / 'artifact-manifest.json', {'run_id': run, 'files': {
        str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return union


def digest_text(s):
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()


def draw_figures(config, out, curves, cells, trials):
    folder = out / 'figures'
    folder.mkdir()
    def save(fig, name):
        fig.tight_layout()
        fig.savefig(folder / (name + '.png'), dpi=160, bbox_inches='tight')
        fig.savefig(folder / (name + '.svg'), bbox_inches='tight')
        plt.close(fig)
    models = list(dict.fromkeys(c['model'] for c in config['configurations']))
    colors = {'obj': '#2563eb', 'seq': '#e87918'}
    styles = {'low': '-', 'medium': '--', 'high': ':'}
    fig, axes = plt.subplots(7, 2, figsize=(13, 16), sharex=True, sharey=True)
    for i, model in enumerate(models):
        for j, frame in enumerate(('cards', 'cats')):
            ax = axes[i, j]
            for kind in ('obj', 'seq'):
                for effort in ('low', 'medium', 'high'):
                    rs = [r for r in curves if r['model'] == model and r['frame'] == frame and r['kind'] == kind and r['effort'] == effort]
                    ax.plot([r['round'] for r in rs], [r['joint_rate'] if r['joint_rate'] is not None else np.nan for r in rs], color=colors[kind], linestyle=styles[effort], label=kind + '/' + effort)
            ax.set_title(model + ' | ' + frame, loc='left')
            ax.set_ylim(-.03, 1.03)
            ax.grid(alpha=.15)
    axes[0, 0].legend(fontsize=8, ncol=2)
    fig.supxlabel('Round before disclosure')
    fig.supylabel('Fraction reporting impact=1 and counterfactual=no')
    save(fig, '01_joint_trajectories')
    settings = config['configurations']
    conditions = [('cards', 'obj'), ('cards', 'seq'), ('cats', 'obj'), ('cats', 'seq')]
    for metric, name, title, maximum in [('joint_rate', '02_round10_joint', 'Round-ten joint judgment reports', 1),
            ('prediction', '04_predictions', 'Terminal components matching generator (uncertainty retained separately)', 12)]:
        matrix = np.full((21, 4), np.nan)
        labels = {}
        for i, c in enumerate(settings):
            for j, (frame, kind) in enumerate(conditions):
                if metric == 'joint_rate':
                    row = next(r for r in cells if r['configuration_id'] == c['configuration_id'] and r['frame'] == frame and r['kind'] == kind)
                    matrix[i, j] = row['joint_rate'] if row['joint_rate'] is not None else np.nan
                    labels[i, j] = f"{row['joint_round10']}/{row['valid_round10']}"
                else:
                    group = [t for t in trials if t['configuration_id'] == c['configuration_id'] and t['frame'] == frame and t['kind'] == kind and t['prediction_matches'] is not None]
                    if group:
                        matrix[i, j] = statistics.mean(t['prediction_matches'] for t in group)
                    labels[i, j] = f'n={len(group)}'
        fig, ax = plt.subplots(figsize=(10, 12))
        im = ax.imshow(matrix, vmin=0, vmax=maximum, cmap='Blues', aspect='auto')
        ax.set_yticks(range(21), [c['configuration_id'] for c in settings])
        ax.set_xticks(range(4), ['Card fixed', 'Card sequence', 'Cat fixed', 'Cat sequence'])
        for (i, j), label in labels.items():
            ax.text(j, i, label, ha='center', va='center', fontsize=8)
        ax.set_title(title)
        fig.colorbar(im, ax=ax)
        save(fig, name)
    fig, ax = plt.subplots(figsize=(12, 4))
    matrix = np.zeros((4, 11), int)
    for j, (frame, kind) in enumerate(conditions):
        for t in trials:
            if t['frame'] == frame and t['kind'] == kind and t['valid_rounds'] == 10:
                matrix[j, t['first_joint'] - 1 if t['first_joint'] is not None else 10] += 1
    im = ax.imshow(matrix, cmap='Blues', aspect='auto')
    ax.set_yticks(range(4), ['Card fixed', 'Card sequence', 'Cat fixed', 'Cat sequence'])
    ax.set_xticks(range(11), [str(i) for i in range(1, 11)] + ['>10'])
    for i in range(4):
        for j in range(11):
            ax.text(j, i, str(matrix[i, j]), ha='center', va='center')
    ax.set_title('First observed joint report; round 1 is an initial report; >10 is censored')
    fig.colorbar(im, ax=ax, label='Complete game-phase sessions')
    save(fig, '03_first_joint_reports')
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, field, title in zip(axes, ['round10_impact', 'post_impact'], ['Round ten before disclosure', 'After disclosure']):
        for kind in ('obj', 'seq'):
            counts = collections.Counter((t['round10_freedom' if field == 'round10_impact' else 'post_freedom'], t[field]) for t in trials if t[field] is not None and t['kind'] == kind)
            for (f, impact), n in counts.items():
                ax.scatter(f, impact, s=25 + n * .3, color=colors[kind], alpha=.55)
        ax.set_title(title)
        ax.set_xlim(-3, 105)
        ax.set_ylim(-3, 105)
        ax.set_xlabel('Selection freedom')
        ax.set_ylabel('Outcome influence')
        ax.grid(alpha=.15)
    save(fig, '05_agency_dimensions')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', default=str(ROOT))
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(export(args.root, args.output), default=str))


if __name__ == '__main__':
    main()
