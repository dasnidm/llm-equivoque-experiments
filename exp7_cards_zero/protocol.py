"""Isolated 0–100 card protocol; frozen 1–100 implementations stay intact."""
import re
import json

import jsonschema

from exp7_cards.protocol import CardProtocol, adapt
from exp7_pre.protocol import PreProtocol, _json, _summary, _surface, phase


class ZeroPreProtocol(PreProtocol):
    def __init__(self):
        super().__init__()
        evaluation = self.historical.data['frames']['cards']['evaluation']
        for old, new in (('1 = no freedom', '0 = no freedom'),
                         ('1 = no effect', '0 = no effect'),
                         ('100 = complete control', '100 = extreme impact')):
            if evaluation.count(old) != 1:
                raise ValueError('Unexpected historical rating prompt')
            evaluation = evaluation.replace(old, new)
        rating_tail = '\n' + self.spec['json_rating']
        if not evaluation.endswith(rating_tail):
            raise ValueError('Unexpected historical rating instruction')
        frame = self.historical.data['frames']['cards']
        frame['evaluation'] = evaluation[:-len(rating_tail)]
        self.historical.data['system'] = 'Respond only in JSON. Use only information from this conversation.'
        tail = ' Reply as JSON with '
        for key in ('turn_1',):
            if frame[key].count(tail) != 1:
                raise ValueError('Unexpected historical choice prompt')
            frame[key] = frame[key].split(tail)[0]
        for feedback in ('K', 'D'):
            if frame['turn_2'][feedback].count(tail) != 1:
                raise ValueError('Unexpected historical choice prompt')
            frame['turn_2'][feedback] = frame['turn_2'][feedback].split(tail)[0]
            old = 'Your chosen card is {final_object}.'
            if frame['turn_3'][feedback].count(old) != 1:
                raise ValueError('Unexpected historical result prompt')
            frame['turn_3'][feedback] = frame['turn_3'][feedback].replace(
                old, 'The remaining card is {final_object}.')
        frame['turn_2']['D'] = ('The two cards you tapped are discarded. '
                                'The remaining cards are {remaining_objects}. Tap one of them.')
        properties = self.historical.data['schemas']['evaluation']['properties']
        for key in ('freedom', 'impact'):
            if properties[key]['minimum'] != 1 or properties[key]['maximum'] != 100:
                raise ValueError('Unexpected historical rating schema')
            properties[key]['minimum'] = 0

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        result = super().parse_response(text, turn, remaining, frame, trial)
        if phase(trial, turn)[1] not in (3, 6, 7):
            return result
        # The original parser rejects 0. Correct only a genuine, unambiguous zero;
        # preserve all its validation metadata and other field handling.
        try:
            value = _json(text)
        except (ValueError, TypeError):
            value = None
        for key in ('freedom', 'impact'):
            if isinstance(value, dict):
                raw = value.get(key)
            else:
                matches = re.findall(r'^\s*(?:\d+[.)]\s*)?(?:\*\*)?' + key
                                     + r'(?:\*\*)?\s*[:=](?:\*\*)?\s*(.*?)\s*$',
                                     text, re.I | re.M)
                raw = _surface(matches[0].strip().rstrip('.')) if len(matches) == 1 else None
                if isinstance(raw, str) and re.fullmatch(r'\d{1,3}', raw):
                    raw = int(raw)
            if type(raw) is int and raw == 0:
                result[key] = 0
                result['_parse']['fields'][key] = 'valid'
            if type(raw) is float:
                # jsonschema accepts integral floats as integers, but this
                # protocol records ratings only as JSON integer tokens.
                result['_parse']['schema_valid'] = False
        info = result['_parse']
        result['_parse'] = _summary(info['fields'], info['response_format'],
                                    info['format_compliant'], info['schema_valid'])
        return result


class ZeroCardProtocol(CardProtocol):
    protocol_id = 'exp7-cards-obj-seq-0to100-refined-v2'

    def __init__(self):
        self.base = ZeroPreProtocol()

    def prompt(self, trial, turn, feedback=None, remaining=None, rounds=None):
        text = super().prompt(trial, turn, feedback, remaining, rounds)
        _, local = phase(adapt(trial), turn)
        if local == 4:
            key = 'explanation_json' if trial['probe_arm'] == 'explanation' else 'neutral_json'
            tail = ' ' + self.base.spec[key]
        elif local == 5:
            tail = '\n\n' + self.base.spec['prediction_json']
        elif local == 7:
            return (text.replace('Before the first selection in Round 1',
                                 'Before the first tap in Round 1')
                    .replace('| First selection |', '| First tap |')
                    .replace('| Second selection |', '| Second tap |')
                    .replace('| keep_selected |', '| kept |')
                    .replace('| discard_selected |', '| discarded |'))
        else:
            return text
        if not text.endswith(tail):
            raise ValueError('Unexpected follow-up format instruction')
        text = text[:-len(tail)]
        if local == 5:
            text = text.replace('first select ', 'first tap ')
            text = text.replace('; then select the ', '; then tap the ')
            text = text.replace(' object in the order of the two remaining objects.',
                                ' card in the order of the two remaining cards.')
        return text

    def schema(self, turn, remaining=None, frame='cards', trial=None):
        schema = super().schema(turn, remaining, frame, trial)
        _, local = phase(adapt(trial), turn)
        if local in (1, 2):
            key = 'cards' if local == 1 else 'card'
            schema['properties'][key] = schema['properties'].pop('selection')
            schema['required'] = [key]
        return schema

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        _, local = phase(adapt(trial), turn)
        if local in (1, 2):
            try:
                value = _json(text)
                jsonschema.validate(value, self.schema(turn, remaining, frame, trial))
            except (ValueError, TypeError, jsonschema.ValidationError) as exc:
                raise ValueError('Invalid structured card response') from exc
            key = 'cards' if local == 1 else 'card'
            # Preserve the runner's internal representation while changing
            # the externally requested and validated schema field.
            text = json.dumps({'selection': value[key]}, ensure_ascii=False)
        return super().parse_response(text, turn, remaining, frame, trial)


MainProtocol = ZeroCardProtocol
