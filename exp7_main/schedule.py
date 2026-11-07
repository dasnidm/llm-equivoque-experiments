"""Outcome-independent allocation for the single-sequence Exp 7 main study.

This module makes no model calls. Saving creates a new immutable allocation
bundle; it never alters any historical manifest or overwrites differing bytes.
The common sequence is a new design choice, not an Exp 5 reconstruction.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path
import random

from exp7_pre.protocol import make_probe_policies

RUN_ID = 'equivoque-2026-11-07-exp7-main-v1'
SEED = 2026110707
MODELS = ('gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra',
          'gpt-6-astra', 'gpt-6-luna', 'gpt-6-sol',
          'gpt-6.1-sol', 'gpt-6.1-terra')
EFFORTS = ('low', 'medium', 'high')
FRAMES = ('cards', 'cats')
FORMATS = ('en_schema', 'en_natural', 'ko_schema', 'ko_natural')
ARMS = FORMATS + ('R_A',)
GAMES = ('obj', 'seq', 'KK', 'KD', 'DK', 'DD')
ORDER = ('A', 'B', 'C', 'D')
COMMON_SEQUENCE = ('A', 'C', 'B', 'D', 'B', 'A', 'D', 'C', 'A', 'B')
CALLS_PER_SESSION = 34


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _rng(seed, label):
    return random.Random(int.from_bytes(hashlib.sha256(
        encoded([seed, label])).digest(), 'big'))


def _slots(game, arm, rng):
    """Allocate reporting-independent strata, splits, folds and terminal arms."""
    slots = []
    core = arm != 'R_A' and game in ('obj', 'seq')
    if core and game == 'obj':
        for si, split in enumerate(('development', 'holdout')):
            for ti, target in enumerate(ORDER):
                # 7/8 crossovers give 30 explanation per split and 15 per target.
                n_explain = 7 + ((si + ti) % 2)
                probes = ['explanation'] * n_explain + ['neutral'] * (15 - n_explain)
                rng.shuffle(probes)
                folds = list(range(5)) * 3
                rng.shuffle(folds)
                for i in range(15):
                    slots.append({'target': target, 'split': split,
                                  'fold': folds[i] if split == 'development' else None,
                                  'probe_arm': probes[i]})
    elif core:
        for split in ('development', 'holdout'):
            probes = ['explanation'] * 30 + ['neutral'] * 30
            folds = list(range(5)) * 12
            rng.shuffle(probes)
            rng.shuffle(folds)
            for i in range(60):
                slots.append({'target': None, 'split': split,
                              'fold': folds[i] if split == 'development' else None,
                              'probe_arm': probes[i]})
    elif game == 'obj':
        for target in ORDER:
            for probe_arm in ('explanation', 'neutral'):
                for _ in range(4):
                    slots.append({'target': target, 'split': 'control',
                                  'fold': None, 'probe_arm': probe_arm})
    else:
        for probe_arm in ('explanation', 'neutral'):
            for _ in range(15):
                slots.append({'target': None, 'split': 'control',
                              'fold': None, 'probe_arm': probe_arm})
    rng.shuffle(slots)
    return slots


def build(run_id=RUN_ID, seed=SEED):
    """Return the complete 77,856-row allocation without writing files."""
    if not isinstance(run_id, str) or not run_id or any(x in run_id for x in ('/', '\\')):
        raise ValueError('run_id must be a nonempty path-free identifier')
    trials = []
    cell_index = 0
    # The visible counterfactual policies are shared across targets and games.
    # Their generation receives only public order and this prespecified seed.
    probe_seed = seed + 1
    policies = make_probe_policies(list(ORDER), probe_seed)
    for model in MODELS:
        for effort in EFFORTS:
            for frame in FRAMES:
                for arm in ARMS:
                    for game in GAMES:
                        cell_index += 1
                        cell_id = f'cell-{cell_index:06d}'
                        slots = _slots(game, arm, _rng(seed, [model, effort, frame, arm, game]))
                        for replicate, slot in enumerate(slots, 1):
                            targets = ([slot['target']] * 10 if game == 'obj'
                                       else list(COMMON_SEQUENCE) if game == 'seq' else [])
                            structure = {'order': ORDER, 'game': game, 'targets': targets}
                            structure_hash = hashlib.sha256(encoded(structure)).hexdigest()
                            trial = {
                                'trial_id': f'main-{len(trials) + 1:06d}',
                                'run_id': run_id,
                                'configuration_id': f'{model}-{effort}',
                                'model': model, 'effort': effort, 'frame': frame,
                                'arm': arm, 'format': 'en_schema' if arm == 'R_A' else arm,
                                'measurement': 'round10_only' if arm == 'R_A' else 'each_round',
                                'game': game, 'kind': game if game in ('obj', 'seq') else 'unforced',
                                'stage_rule': game if game not in ('obj', 'seq') else None,
                                'order': list(ORDER), 'targets': targets, 'n_rounds': 10,
                                'target_identity': slot['target'],
                                'probe_seed': probe_seed, 'probe_policies': copy.deepcopy(policies),
                                'probe_arm': slot['probe_arm'],
                                'split': slot['split'], 'fold': slot['fold'],
                                'cohort': 'main', 'cell_id': cell_id, 'replicate': replicate,
                                'case_id': f'fixed-{structure_hash[:16]}',
                                'structure_sha256': structure_hash,
                            }
                            trials.append(trial)
    _rng(seed, 'global-execution-order').shuffle(trials)
    return {
        'run_id': run_id, 'seed': seed, 'purpose': 'main_evaluation',
        'design_version': 'single-sequence-core120-control30-robj32-v1',
        'created_without_model_outcomes': True,
        'n_rounds': 10, 'calls_per_complete_session': CALLS_PER_SESSION,
        'planned_sessions': len(trials), 'planned_game_rounds': len(trials) * 10,
        'call_cap': CALLS_PER_SESSION * len(trials), 'cell_count': cell_index,
        'profiles': [{'model': m, 'effort': e} for m in MODELS for e in EFFORTS],
        'frames': list(FRAMES), 'arms': list(ARMS), 'games': list(GAMES),
        'abstract_order': list(ORDER), 'common_sequence': list(COMMON_SEQUENCE),
        'sequence_origin': 'New prespecified design choice from the earlier illustrative list; not an Exp5 replay.',
        'probe_policy_assignment': 'One target-independent policy set shared by every conversation.',
        'rules': {
            'automatic_retries': 0, 'replace_failed_sessions': False,
            'technical_sessions_in_primary_analysis': False,
            'validation_unit': 'fresh_conversation_under_fixed_stimuli',
            'development_folds': 5, 'holdout_used_for_model_selection': False,
            'control_outcomes_used_for_model_selection': False,
            'same_conversation_rounds_must_share_split': True,
            'new_sequence_generalization_claim': False,
            'missing_report_is_zero': False,
        },
        'trials': trials,
    }


def build_jobs(schedule, job_size=30):
    """Mix conditions within each model before splitting into disjoint jobs."""
    if not isinstance(job_size, int) or isinstance(job_size, bool) or job_size < 1:
        raise ValueError('job_size must be a positive integer')
    grouped = defaultdict(list)
    for t in schedule['trials']:
        grouped[t['model']].append(t['trial_id'])
    jobs = []
    for mi, model in enumerate(MODELS, 1):
        ids = sorted(grouped[model])
        _rng(schedule['seed'], ['model-job-order', model]).shuffle(ids)
        for ji, start in enumerate(range(0, len(ids), job_size), 1):
            subset = ids[start:start + job_size]
            jobs.append({'job_id': f'model-{mi:02d}-job-{ji:04d}', 'model': model,
                         'model_job_index': ji, 'trial_ids': subset,
                         'n_trials': len(subset),
                         'call_cap': len(subset) * CALLS_PER_SESSION,
                         'status': 'open', 'owner': None, 'claim_token': None})
    return jobs


def audit(schedule, jobs=None):
    """Check scientific allocation and job ownership without any inference."""
    trials = schedule['trials']
    if (len(trials) != 77856 or schedule['planned_sessions'] != len(trials)
            or schedule['call_cap'] != 2647104 or schedule['planned_game_rounds'] != 778560):
        raise ValueError('Wrong planned conversation or call count')
    if schedule['common_sequence'] != list(COMMON_SEQUENCE) or schedule['abstract_order'] != list(ORDER):
        raise ValueError('Metadata disagrees with the fixed stimuli')
    if len({t['trial_id'] for t in trials}) != len(trials):
        raise ValueError('Repeated conversation identifier')
    cells = defaultdict(list)
    for t in trials:
        cells[t['model'], t['effort'], t['frame'], t['arm'], t['game']].append(t)
        if t['run_id'] != schedule['run_id'] or t['order'] != list(ORDER) or t['n_rounds'] != 10:
            raise ValueError('Wrong run, initial order or round count')
        if t['format'] != ('en_schema' if t['arm'] == 'R_A' else t['arm']):
            raise ValueError('Response format does not match assigned arm')
        if t['measurement'] != ('round10_only' if t['arm'] == 'R_A' else 'each_round'):
            raise ValueError('Measurement timing does not match assigned arm')
        if t['kind'] != (t['game'] if t['game'] in ('obj', 'seq') else 'unforced'):
            raise ValueError('Generator kind does not match assigned game')
        if t['game'] == 'seq' and t['targets'] != list(COMMON_SEQUENCE):
            raise ValueError('Sequence is not globally shared')
        if t['game'] == 'obj' and t['targets'] != [t['target_identity']] * 10:
            raise ValueError('Object target changed within a conversation')
        if t['game'] not in ('obj', 'seq') and (t['targets'] or t['stage_rule'] != t['game']):
            raise ValueError('Stable control contains a forced target or wrong rule')
    expected_cells = set(itertools.product(MODELS, EFFORTS, FRAMES, ARMS, GAMES))
    if set(cells) != expected_cells:
        raise ValueError('Missing condition cells')
    for (_, _, _, arm, game), rows in cells.items():
        core = arm != 'R_A' and game in ('obj', 'seq')
        expected = 120 if core else 32 if game == 'obj' else 30
        if len(rows) != expected:
            raise ValueError('Wrong per-cell conversation count')
        if Counter(t['probe_arm'] for t in rows) != {'explanation': expected // 2, 'neutral': expected // 2}:
            raise ValueError('Unbalanced terminal question assignment')
        if game == 'obj' and Counter(t['target_identity'] for t in rows) != {x: expected // 4 for x in ORDER}:
            raise ValueError('Unbalanced fixed object targets')
        if core:
            if Counter(t['split'] for t in rows) != {'development': 60, 'holdout': 60}:
                raise ValueError('Invalid development/holdout allocation')
            for split in ('development', 'holdout'):
                selected = [t for t in rows if t['split'] == split]
                if Counter(t['probe_arm'] for t in selected) != {'explanation': 30, 'neutral': 30}:
                    raise ValueError('Unbalanced terminal questions within split')
                if game == 'obj' and Counter(t['target_identity'] for t in selected) != {x: 15 for x in ORDER}:
                    raise ValueError('Unbalanced fixed targets within split')
            dev = [t for t in rows if t['split'] == 'development']
            if Counter(t['fold'] for t in dev) != {i: 12 for i in range(5)}:
                raise ValueError('Unbalanced development folds')
            if any(t['fold'] is not None for t in rows if t['split'] == 'holdout'):
                raise ValueError('Holdout assigned to a model selection fold')
        elif any(t['split'] != 'control' or t['fold'] is not None for t in rows):
            raise ValueError('Control leaked into predictive model selection')
    if jobs is not None:
        by_id = {t['trial_id']: t for t in trials}
        seen = []
        for j in jobs:
            if len(j['trial_ids']) != j['n_trials'] or j['call_cap'] != 34 * j['n_trials']:
                raise ValueError('Job budget does not match its assignments')
            for trial_id in j['trial_ids']:
                if trial_id not in by_id or by_id[trial_id]['model'] != j['model']:
                    raise ValueError('Job contains missing or another model assignment')
            seen.extend(j['trial_ids'])
        if len(seen) != len(set(seen)) or set(seen) != set(by_id):
            raise ValueError('Jobs overlap or omit assignments')
    return {'passed': True, 'conversations': len(trials), 'cells': len(cells),
            'calls': schedule['call_cap'], 'jobs': len(jobs) if jobs is not None else None,
            'per_model': dict(sorted(Counter(t['model'] for t in trials).items()))}


def save_bundle(schedule, directory, job_size=30):
    """Save compact deterministic files; reject existing differing allocations."""
    directory = Path(directory)
    jobs = build_jobs(schedule, job_size)
    report = audit(schedule, jobs)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0) as stream:
        for row in schedule['trials']:
            stream.write(encoded(row) + b'\n')
    metadata = {k: v for k, v in schedule.items() if k != 'trials'}
    metadata['assignments_file'] = 'assignments.jsonl.gz'
    payloads = {'schedule.json': encoded(metadata) + b'\n',
                'assignments.jsonl.gz': buffer.getvalue(),
                'jobs.json': encoded(jobs) + b'\n',
                'audit.json': encoded(report) + b'\n'}
    summary = {**report, 'run_id': schedule['run_id'],
               'planned_game_rounds': schedule['planned_game_rounds'],
               'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                         for name, data in payloads.items()}}
    payloads['summary.json'] = encoded(summary) + b'\n'
    # Precheck every path before creating any file: no half-updated bundles.
    for name, data in payloads.items():
        path = directory / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'Existing file differs; use a new run directory: {path}')
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        path = directory / name
        if not path.exists():
            with path.open('xb') as f:
                f.write(data)
    return summary


def load_bundle(directory):
    """Load a saved bundle after verifying its recorded file hashes."""
    directory = Path(directory)
    summary = json.loads((directory / 'summary.json').read_text())
    for name, meta in summary['files'].items():
        if Path(name).name != name:
            raise ValueError('Invalid bundle filename')
        data = (directory / name).read_bytes()
        if len(data) != meta['bytes'] or hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise ValueError(f'Allocation hash mismatch: {name}')
    schedule = json.loads((directory / 'schedule.json').read_text())
    with gzip.open(directory / schedule['assignments_file'], 'rt', encoding='utf-8') as f:
        schedule['trials'] = [json.loads(line) for line in f if line.strip()]
    schedule.pop('assignments_file', None)
    audit(schedule, json.loads((directory / 'jobs.json').read_text()))
    return schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default=RUN_ID)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--job-size', type=int, default=30)
    args = parser.parse_args()
    summary = save_bundle(build(args.run_id, args.seed), args.output, args.job_size)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
