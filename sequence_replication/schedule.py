"""Thirty matched case families, counterbalanced identities and positions."""
import itertools
import random
from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, PROMPTS


def make_cases(config, seed=None):
    if config['cases'] != 30 or config['rounds_per_trial'] != 10:
        raise ValueError('This prospective schedule is exactly 30 cases of ten rounds')
    rng = random.Random(config['seeds']['cases'] if seed is None else seed)
    seq_rng = random.Random(config['seeds']['sequence'] if seed is None else seed + 1)
    # Two cases in each identity x position cell, except two distinct marginal
    # cells with one case: both margins have counts 7,7,8,8. Select before calls.
    identities = rng.sample(range(4), 2)
    positions = rng.sample(range(4), 2)
    reduced = set(zip(identities, positions))
    cases = []
    for identity in range(4):
        for position in range(4):
            candidates = [p for p in itertools.permutations(range(4)) if p[position] == identity]
            for order in rng.sample(candidates, 1 if (identity, position) in reduced else 2):
                extra = seq_rng.sample(range(1, 5), 2)
                sequence = [p for p in range(1, 5) for _ in range(2 + int(p in extra))]
                sequence.remove(position + 1)
                seq_rng.shuffle(sequence)
                cases.append({'abstract_order': list(order), 'target_identity': identity,
                              'target_position': position + 1,
                              'positions': [position + 1] + sequence})
    rng.shuffle(cases)
    return [{**case, 'case_id': f'case-{i:03d}'} for i, case in enumerate(cases, 1)]


def make_trial(config, configuration, frame, kind, case, trial_id):
    # Homologous displayed identities: S,C,H,D match cats A,B,C,D.
    names = 'ABDC' if frame == 'cards' else 'ABCD'
    order = [names[i] for i in case['abstract_order']]
    positions = case['positions'] if kind == 'seq' else [case['target_position']] * 10
    return {**configuration, 'run_id': config['run_id'], 'frame': frame, 'kind': kind,
            'pilot_label': f"{'card' if frame == 'cards' else 'cat'}-{kind}",
            'case_id': case['case_id'], 'order': order, 'positions': list(positions),
            'targets': [order[p - 1] for p in positions], 'n_rounds': 10, 'trial_id': trial_id}


def build(config):
    cases = make_cases(config)
    rng = random.Random(config['seeds']['assignment'])
    assigned = {w: [] for w in config['workers']}
    if len(assigned) != 10:
        raise ValueError('Authorized initial assignment has ten workers')
    for c in config['configurations']:
        for frame in ('cards', 'cats'):
            for kind in ('obj', 'seq'):
                shuffled = list(cases)
                rng.shuffle(shuffled)
                workers = list(config['workers'])
                rng.shuffle(workers)
                for i, case in enumerate(shuffled):
                    w = workers[i % 10]
                    tid = '/'.join([config['run_id'], c['configuration_id'], frame, kind, case['case_id']])
                    assigned[w].append({**make_trial(config, c, frame, kind, case, tid), 'worker_id': w})
    for trials in assigned.values():
        rng.shuffle(trials)
    return cases, assigned


def development_trial(config, index, configuration=None, n_rounds=1):
    if n_rounds not in (1, 10):
        raise ValueError('Calibration uses one or ten rounds')
    c = configuration or config['configurations'][index % len(config['configurations'])]
    case = make_cases(config, config['seeds']['development'] + index * 100)[index % 30]
    case['case_id'] = f'development-{index:03d}'
    trial = make_trial(config, c, 'cards' if index % 2 else 'cats',
                       'seq' if index % 3 else 'obj', case,
                       f'calibration/{index:03d}/{c["configuration_id"]}')
    trial['n_rounds'] = n_rounds
    trial['positions'] = trial['positions'][:n_rounds]
    trial['targets'] = trial['targets'][:n_rounds]
    return trial


def generate():
    config = read_json(CONFIG)
    cases, assigned = build(config)
    out = ROOT / 'manifests' / config['run_id']
    write_json(out / 'schedule.json', {'run_id': config['run_id'], 'cases': cases,
               'trials': [t for group in assigned.values() for t in group]})
    for w, trials in assigned.items():
        write_json(out / f'worker-{w}.json', {'run_id': config['run_id'], 'worker_id': w,
                   'schedule_sha256': digest(out / 'schedule.json'),
                   'protocol_sha256': digest(PROMPTS), 'trials': trials})
    print('Generated 2520 sessions, 84 cells, 30 paired cases, 10 workers; 25200 rounds and 83160 evaluation calls.')


if __name__ == '__main__':
    generate()
