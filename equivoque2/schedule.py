import collections
import itertools
import random

from equivoque.core import LABELS, ROOT, digest, read_json, write_json
from .protocol import CONFIG


def balanced(rng, values):
    result = list(values) * 2 + rng.sample(list(values), 2)
    rng.shuffle(result)
    return result


def build(config):
    rng = random.Random(config['seeds']['cases'])
    targets = balanced(rng, LABELS)
    positions = [balanced(rng, range(4)) for _ in range(3)]
    cases = []
    for index, target in enumerate(targets):
        orders = []
        for round_number in range(3):
            candidates = [list(order) for order in itertools.permutations(LABELS)
                          if order[positions[round_number][index]] == target
                          and list(order) not in orders]
            orders.append(rng.choice(candidates))
        cases.append({'case_id': f'case-{index + 1:03d}', 'target': target,
                      'round_orders': orders})
    allocation = random.Random(config['seeds']['assignment'])
    workers = config['workers']
    assigned = {worker: [] for worker in workers}
    for config_index, configuration in enumerate(config['configurations']):
        shuffled = list(cases)
        allocation.shuffle(shuffled)
        by_frame = {'cards': [], 'cats': []}
        for worker_index, worker in enumerate(workers):
            by_frame['cards' if (worker_index + config_index) % 2 == 0 else 'cats'].append(worker)
        for frame, members in by_frame.items():
            allocation.shuffle(members)
            for worker, case in zip(members, shuffled):
                assigned[worker].append({
                    'trial_id': '/'.join([config['run_id'], configuration['configuration_id'],
                                          frame, case['case_id']]),
                    'run_id': config['run_id'], 'worker_id': worker,
                    **configuration, **case, 'frame': frame})
    for index, worker in enumerate(workers):
        random.Random(config['seeds']['execution'] + index).shuffle(assigned[worker])
        assert len(assigned[worker]) == 21
        assert len({t['configuration_id'] for t in assigned[worker]}) == 21
        assert sorted(collections.Counter(t['frame'] for t in assigned[worker]).values()) == [10, 11]
    trials = [t for shard in assigned.values() for t in shard]
    assert len(trials) == len({t['trial_id'] for t in trials}) == 420
    return cases, assigned


def generate():
    config = read_json(CONFIG)
    cases, assigned = build(config)
    directory = ROOT / 'manifests' / config['run_id']
    write_json(directory / 'schedule.json', {'run_id': config['run_id'], 'cases': cases,
               'trials': [trial for shard in assigned.values() for trial in shard]})
    for worker, trials in assigned.items():
        write_json(directory / f'worker-{worker}.json', {
            'run_id': config['run_id'], 'worker_id': worker,
            'schedule_sha256': digest(directory / 'schedule.json'),
            'protocol_sha256': digest(ROOT / 'experiment2/protocol/prompts.json'),
            'trials': trials})
    print('Generated 420 trials in 20 disjoint 21-trial shards.')


if __name__ == '__main__':
    generate()
