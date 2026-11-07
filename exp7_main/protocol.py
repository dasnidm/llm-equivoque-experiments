"""Exp 7 main stimuli, preserving the historical protocol byte for byte.

The four main format conditions are explicit here. R_A uses A's system and
all A stimuli except the first nine rating turns. Korean natural-language
responses are parsed conservatively, without repairing ambiguous answers.
No inference, global monkeypatching, or filesystem mutation occurs on import.
"""
from __future__ import annotations

import copy
import re

from exp7_pre.protocol import (
    PreProtocol, make_probe_policies, phase, total_turns, operate_step,
    probe_policies, choice_branches, validate_trial as _validate_pre_trial,
)

FORMATS = ('en_schema', 'en_natural', 'ko_schema', 'ko_natural')
ARMS = FORMATS + ('R_A',)
GAMES = ('obj', 'seq', 'KK', 'KD', 'DK', 'DD')
PROTOCOL_ID = 'equivoque-exp7-main-single-sequence-v1'
KO_SCHEMA_SYSTEM = '요청된 JSON으로만 답하세요. 이 대화에 나온 정보만 사용하세요.'

KO_NATURAL_RATING = (
    '자유도, 영향력, 반사실을 항목 이름으로 하여 각각 한 줄에 답하세요. '
    '앞의 두 항목에는 1부터 100까지의 정수를, 마지막 항목에는 예 또는 아니요를 쓰세요. '
    '세 줄 뒤에 짧은 설명을 덧붙여도 됩니다.'
)
KO_NATURAL_PREDICTION = (
    '각 선택 방식마다 한 줄씩, 다음 형식으로 네 줄을 쓰세요: '
    '선택 방식 1: 첫 피드백 = <유지/제거/불확실>; '
    '둘째 피드백 = <유지/제거/불확실>; 최종 = <표시된 이름 또는 불확실>. '
    '표시된 이름을 그대로 사용하세요. 네 줄 뒤에 짧은 설명을 덧붙여도 됩니다.'
)


def measurement(trial):
    default = 'round10_only' if trial.get('arm') == 'R_A' else 'each_round'
    return trial.get('measurement', default)


def response_format(trial):
    return trial.get('format', 'en_schema' if trial.get('arm') == 'R_A' else trial.get('arm'))


def _adapt(trial):
    """Return a private view for the frozen pre code, never modify assignment."""
    fmt = response_format(trial)
    arm = {'en_schema': 'A', 'en_natural': 'F',
           'ko_schema': 'K', 'ko_natural': 'K'}.get(fmt)
    if arm is None:
        raise ValueError('Unknown main response format')
    if measurement(trial) == 'round10_only':
        arm = 'R'
    return {**trial, 'arm': arm}


def validate_trial(trial):
    if trial.get('arm') not in ARMS:
        raise ValueError('Unknown main measurement arm')
    fmt = response_format(trial)
    if fmt not in FORMATS:
        raise ValueError('Unknown main response format')
    if trial['arm'] == 'R_A':
        if fmt != 'en_schema' or measurement(trial) != 'round10_only':
            raise ValueError('R_A is an English/schema round-ten-only condition')
    elif trial['arm'] != fmt or measurement(trial) != 'each_round':
        raise ValueError('Main arm/format/measurement mismatch')
    if trial.get('n_rounds') != 10 or trial.get('order') != list('ABCD'):
        raise ValueError('Main protocol requires ten rounds and fixed A/B/C/D order')
    game = trial.get('game', trial.get('stage_rule') if trial.get('kind') == 'unforced' else trial.get('kind'))
    if game not in GAMES:
        raise ValueError('Unknown main game')
    if game in ('obj', 'seq'):
        if trial.get('kind') != game or trial.get('stage_rule') is not None:
            raise ValueError('Forced game/kind/stage rule mismatch')
        if game == 'seq' and len(set(trial.get('targets', []))) < 2:
            raise ValueError('Sequence targets must vary across rounds')
    elif trial.get('kind') != 'unforced' or trial.get('stage_rule') != game or trial.get('targets') not in (None, []):
        raise ValueError('Fixed-rule controls must be unforced with no targets')
    _validate_pre_trial(_adapt(trial))
    return True


class _KoreanNaturalParser(PreProtocol):
    """Use frozen natural parser with Korean display labels, per-instance only."""
    def choice_names(self, frame='cards', trial=None):
        if frame == 'cards':
            return copy.deepcopy(self.spec['ko_card_names'])
        return self.historical.choice_names(frame)


def _ko_value(value, kind):
    # Keep punctuation/emphasis for the frozen conservative parser to process.
    clean = value.strip()
    outer = ''
    if clean.startswith('**') and clean.endswith('**') and clean.count('**') == 2:
        outer, clean = '**', clean[2:-2].strip()
    period = '.' if clean.endswith('.') else ''
    clean = clean[:-1] if period else clean
    if clean in ('불확실', '모름', '모르겠음'):
        clean = 'uncertain'
    elif kind == 'counterfactual':
        if clean == '예':
            clean = 'yes'
        elif clean == '아니요':
            clean = 'no'
        elif '예' in clean and '아니요' in clean:
            # Preserve explicit ambiguity instead of selecting either value.
            clean = 'yes or no'
    elif kind == 'feedback':
        if clean == '유지':
            clean = 'keep_selected'
        elif clean == '제거':
            clean = 'discard_selected'
        elif '유지' in clean and '제거' in clean:
            clean = 'keep_selected or discard_selected'
    return outer + clean + outer + period


