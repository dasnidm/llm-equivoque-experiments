"""Frozen descriptive analysis and standalone visualizations for 28 sessions."""
import argparse
import collections
import csv
import html
import json
from pathlib import Path
import statistics
import tarfile
import zipfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from equivoque.core import ROOT,digest,read_json,write_json
from .protocol import CONFIG,FREEZE,frozen_hashes,probe_policies
from .audit import audit_worker

CONDITIONS=['exp3-pilot-card-obj','exp3-pilot-card-seq','exp3-pilot-cat-obj','exp3-pilot-cat-seq']


def resolve_results(root,run):
    direct=Path(root)/'results'/run
    if any(direct.glob('worker-*/trials/*.json')):return direct
    archives=direct/'raw-archives'
    cache=Path(root)/'work/extracted-results'/run
    if not archives.exists():raise ValueError('No raw results or archives')
    for path in archives.glob('worker-*.tar.gz'):
        with tarfile.open(path,'r:gz') as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:
                    raise ValueError('Unsafe archive member')
            archive.extractall(cache,filter='data')
    return cache


def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def save(fig,out,name):
    fig.savefig(out/(name+'.png'),dpi=160,bbox_inches='tight')
    fig.savefig(out/(name+'.svg'),bbox_inches='tight');plt.close(fig)


def first_round(rows,predicate):
    return next((r['round'] for r in rows if predicate(r)),None)


