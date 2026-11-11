"""Aggregate chronological K/D switch surprisal and first-report values.

Pointwise bootstrap resamples case families, preserving all rounds in each
conversation. No LLM calls; no formal tests or threshold estimation.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
OUT=HERE/'mean_surprisal';OUT.mkdir(exist_ok=True)
data=pd.read_csv(HERE/'temporal_kd_model/temporal_kd_rounds.csv.gz')
assert len(data)==25200 and data.trial_id.nunique()==2520 and data.first_event.sum()==342
assert data.groupby(['configuration_id','frame','kind']).trial_id.nunique().eq(30).all()
data['switch_sum']=(data.switch_first*data.surprise_first_bits+data.switch_second*data.surprise_second_bits)
data['switch_n']=data.switch_first+data.switch_second
sessions=data.groupby(['trial_id','case_id','configuration_id','model','effort','kind','frame'],as_index=False).agg(
    switch_sum=('switch_sum','sum'),switch_n=('switch_n','sum'),
    joint_n=('first_event','sum'))
assert sessions.joint_n.le(1).all()
reports=data[data.first_event].copy()
reports['report_round_surprisal']=reports.surprise_first_bits+reports.surprise_second_bits
reports=reports[['trial_id','report_round_surprisal','cumulative_surprise_bits']]
sessions=sessions.merge(reports,on='trial_id',how='left',validate='one_to_one')
assert sessions.joint_n.sum()==342 and sessions.switch_n.sum()==23527

MODELS=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
EFFORTS=['low','medium','high']
CONFIGS=[f'{m}-{e}' for m in MODELS for e in EFFORTS]
COLORS={'obj':'#246ea5','seq':'#df8126'}
METRICS=['kd_switch','report_round','report_cumulative']

def rng_for(frame,kind,cfg,metric):
    key=f'{frame}|{kind}|{cfg}|{metric}'.encode()
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key).digest()[:8],'big'))

def aggregate(group,metric,frame,kind,cfg):
    assert len(group)==30 and group.case_id.nunique()==30
    if metric=='kd_switch':
        numer=group.switch_sum.to_numpy(float);denom=group.switch_n.to_numpy(float)
    else:
        col='report_round_surprisal' if metric=='report_round' else 'cumulative_surprise_bits'
        numer=group[col].fillna(0).to_numpy(float);denom=group.joint_n.to_numpy(float)
    total_n=int(denom.sum());contributors=int((denom>0).sum())
    value=float(numer.sum()/total_n) if total_n else np.nan
    conversation_mean=float(np.mean(numer[denom>0]/denom[denom>0])) if contributors else np.nan
    lo=hi=np.nan
    if contributors>=2:
        idx=rng_for(frame,kind,cfg,metric).integers(0,30,size=(4000,30))
        denom_boot=denom[idx].sum(axis=1);numer_boot=numer[idx].sum(axis=1)
        valid=denom_boot>0
        vals=numer_boot[valid]/denom_boot[valid]
        lo,hi=np.quantile(vals,[.025,.975])
    return dict(configuration_id=cfg,model=group.model.iloc[0],effort=group.effort.iloc[0],
                frame=frame,kind=kind,metric=metric,n_conversations=30,
                n_contributors=contributors,n_observations=total_n,
                mean=value,mean_equal_conversation=conversation_mean,ci_low=lo,ci_high=hi)

rows=[]
for (cfg,frame,kind),g in sessions.groupby(['configuration_id','frame','kind']):
    for metric in METRICS: rows.append(aggregate(g,metric,frame,kind,cfg))
summary=pd.DataFrame(rows).sort_values(['metric','configuration_id','frame','kind'])
assert len(summary)==21*2*2*3
assert summary[summary.metric.eq('kd_switch')].n_observations.sum()==23527
assert summary[summary.metric.eq('report_round')].n_observations.sum()==342
summary.to_csv(OUT/'mean_surprisal_summary.csv',index=False,float_format='%.12g')
sessions.to_csv(OUT/'conversation_summary.csv.gz',index=False,compression={'method':'gzip','mtime':0})

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10,'pdf.fonttype':42,
                     'axes.spines.top':False,'axes.spines.right':False})
handles=[Line2D([0],[0],marker='o',color='none',markerfacecolor=COLORS[k],markeredgecolor=COLORS[k],
                markersize=7,label='obj · 동일 목표' if k=='obj' else 'seq · 변동 목표') for k in ['obj','seq']]

def plot(metric):
    labels={
      'kd_switch':('K/D가 바뀐 순간의 평균 surprisal','각 K→D 또는 D→K 피드백을 동일하게 가중 · 첫 라벨 제외',
                   '평균 전환 surprisal (bits)'),
      'report_round':('통제 판단이 처음 바뀐 라운드의 평균 surprisal','별표가 나온 라운드의 K/D 두 피드백 surprisal 합 · 해당 보고가 있는 대화만',
                      '보고 라운드의 평균 surprisal (bits)'),
      'report_cumulative':('통제 판단이 처음 바뀐 시점의 평균 누적 D','별표가 나온 시점까지 누적한 K/D surprisal · 해당 보고가 있는 대화만',
                           '첫 보고 시점 평균 누적 D (bits)'),
    }
    title,subtitle,ylabel=labels[metric]
    sub=summary[summary.metric.eq(metric)]
    top=float(sub[['mean','ci_high']].max().max())
    ymax=max(1,np.ceil((top*1.16)*2)/2)
    fig,axs=plt.subplots(2,1,figsize=(24,12),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.985,bottom=.19,top=.87,hspace=.25)
    fig.suptitle(title,fontsize=21,fontweight='bold',y=.98)
    fig.text(.5,.935,subtitle,ha='center',fontsize=12)
    fig.text(.5,.912,'점 = 평균  ·  선 = 사례 패밀리 95% 부트스트랩 구간  ·  비어 있는 칸 = 해당 사건 없음',
             ha='center',fontsize=10.5,color='#516478')
    xs=np.arange(len(CONFIGS))
    for ax,frame,label in zip(axs,['cards','cats'],['카드','고양이']):
        for i in range(7):
            if i%2==0:ax.axvspan(i*3-.5,i*3+2.5,color='#f4f7fa',zorder=0)
        for kind,offset in [('obj',-.17),('seq',.17)]:
            values=sub[(sub.frame==frame)&(sub.kind==kind)].set_index('configuration_id').reindex(CONFIGS)
            for x,(_,row) in zip(xs+offset,values.iterrows()):
                if pd.isna(row['mean']):continue
                if pd.notna(row.ci_low) and pd.notna(row.ci_high):
                    ax.vlines(x,row.ci_low,row.ci_high,color=COLORS[kind],alpha=.6,linewidth=1,zorder=2)
                ax.scatter(x,row['mean'],s=26,c=COLORS[kind],zorder=3)
                if metric!='kd_switch':
                    ax.annotate(str(int(row.n_contributors)),(x,row['mean']),xytext=(0,5),
                                textcoords='offset points',ha='center',fontsize=6.5,color=COLORS[kind])
        ax.set_title(label,loc='left',fontsize=14,fontweight='bold',pad=6)
        ax.set_ylim(0,ymax);ax.set_xlim(-.6,20.6);ax.grid(axis='y',alpha=.22)
    axs[-1].set_xticks(xs,[f'{m}\n{e}' for m in MODELS for e in EFFORTS],fontsize=8)
    fig.text(.018,.51,ylabel,rotation=90,va='center',fontsize=12)
    fig.text(.5,.045,'모델 × 추론 수준',ha='center',fontsize=12)
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.075),frameon=False,ncol=2,fontsize=10)
    if metric!='kd_switch':fig.text(.5,.022,'점 위 숫자 = 첫 보고가 있었던 대화 수. 1개인 경우 구간은 표시하지 않음.',ha='center',fontsize=9,color='#536475')
    else:fig.text(.5,.022,'전환이 없었던 대화는 해당 평균의 분모에 들어가지 않음. 개수와 동일 대화 가중 평균은 CSV 참조.',ha='center',fontsize=9,color='#536475')
    return fig

with PdfPages(OUT/'mean_surprisal_plots.pdf') as pdf:
    for metric in METRICS:
        fig=plot(metric);fig.savefig(OUT/(metric+'.png'),dpi=160,facecolor='white');pdf.savefig(fig,facecolor='white');plt.close(fig)
print('PASS 3 plots, 84 condition cells per metric, 23,527 K/D switches, 342 first reports')
print('no-switch conversations',int(sessions.switch_n.eq(0).sum()))
