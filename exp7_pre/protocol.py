"""Frozen-stimulus protocol for Exp 7-pre; contains no inference or file mutation.

The historical protocol is read, never edited. A reproduces its first 30 turns.
All treatment manifests must preassign probe policies independently of targets.
"""
from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
import random
import re

from equivoque.core import ROOT, LABELS, operate, read_json
from sequence_replication.protocol import SequenceProtocol

PROMPTS = Path(__file__).with_name('prompts.json')
ARMS = ('A', 'J', 'P', 'K', 'JS', 'N', 'R', 'F')
FEEDBACK_NAMES = {'K': 'keep_selected', 'D': 'discard_selected'}
NATURAL_ARMS = ('N', 'F')


def total_turns(trial):
    return 3 * trial.get('n_rounds', 10) + 4


def phase(trial, turn):
    """Return one-based round and local action (1..3, terminal 4..7)."""
    n = trial.get('n_rounds', 10)
    if not isinstance(turn, int) or not 1 <= turn <= 3 * n + 4:
        raise ValueError('Turn outside assigned session')
    if turn <= 3 * n:
        return (turn - 1) // 3 + 1, (turn - 1) % 3 + 1
    return n, turn - 3 * n + 3


def operate_step(trial, round_number, stage, order, selection):
    """Return actual survivors and K/D for one free selection."""
    if stage not in (1, 2):
        raise ValueError('Only two selection stages exist')
    order, selection = list(order), list(selection)
    expected_count = 2 if stage == 1 else 1
    if len(order) != 2 * expected_count or len(selection) != expected_count:
        raise ValueError('Selection or survivor count is invalid')
    if len(set(selection)) != len(selection) or not set(selection) <= set(order):
        raise ValueError('Selection must be distinct and actually available')
    kind = trial['kind']
    if kind in ('obj', 'seq'):
        return operate(order, selection, trial['targets'][round_number - 1])
    if kind != 'unforced' or trial.get('stage_rule') not in ('KK', 'KD', 'DK', 'DD'):
        raise ValueError('Unknown procedure or fixed stage rule')
    action = trial['stage_rule'][stage - 1]
    survivors = [x for x in order if (x in selection) == (action == 'K')]
    return survivors, action


def make_probe_policies(order, seed):
    """Sample only from visible order and an independently assigned probe seed.

    Hidden target, actual choices, feedback and outcomes are not arguments.
    The second action is a position among whatever objects actually remain.
    """
    if len(order) != 4 or set(order) != set(LABELS):
        raise ValueError('Order must contain A/B/C/D exactly once')
    policies = [{'first': list(pair), 'second_position': p}
                for pair in itertools.combinations(order, 2) for p in (1, 2)]
    return random.Random(seed).sample(policies, 4)


def validate_trial(trial):
    if trial.get('arm') not in ARMS:
        raise ValueError('Unknown measurement arm')
    if trial.get('frame', 'cards') not in ('cards', 'cats'):
        raise ValueError('Unknown object frame')
    if trial.get('n_rounds', 10) != 10:
        raise ValueError('The frozen validation protocol has exactly ten rounds')
    if len(trial['order']) != 4 or set(trial['order']) != set(LABELS):
        raise ValueError('Initial order must contain A/B/C/D exactly once')
    if trial['kind'] in ('obj', 'seq'):
        if len(trial['targets']) != 10 or any(t not in LABELS for t in trial['targets']):
            raise ValueError('Invalid precommitted target schedule')
        if trial['kind'] == 'obj' and len(set(trial['targets'])) != 1:
            raise ValueError('Constant-target condition changes target')
    elif trial['kind'] == 'unforced':
        if trial.get('stage_rule') not in ('KK', 'KD', 'DK', 'DD'):
            raise ValueError('Unforced stage rule is not preassigned')
    else:
        raise ValueError('Unknown procedure')
    if trial.get('probe_arm') not in ('explanation', 'neutral'):
        raise ValueError('Probe order must be preassigned')
    policies = trial.get('probe_policies')
    if not isinstance(policies, list) or len(policies) != 4:
        raise ValueError('Four target-independent probe policies are required')
    keys = []
    for p in policies:
        if set(p) != {'first', 'second_position'}:
            raise ValueError('Probe policy contains hidden metadata or invalid keys')
        first = p['first']
        if len(first) != 2 or len(set(first)) != 2 or not set(first) <= set(trial['order']):
            raise ValueError('Invalid first probe selection')
        if p['second_position'] not in (1, 2):
            raise ValueError('Invalid conditional second probe position')
        keys.append((tuple(sorted(first)), p['second_position']))
    if len(set(keys)) != 4:
        raise ValueError('Probe policies must be distinct')
    if trial['arm'] == 'P':
        if trial.get('prompt_variant', 'p1') not in ('p1', 'p2'):
            raise ValueError('Unknown paraphrase')
        if trial.get('frame', 'cards') != 'cards':
            raise ValueError('English paraphrases are defined only for cards')
    return True


