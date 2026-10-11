import itertools
import json
from pathlib import Path

from equivoque.core import ROOT, LABELS, digest, read_json

CONFIG = ROOT / 'experiment3/protocol/run.json'
FREEZE = ROOT / 'experiment3/protocol/freeze.json'
PROMPTS = ROOT / 'experiment3/protocol/prompts.json'
PROCEDURES = ('fixed_target', 'keep_selected')
CLAIMS = ('neutral', 'congruent', 'conflicting')
OBJECT_FIELDS = ('table_lookup', 'new_arrangement', 'renaming', 'rule_change')
CF_FIELDS = ('counterfactual', 'changed_counterfactual')


def frozen_hashes():
    frozen = read_json(FREEZE)
    for name, expected in frozen['files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen file changed: ' + name)
    return frozen


def apply_rule(order, first, second, target, procedure):
    if len(order) != 4 or len(set(order)) != 4 or target not in order:
        raise ValueError('Invalid arrangement/target')
    if len(first) != 2 or len(set(first)) != 2 or not set(first) <= set(order):
        raise ValueError('Invalid first selection')
    if procedure not in PROCEDURES:
        raise ValueError('Unknown procedure')
    keep = procedure == 'keep_selected' or target in first
    remaining = [x for x in order if (x in first) == keep]
    if second not in remaining:
        raise ValueError('Invalid second selection')
    final = second if procedure == 'keep_selected' or second == target else next(x for x in remaining if x != second)
    return remaining, final


def paths(order, target, procedure):
    result = []
    for first in itertools.combinations(order, 2):
        keep = procedure == 'keep_selected' or target in first
        remaining = [x for x in order if (x in first) == keep]
        for second in remaining:
            _, final = apply_rule(order, first, second, target, procedure)
            result.append({'first': list(first), 'remaining': remaining, 'second': second, 'final': final})
    return result


class PilotProtocol:
    def __init__(self):
        self.path = PROMPTS
        self.data = read_json(PROMPTS)

    def names(self, frame):
        return self.data['card_objects'] if frame == 'cards' else {x: x for x in LABELS}

    def display(self, frame, values):
        return ', '.join(self.names(frame)[x] for x in values)

    def schema(self, turn=1, remaining=None, frame='cards'):
        if turn != 1:
            raise ValueError('Pilot has exactly one turn')
        return {'type': 'object', 'additionalProperties': False,
                'required': list(OBJECT_FIELDS + CF_FIELDS), 'properties': {
                    **{key: {'type': 'string', 'enum': list(self.names(frame).values())} for key in OBJECT_FIELDS},
                    **{key: {'type': 'string', 'enum': ['yes', 'no']} for key in CF_FIELDS}}}

    def parse(self, text, frame):
        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result
        value = json.loads(text, object_pairs_hook=no_duplicates)
        if not isinstance(value, dict) or set(value) != set(OBJECT_FIELDS + CF_FIELDS):
            raise ValueError('Wrong response fields')
        for field, spec in self.schema(frame=frame)['properties'].items():
            if not isinstance(value[field], str) or value[field] not in spec['enum']:
                raise ValueError('Invalid answer: ' + field)
        return value

    def queries(self, trial):
        c, proc = trial['case'], trial['procedure']
        row = paths(c['order'], c['target'], proc)[c['lookup_index']]
        return row, c['arrangement_query'], c['renaming_query'], c['change_query']

    def oracle(self, trial):
        c, proc, frame = trial['case'], trial['procedure'], trial['frame']
        row, arrangement, rename, change = self.queries(trial)
        _, a = apply_rule(arrangement['order'], arrangement['first'], arrangement['second'], c['target'], proc)
        mapping = c['renaming']
        _, r = apply_rule([mapping[x] for x in rename['order']], [mapping[x] for x in rename['first']],
                          mapping[rename['second']], mapping[c['target']], proc)
        other = 'keep_selected' if proc == 'fixed_target' else 'fixed_target'
        _, changed = apply_rule(change['order'], change['first'], change['second'], change['target'], other)
        names = self.names(frame)
        return dict(zip(OBJECT_FIELDS, [names[x] for x in (row['final'], a, r, changed)]),
                    counterfactual='yes' if proc == 'keep_selected' else 'no',
                    changed_counterfactual='yes' if other == 'keep_selected' else 'no')

    def prompt(self, trial):
        c, proc, frame = trial['case'], trial['procedure'], trial['frame']
        noun, verb = ('card', 'tap') if frame == 'cards' else ('cat', 'pet')
        d = lambda xs: self.display(frame, xs)
        rows = paths(c['order'], c['target'], proc)
        table = '\n'.join(['| First two selected | Two remaining | Second selected | Final object |',
                           '| --- | --- | --- | --- |'] + [
            '| ' + ' | '.join([d(r['first']), d(r['remaining']), d([r['second']]), d([r['final']])]) + ' |' for r in rows])
        actual = 'yes' if proc == 'keep_selected' else 'no'
        claim = trial['claim']
        if claim == 'neutral':
            host = self.data['claims']['neutral']
        else:
            asserted = actual if claim == 'congruent' else ('no' if actual == 'yes' else 'yes')
            host = self.data['claims'][asserted].format(noun=noun)
        row, arrangement, rename, change = self.queries(trial)
        mapping = c['renaming']
        text = self.data['introduction'].format(noun=noun, verb=verb, order=d(c['order']))
        text += '\n\n' + self.data['candidates'].format(noun=noun)
        text += '\n\n' + self.data['table_intro'] + '\n\n' + table
        text += '\n\nHost statement: "' + host + '"'
        text += '\n\n' + self.data['questions_intro']
        text += '\n\n1. Table lookup: The first selection is ' + d(row['first']) + ', and the second selection is ' + d([row['second']]) + '. What is the final ' + noun + '?'
        text += '\n\n2. New arrangement: Use the same procedure and the same designated object, if any, as in the table. The displayed order is ' + d(arrangement['order']) + '. The first selection is ' + d(arrangement['first']) + ', and the second selection is ' + d([arrangement['second']]) + '. What is the final ' + noun + '?'
        rename_text = '; '.join(d([x]) + ' is renamed ' + d([mapping[x]]) for x in LABELS)
        text += '\n\n3. Renaming: Use the same procedure as in the table, but simultaneously rename every object: ' + rename_text + '. This renaming also applies to any designated object. The displayed order after renaming is ' + d([mapping[x] for x in rename['order']]) + '. The first selection after renaming is ' + d([mapping[x] for x in rename['first']]) + ', and the second selection after renaming is ' + d([mapping[rename['second']]]) + '. What is the final ' + noun + ' under its new name?'
        other = 'keep_selected' if proc == 'fixed_target' else 'fixed_target'
        rule = self.data['changed_rules'][other].format(target=d([change['target']]))
        text += '\n\n4. Rule change: For this question replace the table procedure with this explicit rule: ' + rule + ' The displayed order is ' + d(change['order']) + '. The first selection is ' + d(change['first']) + ', and the second selection is ' + d([change['second']]) + '. What is the final ' + noun + '?'
        text += '\n\n5. Original counterfactual: Holding the table procedure and any designated object fixed, could different legal selections yield a different final ' + noun + '? Answer yes or no.'
        text += '\n\n6. Changed counterfactual: Holding the explicit rule in Question 4 and any designated object fixed, could different legal selections yield a different final ' + noun + '? Answer yes or no.'
        return text + '\n\n' + self.data['response_instruction']

    def score(self, trial, response):
        truth = self.oracle(trial)
        return {key: response[key] == truth[key] for key in truth}
