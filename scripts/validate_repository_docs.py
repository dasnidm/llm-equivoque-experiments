"""Check navigation and curated numbers against saved data; never call models."""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


def read(path):
    file = ROOT / path
    return file.read_text() if file.is_file() else git('show', 'HEAD:' + path)


def read_bytes(path, revision='HEAD'):
    file = ROOT / path
    return file.read_bytes() if file.is_file() else subprocess.check_output(['git', 'show', revision + ':' + path], cwd=ROOT)


def load(path):
    return json.loads(read(path))


def rows(path):
    return list(csv.DictReader(io.StringIO(read(path))))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-base', help='Also verify docs-only changes vs this commit')
    args = parser.parse_args()
    indexed = set(git('ls-tree', '-r', '--name-only', 'HEAD').splitlines())
    docs = [ROOT / 'README.md', ROOT / 'AGENTS.md']
    docs += sorted((ROOT / 'docs').rglob('*.md'))
    indexed.update(str(p.relative_to(ROOT)) for p in (ROOT / 'docs').rglob('*') if p.is_file())
    indexed.update(['README.md', 'AGENTS.md', 'scripts/validate_repository_docs.py'])
    directories = {str(parent) for name in indexed for parent in Path(name).parents}
    checked = 0
    for path in docs:
        if path.name == 'README-before-2026-10-14.md':
            continue  # Historical README links are relative to its original root.
        source = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
        for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', source):
            link = link.strip('<>')
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            require(target.is_relative_to(ROOT), f'Link outside repository: {path}: {link}')
            relative = str(target.relative_to(ROOT)).rstrip('/')
            require(relative in indexed or relative in directories, f'Missing link: {path}: {link}')
            if parsed.fragment and target.suffix == '.md':
                text = read(relative)
                explicit = re.findall(r'<a\s+id="([^"]+)"', text)
                headings = [re.sub(r'[^\w\s-]', '', h.lower()).replace(' ', '-')
                            for h in re.findall(r'^#+\s+(.+)$', text, flags=re.M)]
                require(unquote(parsed.fragment) in explicit + headings, f'Missing anchor: {link}')
            checked += 1
    catalog = load('docs/experiments.json')['experiments']
    require(len(catalog) == len({e['run_id'] for e in catalog}) == 6, 'Catalog must have six distinct studies')
    for experiment in catalog:
        for key in ['report', 'audit', 'tables', 'analysis_bundle', 'raw_results']:
            require(experiment[key] in indexed | directories, f'Missing catalog {key}: {experiment["id"]}')
        audit = load(experiment['audit'])
        require(audit.get('integrity_ok', audit.get('passed')) is True, f'Audit not passed: {experiment["id"]}')
        if 'workers' in audit:
            workers = audit['workers']
            complete = sum(w['counts'].get('complete', 0) for w in workers)
            assigned = sum(w['assigned'] for w in workers)
            calls = audit.get('evaluation_invocations', sum(w.get('subject_invocations', w.get('evaluation_invocations', 0)) for w in workers))
        else:
            complete, assigned, calls = audit['complete'], audit['complete'], audit['evaluation_calls']
        require((assigned, complete, calls) == (experiment['assigned'], experiment['complete'], experiment['evaluation_native_invocations']), f'Catalog counts mismatch: {experiment["id"]}')
        commit = git('rev-parse', experiment['result_tag'] + '^{}').strip()
        require(commit == experiment['result_commit'], f'Tag mismatch: {experiment["result_tag"]}')
    source = 'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/trials.csv'
    sequence = [r for r in rows(source) if r['kind'] == 'seq']
    require(len(sequence) == 1260, 'Sequence denominator')
    observed = {}
    for group in [r for r in rows('docs/data/sequence-response-forms.csv')] + rows('docs/data/sequence-uncertainty-by-effort.csv'):
        selected = [r for r in sequence if r['model'] == group['model'] and (group['effort'] == 'all' or r['effort'] == group['effort'])]
        counts = collections.Counter()
        for trial in selected:
            match, uncertain = int(trial['prediction_matches']), int(trial['prediction_uncertain'])
            wrong = 12 - match - uncertain
            require(wrong >= 0, 'Invalid component accounting')
            category = 'all12_match' if match == 12 else 'all12_uncertain' if uncertain == 12 else 'partial_match_and_uncertain_no_mismatch' if wrong == 0 else 'has_mismatch'
            counts[category] += 1
            counts['match_components'] += match
            counts['mismatch_components'] += wrong
            counts['uncertain_components'] += uncertain
        require(int(group['sessions']) == len(selected), 'Derived session count')
        for key in ['all12_match', 'all12_uncertain', 'partial_match_and_uncertain_no_mismatch', 'has_mismatch', 'match_components', 'mismatch_components', 'uncertain_components']:
            require(counts[key] == int(group[key]), f'Derived count mismatch: {group["model"]}/{group["effort"]}/{key}')
        require(abs(float(group['uncertain_component_percent']) - 100 * counts['uncertain_components'] / (12 * len(selected))) < 1e-9, 'Uncertainty percentage mismatch')
        observed[group['model'], group['effort']] = counts
    require(sum(r['prediction_matches'] == '12' for r in sequence) == 97, 'Perfect forecast count')
    nonperfect = [r for r in sequence if r['prediction_matches'] != '12']
    require(len(nonperfect) == 1163, 'Nonperfect denominator')
    require(sum(int(r['prediction_matches']) + int(r['prediction_uncertain']) == 12 for r in nonperfect) == 884, 'Abstention vs mismatch distinction')
    for metadata in load('docs/data/provenance.json')['files'].values():
        require(hashlib.sha256(read_bytes(metadata['source'])).hexdigest() == metadata['source_sha256'], 'Derived source hash')
    question = next(e for e in catalog if e['id'] == 'question-effect')
    intervention = rows(question['tables'] + '/intervention_trials.csv')
    require(len(intervention) == 180 and all(r['pre_impact'] == '100' and r['pre_cf_no'] == '0' for r in intervention), 'Question-study baseline')
    expected = {('gpt-5.6-sol', 'control'): 0, ('gpt-5.6-sol', 'explanation'): 20, ('gpt-5.6-sol', 'prediction'): 3, ('gpt-6.1-sol', 'control'): 0, ('gpt-6.1-sol', 'explanation'): 0, ('gpt-6.1-sol', 'prediction'): 0}
    for (model, arm), count in expected.items():
        selected = [r for r in intervention if r['model'] == model and r['arm'] == arm]
        require(len(selected) == 30 and sum(int(r['post_joint']) for r in selected) == count, 'Question-study outcome')
    selected = [r for r in intervention if r['model'] == 'gpt-6.1-sol' and r['arm'] == 'prediction']
    require(all(r['post_impact'] == '50' and r['post_cf_no'] == '0' for r in selected), 'Intermediate ratings must be retained')
    archive = load('docs/archive/branches-2026-10-14.json')
    require(len(archive['branches']) == 99, 'Original branch inventory')
    require(sum(r['action'] == 'retain' for r in archive['branches']) == 7, 'Retained branch inventory')
    require(sum(r['action'] == 'retire' for r in archive['branches']) == 92, 'Retired branch inventory')
    for branch in archive['branches']:
        if branch['included_in_latest']:
            require(subprocess.run(['git', 'merge-base', '--is-ancestor', branch['sha'], archive['source_commit']], cwd=ROOT).returncode == 0, 'Unpreserved merged branch')
        else:
            require(git('rev-parse', branch['preservation'] + '^{}').strip() == branch['sha'], 'Unpreserved independent snapshot')
    before_readme = subprocess.check_output(['git', 'show', archive['source_commit'] + ':README.md'], cwd=ROOT)
    require(read_bytes('docs/archive/README-before-2026-10-14.md') == before_readme, 'Historical README must be byte-preserved')
    if args.compare_base:
        changed = git('diff', '--name-only', args.compare_base, '--').splitlines()
        allowed = lambda name: name in ['README.md', 'AGENTS.md', 'scripts/validate_repository_docs.py'] or name.startswith('docs/')
        require(all(allowed(name) for name in changed), 'Existing scientific artifacts changed: ' + str([n for n in changed if not allowed(n)]))
    print(f'PASS: {checked} local links, 6 audited studies, 28 derived groups, question endpoints, 99 preserved branch heads; no model calls.')


if __name__ == '__main__':
    main()
