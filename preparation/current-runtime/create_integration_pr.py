"""Create/reuse a reviewable final integration PR, without merging main."""
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
REPO='dasnidm/llm-equivoque-experiments'
progress=json.loads((ROOT/'preparation/current-runtime/collection-progress.json').read_text())
provenance=json.loads((ROOT/'analysis/results'/RUN/'attempt-01/provenance.json').read_text())
existing=json.loads(subprocess.check_output(['gh','pr','list','--repo',REPO,'--state','all','--limit','100',
                                          '--json','number,url,headRefName,baseRefName'],text=True))
matches=[p for p in existing if p['headRefName']==f'integration/{RUN}'and p['baseRefName']=='main']
assert len(matches)<=1
body=ROOT/'work/coordinator/integration-pr.md'
body.write_text(f'The prepared experiment now has an audited 2,100-trial evaluation across the original 21 model/effort configurations and paired cards/cats cases: {progress["completed"]} complete trials, {progress["subject_invocations"]} evaluation subject invocations, {provenance["valid_pre"]} valid pre-disclosure endpoints and {provenance["valid_post"]} valid post-disclosure endpoints. Raw transcripts, session IDs, failures, schemas, calibration and source hashes are preserved.\n\nThe owner restored ChatGPT authentication and authorized immediate expansion from seven to seventeen executor processes. Original A–G manifests, canonical English prompts, model/effort matrix, targets, seeds, subject paths and 2,100-trial roster remain unchanged. Exclusive remaining-ID subdivision added no replacement or replay calls. Native context/tool isolation and strict-schema compatibility fixes were validated before evaluation.\n\nThe prespecified case-cluster analysis, English report, tidy CSVs, SVG/PNG graphs and portable figure browser are in `analysis/results/{RUN}/attempt-01/`. Primary route contrasts are associations with prespecified sparse-cell rules and shared paired-case bootstrap draws. The report documents the unavoidable environment path topic cue, runtime response recovery and unavailable timing/exit metadata.\n\nValidation: frozen hashes checked in all seventeen worktrees, native live readiness passed, duplicate executor launch blocked without inference, full raw/session/manifest union audit passed, three analysis numerical tests passed, and exported artifacts/denominators verified. Results are integrated on this separate branch for review; main has not been merged.\n')
if matches:pr=matches[0]
else:
    url=subprocess.check_output(['gh','pr','create','--repo',REPO,'--base','main','--head',f'integration/{RUN}',
        '--draft','--title',f'Complete {RUN} evaluation and prespecified analysis','--body-file',str(body)],text=True).strip()
    pr={'number':int(url.rsplit('/',1)[1]),'url':url}
dest=ROOT/'preparation/current-runtime/integration-result-pr.json'
dest.write_text(json.dumps(pr,indent=2)+'\n')
subprocess.run(['git','add',str(dest)],cwd=ROOT,check=True)
if subprocess.run(['git','diff','--cached','--quiet'],cwd=ROOT).returncode:
    subprocess.run(['git','commit','-m','Record final integration review PR'],cwd=ROOT,check=True)
    subprocess.run(['git','push','origin',f'integration/{RUN}'],cwd=ROOT,check=True)
print(pr['url'],flush=True)
