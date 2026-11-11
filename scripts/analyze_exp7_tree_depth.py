"""Offline combinatorics and resource arithmetic for a proposed deeper game."""
from collections import Counter
import hashlib
from itertools import combinations, product
import json
from math import comb, prod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/data/exp7-tree-depth-20261108'


def enumerate_forced_paths(objects, target, prefix=''):
    if len(objects) == 1:
        assert objects == (target,)
        yield prefix
        return
    for chosen in combinations(objects, len(objects)//2):
        keep = target in chosen
        survivors = tuple(x for x in objects if (x in chosen) == keep)
        yield from enumerate_forced_paths(survivors, target, prefix + ('K' if keep else 'D'))


def session_count(controls, obj_n=120):
    # 8 models x 3 efforts x 2 frames; 2 English formats and existing schema R.
    return 8*3*2*(2*(obj_n+120+controls*30)+(32+30+controls*30))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for depth in (2,3,4,5):
        labels = [''.join(p) for p in product('KD', repeat=depth)]
        switch_counts = Counter(sum(a != b for a,b in zip(p,p[1:])) for p in labels)
        assert switch_counts == {s: 2*comb(depth-1,s) for s in range(depth)}
        paths = prod(comb(2**j,2**(j-1)) for j in range(1,depth+1))
        counts = None
        if depth <= 3:
            counts = dict(sorted(Counter(enumerate_forced_paths(tuple(range(2**depth)), 0)).items()))
            assert len(counts) == 2**depth and sum(counts.values()) == paths
            assert set(counts.values()) == {paths // (2**depth)}
        calls = 10*(depth+1)+4
        alternating = ''.join('K' if i%2==0 else 'D' for i in range(depth))
        controls = ['K'*depth, 'D'*depth, alternating, alternating.translate(str.maketrans('KD','DK'))]
        assert len(set(controls)) == 4
        rows.append({
            'cards':2**depth, 'selection_stages_per_round':depth,
            'possible_KD_strings':2**depth, 'literal_unordered_subset_choice_paths':paths,
            'exhaustive_small_tree_audit_counts':counts,
            'within_round_switch_count_distribution_uniform_choices':{
                str(s): {'paths':n,'probability':n/2**depth} for s,n in sorted(switch_counts.items())},
            'expected_within_round_switches_uniform_choices':(depth-1)/2,
            'maximum_within_round_switches':depth-1,
            'feedback_labels_per_10_rounds':10*depth, 'calls_per_10_round_conversation':calls,
            'four_control_templates':controls,
            'four_templates':{'conversations':session_count(4),'calls':session_count(4)*calls,
                             'days_at100':session_count(4)*calls/144000},
            'all_fixed_stage_patterns':{'controls':2**depth,'conversations':session_count(2**depth),
                                       'calls':session_count(2**depth)*calls,
                                       'days_at100':session_count(2**depth)*calls/144000},
            'obj128_four_templates':{'conversations':session_count(4,128),
                                    'calls':session_count(4,128)*calls,
                                    'days_at100':session_count(4,128)*calls/144000},
        })
    sources = [Path('/workspace/attachments/4652a64a-2ce3-40a6-945e-ada4bcd757ff/붙여넣은 텍스트.txt'),
               Path('/workspace/llm-equivoque-experiments/docs/EXP7_HYBRID_COGNITIVE_MODEL.ko.md'),
               ROOT/'exp7_main/analysis_contract.json', ROOT/'exp7_main/schedule.py']
    data = {'status':'proposal_only', 'new_model_calls':0, 'frozen_design_changed':False,
            # Arithmetic remains reproducible when a private attachment or the
            # historical analysis worktree is unavailable on another machine.
            'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in sources},
            'rows':rows,
            'matched_feedback_comparison':[
                {'cards':4,'rounds':15,'feedback_labels':30,'calls':49},
                {'cards':8,'rounds':10,'feedback_labels':30,'calls':44}],
            'full_4_and_8_card_four_template_comparison_days_at100':sum(r['four_templates']['days_at100'] for r in rows[:2]),
            'assumptions':[
                'Select exactly half of the survivors; retain the target-containing half; target fixed before first selection.',
                'Uniform KD probabilities require uniform independent conditional subset choices, not assumed for actual LLM choices.',
                '2^depth counts semantic KD strings, not literal subset-choice paths or paths observed by a single conversation.',
                'One rating after the entire round plus four final calls; stage-by-stage rating requires a different budget.',
                'Resource rows replace the deck size, not cross all deck sizes. Two English formats, 24 profiles, two frames, and one schema R retained.',
                'Four templates are a proposed reduction from exhaustive depth>2 stage-rule controls; not a changed existing manifest.',
                '120 objects requires revised target/split balancing at larger decks; obj128 figures are separate scenarios.',
                '100 successful calls/minute is a planning assumption; larger-deck token use, accuracy and throughput are unmeasured.',
            ]}
    (OUT/'comparison.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'rows':[{k:r[k] for k in ('cards','selection_stages_per_round','possible_KD_strings','calls_per_10_round_conversation','four_templates','all_fixed_stage_patterns')} for r in rows],
                      'exhaustive_4_and_8_card_path_audits':'passed','new_model_calls':0},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
