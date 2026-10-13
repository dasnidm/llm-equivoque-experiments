import json
from pathlib import Path
from sequence_replication.protocol import SequenceProtocol
from equivoque.core import Protocol

class QuestionProtocol(SequenceProtocol):
    def __init__(self):
        super().__init__()
        self.path = Path(__file__).with_name('prompts.json')
        self.intervention = json.loads(self.path.read_text())

    def prompt(self, trial, turn, feedback=None, remaining=None):
        n = 3 * trial['n_rounds']
        if turn <= n or turn == n + 3:
            return super().prompt(trial, turn, feedback, remaining)
        if turn == n + 1:
            if trial['arm'] == 'control': return self.intervention['control']
            source_turn = n + (1 if trial['arm'] == 'explanation' else 2)
            return super().prompt(trial, source_turn, feedback, remaining)
        if turn == n + 2:
            return self.spec['measurement_scope'] + '\n\n' + self.data['frames'][trial['frame']]['evaluation']
        raise ValueError('Invalid turn')

    def schema(self, turn, remaining=None, frame='cards', trial=None):
        n = 3 * trial['n_rounds']
        if turn <= n or turn == n + 3:
            return super().schema(turn, remaining, frame, trial)
        if turn == n + 2: return Protocol.schema(self, 3, remaining, frame)
        if trial['arm'] == 'control':
            return {'type':'object','additionalProperties':False,'required':['description'],
                    'properties':{'description':{'type':'string'}}}
        return super().schema(n + (1 if trial['arm'] == 'explanation' else 2), remaining, frame, trial)

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        n = 3 * trial['n_rounds']
        if turn <= n or turn == n + 3:
            return super().parse_response(text, turn, remaining, frame, trial)
        if turn == n + 2: return Protocol.parse_response(self, text, 3, remaining, frame)
        if trial['arm'] == 'control':
            import jsonschema
            value = json.loads(text)
            jsonschema.validate(value, self.schema(turn,remaining,frame,trial))
            if not value['description'].strip(): raise ValueError('Empty neutral response')
            return value
        # Canonical parsing validates its original turn schema. Use the base
        # instance so its internal self.schema call does not remap turn 32.
        return SequenceProtocol().parse_response(text, n + (1 if trial['arm'] == 'explanation' else 2), remaining, frame, trial)
