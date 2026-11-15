"""English/schema adapter of the preserved pre-study protocol.

Unlike the main-study validator, the pre-study protocol accepts a permuted
card order. No historical protocol or runner is modified.
"""
from exp7_pre.protocol import PreProtocol, validate_trial as validate_pre
from exp7_pre.protocol import phase


def adapt(trial):
    if (trial.get('frame') != 'cards' or trial.get('arm') != 'en_schema'
            or trial.get('format') != 'en_schema'
            or trial.get('measurement') != 'each_round'
            or trial.get('kind') not in ('obj', 'seq')
            or trial.get('game') != trial.get('kind')
            or trial.get('stage_rule') is not None):
        raise ValueError('Not an English/schema card obj/seq assignment')
    if trial['kind'] == 'seq' and len(set(trial['targets'])) < 2:
        raise ValueError('Sequence must vary')
    adapted = {**trial, 'arm': 'A'}
    validate_pre(adapted)
    return adapted


class CardProtocol:
    protocol_id = 'exp7-cards-obj-seq-200-draft-v1'

    def __init__(self):
        self.base = PreProtocol()

    def system(self, trial):
        return self.base.system(adapt(trial))

    def prompt(self, trial, turn, feedback=None, remaining=None, rounds=None):
        return self.base.prompt(adapt(trial), turn, feedback, remaining, rounds)

    def schema(self, turn, remaining=None, frame='cards', trial=None):
        return self.base.schema(turn, remaining, frame, adapt(trial))

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        return self.base.parse_response(text, turn, remaining, frame, adapt(trial))

    def display(self, trial, labels):
        return self.base.display(adapt(trial), labels)


# Compatibility with the isolated worker adapter; historical modules are unchanged.
MainProtocol = CardProtocol