def probe_policies(trial):
    """Attach researcher-side gold labels to preassigned visible policies."""
    result = []
    n = trial.get('n_rounds', 10)
    for policy in trial['probe_policies']:
        first = list(policy['first'])
        remaining, a1 = operate_step(trial, n, 1, trial['order'], first)
        second = remaining[policy['second_position'] - 1]
        final, a2 = operate_step(trial, n, 2, remaining, [second])
        result.append({**copy.deepcopy(policy), 'remaining': remaining, 'second': second,
                       'gold': {'first_feedback': FEEDBACK_NAMES[a1],
                                'second_feedback': FEEDBACK_NAMES[a2], 'final': final[0]}})
    return result


def choice_branches(trial, round_number=None):
    r = round_number or trial.get('n_rounds', 10)
    result = []
    for first in itertools.combinations(trial['order'], 2):
        remaining, a1 = operate_step(trial, r, 1, trial['order'], first)
        for second in remaining:
            final, a2 = operate_step(trial, r, 2, remaining, [second])
            result.append({'first': list(first), 'remaining': remaining, 'second': second,
                           'route': a1 + a2, 'final': final[0]})
    return result


def _substitute(template, values):
    for key, value in values.items():
        template = template.replace('{' + key + '}', str(value))
    # JSON examples have braces too, so only reject template-style named tokens.
    if re.search(r'\{[a-z_]+\}', template):
        raise ValueError('Unresolved prompt template')
    return template


def _json(text):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('Duplicate JSON field')
            out[key] = value
        return out
    return json.loads(text, object_pairs_hook=unique)


def _surface(value):
    """Remove only complete outer Markdown emphasis, never infer a choice."""
    value = value.strip()
    for marker in ('**', '__'):
        if value.startswith(marker) and value.endswith(marker) and value.count(marker) == 2 and len(value) > 2 * len(marker):
            value = value[len(marker):-len(marker)].strip()
            break
    return value


def _field(value, kind, names=None, normalize_display=False):
    if value is None:
        return None, 'unparseable'
    if isinstance(value, str) and value.strip().lower() in ('uncertain', 'unsure', 'unknown'):
        return ('uncertain' if kind in ('feedback', 'final') else None), 'uncertain'
    if isinstance(value, str):
        if kind == 'rating' and len(re.findall(r'\b\d{1,3}\b', value)) > 1:
            return None, 'ambiguous'
        if kind == 'counterfactual' and {'yes', 'no'} <= set(re.findall(r'\b(?:yes|no)\b', value.lower())):
            return None, 'ambiguous'
        if kind == 'feedback' and all(token in value for token in ('keep_selected', 'discard_selected')):
            return None, 'ambiguous'
        match_text = value.casefold() if normalize_display else value
        match_names = [name.casefold() if normalize_display else name for name in (names or {}).values()]
        if kind == 'final' and names and sum(name in match_text for name in match_names) > 1:
            return None, 'ambiguous'
    if kind == 'rating':
        if type(value) is int and 1 <= value <= 100:
            return value, 'valid'
        return None, 'unparseable'
    if kind == 'counterfactual':
        if value in ('yes', 'no'):
            return value, 'valid'
        return None, 'unparseable'
    if kind == 'feedback':
        if value in ('keep_selected', 'discard_selected'):
            return value, 'valid'
        return None, 'unparseable'
    if kind == 'final':
        reverse = {v: k for k, v in names.items()}
        if normalize_display and isinstance(value, str):
            value = _surface(value).casefold()
            reverse = {v.casefold(): k for k, v in names.items()}
        if isinstance(value, str) and value in reverse:
            return reverse[value], 'valid'
        return None, 'unparseable'
    raise ValueError('Unknown parser field')


