"""Compare first-report and not-yet-report dialogues with aligned time.

The round-10 retrospective comparison contains D after earlier reports; the
within-round risk-set comparison only includes dialogues without an earlier
report. CIs are descriptive case-family bootstrap intervals.
"""
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
OUT=HERE/'no_report_comparison';OUT.mkdir(exist_ok=True)
data=pd.read_csv(HERE/'temporal_kd_model/temporal_kd_rounds.csv.gz').sort_values(['trial_id','round'])
assert len(data)==25200 and data.trial_id.nunique()==2520 and data.first_event.sum()==342
assert data.groupby(['configuration_id','frame','kind']).trial_id.nunique().eq(30).all()
assert data.groupby('trial_id').round.agg(list).apply(lambda x:x==list(range(1,11))).all()
ever=data.groupby('trial_id').first_event.max().rename('ever_first_event')
data=data.join(ever,on='trial_id',validate='many_to_one')
assert ever.sum()==342
MODELS=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
EFFORTS=['low','medium','high'];CONFIGS=[f'{m}-{e}' for m in MODELS for e in EFFORTS]
COLORS={'obj':'#246ea5','seq':'#df8126'}

def summarize(group,mask,key):
    """Group contains the original 30 case families, including excluded ones."""
    assert len(group)==30 and group.case_id.nunique()==30
    vals=group.cumulative_surprise_bits.to_numpy(float);select=np.asarray(mask,bool)
    n=int(select.sum());mean=float(vals[select].mean()) if n else np.nan
    lo=hi=np.nan
    if n>=2:
        seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big')
        idx=np.random.default_rng(seed).integers(0,30,size=(3000,30))
        chosen=select[idx];denom=chosen.sum(axis=1)
        numer=(vals[idx]*chosen).sum(axis=1)
        draws=numer[denom>0]/denom[denom>0]
        lo,hi=np.quantile(draws,[.025,.975])
    return {'n':n,'mean':mean,'ci_low':lo,'ci_high':hi}

round10=data[data['round'].eq(10)]
summary10=[]
for (cfg,frame,kind),g in round10.groupby(['configuration_id','frame','kind']):
    for status in ['reported_by_10','not_reported_by_10']:
        mask=g.ever_first_event if status=='reported_by_10' else ~g.ever_first_event
        summary10.append(dict(configuration_id=cfg,model=g.model.iloc[0],effort=g.effort.iloc[0],
            frame=frame,kind=kind,status=status,**summarize(g,mask,f'10|{cfg}|{frame}|{kind}|{status}')))
summary10=pd.DataFrame(summary10)
assert len(summary10)==168 and summary10.n.sum()==2520
assert summary10[summary10.status.eq('reported_by_10')].n.sum()==342
summary10.to_csv(OUT/'round10_report_vs_no.csv',index=False,float_format='%.12g')

risk_summary=[]
for (cfg,frame,kind,round_no),g in data.groupby(['configuration_id','frame','kind','round']):
    eligible=~g.already_event
    for status in ['first_report_now','not_yet_after_round']:
        mask=eligible & (g.first_event if status=='first_report_now' else ~g.first_event)
        risk_summary.append(dict(configuration_id=cfg,model=g.model.iloc[0],effort=g.effort.iloc[0],
            frame=frame,kind=kind,round=round_no,status=status,
            **summarize(g,mask,f'risk|{cfg}|{frame}|{kind}|{round_no}|{status}')))
risk_summary=pd.DataFrame(risk_summary)
assert len(risk_summary)==21*2*2*10*2
assert risk_summary[risk_summary.status.eq('first_report_now')].n.sum()==342
assert risk_summary[risk_summary.status.eq('not_yet_after_round')].n.sum()==23315
risk_summary.to_csv(OUT/'same_round_risk_sets.csv',index=False,float_format='%.12g')

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10,'pdf.fonttype':42,
                     'axes.spines.top':False,'axes.spines.right':False})

