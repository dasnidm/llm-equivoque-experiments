"""Offline, outcome-independent schedules and reserved cases for Exp 7.

The four-object fixed-layout/target space has only 96 distinct structures.
Case IDs are not treated as evidence of novel stimuli.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import random

from equivoque.core import ROOT, read_json
from sequence_replication.protocol import CONFIG
from sequence_replication.schedule import make_cases
from .protocol import ARMS, make_probe_policies, validate_trial

SEED = 2026103007
RUN_ID = 'equivoque-2026-10-30-exp7-pre-v8'
FOCUS = [('gpt-5.6-sol','high'),('gpt-6-astra','low'),
         ('gpt-6-luna','low'),('gpt-6.1-terra','high')]
KINDS = ('obj','seq','unforced')


def encoded(obj):
    return json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()


def fingerprint(case):
    return tuple(case['abstract_order']), case['target_identity']


def balanced_subset(candidates, n, rng):
    """Rejection sample balanced identities/positions, using no model outcomes."""
    if n % 4: raise ValueError('Balanced case count must be divisible by four')
    for _ in range(200000):
        sample = rng.sample(candidates, n)
        a = Counter(c['target_identity'] for c in sample)
        b = Counter(c['target_position'] for c in sample)
        if set(a.values()) == {n//4} and set(b.values()) == {n//4} and len(a)==len(b)==4:
            return sample
    raise RuntimeError('Could not construct balanced unique cases')


def case_partition():
    old = make_cases(read_json(CONFIG))
    used = {fingerprint(c) for c in old}
    assert len(used) == 30
    available = [{'abstract_order':list(order),'target_identity':target,
                  'target_position':order.index(target)+1}
                 for order in itertools.permutations(range(4)) for target in range(4)
                 if (order,target) not in used]
    rng = random.Random(SEED)
    pre = balanced_subset(available,12,rng)
    used.update(fingerprint(c) for c in pre)
    available = [c for c in available if fingerprint(c) not in used]
    calibration = balanced_subset(available,4,rng)
    used.update(fingerprint(c) for c in calibration)
    available = [c for c in available if fingerprint(c) not in used]
    main = balanced_subset(available,48,rng)
    subsets = {'pre':pre,'calibration':calibration,'main_reserved':main}
    for name,cases in subsets.items():
        for i,c in enumerate(cases):
            c['case_id'] = f'{name}-case-{i+1:03d}'
            sequence_rng = random.Random(SEED+10000+int(hashlib.sha256(c['case_id'].encode()).hexdigest()[:8],16))
            extra = sequence_rng.sample(range(1,5),2)
            seq = [p for p in range(1,5) for _ in range(2+int(p in extra))]
            seq.remove(c['target_position']); sequence_rng.shuffle(seq)
            c['positions'] = [c['target_position']]+seq
            c['stage_rule'] = ('KK','KD','DK','DD')[i%4]
            c['probe_seed'] = SEED+20000+int(hashlib.sha256(c['case_id'].encode()).hexdigest()[:8],16)
            c['prompt_variant'] = 'p1' if i%2==0 else 'p2'
            c['structure_sha256'] = hashlib.sha256(encoded(fingerprint(c))).hexdigest()
    # Paraphrase assignment must not be determined by fixed stage-rule parity.
    # In the pre sample, each of four stage rules and target identities/positions
    # receives both variants (1 vs 2 among its three matched case families).
    variant_rng=random.Random(SEED+40000)
    for _ in range(20000):
        first=set(variant_rng.sample(range(12),6))
        if all(all(1<=sum(i in first for i,c in enumerate(pre) if c[key]==value)<=2
                   for value in {c[key] for c in pre})
               for key in ('stage_rule','target_identity','target_position')):
            break
    else:raise RuntimeError('Could not balance paraphrases')
    for i,c in enumerate(pre):c['prompt_variant']='p1' if i in first else 'p2'
    # Existing layout/target structures, calibration, pre and main never overlap.
    structures = [fingerprint(c) for c in old]+[fingerprint(c) for cs in subsets.values() for c in cs]
    assert len(structures)==len(set(structures))==94
    return {'old_structure_count':30,'finite_structure_count':96,
            'unused_structure_count':2,**subsets}


def profiles(scope):
    if scope=='focus': return FOCUS
    return [(m,e) for m in sorted({c['model'] for c in read_json(CONFIG)['configurations']}|{'gpt-6.1-terra'})
            for e in ('low','medium','high')]


def trial(case,model,effort,arm,kind,probe_arm,replicate,run_id):
    names = 'ABDC'  # same abstract identity-to-card correspondence as Exp5
    order = [names[i] for i in case['abstract_order']]
    positions = case['positions'] if kind=='seq' else [case['target_position']]*10
    t = {'run_id':run_id,'configuration_id':f'{model}-{effort}',
         'model':model,'effort':effort,'frame':'cards','arm':arm,'kind':kind,
         'case_id':case['case_id'],'structure_sha256':case['structure_sha256'],
         'n_rounds':10,'order':order,'targets':[order[p-1] for p in positions] if kind!='unforced' else [],
         'stage_rule':case['stage_rule'],'probe_seed':case['probe_seed'],
         'probe_policies':make_probe_policies(order,case['probe_seed']),
         'probe_arm':probe_arm,'prompt_variant':case['prompt_variant'],
         'replicate':replicate,'cohort':'primary' if replicate==1 else 'independent_repeat'}
    validate_trial(t)
    return t


def build(scope='focus',calibration=False):
    partition=case_partition()
    panel=profiles(scope)
    run_id=RUN_ID+('-calibration' if calibration else '')+('-full' if scope=='full' else '')
    cases=partition['calibration'] if calibration else partition['pre']
    rng=random.Random(SEED+30000)
    trials=[]
    if calibration:
        # Cover every arm/procedure; profile rotates, not a full inference sample.
        for a,arm in enumerate(ARMS):
            for k,kind in enumerate(KINDS):
                model,effort=panel[(a*3+k)%len(panel)]
                case=cases[(a+k)%len(cases)]
                trials.append(trial(case,model,effort,arm,kind,'explanation' if (a+k)%2 else 'neutral',1,run_id))
        for t in trials: t['cohort']='calibration'
    else:
        for model,effort in panel:
            for kind in KINDS:
                for arm in ARMS:
                    # Half of the case families per cell, chosen before responses.
                    explain=set(rng.sample([c['case_id'] for c in cases],6))
                    for i,case in enumerate(cases):
                        t=trial(case,model,effort,arm,kind,'explanation' if case['case_id'] in explain else 'neutral',1,run_id)
                        trials.append(t)
                        if arm=='A' and i<2:
                            for rep in (2,3):
                                trials.append({**t,'replicate':rep,'cohort':'independent_repeat'})
    rng.shuffle(trials)
    for i,t in enumerate(trials,1): t['trial_id']=f'{"cal" if calibration else "pre"}-{i:06d}'
    return {'run_id':run_id,'scope':scope,'purpose':'calibration' if calibration else 'exploratory_validation',
            'seed':SEED,'created_without_model_outcomes':True,'n_rounds':10,'calls_per_complete_session':34,
            'planned_sessions':len(trials),'call_cap':34*len(trials),'profiles':[{'model':m,'effort':e} for m,e in panel],
            'cases':cases,'case_partition':partition,'trials':trials,
            'rules':{'automatic_retries':0,'replace_failed_sessions':False,
                     'calibration_in_primary_analysis':False,'equivalence_claim':False,
                     'repeat_cases':[c['case_id'] for c in partition['pre'][:2]]}}


def save(schedule,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(schedule,indent=2,ensure_ascii=False)+'\n'
    if path.exists() and path.read_text()!=content:
        raise ValueError('Existing schedule differs; use a new run ID, never overwrite')
    if not path.exists(): path.write_text(content)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scope',choices=('focus','full'),default='focus')
    p.add_argument('--calibration',action='store_true')
    p.add_argument('--output',type=Path)
    a=p.parse_args();schedule=build(a.scope,a.calibration)
    dest=a.output or ROOT/'manifests'/schedule['run_id']/'schedule.json'
    save(schedule,dest)
    print(json.dumps({'schedule':str(dest),'run_id':schedule['run_id'],
                      'sessions':schedule['planned_sessions'],'call_cap':schedule['call_cap']},indent=2))


if __name__=='__main__': main()
