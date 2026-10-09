"""Create or reuse exactly one GitHub assignment per experiment 2 worker."""
import argparse
import hashlib
import json
import re
import subprocess

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque2.protocol import CONFIG, FREEZE, frozen_hashes

REPOSITORY = 'dasnidm/llm-equivoque-experiments'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--refresh-preparation', action='store_true')
    args = parser.parse_args()
    frozen_hashes()
    config = read_json(CONFIG)
    base = subprocess.check_output(['git', 'rev-parse', args.base], cwd=ROOT, text=True).strip()
    found = json.loads(subprocess.check_output(['gh', 'issue', 'list', '--repo', REPOSITORY,
        '--state', 'all', '--search', config['run_id'] + ' in:title', '--limit', '100',
        '--json', 'number,title,url,body'], cwd=ROOT, text=True))
    brief = (ROOT / 'experiment2/WORKER_BRIEF.md').read_text()
    results = {}
    for w in config['workers']:
        title = f"Experiment 2 {config['run_id']}: Worker {w.upper()} (21 trials)"
        matches = [i for i in found if i['title'] == title]
        if len(matches) > 1:
            raise ValueError('Duplicate assignment issues already exist for worker ' + w)
        manifest = ROOT / 'manifests' / config['run_id'] / f'worker-{w}.json'
        body = f'''Run: `{config['run_id']}`
Worker: **{w.upper()}**; 21 trials, one per requested model/effort configuration.
Base commit: `{base}`
Branch: `worker/{config['run_id']}/{w}`
Manifest: `manifests/{config['run_id']}/worker-{w}.json`
Manifest SHA-256: `{digest(manifest)}`
Freeze SHA-256: `{digest(FREEZE)}`
Integration branch: `integration/{config['run_id']}`
Plan: https://github.com/{REPOSITORY}/blob/{base}/EXPERIMENT_2_PLAN.md

{brief}'''
        if matches:
            issue = matches[0]
            if base not in issue['body'] or digest(manifest) not in issue['body'] or digest(FREEZE) not in issue['body']:
                previous = re.search(r'Base commit: `([a-f0-9]{40})`', issue['body'])
                if not args.refresh_preparation or not previous:
                    raise ValueError('Existing issue has different assignment provenance: ' + w)
                old_bytes = subprocess.check_output(['git', 'show', previous.group(1) + ':' + str(manifest.relative_to(ROOT))], cwd=ROOT)
                old_manifest, new_manifest = json.loads(old_bytes), read_json(manifest)
                if (hashlib.sha256(old_bytes).hexdigest() not in issue['body'] or
                        old_manifest['trials'] != new_manifest['trials'] or
                        old_manifest['schedule_sha256'] != new_manifest['schedule_sha256']):
                    raise ValueError('Preparation refresh would change the assigned trial roster')
                for other in config['workers']:
                    trial_directory = ROOT / 'work/worker-trees' / config['run_id'] / other / 'results' / config['run_id'] / f'worker-{other}' / 'trials'
                    if any(trial_directory.glob('*.json')):
                        raise ValueError('Cannot revise assignment preparation after evaluation starts')
                subprocess.run(['git', 'merge-base', '--is-ancestor', previous.group(1), base], cwd=ROOT, check=True)
                path = ROOT / 'work/coordinator' / config['run_id'] / f'assignment-refresh-{w}.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'body': body}))
                subprocess.run(['gh', 'api', '--method', 'PATCH',
                    f"repos/{REPOSITORY}/issues/{issue['number']}", '--input', str(path),
                    '--jq', '.html_url'], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            url = issue['url']
        else:
            path = ROOT / 'work/coordinator' / config['run_id'] / f'assignment-{w}.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            url = subprocess.check_output(['gh', 'issue', 'create', '--repo', REPOSITORY,
                '--title', title, '--body-file', str(path)], cwd=ROOT, text=True).strip()
        results[w] = {'url': url, 'base_commit': base, 'manifest_sha256': digest(manifest), 'freeze_sha256': digest(FREEZE)}
        write_json(ROOT / 'experiment2/runtime/assignments.json', {'run_id': config['run_id'], 'workers': results})
        print(w.upper() + ': ' + url, flush=True)


if __name__ == '__main__':
    main()