def _summary(fields, response_format, compliant, strict_schema_valid=None):
    values = list(fields.values())
    if all(x in ('valid', 'uncertain') for x in values):
        status = 'valid'
    elif any(x in ('valid', 'uncertain') for x in values):
        status = 'partial'
    elif any(x == 'ambiguous' for x in values):
        status = 'ambiguous'
    else:
        status = 'unparseable'
    return {'status': status, 'fields': fields, 'response_format': response_format,
            'format_compliant': compliant, 'schema_valid': strict_schema_valid}


class PreProtocol:
    def __init__(self, path=None):
        self.path = Path(path or PROMPTS)
        self.spec = read_json(self.path)
        self.historical = SequenceProtocol()
        # Kept for compatibility with inspection utilities; transport uses system(trial).
        self.data = copy.deepcopy(self.historical.data)

    def system(self, trial):
        if trial['arm'] == 'A':
            return self.historical.data['system']
        return self.spec['systems']['ko' if trial['arm'] == 'K' else 'neutral']

    def choice_names(self, frame='cards', trial=None):
        if frame == 'cards' and trial and trial['arm'] == 'K':
            return copy.deepcopy(self.spec['ko_card_names'])
        return self.historical.choice_names(frame)

    def display(self, trial, labels):
        names = self.choice_names(trial.get('frame', 'cards'), trial)
        return ', '.join(names[x] for x in labels)

    def _evaluation(self, trial):
        arm, frame = trial['arm'], trial.get('frame', 'cards')
        if arm == 'K':
            return _substitute(self.spec['ko']['evaluation'], self._ko_values(frame))
        if arm == 'P':
            return self.spec['paraphrases'][trial.get('prompt_variant', 'p1')]['evaluation']
        evaluation = self.historical.data['frames'][frame]['evaluation']
        if arm in NATURAL_ARMS:
            evaluation = evaluation.replace(self.spec['json_rating'], self.spec['natural_rating'])
        return evaluation

    @staticmethod
    def _ko_values(frame):
        if frame == 'cards':
            return {'noun': '카드', 'verb': '두드리세요', 'past': '두드린',
                    'verb_inf': '두드릴지', 'removed': '버려집니다', 'name_kind': '카드 이름'}
        return {'noun': '고양이', 'verb': '쓰다듬으세요', 'past': '쓰다듬은',
                'verb_inf': '쓰다듬을지', 'removed': '떠납니다', 'name_kind': '고양이 표시'}

    def _final(self, trial, round_number, remaining, rounds):
        if remaining is not None and len(remaining) == 1:
            return remaining[0]
        if trial['kind'] != 'unforced':
            return trial['targets'][round_number - 1]
        if rounds and len(rounds) >= round_number:
            row = rounds[round_number - 1]
            if len(row.get('remaining', [])) == 1:
                return row['remaining'][0]
            if row.get('final') in LABELS:
                return row['final']
        raise ValueError('Observed final object required for unforced feedback')

    def prompt(self, trial, turn, feedback=None, remaining=None, rounds=None):
        validate_trial(trial)
        r, local = phase(trial, turn)
        arm, frame = trial['arm'], trial.get('frame', 'cards')
        lang = 'ko' if arm == 'K' else 'en'
        n = trial.get('n_rounds', 10)
        if local <= 3:
            if local in (2, 3) and feedback not in ('K', 'D'):
                raise ValueError('Observed feedback required')
            final = self._final(trial, r, remaining, rounds) if local == 3 else None
            # For A/J/JS/N/R/F the game narration is literally historical text.
            if arm not in ('P', 'K'):
                templates = self.historical.data['frames'][frame]
                template = templates[f'turn_{local}']
            elif arm == 'P':
                template = self.spec['paraphrases'][trial.get('prompt_variant', 'p1')][f'turn_{local}']
            else:
                template = self.spec['ko'][f'turn_{local}']
            if local in (2, 3):
                template = template[feedback]
            values = {'ordered_objects': self.display(trial, trial['order']),
                      'remaining_objects': self.display(trial, remaining or []),
                      'final_object': self.display(trial, [final]) if final else ''}
            if arm == 'K':
                values.update(self._ko_values(frame))
            text = _substitute(template, values)
            if arm == 'F' and local < 3:
                # Replace the instruction tail, retaining original question and feedback.
                text = text.split('Reply as JSON with ', 1)[0].rstrip() + ' '
                ending = self.spec['natural_choice_pair' if local == 1 else 'natural_choice_single']
                if frame == 'cats':
                    ending = ending.replace('card names', 'cat labels').replace('card you select', 'cat you select')
                text += ending
            if local == 1 and r > 1:
                text = _substitute(self.spec['ko']['restart'] if arm == 'K' else self.historical.spec['round_restart'], {'round': r}) + text
            if local == 3:
                if arm == 'R' and r < n:
                    return text + '\n\n' + self.spec['ack_json']
                scope = self.spec['scope_ko'] if arm == 'K' else self.historical.spec['measurement_scope']
                text += '\n\n' + scope + '\n\n' + self._evaluation(trial)
            return text
        if local == 4:
            name = 'explanation' if trial['probe_arm'] == 'explanation' else 'neutral'
            noun = ('카드' if frame == 'cards' else '고양이') if lang == 'ko' else ('card' if frame == 'cards' else 'cat')
            text = _substitute(self.spec[f'{name}_{lang}'], {'noun': noun})
            if arm not in NATURAL_ARMS:
                text += ' ' + self.spec[name + '_json' + ('_ko' if lang == 'ko' else '')]
            return text
        if local == 5:
            policies = []
            # Crucially, no calls to probe_policies(gold) or targets here.
            for i, policy in enumerate(trial['probe_policies'], 1):
                if lang == 'ko':
                    ordinal = '첫 번째' if policy['second_position'] == 1 else '마지막'
                    policies.append(f'선택 방식 {i}: 먼저 {self.display(trial, policy["first"])}를 고른 다음, 남은 두 대상의 순서에서 {ordinal} 대상을 고르세요.')
                else:
                    ordinal = 'first' if policy['second_position'] == 1 else 'last'
                    policies.append(f'Policy {i}: first select {self.display(trial, policy["first"])}; then select the {ordinal} object in the order of the two remaining objects.')
            text = _substitute(self.spec['prediction_' + lang], {'round': n, 'ordered_objects': self.display(trial, trial['order']), 'policies': '\n'.join(policies)})
            ending = self.spec['prediction_natural'] if arm in NATURAL_ARMS else self.spec['prediction_json' + ('_ko' if lang == 'ko' else '')]
            return text + '\n\n' + ending
        if local == 6:
            return self.spec['rerating_' + lang] + '\n\n' + self._evaluation(trial)
        return self.disclosure(trial) + '\n\n' + self.spec['scope_' + lang] + '\n\n' + self._evaluation(trial)

    def disclosure(self, trial):
        ko = trial['arm'] == 'K'
        if trial['kind'] == 'unforced':
            first, second = trial['stage_rule']
            if ko:
                a = {'K': '고른 대상을 남기는 것', 'D': '고른 대상을 버리는 것'}
                text = f'첫 라운드가 시작되기 전에 단계별 규칙이 고정되어 있었습니다. 모든 라운드에서 첫 단계의 규칙은 {a[first]}이고 두 번째 단계의 규칙은 {a[second]}입니다. 각 단계에 해당 규칙을 적용한 뒤 남은 단 하나의 대상을 최종 결과로 삼았습니다. 최종 대상은 미리 고정하지 않았습니다. 아래 표처럼 선택에 따라 최종 결과가 달라질 수 있습니다.'
            else:
                a = {'K': 'keep the selected objects', 'D': 'discard the selected objects'}
                text = f'Before Round 1, one rule was fixed for each stage. In every round, the first stage would {a[first]}, and the second stage would {a[second]}. The final object was not fixed in advance. Different choices can produce different final objects, as the table shows.'
        else:
            schedule = '\n'.join(f'{i}. {self.display(trial, [t])}' for i, t in enumerate(trial['targets'], 1))
            text = ('첫 라운드의 첫 선택 전에 각 라운드의 최종 대상이 아래 일정대로 고정되어 있었습니다. 매 단계에서 해당 라운드의 고정된 대상이 들어 있는 쪽을 남겼습니다.\n\n라운드별 고정 대상:\n' if ko else "Before the first selection in Round 1, each round's final object was fixed according to the schedule below. At every step, the group containing that round's fixed object was kept.\n\nFixed objects by round:\n") + schedule
        headings = ['첫 선택', '첫 피드백', '두 번째 선택', '두 번째 피드백', '최종 대상'] if ko else ['First selection', 'First feedback', 'Second selection', 'Second feedback', 'Final object']
        table = ['| ' + ' | '.join(headings) + ' |', '| --- | --- | --- | --- | --- |']
        for row in choice_branches(trial):
            table.append('| ' + ' | '.join([self.display(trial, row['first']), FEEDBACK_NAMES[row['route'][0]], self.display(trial, [row['second']]), FEEDBACK_NAMES[row['route'][1]], self.display(trial, [row['final']])]) + ' |')
        title = '\n\n마지막 라운드의 모든 12개 유효 선택 경로:\n\n' if ko else '\n\nAll 12 valid choice paths for the last round:\n\n'
        return text + title + '\n'.join(table)

    def canonical_schema(self, turn, remaining=None, frame='cards', trial=None):
        if trial is None:
            raise ValueError('Trial is required')
        r, local = phase(trial, turn)
        names = self.choice_names(frame, trial)
        if local < 3:
            schema = self.historical.schema(local, remaining, frame, {'n_rounds': 10})
            if local == 1:
                schema['properties']['selection']['items']['enum'] = list(names.values())
            else:
                schema['properties']['selection']['enum'] = [names[x] for x in remaining]
            return schema
        if local == 3 and trial['arm'] == 'R' and r < trial.get('n_rounds', 10):
            return {'type':'object','properties':{'ack':{'type':'string','enum':['ok']}},'required':['ack'],'additionalProperties':False}
        if local in (3, 6, 7):
            return copy.deepcopy(self.historical.data['schemas']['evaluation'])
        if local == 4:
            key = 'rule' if trial['probe_arm'] == 'explanation' else 'acknowledgment'
            return {'type':'object','properties':{key:{'type':'string'}},'required':[key],'additionalProperties':False}
        item = {'type':'object','properties':{
            'first_feedback':{'type':'string','enum':['keep_selected','discard_selected','uncertain']},
            'second_feedback':{'type':'string','enum':['keep_selected','discard_selected','uncertain']},
            'final':{'type':'string','enum':list(names.values())+['uncertain']}},
            'required':['first_feedback','second_feedback','final'],'additionalProperties':False}
        return {'type':'object','properties':{f'policy_{i}':copy.deepcopy(item) for i in range(1,5)},'required':[f'policy_{i}' for i in range(1,5)],'additionalProperties':False}

    def schema(self, turn, remaining=None, frame='cards', trial=None):
        _, local = phase(trial, turn)
        if trial['arm'] == 'F' or (trial['arm'] == 'N' and local >= 3):
            return None
        if trial['arm'] == 'JS' and local in (3, 6, 7):
            return None
        return self.canonical_schema(turn, remaining, frame, trial)

    def parse_response(self, text, turn, remaining=None, frame='cards', trial=None):
        if trial is None:
            raise ValueError('Trial is required')
        r, local = phase(trial, turn)
        names = self.choice_names(frame, trial)
        try:
            value = _json(text)
            response_format = 'json'
        except (ValueError, TypeError):
            value = None
            response_format = 'invalid_json' if text.lstrip().startswith(('{', '[')) else 'text'
        natural = trial['arm'] == 'F' or (trial['arm'] == 'N' and local >= 3)
        compliant = (response_format == 'text') if natural else (response_format == 'json')
        schema_valid = False
        if response_format == 'json':
            import jsonschema
            try:
                jsonschema.validate(value, self.canonical_schema(turn, remaining, frame, trial))
                schema_valid = True
            except jsonschema.ValidationError:
                pass
        if local < 3:
            reverse = {v:k for k,v in names.items()}
            if not natural:
                if not schema_valid:
                    raise ValueError('Invalid structured selection')
                selection = value['selection']
            elif isinstance(value, dict) and set(value) == {'selection'}:
                selection = value['selection']
            else:
                cleaned = _surface(text.strip().rstrip('.'))
                selection = [s.strip() for s in cleaned.split(',')] if local == 1 else cleaned
            if natural:
                # The four displayed names have a unique case-folded mapping.
                # Normalize only complete labels; never extract them from prose.
                reverse = {v.casefold(): k for k, v in names.items()}
                if isinstance(selection, list):
                    selection = [_surface(s).casefold() if isinstance(s, str) else s for s in selection]
                elif isinstance(selection, str):
                    selection = _surface(selection).casefold()
            if local == 1:
                if not isinstance(selection, list) or len(selection) != 2 or any(not isinstance(s,str) or s not in reverse for s in selection) or len(set(selection)) != 2:
                    raise ValueError('Expected exactly two distinct displayed names')
                selection = [reverse[s] for s in selection]
            else:
                if not isinstance(selection, str) or selection not in reverse or reverse[selection] not in (remaining or []):
                    raise ValueError('Expected exactly one actually remaining displayed name')
                selection = reverse[selection]
            return {'selection':selection,'_parse':_summary({'selection':'valid'},response_format,compliant,schema_valid)}
        if local == 3 and trial['arm'] == 'R' and r < trial.get('n_rounds', 10):
            ok = isinstance(value,dict) and value == {'ack':'ok'}
            return {'ack':'ok' if ok else None,'_parse':_summary({'ack':'valid' if ok else 'unparseable'},response_format,compliant,schema_valid)}
        if local == 4:
            key = 'rule' if trial['probe_arm'] == 'explanation' else 'acknowledgment'
            answer = value.get(key) if isinstance(value,dict) else (text.strip() if natural else None)
            valid = isinstance(answer,str) and bool(answer.strip())
            return {key:answer if valid else None,'_parse':_summary({key:'valid' if valid else 'unparseable'},response_format,compliant,schema_valid)}
        if local in (3,6,7):
            fields, out = {}, {}
            for key, kind in [('freedom','rating'),('impact','rating'),('counterfactual','counterfactual')]:
                if isinstance(value,dict):
                    raw = value.get(key)
                    duplicate = False
                else:
                    matches = re.findall(r'^\s*(?:\d+[.)]\s*)?(?:\*\*)?' + key + r'(?:\*\*)?\s*[:=](?:\*\*)?\s*(.*?)\s*$',text,re.I|re.M)
                    duplicate = len(matches)>1
                    raw = _surface(matches[0].strip().rstrip('.')) if len(matches)==1 else None
                    if kind=='rating' and isinstance(raw,str) and re.fullmatch(r'\d{1,3}',raw):
                        raw = int(raw)
                    if kind=='counterfactual' and isinstance(raw,str):
                        raw = raw.lower()
                out[key], fields[key] = (None,'ambiguous') if duplicate else _field(raw,kind)
            out['_parse'] = _summary(fields,response_format,compliant,schema_valid)
            return out
        fields, out = {}, {}
        for i in range(1,5):
            policy_key = f'policy_{i}'
            if isinstance(value,dict):
                row = value.get(policy_key, {})
                row = row if isinstance(row,dict) else {}
                duplicate = False
            else:
                lines = re.findall(r'^\s*Policy\s+'+str(i)+r'\s*:\s*(.*?)\s*$',text,re.I|re.M)
                duplicate = len(lines)>1
                row = {}
                if len(lines)==1:
                    for piece in lines[0].split(';'):
                        found = re.fullmatch(r'\s*(first_feedback|second_feedback|final)\s*=\s*(.*?)\s*',piece,re.I)
                        if found:
                            k,v = found.groups()
                            k=k.lower()
                            if k in row:duplicate=True
                            row[k]=v.rstrip('.')
            out[policy_key] = {}
            for key, kind in [('first_feedback','feedback'),('second_feedback','feedback'),('final','final')]:
                v,status = (None,'ambiguous') if duplicate else _field(row.get(key),kind,names,normalize_display=natural)
                out[policy_key][key] = v
                fields[policy_key+'.'+key] = status
        out['_parse'] = _summary(fields,response_format,compliant,schema_valid)
        return out
