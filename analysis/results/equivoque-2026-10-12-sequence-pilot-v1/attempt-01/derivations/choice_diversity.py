"""Supplementary descriptive choice-diversity table; no inference or new scoring."""
import argparse
import collections
import csv
import json
from pathlib import Path
import sys
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True)
a=p.parse_args();root=Path(a.root);sys.path.insert(0,str(root))
from equivoque.core import operate,read_json
run='equivoque-2026-10-12-sequence-pilot-v1';rows=[]
for path in sorted((root/'results'/run).glob('worker-*/trials/*.json')):
 s=read_json(path);t=s['trial'];first={r['round']:r['parsed']['selection'] for r in s['turns'] if r['local_turn']==1 and 'parsed' in r}
 second={r['round']:r['parsed']['selection'] for r in s['turns'] if r['local_turn']==2 and 'parsed' in r}
 policies=[];pairs=[];routes=[];outcomes=[]
 for r in sorted(first.keys() & second.keys()):
  pair=tuple(x for x in t['order'] if x in first[r]);remaining,op=operate(t['order'],list(pair),t['targets'][r-1])
  policies.append((pair,remaining.index(second[r])+1));pairs.append(pair);routes.append(s['rounds'][r-1]['route']);outcomes.append(t['targets'][r-1])
 counts=collections.Counter(policies)
 rows.append({'trial_id':t['trial_id'],'model':t['model'],'frame':t['frame'],'kind':t['kind'],'observed_full_choice_paths':len(policies),
              'distinct_first_pairs':len(set(pairs)),'distinct_choice_policies_of_12':len(counts),
              'modal_policy_count':max(counts.values(),default=0),'distinct_realized_routes':len(set(routes)),
              'distinct_final_objects':len(set(outcomes)),'policy_counts':json.dumps({str(k):v for k,v in counts.items()}),
              'route_counts':json.dumps(dict(collections.Counter(routes)))})
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
with out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(json.dumps({'sessions':len(rows),'one_observed_policy_sessions':sum(r['distinct_choice_policies_of_12']==1 for r in rows),'status':'supplementary exploratory description; no discovery-time inference'}))
