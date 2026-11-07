"""Read-only storage/compression audit; no inference, publication, or pruning.

Select the lowest planned trial ID in each pre profile/arm/game stratum without
looking at response values or completion status. Archive only temporary copies,
then verify every archived file against a streamed SHA256 of its source bytes.
Persist sizes, counts, hashes, and explicit extrapolation assumptions only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exp7_main.worker import public_state


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sha_stream(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
    return h.hexdigest()


def tree_stats(directory, state_tree=False):
    counts = Counter()
    for base, directories, files in os.walk(directory):
        directory_path = Path(base)
        counts['directories'] += 1
        counts['directory_allocated_bytes'] += directory_path.stat().st_blocks * 512
        for name in files:
            p = directory_path / name
            st = p.stat()
            category = ('journal' if name.endswith('.journal.jsonl') else
                        'state' if state_tree and name.endswith('.json') else
                        'lock' if state_tree and name.endswith('.lock') else 'raw' if not state_tree else 'other')
            counts[category + '_files'] += 1
            counts[category + '_bytes'] += st.st_size
            counts[category + '_allocated_bytes'] += st.st_blocks * 512
            counts['files'] += 1
            counts['file_bytes'] += st.st_size
            counts['file_allocated_bytes'] += st.st_blocks * 512
    counts['total_allocated_bytes'] = counts['file_allocated_bytes'] + counts['directory_allocated_bytes']
    return dict(counts)


def archive_and_verify(paths, destination):
    """Preserve contents exactly; normalize archive metadata for reproducibility."""
    expected = {}
    totals = Counter()
    for p in sorted(set(paths)):
        p = p.resolve()
        if not p.is_file() or not p.is_relative_to(ROOT):
            raise ValueError('Missing or outside-repository source artifact')
        name = str(p.relative_to(ROOT))
        expected[name] = sha_file(p)
        st = p.stat()
        totals['file_bytes'] += st.st_size
        totals['file_allocated_bytes'] += st.st_blocks * 512
        totals['files'] += 1
    with Path(destination).open('wb') as out:
        with gzip.GzipFile(filename='', mode='wb', fileobj=out, mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for name in sorted(expected):
                    p = ROOT / name
                    info = archive.gettarinfo(str(p), arcname=name)
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    with p.open('rb') as source:
                        archive.addfile(info, source)
    checked = set()
    with tarfile.open(destination, 'r|gz') as archive:
        for member in archive:
            if not member.isfile() or member.name in checked or member.name not in expected:
                raise ValueError('Unexpected archive member')
            stream = archive.extractfile(member)
            if stream is None or sha_stream(stream) != expected[member.name]:
                raise ValueError('Archive content hash mismatch')
            checked.add(member.name)
    if checked != set(expected):
        raise ValueError('Archive omitted source artifacts')
    totals['gzip_tar_bytes'] = Path(destination).stat().st_size
    totals['source_file_hashes_digest'] = hashlib.sha256(encode(expected)).hexdigest()
    totals['archive_sha256'] = sha_file(destination)
    totals['verified_files'] = len(checked)
    return dict(totals)


def gzip_public(states, destination):
    """Match export_job's JSONL encoding and gzip level, using bounded writes."""
    size = 0
    source_hash = hashlib.sha256()
    with Path(destination).open('wb') as out:
        with gzip.GzipFile(filename='', fileobj=out, mode='wb', mtime=0, compresslevel=9) as gz:
            for state in states:
                data = (json.dumps(public_state(state), ensure_ascii=False,
                                   sort_keys=True, allow_nan=False) + '\n').encode()
                size += len(data)
                source_hash.update(data)
                gz.write(data)
    with gzip.open(destination, 'rb') as f:
        if sha_stream(f) != source_hash.hexdigest():
            raise ValueError('Public gzip JSONL readback mismatch')
    return {'jsonl_bytes': size, 'gzip_bytes': Path(destination).stat().st_size,
            'jsonl_sha256': source_hash.hexdigest(), 'gzip_sha256': sha_file(destination)}