def plot10():
    fig,axs=plt.subplots(2,1,figsize=(25,12),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.985,bottom=.20,top=.865,hspace=.25)
    fig.suptitle('10라운드의 누적 D: 보고가 있었던 대화와 없었던 대화',fontsize=21,fontweight='bold',y=.98)
    fig.text(.5,.936,'모든 점은 같은 10라운드 값  ·  채운 점 = 10라운드 안에 첫 공동 보고  ·  빈 점 = 10라운드까지 보고 없음',ha='center',fontsize=11.5)
    fig.text(.5,.914,'보고가 있었던 대화는 보고 이후의 K/D도 포함하므로, 이 그림만으로 전환을 예측하거나 원인을 판단할 수 없음',ha='center',fontsize=10.5,color='#516478')
    offsets={('obj','reported_by_10'):-.27,('obj','not_reported_by_10'):-.09,
             ('seq','reported_by_10'):.09,('seq','not_reported_by_10'):.27}
    xs=np.arange(21)
    for ax,frame,label in zip(axs,['cards','cats'],['카드','고양이']):
        for i in range(7):
            if i%2==0:ax.axvspan(i*3-.5,i*3+2.5,color='#f4f7fa',zorder=0)
        for kind in ['obj','seq']:
            for status in ['reported_by_10','not_reported_by_10']:
                cells=summary10[(summary10.frame==frame)&(summary10.kind==kind)&(summary10.status==status)].set_index('configuration_id').reindex(CONFIGS)
                for x,(_,r) in zip(xs+offsets[(kind,status)],cells.iterrows()):
                    if pd.isna(r['mean']):continue
                    if pd.notna(r.ci_low) and pd.notna(r.ci_high):ax.vlines(x,r.ci_low,r.ci_high,color=COLORS[kind],alpha=.45,linewidth=.8,zorder=2)
                    filled=status=='reported_by_10'
                    ax.scatter(x,r['mean'],s=32,edgecolors=COLORS[kind],facecolors=COLORS[kind] if filled else 'white',linewidths=1.2,zorder=3)
                    if filled:ax.annotate(str(int(r.n)),(x,r['mean']),xytext=(0,5),textcoords='offset points',ha='center',fontsize=6.5,color=COLORS[kind])
        ax.set_title(label,loc='left',fontsize=14,fontweight='bold',pad=5)
        ax.set_ylim(0,25);ax.set_xlim(-.6,20.6);ax.grid(axis='y',alpha=.22)
    axs[-1].set_xticks(xs,[f'{m}\n{e}' for m in MODELS for e in EFFORTS],fontsize=8)
    fig.text(.018,.50,'10라운드의 평균 누적 D (bits)',rotation=90,va='center',fontsize=12)
    handles=[Line2D([0],[0],marker='o',color='none',markerfacecolor=COLORS['obj'],markeredgecolor=COLORS['obj'],label='obj · 보고 있음'),
             Line2D([0],[0],marker='o',color='none',markerfacecolor='white',markeredgecolor=COLORS['obj'],label='obj · 보고 없음'),
             Line2D([0],[0],marker='o',color='none',markerfacecolor=COLORS['seq'],markeredgecolor=COLORS['seq'],label='seq · 보고 있음'),
             Line2D([0],[0],marker='o',color='none',markerfacecolor='white',markeredgecolor=COLORS['seq'],label='seq · 보고 없음')]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.075),frameon=False,ncol=4,fontsize=10)
    fig.text(.5,.045,'모델 × 추론 수준',ha='center',fontsize=12)
    fig.text(.5,.021,'보고 있음 점의 숫자 = 대화 수. 각 조건은 30개 대화. 세로선 = 사례 패밀리 95% 점별 부트스트랩 구간.',ha='center',fontsize=9,color='#536475')
    return fig

