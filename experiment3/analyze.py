"""Frozen descriptive pilot estimators: no rankings, p values, or main launch."""
import csv
from collections import defaultdict
import json
import statistics
import subprocess
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from equivoque.core import ROOT, digest, read_json, write_json
from .protocol import CONFIG, FREEZE, OBJECT_FIELDS, CF_FIELDS, PilotProtocol
from .audit import union


def mean(values):
    values=list(values)
    return statistics.mean(values) if values else None


def csv_write(path, rows):
    if not rows: return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def estimate(states):
    rows=[]
    protocol=PilotProtocol()
    for s in states:
        t=s['trial']; valid=s['status']=='complete'; correct=s.get('correct',{})
        rows.append({'trial_id':t['trial_id'],'configuration_id':t['configuration_id'], 'model':t['model'],'effort':t['effort'],
                     'frame':t['frame'],'procedure':t['procedure'],'claim':t['claim'],'case_id':t['case']['case_id'],
                     'worker':t['worker_id'],'target':t['case']['target'],'target_position':t['case']['target_position'],
                     'status':s['status'],'valid':int(valid), 'transfer_accuracy':mean(int(correct[k]) for k in OBJECT_FIELDS[1:]) if valid else None,
                     **{k+'_correct':int(correct[k]) if valid else None for k in OBJECT_FIELDS+CF_FIELDS},
                     **{k+'_answer':s.get('response',{}).get(k) for k in OBJECT_FIELDS+CF_FIELDS},
                     **{k+'_expected':v for k,v in protocol.oracle(t).items()},
                     'all_transfer_correct':int(all(correct[k] for k in OBJECT_FIELDS[1:])) if valid else None,
                     'session_id':(s.get('result') or {}).get('session_id'),
                     'duration_seconds':(s.get('result') or {}).get('duration_seconds'),
                     'error':s.get('error')})
    groups=defaultdict(list)
    for r in rows: groups[(r['configuration_id'],r['frame'],r['procedure'],r['claim'])].append(r)
    cells=[]
    for key,group in sorted(groups.items()):
        valid=[r for r in group if r['valid']]
        cells.append(dict(zip(('configuration_id','frame','procedure','claim'),key),assigned=len(group),valid=len(valid),
                          transfer_accuracy=mean(r['transfer_accuracy'] for r in valid),
                          **{k+'_accuracy':mean(r[k+'_correct'] for r in valid) for k in OBJECT_FIELDS+CF_FIELDS},
                          all_transfer_correct=mean(r['all_transfer_correct'] for r in valid)))
    lookup={(r['configuration_id'],r['frame'],r['procedure'],r['case_id'],r['claim']):r for r in rows}
    pairs=[]
    for r in rows:
        if r['claim'] not in ('conflicting','congruent'): continue
        n=lookup[tuple(r[k] for k in ('configuration_id','frame','procedure','case_id'))+('neutral',)]
        valid=bool(r['valid'] and n['valid'])
        pairs.append({k:r[k] for k in ('configuration_id','frame','procedure','case_id','claim')} | {
                     'both_valid':int(valid),'transfer_difference':r['transfer_accuracy']-n['transfer_accuracy'] if valid else None})
    # Equal weights across configuration × frame × procedure cells with paired cases.
    contrasts=[]
    for claim in ('conflicting','congruent'):
        selected=[p for p in pairs if p['claim']==claim]
        by_cell=defaultdict(list)
        for p in selected:
            if p['both_valid']: by_cell[tuple(p[k] for k in ('configuration_id','frame','procedure'))].append(p['transfer_difference'])
        cell_means=[mean(v) for v in by_cell.values()]
        contrasts.append({'claim':claim,'contrast':'claim minus neutral','paired_assigned':len(selected),
                          'paired_valid':sum(p['both_valid'] for p in selected),'cells_assigned':84,'cells_valid':len(by_cell),
                          'case_families':len({p['case_id'] for p in selected if p['both_valid']}),
                          'difference':mean(cell_means)})
    return rows,cells,pairs,contrasts


