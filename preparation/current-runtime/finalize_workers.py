"""Audit finished shards, publish only assigned results, and reuse result PRs."""
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUN = 'equivoque-2026-10-09-v1'
REPO = 'dasnidm/llm-equivoque-experiments'
assignment = json.loads((ROOT / 'preparation/current-runtime/assignments-03.json').read_text())
existing = json.loads(subprocess.check_output(['gh', 'pr', 'list', '--repo', REPO,
    '--state', 'all', '--limit', '100', '--json', 'number,url,headRefName,baseRefName,state'], text=True))
returns = []
for worker in 'abcdefg':
    tree = ROOT / 'work/worker-trees' / RUN / worker
    directory = tree / 'results' / RUN / f'worker-{worker}'
    audit_path = directory / 'audit.json'
    if not audit_path.exists():
        raise SystemExit(f'Worker {worker} has not finished; no premature result publication')
    current = json.loads(audit_path.read_text())
    if not current['collection_finished'] or not current['integrity_ok']:
        raise SystemExit(f'Worker {worker} is incomplete or failed audit')
    subprocess.run([sys.executable, '-m', 'equivoque', 'audit', '--manifest',
        f'manifests/{RUN}/worker-{worker}.json', '--output', f'results/{RUN}/worker-{worker}'],
        cwd=tree, stdout=subprocess.DEVNULL, check=True)
    current = json.loads(audit_path.read_text())
    states = [json.loads(p.read_text()) for p in (directory / 'trials').glob('*.json')]
    calibration = [json.loads(p.read_text()) for p in directory.glob('preflight*/readiness.json')]
    turns = [t for s in states for t in s['turns']]
    durations = [t['duration_seconds'] for t in turns if t['duration_seconds'] is not None]
    usage = {}
    for key in ('input_tokens', 'cached_input_tokens', 'output_tokens'):
        values = [(t.get('usage') or {}).get(key) for t in turns]
        available = [v for v in values if v is not None]
        usage[key] = {'reported_turns': len(available), 'sum': sum(available) if available else None}
    provenance = json.loads((directory / 'provenance.json').read_text())
    report = {**current, 'base_commit': provenance['base_commit'],
        'freeze_sha256': provenance['freeze_sha256'], 'protocol_sha256': provenance['protocol_sha256'],
        'schedule_sha256': provenance['schedule_sha256'],
        'partial_trials': sum(s['status'] != 'complete' and bool(s['turns']) for s in states),
        'partial_note': 'Partial is an overlapping description of terminal trials with some returned turns, not an additional mutually exclusive status.',
        'calibration_invocations': sum(p['subject_invocations'] for p in calibration),
        'calibration_attempts': [{'attempt': p.parent.name, 'subject_invocations': json.loads(p.read_text())['subject_invocations']}
                                 for p in sorted(directory.glob('preflight*/readiness.json'))],
        'median_turn_seconds': statistics.median(durations) if durations else None,
        'mean_turn_seconds': statistics.mean(durations) if durations else None,
        'available_usage': usage, 'billing_cost': None,
        'failure_types': {error: sum(s.get('error') == error for s in states)
                          for error in sorted({s['error'] for s in states if s.get('error')})},
        'reported_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (directory / 'completion.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = [f'# Worker {worker.upper()} completion', '', f'Run: `{RUN}`.',
        f'Approved base: `{provenance["base_commit"]}`.',
        f'Freeze SHA-256: `{provenance["freeze_sha256"]}`.',
        f'Manifest SHA-256: `{current["manifest_sha256"]}`.', '',
        f'Assigned {current["assigned"]}; attempted {current["attempted"]}; statuses: {json.dumps(current["counts"], sort_keys=True)}.',
        f'Valid pre: {current["valid_pre"]}; valid post: {current["valid_post"]}.',
        f'Evaluation subject invocations: {current["subject_invocations"]}; calibration invocations across retained attempts: {report["calibration_invocations"]}.',
        f'Overlapping partial-trial count: {report["partial_trials"]}.',
        f'Median recorded turn latency: {report["median_turn_seconds"]:.3f} seconds.', '',
        'Raw logs, failed preflights, exact canonical/provider schemas, readiness, provenance, audit, route/configuration/frame counts, available usage, and all errors are retained in this assigned directory. HTTP attempts and billing costs are unavailable. No replacement trials, shared-source edits during collection, or final analysis were performed by this worker.', '']
    (directory / 'COMPLETION.md').write_text('\n'.join(lines))
    subprocess.run(['git', '-C', str(tree), 'add', f'results/{RUN}/worker-{worker}'], check=True)
    if subprocess.run(['git', '-C', str(tree), 'diff', '--cached', '--quiet']).returncode:
        subprocess.run(['git', '-C', str(tree), 'commit', '-m',
                        f'Worker {worker.upper()}: complete assigned evaluation and preserve audit'], check=True,
                       stdout=subprocess.DEVNULL)
    branch = f'worker/{RUN}/{worker}'
    subprocess.run(['git', '-C', str(tree), 'push', 'origin', branch], check=True)
    matching = [p for p in existing if p['headRefName'] == branch and
                p['baseRefName'] == f'integration/{RUN}']
    if len(matching) > 1:
        raise SystemExit('Duplicate existing result PRs; inspect rather than creating another')
    if matching:
        pr = matching[0]
    else:
        issue = next(a['number'] for a in assignment['assignments'] if a['worker_id'] == worker)
        body = ROOT / f'work/coordinator/result-pr-{worker}.md'
        body.write_text(f'Worker {worker.upper()} completed the frozen assigned roster: '
            f'{current["assigned"]} assigned, {current["attempted"]} attempted, '
            f'{current["counts"].get("complete",0)} complete, '
            f'{current["counts"].get("failed",0)} failed, '
            f'{current["counts"].get("interrupted",0)} interrupted, '
            f'{current["counts"].get("unattempted",0)} unattempted.\n\n'
            f'Approved shared source `{provenance["base_commit"]}` and frozen manifest/protocol hashes are preserved. '
            f'Only `results/{RUN}/worker-{worker}/` artifacts differ from the integration source: raw transcripts/journals, '
            'all preflight attempts, passing readiness, provenance, audit, and completion. '
            'No trials were replaced. Calibration remains separate from evaluation.\n\n'
            f'Validation: shard integrity audit passed; {current["valid_pre"]} valid pre endpoints, '
            f'{current["valid_post"]} valid post endpoints; {current["subject_invocations"]} evaluation invocations. '
            'Coordinator cross-shard audit and analysis follow integration.\n\n'
            f'Closes #{issue}.\n')
        url = subprocess.check_output(['gh', 'pr', 'create', '--repo', REPO, '--base',
            f'integration/{RUN}', '--head', branch, '--title', f'Worker {worker.upper()}: {RUN} results',
            '--body-file', str(body)], text=True).strip()
        pr = {'number': int(url.rsplit('/', 1)[1]), 'url': url}
    returns.append({'worker_id': worker, **pr,
        'result_commit': subprocess.check_output(['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()})
    print(worker, pr['url'], flush=True)
(ROOT / 'preparation/current-runtime/worker-result-prs.json').write_text(json.dumps(returns, indent=2) + '\n')
