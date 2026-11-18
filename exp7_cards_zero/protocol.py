"""Isolated 0–100 card protocol; frozen 1–100 implementations stay intact."""
import re

from exp7_cards.protocol import CardProtocol
from exp7_pre.protocol import PreProtocol, _json, _summary, _surface, phase


class ZeroPreProtocol(PreProtocol):
    def __init__(self):
        super().__init__()
        evaluation = self.historical.data['frames']['cards']['evaluation']
        for old, new in (('1 = no freedom', '0 = no freedom'),
                         ('1 = no effect', '0 = no effect')):
            if evaluation.count(old) != 1:
                raise ValueError('Unexpected historical rating prompt')
            evaluation = evaluation.replace(old, new)
        self.historical.data['frames']['cards']['evaluation'] = evaluation
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
    protocol_id = 'exp7-cards-obj-seq-0to100-v1'

    def __init__(self):
        self.base = ZeroPreProtocol()


MainProtocol = ZeroCardProtocol
