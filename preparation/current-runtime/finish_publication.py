"""Resume publication after a preserved GitHub authentication failure; no inference."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
r=json.loads((ROOT/'preparation/current-runtime/collection-progress.json').read_text())
assert not r['halted'] and all(v['exit_code']==0 for v in r['executors'].values())
assert len(json.loads((ROOT/'preparation/current-runtime/helper-result-prs.json').read_text()))==10
assert len(json.loads((ROOT/'preparation/current-runtime/worker-result-prs.json').read_text()))==7
subprocess.run([sys.executable,str(ROOT/'work/coordinator/integrate.py')],cwd=ROOT,check=True)
output = ROOT / 'analysis/results' / RUN / 'attempt-01'
print('Running the frozen prespecified analysis on integrated raw data.', flush=True)
subprocess.run([sys.executable, 'analysis/analyze.py', '--output', str(output)], cwd=ROOT, check=True)
subprocess.run([sys.executable,str(ROOT/'work/coordinator/verify_artifacts.py')],cwd=ROOT,check=True)
for name in ('checkpoint.py', 'finalize_workers.py', 'integrate.py', 'postprocess.py',
             'recover_durable_turns.py', 'resume_collect.py', 'helper_preflight.py', 'pause_for_expansion.py',
             'recover_expansion_turns.py', 'expand_assignments.py', 'expanded_executor.py',
             'expanded_collect.py', 'checkpoint_expanded.py', 'finalize_helpers.py',
             'verify_artifacts.py', 'create_integration_pr.py', 'monitor_expanded.py',
             'drain_systemic_failure.py', 'reconcile_systemic_drain.py', 'recheck_service.py',
             'prepare_resume_02.py', 'resume_executor_02.py', 'resume_collect_02.py',
             'recover_reattachment_03.py', 'recheck_service_02.py', 'prepare_resume_03.py',
             'resume_executor_03.py', 'resume_collect_03.py', 'finish_publication.py'):
    shutil.copyfile(ROOT / 'work/coordinator' / name,
                    ROOT / 'preparation/current-runtime' / name)
shutil.copyfile(ROOT / 'work/coordinator/archive_native.py', ROOT / 'preparation/current-runtime/archive_native.py')
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
    + 'Seven actual 300-second timeouts remain terminal failures. After draining already-requested responses without replay and passing 21 shared service checks, all 17 executors resumed with measured whole-trial concurrency and delay-sensitive intake. '
    + 'A second runtime reattachment was reconciled from 17 final native responses without replay, followed by another 21 shared service checks and a separately gated resumption. '
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
