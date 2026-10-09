from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = tuple('ABCD')


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operate(order, selection, target):
    if not selection or len(set(selection)) != len(selection):
        raise ValueError('Empty or repeated selection')
    if not set(selection) <= set(order) or target not in order:
        raise ValueError('Invalid selection or target')
    keep = target in selection
    return [x for x in order if (x in selection) == keep], 'K' if keep else 'D'


def branches(order, target):
    if len(order) != 4 or set(order) != set(LABELS):
        raise ValueError('Initial order must contain A/B/C/D exactly once')
    rows = []
    for first in itertools.combinations(order, 2):
        remaining, first_op = operate(order, first, target)
        for second in remaining:
            final, second_op = operate(remaining, [second], target)
            if final != [target]:
                raise AssertionError('Fixed-target invariant violated')
            rows.append({'first': list(first), 'remaining': remaining,
                         'second': second, 'final': final[0],
                         'route': first_op + second_op})
    return rows


class Protocol:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / 'protocol/prompts.v1.json')
        self.data = read_json(self.path)

    def display(self, frame, labels):
        if frame == 'cards':
            return ', '.join(f'{x} ({self.data["card_objects"][x]})'
                             for x in labels)
        return ', '.join(labels)

    def table(self, trial):
        headings = self.data['frames'][trial['frame']]['branch_headers']
        lines = ['| ' + ' | '.join(headings) + ' |',
                 '| --- | --- | --- | --- |']
        for row in branches(trial['order'], trial['target']):
            lines.append('| ' + ' | '.join([', '.join(row['first']),
                         ', '.join(row['remaining']), row['second'],
                         row['final']]) + ' |')
        return '\n'.join(lines)

    def prompt(self, trial, turn, feedback=None, remaining=None):
        frame = trial['frame']
        f = self.data['frames'][frame]
        template = f[f'turn_{turn}']
        if turn in (2, 3):
            template = template[feedback]
        values = {'ordered_objects': self.display(frame, trial['order']),
                  'remaining_labels': ', '.join(remaining or []),
                  'final_object': self.display(frame, [trial['target']]),
                  'branch_table': self.table(trial) if turn == 4 else ''}
        for key, value in values.items():
            template = template.replace('{' + key + '}', value)
        if any(token in template for token in self.data['rendering']['tokens']):
            raise ValueError('Unresolved prompt token')
        if turn in (3, 4):
            template += '\n\n' + f['evaluation']
        return template

    def schema(self, turn, remaining=None):
        key = f'turn_{turn}' if turn < 3 else 'evaluation'
        schema = json.loads(json.dumps(self.data['schemas'][key]))
        if turn == 2:
            schema['properties']['selection']['enum'] = list(remaining)
        return schema


def parse_response(text, turn, remaining=None):
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    if turn < 3:
        if set(value) != {'selection'}:
            raise ValueError('Unexpected selection fields')
        selection = value['selection']
        if turn == 1:
            if (not isinstance(selection, list) or len(selection) != 2 or
                    any(not isinstance(x, str) or x not in LABELS
                        for x in selection) or len(set(selection)) != 2):
                raise ValueError('Expected two distinct A/B/C/D labels')
        elif not isinstance(selection, str) or selection not in remaining:
            raise ValueError('Expected one actually remaining label')
    else:
        if set(value) != {'freedom', 'impact', 'counterfactual'}:
            raise ValueError('Unexpected evaluation fields')
        for key in ('freedom', 'impact'):
            if type(value[key]) is not int or not 1 <= value[key] <= 100:
                raise ValueError('Ratings must be integers from 1 to 100')
        if value['counterfactual'] not in ('yes', 'no'):
            raise ValueError('Expected yes/no')
    return value


def frozen_hashes(root=ROOT):
    freeze = read_json(root / 'protocol/freeze.json')
    for path, expected in freeze['files'].items():
        if digest(root / path) != expected:
            raise ValueError(f'Frozen file changed: {path}')
    return freeze