def export(root,out):
    frozen_hashes();config=read_json(CONFIG);run=config['run_id'];root=Path(root);out=Path(out)
    if out.exists():raise ValueError('Analysis output exists; preserve earlier attempt')
    out.mkdir(parents=True);(out/'tables').mkdir();(out/'figures').mkdir()
    data=resolve_results(root,run);audits=[];states=[];seen=set();sessions=set()
    for w in config['workers']:
        manifest=root/'manifests'/run/f'worker-{w}.json'
        audit=audit_worker(manifest,data/f'worker-{w}');audits.append(audit)
        if not audit['integrity_ok']:raise ValueError('Worker audit failed: '+str(audit['errors'][:3]))
        for path in (data/f'worker-{w}'/'trials').glob('*.json'):
            s=read_json(path)
            if s['trial']['trial_id'] in seen or (s.get('session_id') and s['session_id'] in sessions):raise ValueError('Duplicate trial/session across workers')
            seen.add(s['trial']['trial_id'])
            if s.get('session_id'):sessions.add(s['session_id'])
            states.append(s)
    summary_audit={'run_id':run,'assigned':28,'attempted':len(states),'counts':dict(collections.Counter(s['status'] for s in states)),
                   'unattempted':28-len(states),'evaluation_invocations':sum(a['subject_invocations'] for a in audits),
                   'valid_measurements':sum(a['valid_measurements'] for a in audits),'workers':audits,
                   'integrity_ok':True,'unique_native_sessions':len(sessions),
                   'compaction_events':[e for a in audits for e in a['compaction_events']]}
    write_json(out/'union_audit.json',summary_audit)
    measurements=[];turns=[];choices=[];trials=[];rules=[];predictions=[]
    coding_path=root/'experiment7/runtime/rule-coding.json'
    coding=read_json(coding_path) if coding_path.exists() else {}
    for s in states:
        t=s['trial'];base={k:t[k] for k in ('trial_id','configuration_id','model','frame','kind','pilot_label','worker_id')}
        pre=[];post=None;rule=None;prediction=None
        for record in s['turns']:
            turns.append({**base,'turn':record['turn'],'round':record['round'],'local_turn':record['local_turn'],
                          'ok':record['ok'],'parsed':bool(record.get('parsed')),'duration_seconds':record.get('duration_seconds'),
                          'requested_at':record['requested_at'],'received_at':record['received_at'],'session_id':record.get('session_id')})
            value=record.get('parsed')
            if value is None:continue
            local=record['local_turn'];r=record['round']
            if local==3:
                row={**base,'round':r,'target_position':t['positions'][r-1],'target_internal':t['targets'][r-1],
                     'freedom':value['freedom'],'impact':value['impact'],'counterfactual':value['counterfactual']}
                pre.append(row);measurements.append(row)
            elif local==4:rule=value['rule']
            elif local==5:prediction=value
            elif local==6:post=value
            elif local in (1,2):choices.append({**base,'round':r,'stage':local,'selection':json.dumps(value['selection']),
                 'route':s['rounds'][r-1]['route'],'target_position':t['positions'][r-1]})
        pre.sort(key=lambda r:r['round'])
        category=coding.get(t['trial_id'],{}).get('category','uncoded')
        rules.append({**base,'rule':rule,'category':category})
        match=uncertain=0
        if prediction:
            for i,policy in enumerate(probe_policies(t),1):
                answer=prediction[f'policy_{i}'];gold=policy['gold']
                for field in ('first_feedback','second_feedback','final'):
                    actual=answer[field];is_uncertain=actual=='uncertain';is_match=actual==gold[field]
                    match+=is_match;uncertain+=is_uncertain
                    predictions.append({**base,'policy':i,'component':field,'answer':actual,'generator_value':gold[field],
                                        'matches_generator':is_match,'uncertain':is_uncertain})
        trials.append({**base,'status':s['status'],'valid_rounds':len(pre),'calls':len(s['turns']),
            'first_impact_1':first_round(pre,lambda r:r['impact']==1),
            'first_impact_below_100':first_round(pre,lambda r:r['impact']<100),
            'first_counterfactual_no':first_round(pre,lambda r:r['counterfactual']=='no'),
            'impact_reversals':sum(a['impact']==1 and b['impact']>1 for a,b in zip(pre,pre[1:])),
            'counterfactual_reversals':sum(a['counterfactual']=='no' and b['counterfactual']=='yes' for a,b in zip(pre,pre[1:])),
            'round1_freedom':pre[0]['freedom'] if pre else None,'round1_impact':pre[0]['impact'] if pre else None,
            'last_observed_round':pre[-1]['round'] if pre else None,'last_freedom':pre[-1]['freedom'] if pre else None,
            'last_impact':pre[-1]['impact'] if pre else None,'last_counterfactual':pre[-1]['counterfactual'] if pre else None,
            'rule_category':category,'prediction_generator_matches':match if prediction else None,
            'prediction_uncertain_components':uncertain if prediction else None,
            'post_freedom':post['freedom'] if post else None,'post_impact':post['impact'] if post else None,
            'post_counterfactual':post['counterfactual'] if post else None,'error':s.get('error')})
    common=['trial_id','configuration_id','model','frame','kind','pilot_label','worker_id']
    for name,rows,extra in [('measurements',measurements,['round','target_position','target_internal','freedom','impact','counterfactual']),
            ('turns',turns,['turn','round','local_turn','ok','parsed','duration_seconds','requested_at','received_at','session_id']),
            ('choices',choices,['round','stage','selection','route','target_position']),
            ('rules',rules,['rule','category']),('predictions',predictions,['policy','component','answer','generator_value','matches_generator','uncertain'])]:
        write_csv(out/'tables'/f'{name}.csv',rows,common+extra)
    write_csv(out/'tables/trials.csv',trials,list(trials[0]) if trials else common+['status'])
    models=[c['model'] for c in config['configurations']]
    colors={'obj':'#2563eb','seq':'#e87918'}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    for metric in ('impact','freedom'):
        fig,axes=plt.subplots(7,2,figsize=(13,16),sharex=True,sharey=True)
        for i,model in enumerate(models):
            for j,frame in enumerate(('cards','cats')):
                ax=axes[i,j]
                for kind in ('obj','seq'):
                    group=sorted([r for r in measurements if r['model']==model and r['frame']==frame and r['kind']==kind],key=lambda r:r['round'])
                    ax.plot([r['round'] for r in group],[r[metric] for r in group],color=colors[kind],lw=2,marker='.',label='Constant target' if kind=='obj' else 'Varying sequence')
                ax.set_title(model+' | '+frame,loc='left');ax.set_ylim(-3,104);ax.set_xlim(1,30);ax.set_yticks([1,25,50,75,100]);ax.grid(alpha=.15)
        axes[0,0].legend(loc='lower left',fontsize=9)
        fig.supxlabel('Game round, before disclosure');fig.supylabel(metric.capitalize()+' rating (1-100)')
        fig.suptitle('Reported '+metric+' | one conversation per model and condition',y=.995)
        fig.tight_layout();save(fig,out/'figures','01_impact_trajectories' if metric=='impact' else '02_freedom_trajectories')
    fig,axes=plt.subplots(1,2,figsize=(14,5.3))
    for ax,field,title in zip(axes,['first_impact_1','first_counterfactual_no'],['First impact rating of 1','First counterfactual no']):
        matrix=np.full((7,4),np.nan);labels={}
        for i,model in enumerate(models):
            for j,condition in enumerate(CONDITIONS):
                row=next((t for t in trials if t['model']==model and t['pilot_label']==condition),None)
                if row and row[field] is not None:matrix[i,j]=row[field];labels[i,j]=str(row[field])
                elif row:labels[i,j]='>'+str(row['last_observed_round'] or 0)+(' *' if row['status']!='complete' else '')
                else:labels[i,j]='NA'
        cmap=plt.get_cmap('viridis_r').copy();cmap.set_bad('#eeeeee');im=ax.imshow(matrix,vmin=1,vmax=30,cmap=cmap,aspect='auto')
        ax.set_xticks(range(4),['Card fixed','Card sequence','Cat fixed','Cat sequence'],rotation=25,ha='right');ax.set_yticks(range(7),models);ax.set_title(title)
        for (i,j),label in labels.items():ax.text(j,i,label,ha='center',va='center',color='black',fontsize=10)
        fig.colorbar(im,ax=ax,label='Round')
    fig.suptitle('Observed judgment events; >30 means no event observed by round 30. * = partial session')
    fig.tight_layout();save(fig,out/'figures','03_first_observed_events')
    fig,axes=plt.subplots(2,4,figsize=(15,8),sharex=True,sharey=True)
    for ax,model in zip(axes.flat,models):
        for kind in ('obj','seq'):
            group=[r for r in measurements if r['model']==model and r['kind']==kind]
            counts=collections.Counter((r['freedom'],r['impact']) for r in group)
            for (f,i),count in counts.items():ax.scatter(f,i,s=25+count*5,c=colors[kind],alpha=.55,edgecolors='white')
        ax.set_title(model);ax.set_xlim(-5,106);ax.set_ylim(-5,106);ax.grid(alpha=.15)
    axes.flat[-1].axis('off');fig.supxlabel('Selection freedom');fig.supylabel('Perceived causal influence')
    fig.suptitle('Two agency dimensions | bubble area reflects repeated reports | blue fixed, orange sequence')
    fig.tight_layout();save(fig,out/'figures','04_agency_dimensions')
    matrix=np.full((7,4),np.nan);uncertainties={}
    for i,model in enumerate(models):
        for j,condition in enumerate(CONDITIONS):
            row=next((t for t in trials if t['model']==model and t['pilot_label']==condition),None)
            if row and row['prediction_generator_matches'] is not None:
                matrix[i,j]=row['prediction_generator_matches'];uncertainties[i,j]=row['prediction_uncertain_components']
    fig,ax=plt.subplots(figsize=(10,5));im=ax.imshow(matrix,vmin=0,vmax=12,cmap='Blues',aspect='auto')
    ax.set_xticks(range(4),['Card fixed','Card sequence','Cat fixed','Cat sequence']);ax.set_yticks(range(7),models)
    for (i,j),u in uncertainties.items():ax.text(j,i,f'{int(matrix[i,j])}/12\n{u} uncertain',ha='center',va='center',fontsize=9,color='black')
    ax.set_title('Retrospective predictions matching the actual generator\nMechanism compatibility, not proof of uniquely inferred causation')
    fig.colorbar(im,ax=ax,label='Matching components');fig.tight_layout();save(fig,out/'figures','05_prediction_compatibility')
    endpoints=[t for t in trials if t['valid_rounds']==30]
    aggregates=[]
    for kind in ('obj','seq'):
        subset=[t for t in endpoints if t['kind']==kind]
        aggregates.append({'kind':kind,'valid_round30':len(subset),'impact_1':sum(t['last_impact']==1 for t in subset),
            'counterfactual_no':sum(t['last_counterfactual']=='no' for t in subset),
            'mean_impact':statistics.mean(t['last_impact'] for t in subset) if subset else None,
            'mean_freedom':statistics.mean(t['last_freedom'] for t in subset) if subset else None})
    write_csv(out/'tables/condition_summary.csv',aggregates,list(aggregates[0]))
    post=[t for t in trials if t['post_impact'] is not None]
    rule_counts=collections.Counter(t['rule_category'] for t in trials)
    intermediate=sum(r['impact'] not in (1,100) for r in measurements)
    lines=['# Thirty round forcing sequence pilot','',
      f"Seven requested low-effort models completed {summary_audit['counts'].get('complete',0)} of 28 assigned conversations. The study contains {len(measurements)} valid pre-disclosure ratings and {summary_audit['evaluation_invocations']} attempted evaluation invocations. No failed conversation was replaced.",
      '', '## Design','',
      'Each model received cards and cats under a constant target and one shared precommitted varying target sequence. Layout stayed fixed: spades, clubs, hearts, diamonds; cats A, B, C, D. Every round used the unchanged freedom, impact and yes/no counterfactual questions. The constant target matched the sequence\'s first position. All 30 rounds continued despite low ratings. Rule accounts and retrospective predictions preceded disclosure.',
      '', '## Observed results','',
      '| Schedule | Valid round 30 | Impact = 1 | Counterfactual no | Mean impact | Mean freedom |',
      '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in aggregates:
        mi=f"{row['mean_impact']:.2f}" if row['mean_impact'] is not None else 'NA';mf=f"{row['mean_freedom']:.2f}" if row['mean_freedom'] is not None else 'NA'
        lines.append(f"| {row['kind']} | {row['valid_round30']} | {row['impact_1']} | {row['counterfactual_no']} | {mi} | {mf} |")
    lines+=['',f"Across all pre-disclosure observations, {intermediate} impact ratings were between 1 and 100. Impact returned from 1 to a higher rating {sum(t['impact_reversals'] for t in trials)} times; counterfactual answers returned from no to yes {sum(t['counterfactual_reversals'] for t in trials)} times. At disclosure, {sum(t['post_impact']==1 for t in post)}/{len(post)} impact ratings were 1 and {sum(t['post_counterfactual']=='no' for t in post)}/{len(post)} counterfactual answers were no.",
      '', '### First observed impact rating of 1','',
      '| Model | Card fixed | Card sequence | Cat fixed | Cat sequence |','| --- | ---: | ---: | ---: | ---: |']
    for model in models:
        labels=[]
        for condition in CONDITIONS:
            row=next((t for t in trials if t['model']==model and t['pilot_label']==condition),None)
            labels.append(str(row['first_impact_1']) if row and row['first_impact_1'] is not None else '>'+str(row['last_observed_round'] or 0) if row else 'NA')
        lines.append('| '+model+' | '+' | '.join(labels)+' |')
    lines+=['','An event in round 1 is an initial report, not a demonstrated transition. No event by round 30 is censored observation, not evidence of permanent inability. Full freedom trajectories and earlier intermediate impact scores remain in the tables.',
      '', '## Interpretation and limits','',
      'Freedom to select objects and causal influence on outcomes are separate agency-related reports. Low impact does not establish conditional-rule knowledge. Terminal explanations are elicited accounts, not records of when an internal discovery occurred. The prediction table counts compatibility with the actual hidden generator; uncertainty or a plausible alternative procedure is not automatically a reasoning failure.',
      '', 'There is one conversation per model, frame and schedule and only one shared varying sequence. These results describe this screen; they do not estimate a model\'s usual discovery time, support confirmatory rankings, or justify population curve fitting. Fixed identity and position covary; changing targets can also change keep/discard routes. Repeated measurement may invite reflection. Comparisons with the human Kuhn study are procedural analogies, not direct replications.',
      '', '## Validation and provenance','',
      f"The cross-worker raw audit passed; {summary_audit['unique_native_sessions']} native sessions were unique. Detected compaction events: {len(summary_audit['compaction_events'])}. Requested model/low effort, pinned CLI, native schema and zero offered tools were checked before release. Hidden backend model versions, wire-level retry counts and billing cost are not independently attested. Resume token counters are not billing estimates.",
      '', 'Calibration and all earlier experiments are excluded. Raw failures and native diagnostics are preserved. See union_audit.json, provenance.json, the invocation ledger, CSV tables and artifact hashes. Figures are descriptive; there are no inferential confidence intervals.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    provenance={'run_id':run,'freeze_sha256':digest(FREEZE),'config_sha256':digest(CONFIG),'analysis_sha256':digest(ROOT/'experiment7/analyze.py'),
                'rule_coding_sha256':digest(coding_path) if coding_path.exists() else None,
                'models_requested':config['configurations'],'subject_context':'Neutral empty native-study/UUID/subject directory, no repository/condition names, zero tools',
                'raw_audit_sha256':digest(out/'union_audit.json'),'inference':'descriptive only; one shared sequence'}
    write_json(out/'provenance.json',provenance)
    # Offline explorer: all data embedded, no network or external JavaScript.
    explorer='''<!doctype html><meta charset="utf-8"><title>Forcing sequence trajectories</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:0 20px}select{font:inherit;margin:8px}canvas{width:100%;height:420px;border:1px solid #ddd}pre{white-space:pre-wrap}a{color:#2563eb}</style><h1>Thirty-round forcing sequence pilot</h1><p>One conversation per model, frame and schedule. Blue: constant target. Orange: varying target. Scores are reports, not discovery proofs.</p><select id="model"></select><select id="frame"><option>cards</option><option>cats</option></select><select id="metric"><option>impact</option><option>freedom</option></select><canvas id="plot" width="1000" height="420"></canvas><pre id="events"></pre><p><a href="REPORT.md">English report</a> · <a href="tables/trials.csv">Session table</a></p><script>const rows=__ROWS__,trials=__TRIALS__,models=__MODELS__;const model=document.getElementById('model'),frame=document.getElementById('frame'),metric=document.getElementById('metric');models.forEach(m=>{const o=document.createElement('option');o.textContent=m;model.append(o)});function draw(){const c=document.getElementById('plot'),x=c.getContext('2d');x.clearRect(0,0,1000,420);const px=n=>60+(n-1)*900/29,py=v=>370-(v-1)*330/99;x.strokeStyle='#ddd';x.fillStyle='#333';x.font='14px system-ui';[1,25,50,75,100].forEach(v=>{x.beginPath();x.moveTo(60,py(v));x.lineTo(960,py(v));x.stroke();x.fillText(v,15,py(v)+5)});[1,5,10,20,30].forEach(n=>x.fillText(n,px(n)-5,395));['obj','seq'].forEach((k,i)=>{const r=rows.filter(r=>r.model===model.value&&r.frame===frame.value&&r.kind===k).sort((a,b)=>a.round-b.round);x.strokeStyle=i?'#e87918':'#2563eb';x.lineWidth=3;x.beginPath();r.forEach((r,j)=>j?x.lineTo(px(r.round),py(r[metric.value])):x.moveTo(px(r.round),py(r[metric.value])));x.stroke()});document.getElementById('events').textContent=trials.filter(t=>t.model===model.value&&t.frame===frame.value).map(t=>t.kind+': first impact 1 = '+(t.first_impact_1===null?'> '+t.last_observed_round:t.first_impact_1)+'; first counterfactual no = '+(t.first_counterfactual_no===null?'> '+t.last_observed_round:t.first_counterfactual_no)).join('\\n')}[model,frame,metric].forEach(s=>s.onchange=draw);draw();</script>'''
    explorer=explorer.replace('__ROWS__',json.dumps(measurements).replace('<','\\u003c')).replace('__TRIALS__',json.dumps(trials).replace('<','\\u003c')).replace('__MODELS__',json.dumps(models))
    (out/'explorer.html').write_text(explorer)
    manifest={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}
    write_json(out/'artifact-manifest.json',{'run_id':run,'files':manifest})
    return summary_audit


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(ROOT));p.add_argument('--output',required=True)
    args=p.parse_args();audit=export(args.root,args.output);print(json.dumps({k:v for k,v in audit.items() if k!='workers'}))


if __name__=='__main__':main()
