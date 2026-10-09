"""Hash the prepared protocol, source, analysis specification, and manifests."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equivoque.core import digest, read_json, write_json

config = read_json(ROOT / 'protocol/run.v1.json')
paths = [ROOT / name for name in (
    'README.md', 'EXPERIMENT_PLAN.md', 'PROMPTS.md', 'WORKER_BRIEF.md',
    'PREPARATION_STATUS.md', 'NEXT_SESSION_PROMPT.md',
    'protocol/prompts.v1.json', 'protocol/run.v1.json')]
for directory in ('equivoque', 'scripts', 'tests'):
    paths.extend(sorted((ROOT / directory).glob('*.py')))
paths.extend(sorted((ROOT / 'manifests' / config['run_id']).glob('*.json')))
paths.extend(sorted((ROOT / 'preparation').glob('*.json')))
write_json(ROOT / 'protocol/freeze.json', {
    'run_id': config['run_id'], 'status': 'prepared_pending_live_readiness',
    'files': {str(path.relative_to(ROOT)): digest(path) for path in paths}})
print(f'Frozen {len(paths)} prepared files; live readiness is a separate gate.')