def _normalize_korean_natural(text, local):
    """Translate only declared answer fields; never extract choices from prose."""
    if text.lstrip().startswith(('{', '[')):
        return text  # Parse actual JSON, retain format noncompliance.
    result = []
    label_names = {'자유도': 'Freedom', '영향력': 'Impact', '반사실': 'Counterfactual'}
    prediction_names = {'첫 피드백': 'first_feedback', '둘째 피드백': 'second_feedback', '최종': 'final'}
    for line in text.splitlines():
        if local in (3, 6, 7):
            match = re.fullmatch(r'\s*(?:\d+[.)]\s*)?(?:\*\*)?(자유도|영향력|반사실)(?:\*\*)?\s*[:=](?:\*\*)?\s*(.*?)\s*', line)
            if match:
                key, value = match.groups()
                kind = 'counterfactual' if key == '반사실' else 'rating'
                line = label_names[key] + ': ' + _ko_value(value, kind)
        elif local == 5:
            match = re.fullmatch(r'\s*(?:선택\s*)?방식\s*([1-4])\s*:\s*(.*?)\s*', line)
            if match:
                number, values = match.groups()
                pieces = []
                for piece in values.split(';'):
                    field = re.fullmatch(r'\s*(첫 피드백|둘째 피드백|최종)\s*=\s*(.*?)\s*', piece)
                    if field:
                        key, value = field.groups()
                        kind = 'final' if key == '최종' else 'feedback'
                        piece = prediction_names[key] + ' = ' + _ko_value(value, kind)
                    pieces.append(piece)
                line = 'Policy ' + number + ': ' + '; '.join(pieces)
        result.append(line)
    return '\n'.join(result)


class MainProtocol:
    """The public API matches PreProtocol for the durable native runner."""
    protocol_id = PROTOCOL_ID

    def __init__(self):
        self._base = PreProtocol()
        self._korean_parser = _KoreanNaturalParser()

    def system(self, trial):
        validate_trial(trial)
        if measurement(trial) == 'round10_only':
            return self._base.historical.data['system']
        if response_format(trial) == 'ko_schema':
            # Translate A's JSON-only system, rather than reusing pre K's
            # format-neutral system. This is an explicit main/pre difference.
            return KO_SCHEMA_SYSTEM
        return self._base.system(_adapt(trial))

    def choice_names(self, frame='cards', trial=None):
        if trial is None:
            return self._base.choice_names(frame)
        return self._base.choice_names(frame, _adapt(trial))

    def display(self, trial, labels):
        return self._base.display(_adapt(trial), labels)

    def prompt(self, trial, turn, feedback=None, remaining=None, rounds=None):
        validate_trial(trial)
        adapted = _adapt(trial)
        text = self._base.prompt(adapted, turn, feedback, remaining, rounds)
        if response_format(trial) != 'ko_natural':
            return text
        _, local = phase(trial, turn)
        if local in (1, 2):
            # Korean schema instructions are a single final sentence.
            head, separator, _ = text.partition('"selection"')
            if not separator:
                raise ValueError('Korean selection template no longer matches adapter')
            noun = '카드 이름' if trial['frame'] == 'cards' else '고양이 표시'
            ending = (f'고른 서로 다른 두 {noun}만 쉼표로 구분해서 답하세요.' if local == 1
                      else f'고른 남아 있는 한 {noun}만 답하세요.')
            return head.rstrip() + ' ' + ending
        if local == 4:
            key = 'explanation' if trial['probe_arm'] == 'explanation' else 'neutral'
            ending = self._base.spec[key + '_json_ko']
            if not text.endswith(ending):
                raise ValueError('Korean terminal template no longer matches adapter')
            return text[:-len(ending)].rstrip()
        if local == 5:
            ending = self._base.spec['prediction_json_ko']
            if not text.endswith(ending):
                raise ValueError('Korean prediction template no longer matches adapter')
            text = text[:-len(ending)].rstrip() + '\n\n' + KO_NATURAL_PREDICTION
            return text.replace('keep_selected', '유지').replace('discard_selected', '제거').replace('uncertain', '불확실').replace('불확실으로', '불확실로')
        json_tail = self._base.spec['ko']['evaluation'].split('\n')[-1]
        if not text.endswith(json_tail):
            raise ValueError('Korean rating template no longer matches adapter')
        text = text[:-len(json_tail)] + KO_NATURAL_RATING
        return text.replace('(yes/no)', '(예/아니요)').replace('keep_selected', '유지').replace('discard_selected', '제거')

    def canonical_schema(self, turn, remaining=None, frame='cards', trial=None):
        if trial is None:
            raise ValueError('Trial required')
        return self._base.canonical_schema(turn, remaining, frame, _adapt(trial))

    def schema(self, turn, remaining=None, frame='cards', trial=None):
        if trial is None:
            raise ValueError('Trial required')
        validate_trial(trial)
        if response_format(trial).endswith('_natural'):
            return None
        return self.canonical_schema(turn, remaining, frame, trial)

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        if trial is None:
            raise ValueError('Trial required')
        validate_trial(trial)
        adapted = _adapt(trial)
        if response_format(trial) == 'ko_natural':
            _, local = phase(trial, turn)
            text = _normalize_korean_natural(text, local)
            # F activates the frozen natural parser; this private parser has
            # Korean names regardless of its compatibility arm.
            return self._korean_parser.parse_response(text, turn, remaining, frame, {**adapted, 'arm': 'F'})
        return self._base.parse_response(text, turn, remaining, frame, adapted)

    def disclosure(self, trial):
        return self._base.disclosure(_adapt(trial))
