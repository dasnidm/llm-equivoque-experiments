"""One precommitted position sequence shared by all 28 evaluation sessions."""
import random
from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, PROMPTS


def position_sequence(seed):
    rng = random.Random(seed)
    extra = rng.sample(range(1,5), 2)
    sequence = [p for p in range(1,5) for _ in range(7 + int(p in extra))]
    rng.shuffle(sequence)
    return sequence


def make_trial(config, configuration, frame, kind, positions, trial_id, n_rounds=30):
    order = list('ABDC' if frame == 'cards' else 'ABCD')
    assigned = positions[:n_rounds] if kind == 'seq' else [positions[0]] * n_rounds
    return {**configuration, 'run_id': config['run_id'], 'frame': frame, 'kind': kind,
            'pilot_label': f"exp3-pilot-{'card' if frame=='cards' else 'cat'}-{kind}",
            'order': order, 'positions': assigned, 'targets': [order[p-1] for p in assigned],
            'n_rounds': n_rounds, 'trial_id': trial_id}


def build(config):
    positions = position_sequence(config['seeds']['sequence'])
    trials = []
    for c in config['configurations']:
        for frame in ('cards', 'cats'):
            for kind in ('obj', 'seq'):
                tid = '/'.join([config['run_id'], c['configuration_id'], frame, kind])
                trials.append(make_trial(config,c,frame,kind,positions,tid))
    random.Random(config['seeds']['assignment']).shuffle(trials)
    assigned = {w:[] for w in config['workers']}
    for i, trial in enumerate(trials):
        w = config['workers'][i % len(config['workers'])]
        assigned[w].append({**trial, 'worker_id':w})
    return positions, assigned


def development_trial(config, index, configuration=None, n_rounds=1):
    c = configuration or config['configurations'][index % len(config['configurations'])]
    positions = position_sequence(config['seeds']['development'] + index)
    return make_trial(config,c,'cards' if index%2 else 'cats',
                      'seq' if index%3 else 'obj',positions,
                      f'calibration/{index:03d}/{c["configuration_id"]}',n_rounds)


def generate():
    config = read_json(CONFIG)
    positions, assigned = build(config)
    out = ROOT/'manifests'/config['run_id']
    write_json(out/'schedule.json', {'run_id':config['run_id'],'positions':positions,
                                   'trials':[t for group in assigned.values() for t in group]})
    for w, trials in assigned.items():
        write_json(out/f'worker-{w}.json', {'run_id':config['run_id'],'worker_id':w,
            'schedule_sha256':digest(out/'schedule.json'),'protocol_sha256':digest(PROMPTS),'trials':trials})
    print('Generated 28 sessions across 20 workers; 840 rounds, 2604 planned evaluation calls.')


if __name__ == '__main__': generate()