def main():
    config=read_json(CONFIG)
    out=ROOT/'analysis/results'/config['run_id']/'attempt-01'
    out.mkdir(parents=True,exist_ok=False)
    audit,states=union(out/'union_audit.json')
    rows,cells,pairs,contrasts=estimate(states)
    tables=out/'tables'; tables.mkdir()
    for name,data in [('tasks',rows),('condition_cells',cells),('paired_contrasts',pairs),('overall_contrasts',contrasts)]:
        csv_write(tables/(name+'.csv'),data)
    grouped=[]
    for claim in ('neutral','congruent','conflicting'):
        for proc in ('fixed_target','keep_selected'):
            selected=[r for r in cells if r['claim']==claim and r['procedure']==proc]
            grouped.append({'claim':claim,'procedure':proc,'assigned':sum(r['assigned'] for r in selected),
                            'valid':sum(r['valid'] for r in selected),
                            **{metric:mean(r[metric] for r in selected if r[metric] is not None) for metric in
                               ('transfer_accuracy','table_lookup_accuracy','counterfactual_accuracy','changed_counterfactual_accuracy','all_transfer_correct')}})
    csv_write(tables/'condition_summary.csv',grouped)
    by_case=[]
    for case in sorted({r['case_id'] for r in rows}):
        for claim in ('neutral','congruent','conflicting'):
            subset=[r for r in rows if r['case_id']==case and r['claim']==claim and r['valid']]
            by_case.append({'case_id':case,'claim':claim,'valid':len(subset),'transfer_accuracy':mean(r['transfer_accuracy'] for r in subset)})
    csv_write(tables/'case_summary.csv',by_case)
    figdir=out/'figures'; figdir.mkdir()
    figure_names=[]
    def save(fig,name):
        fig.tight_layout(); fig.savefig(figdir/(name+'.png'),dpi=160);fig.savefig(figdir/(name+'.svg'));plt.close(fig);figure_names.append(name)
    fig,ax=plt.subplots(figsize=(8,4))
    x=np.arange(3)
    for i,proc in enumerate(('fixed_target','keep_selected')):
        selected=[next(r for r in grouped if r['claim']==claim and r['procedure']==proc) for claim in ('neutral','congruent','conflicting')]
        ax.bar(x+(i-.5)*.32,[100*r['transfer_accuracy'] if r['transfer_accuracy'] is not None else np.nan for r in selected],.32,label=proc)
    ax.set(xticks=x,xticklabels=['Neutral','Congruent','Conflicting'],ylabel='Transfer accuracy (%)',ylim=(0,105),title='Pilot: objective transfer accuracy by host claim')
    ax.legend();save(fig,'01_transfer_conditions')
    fig,ax=plt.subplots(figsize=(9,4))
    metrics=['table_lookup','new_arrangement','renaming','rule_change','counterfactual','changed_counterfactual']
    for i,claim in enumerate(('neutral','congruent','conflicting')):
        subset=[r for r in cells if r['claim']==claim]
        ax.bar(np.arange(6)+(i-1)*.25,[100*mean(r[m+'_accuracy'] for r in subset if r[m+'_accuracy'] is not None) for m in metrics],.25,label=claim)
    ax.set(xticks=np.arange(6),xticklabels=['Lookup','Arrangement','Renaming','Rule change','Original CF','Changed CF'],ylabel='Accuracy (%)',ylim=(0,105),title='Pilot: control and transfer items');ax.legend();save(fig,'02_items')
    fig,ax=plt.subplots(figsize=(8,9))
    configs=[c['configuration_id'] for c in config['configurations']]
    image=np.array([[100*mean(r['transfer_accuracy'] for r in cells if r['configuration_id']==c and r['claim']==claim and r['transfer_accuracy'] is not None) for claim in ('neutral','congruent','conflicting')] for c in configs])
    im=ax.imshow(image,vmin=0,vmax=100,cmap='viridis',aspect='auto');ax.set(xticks=range(3),xticklabels=['Neutral','Congruent','Conflicting'],yticks=range(21),yticklabels=configs,title='Descriptive pilot accuracy; no model ranking')
    fig.colorbar(im,ax=ax,label='Transfer accuracy (%)');save(fig,'03_configurations')
    fig,ax=plt.subplots(figsize=(8,4))
    for claim in ('neutral','congruent','conflicting'):
        values=[r for r in by_case if r['claim']==claim]
        ax.plot(range(1,9),[100*r['transfer_accuracy'] for r in values],marker='o',label=claim)
    ax.set(xlabel='Shared pilot case family',ylabel='Transfer accuracy (%)',ylim=(0,105),xticks=range(1,9),title='Eight shared case families');ax.legend();save(fig,'04_cases')
    durations=[r['duration_seconds'] for r in rows if r['duration_seconds'] is not None]
    fig,ax=plt.subplots(figsize=(7,4));ax.hist(durations,bins=30);ax.set(xlabel='Observed native request seconds',ylabel='Tasks',title='Operational latency; not a randomized speed comparison');save(fig,'05_latency')
    calls=sum((r.get('subject_invocations',0)) for p in (ROOT/'experiment3/runtime').glob('shared-preflight-*/readiness.json') for r in [read_json(p)])
    calls+=sum(read_json(p)['subject_invocations'] for p in (ROOT/'results'/config['run_id']).glob('worker-*/preflight-*/readiness.json'))
    write_json(out/'invocation-ledger.json',{'evaluation_native_invocations':len(states),'calibration_native_invocations':calls,
               'calibration_excluded':True,'http_attempt_count':'unknown; native CLI may retry internally','usage_note':'Native usage is retained, not converted to billable cost.'})
    valid=[r for r in rows if r['valid']]
    primary=contrasts[0]['difference']
    overall=mean(r['transfer_accuracy'] for r in cells if r['transfer_accuracy'] is not None)
    report=f'''# Experiment 3 pilot report

Run `{config['run_id']}`. Pilot only: 2,016 assigned single-turn tasks, 21 requested model/effort configurations, two frames, two procedures, three host claims, eight matched case families. There were {len(valid)} valid tasks; status counts: {json.dumps(audit['counts'])}. Four object questions and two binary counterfactual questions share one response and are not independent trials.

## Descriptive findings

Mean transfer accuracy (Questions 2–4): {100*overall:.3f}%. The prespecified conflicting-minus-neutral contrast is {100*primary:.3f} percentage points, equally weighting configuration × frame × procedure cells and using matched valid case pairs. Supporting paired tasks: {contrasts[0]['paired_valid']}/{contrasts[0]['paired_assigned']}; cells: {contrasts[0]['cells_valid']}/84; shared case families: {contrasts[0]['case_families']}/8. Table lookup is a control and does not contribute to transfer accuracy. Question-level and condition-cell denominators are in the CSVs.

This is an exploratory screening pilot. It provides no confirmatory significance tests, model rankings, power guarantee, or isolated estimate of subjective choice freedom. The task tests responses to a fully supplied vignette, two candidate procedures, an exhaustive verified table, and a host opinion. A small effect may reflect ceiling accuracy or an ineffective opinion manipulation; it does not establish general resistance to social influence. Fixed-target and selection-retaining procedures are balanced, so always answering no achieves 50% on the original counterfactual.

## Integrity and runtime

Union audit passed: {audit['unique_sessions']} distinct evaluation sessions and {audit['raw_files_verified']} verified native raw files. Frozen SHA-256: `{digest(FREEZE)}`. Source revision and audit evidence are in provenance.json. Every task starts a fresh native Codex ChatGPT session, with zero offered tools verified in offline request-body inspections. Requested model/effort matches the catalog and inspected request; final CLI events do not independently attest the provider's internal model version. Raw usage, warnings, errors, exact prompts/schemas, and session IDs are preserved. The native CLI may retry HTTP internally; wire request counts and billing cost remain unknown.

Calibration: {calls} native invocations, excluded. No uncertain task is replayed and no failed task is replaced. Missing answers stay missing. Operational concurrency observations are not a randomized throughput comparison. All earlier experiment data and canonical prompts remain unchanged.

## Next-step criteria

Review item-specific errors, paired claim sensitivity, case dependence, missingness, label/position patterns, and neutral accuracy before designing the main experiment. If accuracy is near ceiling, develop harder disjoint cases rather than silently expanding this pilot. Any main collection needs a separately frozen protocol and authorization. No Experiment 3 main trial or Experiment 4–7 task was collected.

## Figures and tables

'''
    for name in figure_names: report+=f'![{name}](figures/{name}.png)\n\n'
    (out/'REPORT.md').write_text(report)
    html='<html lang="en"><meta charset="utf-8"><title>Experiment 3 pilot</title><style>body{max-width:1000px;margin:2rem auto;font-family:system-ui}img{max-width:100%}</style><h1>Experiment 3 pilot</h1><p>Exploratory; eight shared cases. Calibration excluded. No model ranking.</p><p><a href="REPORT.md">English report</a></p>'
    html+=''.join(f'<figure><img src="figures/{n}.svg"><figcaption>{n.replace("_"," ")}</figcaption></figure>' for n in figure_names)
    (out/'index.html').write_text(html+'</html>')
    write_json(out/'provenance.json',{'run_id':config['run_id'],'freeze_sha256':digest(FREEZE),
               'integration_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
               'analysis_source_sha256':digest(Path(__file__)),'scope':'pilot_only','independent_case_families':8,
               'primary':'Mean accuracy of Q2–Q4; paired conflicting-minus-neutral; equal config/frame/procedure cell weights'})
    write_json(out/'artifact-manifest.json',{'files':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    print(json.dumps({'out':str(out),'valid':len(valid),'transfer_accuracy':overall,'primary_contrast':primary}))


if __name__=='__main__':
    main()
