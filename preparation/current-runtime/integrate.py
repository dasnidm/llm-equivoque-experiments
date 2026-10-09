"""Audit the complete worker union before merging result branches to integration."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equivoque.audit import audit_worker
from equivoque.core import digest, frozen_hashes, read_json, write_json
from equivoque.transport import provider_schema

RUN = 'equivoque-2026-10-09-v1'
frozen_hashes()
release = read_json(ROOT / 'preparation/current-runtime/coordinator-launch.json')
expected = {t['trial_id'] for t in read_json(ROOT / 'manifests' / RUN / 'schedule.json')['trials']}
seen, sessions, reports = set(), set(), []
for worker in 'abcdefg':
    tree = ROOT / 'work/worker-trees' / RUN / worker
    directory = tree / 'results' / RUN / f'worker-{worker}'
    manifest = tree / 'manifests' / RUN / f'worker-{worker}.json'
    audit = audit_worker(manifest, directory)
    if not audit['integrity_ok'] or not audit['collection_finished']:
        raise SystemExit('Incomplete or invalid shard: ' + worker)
    provenance = read_json(directory / 'provenance.json')
    if provenance['base_commit'] != release['base_commit'] or (
            provenance['freeze_sha256'] != release['freeze_sha256']):
        raise SystemExit('Mismatched source/freeze provenance')
    for path in (directory / 'trials').glob('*.json'):
        state = read_json(path)
        trial_id = state['trial']['trial_id']
        if trial_id in seen:
            raise SystemExit('Duplicate trial across shards')
        seen.add(trial_id)
        session = state.get('session_id')
        if session and session in sessions:
            raise SystemExit('Native session reused across shards')
        if session:
            sessions.add(session)
        journal = [json.loads(line) for line in path.with_suffix('.journal.jsonl').read_text().splitlines()]
        original = [x for x in journal if x['type'] == 'response_checkpoint']
        for turn, raw in zip(state['turns'], original):
            if {k: v for k, v in turn.items() if k != 'parsed'} != {k: v for k, v in raw.items() if k != 'type'}:
                raise SystemExit('Full raw journal discrepancy')
            if turn.get('provider_schema') != provider_schema(turn['schema']):
                raise SystemExit('Incorrect provider schema')
            if turn['ok'] and (turn['tool_events'] or turn['metadata_fallback'] or turn['timeout']):
                raise SystemExit('Contaminated successful turn')
    reports.append(audit)
if seen != expected:
    raise SystemExit('Manifest union does not match complete scheduled roster')
write_json(ROOT / 'preparation/current-runtime/pre-integration-audit.json',
    {'integrity_ok': True, 'run_id': RUN, 'assigned': len(expected),
     'actual_trial_ids': len(seen), 'unique_native_sessions': len(sessions), 'workers': reports})
subprocess.run(['git', 'add', 'preparation/current-runtime/pre-integration-audit.json'], cwd=ROOT, check=True)
subprocess.run(['git', 'commit', '-m', 'Audit all seven raw shards before result integration'], cwd=ROOT, check=True)
for worker in 'abcdefg':
    subprocess.run(['git', 'merge', '--no-ff', '-m', f'Integrate audited worker {worker.upper()} results',
                    f'worker/{RUN}/{worker}'], cwd=ROOT, check=True)
subprocess.run(['git', 'push', 'origin', f'integration/{RUN}'], cwd=ROOT, check=True)
print('Integrated 2,100 assigned records on the separate integration branch.', flush=True)
