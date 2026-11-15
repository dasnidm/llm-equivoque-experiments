"""Deterministic, offline-only allocation; does not launch model requests."""
from collections import Counter, defaultdict
from copy import deepcopy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import random

from exp7_pre.protocol import make_probe_policies
from .protocol import adapt

RUN_ID = 'equivoque-exp7-cards-200-20261115'
SEED = 2026111501
MODELS = ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol', 'gpt-6-luna',
          'gpt-6-sol', 'gpt-6-astra', 'gpt-6.1-sol')
EFFORTS = ('low', 'medium', 'high')
LABELS = tuple('ABCD')
CALLS = 34


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def rng_for(label):
    return random.Random(int.from_bytes(hashlib.sha256(encoded([SEED, label])).digest(), 'big'))


def case_families():
    """200 unique balanced sequences; shared across conditions and configs.

    First 50 cases are the initial assessment batch. Identical case IDs never
    cross development/holdout or development folds. Fixed target conditions
    necessarily reuse the same four target identities in all splits.
    """
    rng = rng_for('stimuli')
    seen = set()
    orders = list(itertools.permutations(LABELS))
    # Repeated shuffled blocks make the 24 layouts approximately balanced.
    layouts = []
    while len(layouts) < 200:
        block = orders[:]
        rng.shuffle(block)
        layouts.extend(block)
    result = []
    for i in range(200):
        target = LABELS[i % 4]
        while True:
            doubled = set(rng.sample(list(LABELS), 2))
            pool = [x for x in LABELS for _ in range(3 if x in doubled else 2)]
            pool.remove(target)
            rng.shuffle(pool)
            seq = (target, *pool)
            if seq not in seen:
                seen.add(seq)
                break
        holdout = i % 5 == 4
        result.append({'case_id': f'case-{i+1:03}', 'order': list(layouts[i]),
                       'target': target, 'sequence': list(seq),
                       'split': 'holdout' if holdout else 'development',
                       'fold': None if holdout else (i // 5) % 5,
                       'stage': 'initial-50' if i < 50 else 'remaining-150',
                       'probe_arm': 'explanation' if (i // 4) % 2 == 0 else 'neutral'})
    return result


def build():
    cases = case_families()
    policies = make_probe_policies(list(LABELS), SEED + 1)
    trials = []
    for model, effort, game in itertools.product(MODELS, EFFORTS, ('obj', 'seq')):
        for index, case in enumerate(cases, 1):
            targets = [case['target']] * 10 if game == 'obj' else case['sequence'][:]
            structure = {'order': case['order'], 'game': game, 'targets': targets}
            trial = {'trial_id': f'{model}-{effort}-{game}-{index:03}', 'run_id': RUN_ID,
                     'configuration_id': f'{model}-{effort}', 'model': model, 'effort': effort,
                     'frame': 'cards', 'arm': 'en_schema', 'format': 'en_schema',
                     'measurement': 'each_round', 'game': game, 'kind': game,
                     'stage_rule': None, 'order': case['order'][:], 'targets': targets,
                     'n_rounds': 10, 'target_identity': case['target'] if game == 'obj' else None,
                     'probe_seed': SEED + 1, 'probe_policies': deepcopy(policies),
                     'probe_arm': case['probe_arm'], 'split': case['split'], 'fold': case['fold'],
                     'stage': case['stage'], 'case_id': case['case_id'], 'replicate': index,
                     'cohort': 'main', 'cell_id': f'{model}-{effort}-{game}',
                     'structure_sha256': hashlib.sha256(encoded(structure)).hexdigest()}
            trials.append(trial)
    rng_for('execution-order').shuffle(trials)
    meta = {'run_id': RUN_ID, 'status': 'draft_offline_only', 'seed': SEED,
            'cells': 42, 'per_cell': 200, 'planned_sessions': 8400,
            'planned_rounds': 84000, 'calls_per_complete_session': CALLS,
            'planned_calls': 285600, 'initial_sessions': 2100,
            'models': list(MODELS), 'efforts': list(EFFORTS), 'games': ['obj', 'seq'],
            'frame': 'cards', 'format': 'en_schema', 'cases': cases,
            'holdout_definition': 'held-out case families; seq schedules are unique; obj repeats four target identities',
            'sequence_generation': 'each target appears two or three times; first target matched to obj; unique across 200 cases',
            'ready_for_live_collection': False}
    return meta, trials


def audit(meta, trials):
    if (meta.get('run_id') != RUN_ID or meta.get('seed') != SEED
            or meta.get('cells') != 42 or meta.get('per_cell') != 200
            or meta.get('planned_sessions') != 8400 or meta.get('planned_rounds') != 84000
            or meta.get('ready_for_live_collection') is not False):
        raise ValueError('Invalid schedule metadata')
    expected_cases = {c['case_id']: c for c in case_families()}
    if meta.get('cases') != list(expected_cases.values()):
        raise ValueError('Stored case families differ from seeded allocation')
    if len(trials) != 8400 or len({t['trial_id'] for t in trials}) != 8400:
        raise ValueError('Wrong session count or duplicate trial ID')
    if meta['planned_calls'] != len(trials) * CALLS:
        raise ValueError('Wrong call count')
    groups = defaultdict(list)
    by_case = defaultdict(list)
    for trial in trials:
        adapt(trial)
        c = expected_cases.get(trial['case_id'])
        if c is None or any(trial[k] != c[k] for k in ('order', 'split', 'fold', 'stage', 'probe_arm')):
            raise ValueError('Trial disagrees with seeded case family')
        expected_targets = [c['target']] * 10 if trial['game'] == 'obj' else c['sequence']
        if trial['targets'] != expected_targets or trial.get('run_id') != RUN_ID:
            raise ValueError('Trial targets or run mismatch')
        groups[trial['model'], trial['effort'], trial['game']].append(trial)
        by_case[trial['case_id']].append(trial)
        structure = {k: trial[k] for k in ('order', 'game', 'targets')}
        if hashlib.sha256(encoded(structure)).hexdigest() != trial['structure_sha256']:
            raise ValueError('Structure hash mismatch')
    if set(groups) != set(itertools.product(MODELS, EFFORTS, ('obj', 'seq'))):
        raise ValueError('Missing or unexpected cell')
    for (_, _, game), rows in groups.items():
        if len(rows) != 200 or Counter(t['stage'] for t in rows) != {'initial-50': 50, 'remaining-150': 150}:
            raise ValueError('Cell or stage size mismatch')
        if Counter(t['split'] for t in rows) != {'development': 160, 'holdout': 40}:
            raise ValueError('Wrong split')
        if Counter(t['fold'] for t in rows if t['split'] == 'development') != dict.fromkeys(range(5), 32):
            raise ValueError('Wrong folds')
        if Counter(t['probe_arm'] for t in rows) != {'explanation': 100, 'neutral': 100}:
            raise ValueError('Wrong probe balance')
        if game == 'obj' and Counter(t['target_identity'] for t in rows) != dict.fromkeys(LABELS, 50):
            raise ValueError('Wrong fixed target balance')
        if game == 'seq' and (len({tuple(t['targets']) for t in rows}) != 200
                or any(sorted(Counter(t['targets']).values()) != [2, 2, 3, 3] for t in rows)):
            raise ValueError('Wrong varying sequences')
    if len(by_case) != 200:
        raise ValueError('Wrong family count')
    for rows in by_case.values():
        if len(rows) != 42 or len({(t['split'], t['fold'], t['stage'], tuple(t['order'])) for t in rows}) != 1:
            raise ValueError('Family leakage or mismatched card order')
        obj = {tuple(t['targets']) for t in rows if t['game'] == 'obj'}
        seq = {tuple(t['targets']) for t in rows if t['game'] == 'seq'}
        if len(obj) != 1 or len(seq) != 1 or next(iter(obj))[0] != next(iter(seq))[0]:
            raise ValueError('Paired stimuli mismatch')
    return {'passed': True, 'cells': len(groups), 'cases': len(by_case),
            'trials': len(trials), 'calls': len(trials) * CALLS}


def make_jobs(trials):
    """Create disjoint, stage-separated 30-trial work packages, offline only."""
    jobs = []
    for mi, model in enumerate(MODELS, 1):
        for stage in ('initial-50', 'remaining-150'):
            ids = sorted(t['trial_id'] for t in trials if t['model'] == model and t['stage'] == stage)
            rng_for(['jobs', model, stage]).shuffle(ids)
            for j, start in enumerate(range(0, len(ids), 30), 1):
                subset = ids[start:start + 30]
                jobs.append({'job_id': f'm{mi:02}-{stage}-job{j:02}', 'model': model,
                             'stage': stage, 'trial_ids': subset, 'n_trials': len(subset),
                             'call_cap': len(subset) * CALLS})
    return jobs


def audit_jobs(trials, jobs):
    by_id = {t['trial_id']: t for t in trials}
    seen = []
    for job in jobs:
        if (len(job['trial_ids']) != job['n_trials'] or job['n_trials'] > 30
                or job['call_cap'] != job['n_trials'] * CALLS):
            raise ValueError('Invalid job size or budget')
        for ident in job['trial_ids']:
            t = by_id.get(ident)
            if t is None or t['model'] != job['model'] or t['stage'] != job['stage']:
                raise ValueError('Job references a missing or mismatched trial')
        seen.extend(job['trial_ids'])
    if len(jobs) != 280 or len(seen) != len(set(seen)) or set(seen) != set(by_id):
        raise ValueError('Jobs overlap or omit assignments')
    return {'jobs': len(jobs), 'initial_jobs': sum(j['stage'] == 'initial-50' for j in jobs)}


def save(destination):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    meta, trials = build()
    result = audit(meta, trials)
    jobs = make_jobs(trials)
    result.update(audit_jobs(trials, jobs))
    payloads = {'schedule.json': encoded(meta) + b'\n',
                'assignments.jsonl.gz': gzip.compress(b''.join(encoded(t) + b'\n' for t in trials), mtime=0),
                'jobs.json': encoded(jobs) + b'\n',
                'audit.json': encoded(result) + b'\n'}
    for name, data in payloads.items():
        path = dest / name
        if path.exists() and path.read_bytes() != data:
            raise FileExistsError(f'Refusing to overwrite different bytes: {path}')
        if not path.exists():
            path.write_bytes(data)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    print(json.dumps(save(p.parse_args().output), indent=2))
