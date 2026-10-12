"""Canonical game wording, fixed layouts and round-specific hidden targets."""
import copy
import itertools
import json
from pathlib import Path

from equivoque.core import ROOT, Protocol, digest, operate, read_json

CONFIG = ROOT / 'sequence_replication/protocol/run.json'
FREEZE = ROOT / 'sequence_replication/protocol/freeze.json'
PROMPTS = ROOT / 'sequence_replication/protocol/prompts.json'


def frozen_hashes():
    freeze = read_json(FREEZE)
    for name, expected in freeze['files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen source changed: ' + name)
    return freeze


def phase(trial, turn):
    n = trial.get('n_rounds', 30)
    if 1 <= turn <= 3*n:
        return (turn-1)//3+1, (turn-1)%3+1
    if 3*n < turn <= 3*n+3:
        return n, turn-3*n+3
    raise ValueError('Turn outside assigned session')


def probe_policies(trial):
    target, order = trial['targets'][-1], trial['order']
    other = next(x for x in order if x != target)
    pair = [x for x in order if x in (target, other)]
    complement = [x for x in order if x not in pair]
    result = []
    for first in (pair, complement):
        remaining, first_feedback = operate(order, first, target)
        for index in (0, 1):
            second = remaining[index]
            final, second_feedback = operate(remaining, [second], target)
            result.append({'first': first, 'second_position': index+1,
                'gold': {'first_feedback': 'keep_selected' if first_feedback == 'K' else 'discard_selected',
                         'second_feedback': 'keep_selected' if second_feedback == 'K' else 'discard_selected',
                         'final': final[0]}})
    return result


class SequenceProtocol(Protocol):
    def __init__(self, path=None):
        self.path = Path(path or PROMPTS)
        self.spec = read_json(self.path)
        self.data = self.spec['base']

    def prompt(self, trial, turn, feedback=None, remaining=None):
        r, local = phase(trial, turn)
        frame, n = trial['frame'], trial['n_rounds']
        current = {**trial, 'target': trial['targets'][r-1]}
        if local <= 3:
            text = super().prompt(current, local, feedback, remaining)
            if local == 1 and r > 1:
                text = self.spec['round_restart'].replace('{round}', str(r)) + text
            if local == 3:
                suffix = '\n\n' + self.data['frames'][frame]['evaluation']
                assert text.endswith(suffix)
                text = text[:-len(suffix)] + '\n\n' + self.spec['measurement_scope'] + suffix
            return text
        noun = 'card' if frame == 'cards' else 'cat'
        if local == 4:
            return self.spec['rule'].replace('{object}', noun)
        if local == 5:
            policies = []
            for i, policy in enumerate(probe_policies(trial), 1):
                ordinal = 'first' if policy['second_position'] == 1 else 'last'
                policies.append(f"Policy {i}: first select {self.display(frame, policy['first'])}; then select the {ordinal} object in the order of the two remaining objects.")
            return self.spec['predictions'].replace('{round}', str(n)).replace(
                '{ordered_objects}', self.display(frame, trial['order'])).replace(
                '{policies}', '\n'.join(policies))
        schedule = '\n'.join(f"{i}. {self.display(frame, [target])}" for i, target in enumerate(trial['targets'], 1))
        text = self.spec['disclosure'][frame].replace('{round}', str(n)).replace(
            '{schedule}', schedule).replace('{branch_table}', self.table(current))
        return text + '\n\n' + self.spec['measurement_scope'] + '\n\n' + self.data['frames'][frame]['evaluation']

    def schema(self, turn, remaining=None, frame='cats', trial=None):
        _, local = phase(trial or {'n_rounds': 30}, turn)
        if local <= 3:
            return super().schema(local, remaining, frame)
        if local == 4:
            return copy.deepcopy(self.spec['schemas']['rule'])
        if local == 6:
            return super().schema(4, remaining, frame)
        names = list(self.choice_names(frame).values()) + ['uncertain']
        item = {'type': 'object', 'additionalProperties': False,
                'required': ['first_feedback', 'second_feedback', 'final'],
                'properties': {'first_feedback': {'type': 'string', 'enum': ['keep_selected', 'discard_selected', 'uncertain']},
                               'second_feedback': {'type': 'string', 'enum': ['keep_selected', 'discard_selected', 'uncertain']},
                               'final': {'type': 'string', 'enum': names}}}
        return {'type': 'object', 'additionalProperties': False,
                'required': [f'policy_{i}' for i in range(1,5)],
                'properties': {f'policy_{i}': copy.deepcopy(item) for i in range(1,5)}}

    def parse_response(self, text, turn, remaining=None, frame='cats', trial=None):
        _, local = phase(trial or {'n_rounds': 30}, turn)
        if local <= 3 or local == 6:
            return super().parse_response(text, local if local <= 3 else 4, remaining, frame)
        import jsonschema
        value = json.loads(text)
        try:
            jsonschema.validate(value, self.schema(turn, remaining, frame, trial))
        except jsonschema.ValidationError as error:
            raise ValueError('Terminal response schema mismatch') from error
        if local == 4:
            if not value['rule'].strip():
                raise ValueError('Empty rule account')
            return value
        reverse = {v:k for k,v in self.choice_names(frame).items()}
        for item in value.values():
            if item['final'] != 'uncertain':
                item['final'] = reverse[item['final']]
        return value
