"""Build the deterministic seven-worker schedule; never consult subject outputs."""
import collections
import itertools
import random

from .core import LABELS, ROOT, digest, read_json, write_json


def make_cases(seed):
    rng = random.Random(seed)
    cases = []
    for target in LABELS:
        for position in range(4):
            others = [x for x in LABELS if x != target]
            permutations = list(itertools.permutations(others))
            rng.shuffle(permutations)
            for permutation in permutations[:3]:
                order = list(permutation)
                order.insert(position, target)
                cases.append({'target': target, 'order': order})
    extra_targets = rng.sample(list(LABELS), 2)
    extra_positions = rng.sample(list(range(4)), 2)
    for target, position in zip(extra_targets, extra_positions):
        used = {(x['target'], tuple(x['order'])) for x in cases}
        candidates = [list(order) for order in itertools.permutations(LABELS)
                      if order[position] == target and
                      (target, order) not in used]
        cases.append({'target': target, 'order': rng.choice(candidates)})
    rng.shuffle(cases)
    for index, case in enumerate(cases, 1):
        case['case_id'] = f'case-{index:03d}'
    return cases


def build(config):
    workers = list('abcdefg')
    cases = make_cases(config['seeds']['cases'])
    allocation_rng = random.Random(config['seeds']['assignment'])
    assigned = {worker: [] for worker in workers}
    for index, configuration in enumerate(config['configurations']):
        shuffled = list(cases)
        allocation_rng.shuffle(shuffled)
        counts = {worker: 7 + (i == index % 7)
                  for i, worker in enumerate(workers)}
        offset = 0
        for worker in workers:
            for case in shuffled[offset:offset + counts[worker]]:
                for frame in ('cards', 'cats'):
                    assigned[worker].append({
                        'trial_id': '/'.join([config['run_id'],
                            configuration['configuration_id'], frame,
                            case['case_id']]),
                        'run_id': config['run_id'], 'worker_id': worker,
                        **configuration, **case, 'frame': frame})
            offset += counts[worker]
        assert offset == 50
    for index, worker in enumerate(workers):
        random.Random(config['seeds']['execution'] + index).shuffle(assigned[worker])
    trials = [trial for worker in workers for trial in assigned[worker]]
    assert len(trials) == len({t['trial_id'] for t in trials}) == 2100
    for worker, shard in assigned.items():
        assert len(shard) == 300
        assert collections.Counter(t['frame'] for t in shard) == {
            'cards': 150, 'cats': 150}
    return cases, assigned


def generate():
    config = read_json(ROOT / 'protocol/run.v1.json')
    cases, assigned = build(config)
    directory = ROOT / 'manifests' / config['run_id']
    full = {'run_id': config['run_id'], 'cases': cases,
            'trials': [trial for shard in assigned.values() for trial in shard]}
    write_json(directory / 'schedule.json', full)
    schedule_hash = digest(directory / 'schedule.json')
    for worker, trials in assigned.items():
        write_json(directory / f'worker-{worker}.json', {
            'run_id': config['run_id'], 'worker_id': worker,
            'schedule_sha256': schedule_hash,
            'protocol_sha256': digest(ROOT / 'protocol/prompts.v1.json'),
            'trials': trials})
    print(f'Generated seven disjoint 300-trial manifests: {directory.relative_to(ROOT)}')


if __name__ == '__main__':
    generate()