def projected_native_counts(assignment_path):
    counts = Counter()
    per_model = defaultdict(Counter)
    for line in gzip.open(assignment_path, 'rt', encoding='utf-8'):
        t = json.loads(line)
        schema = t['format'].endswith('_schema')
        n = t['n_rounds'] * 3 + 4
        current = Counter({'conversations': 1, 'logical_calls': n,
                           'schema_conversations' if schema else 'natural_conversations': 1,
                           'native_files': 1 + n * (4 if schema else 3),
                           'native_directories': 1 + n,
                           'state_journal_lock_files': 3,
                           'opaque_subject_directories': 2})
        counts.update(current)
        per_model[t['model']].update(current)
    return {'all_models': dict(counts), 'per_model': {k: dict(v) for k, v in sorted(per_model.items())},
            'assumptions': ['All 34 logical calls complete; one subject-system file per conversation.',
                            'Every turn has prompt, events, stderr; only schema formats add schema.json.',
                            'Native directories count conversation root plus 34 turn directories.',
                            'State JSON, journal JSONL, lock are separate files per conversation.',
                            'Opaque per-session parent and subject directories are outside the result tree.',
                            'Job/worker bookkeeping, git objects, CLI rollout files and CLI databases are additional.']}


def extrapolate(rows, assignment_path):
    # Storage proxies only: pre R is matched to J, while main R_A is matched to A.
    reference = {'en_schema': 'A', 'ko_schema': 'K', 'en_natural': 'F', 'ko_natural': 'F'}
    indexed = defaultdict(list)
    for row in rows:
        indexed[row['arm'], row['kind']].append(row)
    cells = Counter()
    for line in gzip.open(assignment_path, 'rt', encoding='utf-8'):
        t = json.loads(line)
        arm = 'R' if t['arm'] == 'R_A' else reference[t['format']]
        cells[t['model'], t['format'], t['arm'], t['kind'], arm] += 1
    measures = ('private_file_bytes', 'private_file_allocated_bytes', 'private_tar_gzip_bytes',
                'public_jsonl_bytes', 'public_gzip_bytes')
    projected = []
    for key, n in sorted(cells.items()):
        model, form, arm, kind, pre_arm = key
        samples = indexed[pre_arm, kind]
        estimates = {}
        for measure in measures:
            rates = [r[measure] * 34 / r['observed_request_count'] for r in samples if r['observed_request_count']]
            if not rates:
                raise ValueError('Reference stratum lacks observed requests')
            estimates[measure] = {'mean': n * sum(rates) / len(rates),
                                 'sample_min_scenario': n * min(rates),
                                 'sample_max_scenario': n * max(rates)}
        projected.append({'model': model, 'format': form, 'arm': arm, 'kind': kind,
                          'conversations': n, 'pre_storage_proxy_arm': pre_arm,
                          'reference_conversations': len(samples), 'estimates': estimates})
    sums = {metric: {case: sum(r['estimates'][metric][case] for r in projected)
                     for case in ('mean', 'sample_min_scenario', 'sample_max_scenario')}
            for metric in measures}
    return {'all_models': sums, 'per_model_mean': {m: sums[m]['mean'] / 8 for m in measures},
            'strata': projected,
            'method': 'Each of four sampled pre profiles contributes one observation per arm/kind; normalize observed bytes to 34 requests, average equally, then multiply exact main allocation counts.',
            'limitations': ['These are storage scenarios, not confidence intervals or capacity guarantees.',
                           'An early partial session is retained; request-count scaling also scales its fixed metadata overhead.',
                           'Main Korean natural output has no exact pre analogue and uses English natural F as a proxy.',
                           'Only four pre model-effort profiles were measured; new models, efforts and cats can be longer.',
                           'Main R_A differs from pre R in the system instruction; R is a storage proxy only.',
                           'Private compression is measured per conversation; batch compression can differ.',
                           'Directory allocation, opaque cwd, CLI rollouts/databases, git copies, calibration and backups are not in these byte estimates.',
                           'Archives are an additional copy until a separately verified, authorized retention policy removes loose files.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre-run', default='equivoque-2026-10-30-exp7-pre-v8')
    parser.add_argument('--main-run', default='equivoque-2026-11-07-exp7-main-v1')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/data/exp7-storage-2026-11-07')
    args = parser.parse_args()
    pre_root = ROOT / 'results' / args.pre_run
    pre_manifest = ROOT / 'manifests' / args.pre_run / 'schedule.json'
    main_assignment = ROOT / 'manifests' / args.main_run / 'assignments.jsonl.gz'
    plan = json.loads(pre_manifest.read_text())
    selected = {}
    for t in sorted(plan['trials'], key=lambda t: t['trial_id']):
        selected.setdefault((t['model'], t['effort'], t['arm'], t['kind']), t)
    if len(selected) != 96:
        raise ValueError('Expected 4 profiles × 8 arms × 3 games = 96 prespecified samples')
    historical = {'states_tree': tree_stats(pre_root / 'states', True),
                  'native_tree': tree_stats(pre_root / 'native-raw')}
    sampled, states, all_paths = [], [], set()
    with tempfile.TemporaryDirectory(prefix='exp7-storage-audit-') as temp:
        temp = Path(temp)
        for _, t in sorted(selected.items()):
            tid = t['trial_id']
            state_path = pre_root / 'states' / (tid + '.json')
            journal_path = state_path.with_suffix('.journal.jsonl')
            state = json.loads(state_path.read_text())
            references = {}
            for record in state.get('turns', []):
                for raw in record.get('raw_files', []):
                    references[Path(raw['path']).resolve()] = raw['sha256']
            for raw in state.get('pending_raw_files', []):
                references[Path(raw['path']).resolve()] = raw['sha256']
            for path, expected in references.items():
                if sha_file(path) != expected:
                    raise ValueError('Referenced historical raw content changed')
            paths = {state_path, journal_path, *references}
            private = archive_and_verify(paths, temp / 'private.tar.gz')
            public = gzip_public([state], temp / 'public.jsonl.gz')
            requests = len(state['turns']) + int(state.get('pending_turn') is not None)
            sampled.append({'trial_id': tid, 'model': t['model'], 'effort': t['effort'],
                            'arm': t['arm'], 'kind': t['kind'], 'status': state['status'],
                            'observed_request_count': requests, 'recorded_responses': len(state['turns']),
                            'state_sha256': sha_file(state_path), 'journal_sha256': sha_file(journal_path),
                            'private_files': private['files'], 'verified_archive_files': private['verified_files'],
                            'private_file_bytes': private['file_bytes'],
                            'private_file_allocated_bytes': private['file_allocated_bytes'],
                            'private_tar_gzip_bytes': private['gzip_tar_bytes'],
                            'private_archive_sha256': private['archive_sha256'],
                            'source_file_hashes_digest': private['source_file_hashes_digest'],
                            'public_jsonl_bytes': public['jsonl_bytes'], 'public_gzip_bytes': public['gzip_bytes'],
                            'public_jsonl_sha256': public['jsonl_sha256'],
                            'private_compressed_fraction': private['gzip_tar_bytes'] / private['file_bytes'],
                            'public_compressed_fraction': public['gzip_bytes'] / public['jsonl_bytes']})
            states.append(state)
            all_paths.update(paths)
        combined_private = archive_and_verify(all_paths, temp / 'all-private.tar.gz')
        combined_public = gzip_public(states, temp / 'all-public.jsonl.gz')
    counts = projected_native_counts(main_assignment)
    projection = extrapolate(sampled, main_assignment)
    summary = {'pre_run': args.pre_run, 'main_run': args.main_run,
               'sampling_rule': 'Lowest planned trial ID in each model/effort/arm/kind stratum, before inspecting status or responses.',
               'sample_size': len(sampled), 'sample_statuses': dict(Counter(r['status'] for r in sampled)),
               'historical_loose_storage': historical,
               'sample_private': combined_private, 'sample_public': combined_public,
               'all_sample_archive_readbacks_verified': True,
               'source_files_modified': 0, 'persistent_archives_created': 0,
               'new_model_calls': 0, 'published_raw_or_public_response_content': False,
               'main_exact_file_counts': counts,
               'main_projected_bytes': projection['all_models'],
               'main_per_model_projected_bytes': projection['per_model_mean'],
               'projection_limitations': projection['limitations']}
    sources = [pre_manifest, main_assignment, ROOT / 'exp7_main/worker.py',
               ROOT / 'exp7_pre/transport.py', Path(__file__).resolve()]
    provenance = {'source_sha256': {str(p.relative_to(ROOT)): sha_file(p) for p in sources},
                  'gzip_compresslevel': 9, 'gzip_mtime': 0,
                  'tar_metadata': 'uid/gid/mtime=0 and owner names blank; file content unchanged',
                  'allocation_normalization': 'Observed per-conversation request count scaled to 34 calls; exact main condition frequencies.',
                  'sample_source_file_hashes': 'Each stratum records the SHA256 of sorted relative-path → source SHA256 mapping.'}
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    for name, obj in [('summary.json', summary), ('sample_strata.json', sampled),
                      ('projection.json', projection), ('provenance.json', provenance)]:
        payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
        path = output / name
        if path.exists() and path.read_text() != payload:
            raise ValueError('Existing audit differs; choose a new output directory')
        if not path.exists():
            with path.open('x') as f:
                f.write(payload)
    print(json.dumps({'output': str(output), 'sample_size': len(sampled),
                      'verified_private_files': combined_private['verified_files'],
                      'main_per_model_projected_bytes': projection['per_model_mean'],
                      'main_per_model_counts': next(iter(counts['per_model'].values()))}, indent=2))


if __name__ == '__main__':
    main()
