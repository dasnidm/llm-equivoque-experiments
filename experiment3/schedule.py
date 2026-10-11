import itertools
import random
from equivoque.core import ROOT, LABELS, digest, read_json, write_json
from .protocol import CONFIG, PROMPTS, PROCEDURES, CLAIMS


def cases(seed, prefix='pilot', excluded=()):
    rng = random.Random(seed)
    excluded = set((tuple(c['order']), c['target']) for c in excluded)
    result = []
    for i in range(8):
        target, position = LABELS[i % 4], (i // 4 + i % 4) % 4
        order = list(rng.choice([o for o in itertools.permutations(LABELS)
                                if o[position] == target and (o, target) not in excluded]))
        other = LABELS[(i % 4 + 1) % 4]
        alternatives = [list(o) for o in itertools.permutations(LABELS) if list(o) != order]
        rng.shuffle(alternatives)
        arranged, renamed, changed = alternatives[:3]
        mapping = {x: LABELS[(j + 1 + i % 3) % 4] for j, x in enumerate(LABELS)}
        changed_target = LABELS[(i + 2) % 4]
        changed_other = LABELS[(i + 3) % 4]
        result.append({'case_id': f'{prefix}-{i + 1:02d}', 'target': target, 'order': order,
                       'target_position': position, 'lookup_index': (i * 5) % 12,
                       'arrangement_query': {'order': arranged, 'first': [target, other], 'second': target if i < 4 else other},
                       'renaming': mapping,
                       'renaming_query': {'order': renamed, 'first': [target, other], 'second': other if i < 4 else target},
                       'change_query': {'order': changed, 'target': changed_target,
                                        'first': [changed_target, changed_other],
                                        'second': changed_other if i < 4 else changed_target}})
    return result


def generate():
    config = read_json(CONFIG)
    families = cases(config['seeds']['cases'])
    trials = []
    for conf in config['configurations']:
        for frame in ('cards', 'cats'):
            for proc in PROCEDURES:
                for claim in CLAIMS:
                    for case in families:
                        trials.append({**conf, 'run_id': config['run_id'], 'frame': frame,
                                       'procedure': proc, 'claim': claim, 'case': case,
                                       'trial_id': '/'.join([config['run_id'], conf['configuration_id'], frame, proc, claim, case['case_id']])})
    random.Random(config['seeds']['assignment']).shuffle(trials)
    shards = {w: [] for w in config['workers']}
    for i, trial in enumerate(trials):
        worker = config['workers'][i % len(shards)]
        trial['worker_id'] = worker
        shards[worker].append(trial)
    path = ROOT / 'manifests' / config['run_id']
    write_json(path / 'schedule.json', {'run_id': config['run_id'], 'cases': families, 'trials': trials})
    for worker, shard in shards.items():
        write_json(path / f'worker-{worker}.json', {'run_id': config['run_id'], 'worker_id': worker,
                   'schedule_sha256': digest(path / 'schedule.json'), 'protocol_sha256': digest(PROMPTS), 'trials': shard})
    write_json(ROOT / 'experiment3/protocol/development-cases.json', {'cases': cases(config['seeds']['development'], 'development', families)})
    print(f'{len(trials)} single-turn tasks; {len(shards)} disjoint workers; 8 shared pilot case families.')


if __name__ == '__main__':
    generate()
