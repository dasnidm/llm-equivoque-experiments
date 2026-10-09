from pathlib import Path

from equivoque.core import Protocol, ROOT, digest, read_json

CONFIG = ROOT / 'experiment2/protocol/run.json'
FREEZE = ROOT / 'experiment2/protocol/freeze.json'


def frozen_hashes():
    frozen = read_json(FREEZE)
    for name, expected in frozen['files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Experiment 2 frozen file changed: ' + name)
    return frozen


def phase(turn):
    if not 1 <= turn <= 9:
        raise ValueError('Experiment 2 requires turns 1 through 9')
    return (3, 4) if turn == 9 else ((turn - 1) // 3 + 1, (turn - 1) % 3 + 1)


class RepeatedProtocol(Protocol):
    def __init__(self, path=None):
        self.path = Path(path or ROOT / 'experiment2/protocol/prompts.json')
        self.spec = read_json(self.path)
        self.data = self.spec['base']
        if self.spec.get('sequence') != {'turns_per_trial': 9, 'measurement_turns': [3, 6, 9], 'disclosure_turn': 9}:
            raise ValueError('Stimulus sequence must match the frozen nine-turn protocol')

    def prompt(self, trial, turn, feedback=None, remaining=None):
        round_number, local_turn = phase(turn)
        frame = trial['frame']
        local_trial = {**trial, 'order': trial['round_orders'][round_number - 1]}
        evaluation = self.data['frames'][frame]['evaluation']
        if turn == 9:
            tables = '\n\n'.join('Round ' + str(index) + '\n\n' + self.table(
                {**trial, 'order': order})
                for index, order in enumerate(trial['round_orders'], 1))
            text = self.spec['disclosure'][frame].replace(
                '{final_object}', self.display(frame, [trial['target']])).replace(
                '{round_tables}', tables)
            final_feedback = super().prompt(local_trial, 3, feedback, remaining)
            suffix = '\n\n' + evaluation
            assert final_feedback.endswith(suffix)
            text = final_feedback[:-len(suffix)] + '\n\n' + text
        else:
            text = super().prompt(local_trial, local_turn, feedback, remaining)
            if local_turn == 1 and round_number > 1:
                text = self.spec['round_restart'].replace('{round}', str(round_number)) + text
            if local_turn == 3:
                suffix = '\n\n' + evaluation
                assert text.endswith(suffix)
                text = text[:-len(suffix)]
        if local_turn in (3, 4):
            text += '\n\n' + self.spec['measurement_scope'] + '\n\n' + evaluation
        return text

    def schema(self, turn, remaining=None, frame='cats'):
        return super().schema(phase(turn)[1], remaining, frame)

    def parse_response(self, text, turn, remaining=None, frame='cats'):
        return super().parse_response(text, phase(turn)[1], remaining, frame)
