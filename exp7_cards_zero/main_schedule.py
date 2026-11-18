"""Deterministic experiment 7 allocation in two balanced 100-trial waves."""
from collections import Counter
import gzip
import hashlib
import itertools
import json
from pathlib import Path

from .schedule import MODELS, EFFORTS, audit as audit_base, build as base_build, encoded, rng_for

RUN_ID = 'equivoque-exp7-cards-0to100-100x2-20261118'


def build():
    meta, rows = base_build()
    audit_base(meta, rows)
    for row in rows:
        row['run_id'] = RUN_ID
        row['stage'] = 'wave-1' if row['replicate'] <= 100 else 'wave-2'
        row['trial_id'] = 'main-' + row['trial_id']
    waves = []
    for stage in ('wave-1', 'wave-2'):
        part = [row for row in rows if row['stage'] == stage]
        rng_for([RUN_ID, stage, 'execution-order']).shuffle(part)
        waves.extend(part)
    audit(waves)
    return waves


def audit(rows):
    if len(rows) != 8400 or len({x['trial_id'] for x in rows}) != 8400:
        raise ValueError('Expected 8400 unique trials')
    if any(x['run_id'] != RUN_ID for x in rows):
        raise ValueError('Run ID differs')
    expected = set(itertools.product(MODELS, EFFORTS, ('obj', 'seq'), ('wave-1', 'wave-2')))
    counts = Counter((x['model'], x['effort'], x['game'], x['stage']) for x in rows)
    if set(counts) != expected or set(counts.values()) != {100}:
        raise ValueError('Expected 100 trials in each of 42 cells per wave')
    if any((x['stage'] == 'wave-1') != (x['replicate'] <= 100) for x in rows):
        raise ValueError('Incorrect case-to-wave mapping')
    if [x['stage'] for x in rows] != ['wave-1'] * 4200 + ['wave-2'] * 4200:
        raise ValueError('Wave order is invalid')
    return {'run_id': RUN_ID, 'sessions': 8400, 'cells': 42,
            'per_cell_per_wave': 100, 'wave_sessions': 4200, 'calls_per_complete': 34}


def save(path):
    path = Path(path)
    rows = build()
    data = gzip.compress(b''.join(encoded(x) + b'\n' for x in rows), mtime=0)
    if path.exists() and path.read_bytes() != data:
        raise FileExistsError('Refusing to overwrite an existing different allocation')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return {**audit(rows), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def load(path, expected_sha256):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('Allocation hash mismatch')
    rows = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    audit(rows)
    if rows != build():
        raise ValueError('Allocation differs from deterministic design')
    return rows
