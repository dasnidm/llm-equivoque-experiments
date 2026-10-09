"""Freeze experiment 2 without altering the experiment 1 freeze."""
from equivoque.core import ROOT, digest, read_json, write_json
from equivoque2.protocol import CONFIG, FREEZE

config = read_json(CONFIG)
paths = [ROOT / 'EXPERIMENT_2_PLAN.md', ROOT / 'protocol/prompts.v1.json', ROOT / 'protocol/run.v1.json']
for name in ('equivoque', 'equivoque2'):
    paths.extend(sorted((ROOT / name).glob('*.py')))
for pattern in ('*.py', '*.md', 'protocol/run.json', 'protocol/prompts.json'):
    paths.extend(sorted((ROOT / 'experiment2').glob(pattern)))
paths.extend(sorted((ROOT / 'manifests' / config['run_id']).glob('*.json')))
write_json(FREEZE, {'run_id': config['run_id'], 'status': 'prepared_pending_live_readiness',
                   'files': {str(path.relative_to(ROOT)): digest(path) for path in paths}})
print('Frozen ' + str(len(paths)) + ' experiment 2 preparation files.')
