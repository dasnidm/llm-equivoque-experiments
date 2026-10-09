"""Finish authorized integration and analysis after collection, fail closed."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'
progress = ROOT / 'preparation/current-runtime/collection-progress.json'
while True:
    r = json.loads(progress.read_text())
    if r['halted']:
        raise SystemExit('Coordinator collection halted. Preserve evidence; no automatic analysis.')
    if all(s['exit_code'] == 0 for s in r['workers'].values()):
        break
    time.sleep(5)
time.sleep(5)
for step in ('finalize_helpers.py', 'finalize_workers.py', 'integrate.py'):
    print('Starting ' + step, flush=True)
    subprocess.run([sys.executable, str(ROOT / 'work/coordinator' / step)], cwd=ROOT, check=True)
output = ROOT / 'analysis/results' / RUN / 'attempt-01'
print('Running the frozen prespecified analysis on integrated raw data.', flush=True)
subprocess.run([sys.executable, 'analysis/analyze.py', '--output', str(output)], cwd=ROOT, check=True)
subprocess.run([sys.executable,str(ROOT/'work/coordinator/verify_artifacts.py')],cwd=ROOT,check=True)
for name in ('checkpoint.py', 'finalize_workers.py', 'integrate.py', 'postprocess.py',
             'recover_durable_turns.py', 'resume_collect.py', 'helper_preflight.py', 'pause_for_expansion.py',
             'recover_expansion_turns.py', 'expand_assignments.py', 'expanded_executor.py',
             'expanded_collect.py', 'checkpoint_expanded.py', 'finalize_helpers.py',
             'verify_artifacts.py', 'create_integration_pr.py', 'monitor_expanded.py'):
    shutil.copyfile(ROOT / 'work/coordinator' / name,
                    ROOT / 'preparation/current-runtime' / name)
for line in ['Completed roster: ' + str(r['attempted']),
             'Completed trials: ' + str(r['completed']),
             'Evaluation subject invocations: ' + str(r['subject_invocations'])]:
    print(line, flush=True)
status = ROOT / 'RUN_STATUS.md'
status.write_text('# Completed evaluation\n\nRun: `' + RUN + '`.\n\n'
    + f'{r["attempted"]} assigned trials attempted; {r["completed"]} complete; '
    + f'{r["subject_invocations"]} evaluation subject invocations.\n\n'
    + 'All seven workers passed live readiness at the common frozen source. '
    + 'Concurrency was measured at two and four before expansion to seven. The user subsequently authorized ten additional executors and immediate concurrency 17; the original A–G manifests and total 2,100-trial roster remained unchanged. '
    + 'All raw records, prior preflight failures, session IDs, hashes, and errors are retained. '
    + 'The coordinator audited the seven-shard union before integrating results on the separate integration branch.\n\n'
    + f'See `analysis/results/{RUN}/attempt-01/REPORT.md` for the English report and endpoint denominators, '
    + '`index.html` for the portable figure browser, `tables/` for CSVs, `figures/` for SVG/PNG exports, '
    + 'and `provenance.json` for the exact integrated-data revision and analysis source hash.\n')
subprocess.run(['git', 'add', 'analysis/results', 'preparation/current-runtime', 'RUN_STATUS.md'], cwd=ROOT, check=True)
subprocess.run(['git', 'commit', '-m', 'Publish prespecified paired-case analysis and English report'], cwd=ROOT, check=True)
subprocess.run(['git', 'push', 'origin', f'integration/{RUN}'], cwd=ROOT, check=True)
subprocess.run([sys.executable,str(ROOT/'work/coordinator/create_integration_pr.py')],cwd=ROOT,check=True)
deliver = Path('/codex/browser/projectless/0026-thread/output')
deliver.mkdir(parents=True, exist_ok=True)
shutil.copytree(output, deliver / 'equivoque-analysis', dirs_exist_ok=False)
shutil.make_archive(str(deliver / 'equivoque-analysis'), 'zip', output)
print('Analysis artifacts published and copied to user-facing outputs.', flush=True)