def plot_risk(cfg):
    sub=risk_summary[risk_summary.configuration_id.eq(cfg)]
    fig,axes=plt.subplots(2,2,figsize=(15,10),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.98,top=.78,bottom=.13,wspace=.12,hspace=.28)
    fig.suptitle(f'{cfg} | 같은 라운드에서 보고 여부별 평균 D',y=.975,fontsize=19,fontweight='bold')
    fig.text(.5,.927,'이전 라운드까지 첫 공동 보고가 없었던 대화만 포함  ·  점 위 숫자 = 해당 라운드 첫 보고 대화 수',ha='center',fontsize=11)
    fig.text(.5,.895,'전환하지 않은 대화도 파란 선에 포함하며, 이후 첫 보고가 나오면 그다음 라운드부터 제외',ha='center',fontsize=10.5,color='#4c6073')
    fig.text(.5,.866,'D는 해당 라운드 K/D 피드백을 본 후, 통제 질문에 답하기 전 계산. 선과 구간은 기술적 비교임.',ha='center',fontsize=10,color='#4c6073')
    panels=[('obj','cards','obj · 카드'),('obj','cats','obj · 고양이'),('seq','cards','seq · 카드'),('seq','cats','seq · 고양이')]
    for ax,(kind,frame,label) in zip(axes.flat,panels):
        z=sub[(sub.kind==kind)&(sub.frame==frame)]
        none=z[z.status.eq('not_yet_after_round')].sort_values('round');ev=z[z.status.eq('first_report_now')].sort_values('round')
        ax.plot(none['round'],none['mean'],color='#2878ad',lw=1.8,marker='o',markersize=3,zorder=3)
        finite=none.ci_low.notna()&none.ci_high.notna()
        if finite.any():ax.fill_between(none['round'].to_numpy(),none.ci_low.to_numpy(),none.ci_high.to_numpy(),color='#2878ad',alpha=.12,zorder=1)
        for r in ev.itertuples(index=False):
            if r.n==0:continue
            if pd.notna(r.ci_low) and pd.notna(r.ci_high):ax.vlines(r.round,r.ci_low,r.ci_high,color='#cf2939',alpha=.55,lw=1,zorder=2)
            ax.scatter(r.round,r.mean,color='#cf2939',marker='*',s=90,edgecolors='white',linewidths=.4,zorder=4)
            ax.annotate(str(r.n),(r.round,r.mean),xytext=(5,5),textcoords='offset points',fontsize=8,color='#ad2331')
        count=int(ev.n.sum());ax.set_title(f'{label}  |  총 30개 대화 · 10라운드 내 첫 보고 {count}개',fontsize=11)
        ax.set_xlim(.75,10.25);ax.set_ylim(-.5,25.5);ax.set_xticks(range(1,11));ax.set_yticks([0,5,10,15,20,25])
        ax.grid(color='#d9e1e8',linewidth=.7,alpha=.7,zorder=0)
    fig.text(.025,.48,'같은 라운드의 평균 누적 D (bits)',rotation=90,fontsize=12,va='center')
    fig.text(.5,.075,'라운드',fontsize=12,ha='center')
    handles=[Line2D([0],[0],color='#2878ad',lw=2,marker='o',markersize=4,label='아직 첫 보고 없음'),
             Line2D([0],[0],marker='*',color='none',markerfacecolor='#cf2939',markersize=11,label='해당 라운드 첫 보고')]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.025),ncol=2,frameon=False,fontsize=10)
    return fig

fig=plot10();fig.savefig(OUT/'round10_report_vs_no.png',dpi=160,facecolor='white')
with PdfPages(OUT/'round10_report_vs_no.pdf') as pdf:pdf.savefig(fig,facecolor='white')
plt.close(fig)
with PdfPages(OUT/'same_round_all_21.pdf') as pdf:
    for cfg in CONFIGS:
        fig=plot_risk(cfg);fig.savefig(OUT/(cfg+'-same-round.png'),dpi=150,facecolor='white');pdf.savefig(fig,facecolor='white');plt.close(fig)
        print(cfg,flush=True)
print('PASS: 2,520 dialogues; 342 first reports; 2,178 without first report; 21 configurations')
