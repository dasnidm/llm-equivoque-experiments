"""Archive exact durable native files for terminal trials; never invoke a model."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'


def archive_trial(executor, worker, directory, state):
    assert state['status'] in ('complete', 'failed', 'interrupted')
    assert state.get('pending_turn') is None
    source = ROOT / 'work/worker-trees' / RUN / worker / 'work' / RUN / worker / state['scratch_id']
    slug = state['trial']['trial_id'].replace('/', '__')
    destination = directory / f'native-raw-executor-{executor}' / slug
    destination.mkdir(parents=True, exist_ok=True)
    names = ['subject-system.txt']
    for turn in state['turns']:
        number = turn['turn']
        events_path = source / f'turn-{number:02d}.events.jsonl'
        events, malformed = [], 0
        for line in events_path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
        assert events == turn['events']
        assert malformed == turn['malformed_event_lines']
        assert (source / f'turn-{number:02d}.stderr.txt').read_text() == turn['stderr']
        assert json.loads((source / f'turn-{number:02d}.schema.json').read_text()) == turn['provider_schema']
        names.extend(f'turn-{number:02d}.{suffix}' for suffix in ('events.jsonl', 'stderr.txt', 'schema.json'))
    assert (source / 'subject-system.txt').read_text() == json.loads((ROOT / 'protocol/prompts.v1.json').read_text())['system']
    hashes = {}
    for name in names:
        data = (source / name).read_bytes()
        target = destination / name
        if target.exists():
            assert target.read_bytes() == data, f'Archived native file changed: {target}'
        else:
            with target.open('xb') as handle:
                handle.write(data)
        hashes[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    metadata = {'trial_id': state['trial']['trial_id'], 'executor_id': executor,
                'logical_worker': worker, 'scratch_id': state['scratch_id'],
                'session_id': state.get('session_id'), 'files': hashes,
                'note': 'Exact terminal native files. No new invocation; state and journal remain canonical.'}
    path = destination / 'files.json'
    if path.exists():
        assert json.loads(path.read_text()) == metadata
    else:
        path.write_text(json.dumps(metadata, indent=2) + '\n')
    return destination
