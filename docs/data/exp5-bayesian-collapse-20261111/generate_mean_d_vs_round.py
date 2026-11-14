"""Plot mean D versus mean first-report round and show unreported counts.

Means use first joint reports only. Dialogues without a report are right-censored
at round 10 and are displayed separately, never assigned an event at round 10.
All input is the existing temporal K/D reanalysis; no new inference calls.
"""
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.backends.backend_pdf import PdfPages

HERE=Path(__file__).resolve().parent
OUT=HERE/'mean_d_vs_round';OUT.mkdir(exist_ok=True)
data=pd.read_csv(HERE/'temporal_kd_model/temporal_kd_rounds.csv.gz')
assert len(data)==25200 and data.trial_id.nunique()==2520 and data.first_event.sum()==342
assert data.groupby(['configuration_id','frame','kind']).trial_id.nunique().eq(30).all()
assert data.groupby('trial_id').size().eq(10).all()
MODELS=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
EFFORTS=['low','medium','high'];CONFIGS=[f'{m}-{e}' for m in MODELS for e in EFFORTS]
COLORS={'gpt-5.6-luna':'#586f82','gpt-5.6-terra':'#ad6822','gpt-5.6-sol':'#2867a5',
        'gpt-6-luna':'#ae557f','gpt-6-sol':'#688831','gpt-6-astra':'#cc483b','gpt-6.1-sol':'#7850a2'}
MARKERS={'low':'o','medium':'s','high':'^'}

events=data[data.first_event].copy()
assert events.trial_id.is_unique
events=events[['trial_id','case_id','configuration_id','model','effort','frame','kind','round','cumulative_surprise_bits']]
events.to_csv(OUT/'first_report_points.csv',index=False,float_format='%.12g')
cells=data[data['round'].eq(10)][['trial_id','case_id','configuration_id','model','effort','frame','kind']].copy()
cells=cells.merge(events[['trial_id','round','cumulative_surprise_bits']],on='trial_id',how='left',validate='one_to_one')
assert len(cells)==2520 and cells['round'].notna().sum()==342

rows=[]
for (cfg,frame,kind),g in cells.groupby(['configuration_id','frame','kind'],sort=True):
    assert len(g)==30 and g.case_id.nunique()==30
    e=g['round'].notna().to_numpy();n=int(e.sum())
    r=g['round'].fillna(0).to_numpy(float);D=g.cumulative_surprise_bits.fillna(0).to_numpy(float)
    round_mean=float(r[e].mean()) if n else np.nan
    d_mean=float(D[e].mean()) if n else np.nan
    rlo=rhi=dlo=dhi=np.nan
    # For visual restraint and to flag very sparse cells, only draw intervals
    # when >=5 reports. Resample all original case families, including censored.
    if n>=5:
        seed=int.from_bytes(hashlib.sha256(f'{cfg}|{frame}|{kind}'.encode()).digest()[:8],'big')
        idx=np.random.default_rng(seed).integers(0,30,size=(5000,30))
        included=e[idx];denom=included.sum(axis=1);valid=denom>0
        br=(r[idx]*included).sum(axis=1)[valid]/denom[valid]
        bd=(D[idx]*included).sum(axis=1)[valid]/denom[valid]
        rlo,rhi=np.quantile(br,[.025,.975]);dlo,dhi=np.quantile(bd,[.025,.975])
    rows.append(dict(configuration_id=cfg,model=g.model.iloc[0],effort=g.effort.iloc[0],frame=frame,kind=kind,
                     n_total=30,n_report=n,n_no_report=30-n,mean_report_round=round_mean,
                     mean_D_at_first_report=d_mean,round_ci_low=rlo,round_ci_high=rhi,D_ci_low=dlo,D_ci_high=dhi))
summary=pd.DataFrame(rows).sort_values(['frame','kind','configuration_id'])
assert len(summary)==84 and summary.n_report.sum()==342 and summary.n_no_report.sum()==2178
summary.to_csv(OUT/'mean_d_and_round.csv',index=False,float_format='%.12g')

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10,
                     'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})

def scatter():
    fig,axes=plt.subplots(2,2,figsize=(19,13),sharex=True,sharey=True)
    fig.subplots_adjust(left=.08,right=.975,bottom=.13,top=.75,wspace=.13,hspace=.24)
    fig.suptitle('첫 공동 보고의 평균 라운드와 평균 누적 D',fontsize=21,fontweight='bold',y=.98)
    fig.text(.5,.941,'점 하나 = 모델 × 추론 수준 한 조합  ·  점 옆 숫자 = 10라운드 안에 첫 보고한 대화 수 / 30',ha='center',fontsize=11.5)
    fig.text(.5,.916,'평균은 첫 보고가 관찰된 대화에서만 계산. 보고가 없으면 점이 없으며 전환을 10라운드로 간주하지 않음.',ha='center',fontsize=10.5,color='#526478')
    fig.text(.5,.892,'가로·세로선은 각 축의 점별 95% 사례 부트스트랩 구간(n≥5). 동시 신뢰영역이나 차이 검정은 아님.',ha='center',fontsize=10,color='#526478')
    handles=[Line2D([0],[0],marker='o',linestyle='none',markerfacecolor=COLORS[m],markeredgecolor='white',markersize=8,label=m) for m in MODELS]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.87),ncol=7,frameon=False,fontsize=9)
    markerhandles=[Line2D([0],[0],marker=MARKERS[e],linestyle='none',color='#40576b',markersize=7,label=e.upper()) for e in EFFORTS]
    fig.legend(handles=markerhandles,loc='upper center',bbox_to_anchor=(.5,.832),ncol=3,frameon=False,fontsize=9,title='추론 수준',title_fontsize=9)
    panels=[('obj','cards','obj · 카드'),('seq','cards','seq · 카드'),
            ('obj','cats','obj · 고양이'),('seq','cats','seq · 고양이')]
    for ax,(kind,frame,title) in zip(axes.flat,panels):
        s=summary[(summary.kind==kind)&(summary.frame==frame)]
        n_zero=int(s.n_report.eq(0).sum());n_events=int(s.n_report.sum());n_sparse=int(s.n_report.between(1,4).sum())
        ax.set_title(f'{title}  |  첫 보고 {n_events}/630개 대화 · 보고 없는 조합 {n_zero}/21',fontsize=11,fontweight='bold')
        for i,r in enumerate(s.itertuples(index=False)):
            if r.n_report==0:continue
            x,y=r.mean_report_round,r.mean_D_at_first_report;color=COLORS[r.model]
            if pd.notna(r.round_ci_low):
                ax.hlines(y,r.round_ci_low,r.round_ci_high,color=color,alpha=.5,lw=.9,zorder=2)
                ax.vlines(x,r.D_ci_low,r.D_ci_high,color=color,alpha=.5,lw=.9,zorder=2)
            ax.scatter(x,y,s=55,c=color,marker=MARKERS[r.effort],edgecolors='white',linewidths=.55,alpha=.92,zorder=3)
            offset=[(5,5),(5,-9),(-18,5),(-18,-9)][i%4]
            ax.annotate(str(r.n_report),(x,y),xytext=offset,textcoords='offset points',fontsize=8,color=color,
                        bbox={'facecolor':'white','edgecolor':'none','alpha':.65,'pad':.3},zorder=4)
        ax.set_xlim(.8,10.3);ax.set_ylim(-.6,24);ax.set_xticks(range(1,11));ax.set_yticks([0,5,10,15,20]);ax.grid(alpha=.22)
        ax.text(.02,.965,f'보고 1~4개 조합: {n_sparse}개 (구간 미표시)',transform=ax.transAxes,ha='left',va='top',fontsize=8.5,color='#5d7082')
    fig.text(.5,.06,'첫 공동 보고 라운드의 평균',ha='center',fontsize=12)
    fig.text(.018,.46,'첫 공동 보고 시점의 평균 누적 D (bits)',rotation=90,va='center',fontsize=12)
    return fig

def counts():
    fig,axes=plt.subplots(2,2,figsize=(23,13),sharex=True,sharey=True)
    fig.subplots_adjust(left=.07,right=.985,bottom=.19,top=.87,wspace=.08,hspace=.25)
    fig.suptitle('10라운드 안에 첫 공동 보고가 있었던 대화와 없었던 대화',fontsize=20,fontweight='bold',y=.98)
    fig.text(.5,.938,'각 막대 = 해당 조건의 대화 30개  ·  색 = 첫 공동 보고 있음  ·  회색 = 10라운드까지 없음',ha='center',fontsize=11)
    fig.text(.5,.912,'보고가 없는 대화는 10라운드 이후 시점이 알려지지 않은 관측이며, 10라운드에 전환한 것으로 계산하지 않음',ha='center',fontsize=10,color='#526478')
    xs=np.arange(21);panels=[('obj','cards','obj · 카드'),('seq','cards','seq · 카드'),('obj','cats','obj · 고양이'),('seq','cats','seq · 고양이')]
    for ax,(kind,frame,title) in zip(axes.flat,panels):
        s=summary[(summary.kind==kind)&(summary.frame==frame)].set_index('configuration_id').reindex(CONFIGS)
        ns=s.n_report.to_numpy(int);no=s.n_no_report.to_numpy(int)
        colors=[COLORS[m] for m in MODELS for _ in EFFORTS]
        ax.bar(xs,ns,color=colors,width=.72,zorder=2)
        ax.bar(xs,no,bottom=ns,color='#dfe5ea',width=.72,zorder=1)
        for x,n in zip(xs,ns):
            ax.text(x,n+.4 if n else .4,str(n),ha='center',va='bottom',fontsize=6.5,color='#26394a')
        ax.set_title(f'{title}  |  첫 보고 {ns.sum()}/630개 대화',loc='left',fontsize=12,fontweight='bold')
        ax.set_ylim(0,32.8);ax.set_xlim(-.6,20.6);ax.set_yticks([0,10,20,30]);ax.grid(axis='y',alpha=.15,zorder=0)
    axes[-1,0].set_xticks(xs,[f'{m}\n{e}' for m in MODELS for e in EFFORTS],rotation=70,ha='right',fontsize=7)
    axes[-1,1].set_xticks(xs,[f'{m}\n{e}' for m in MODELS for e in EFFORTS],rotation=70,ha='right',fontsize=7)
    fig.text(.018,.48,'대화 수',rotation=90,va='center',fontsize=12)
    fig.text(.5,.035,'모델 × 추론 수준  ·  막대의 숫자 = 첫 보고 대화 수',ha='center',fontsize=11)
    return fig

a=scatter();b=counts()
a.savefig(OUT/'mean_d_vs_mean_round.png',dpi=160,facecolor='white')
b.savefig(OUT/'reported_and_unreported_counts.png',dpi=160,facecolor='white')
with PdfPages(OUT/'mean_d_vs_round_and_counts.pdf') as pdf:
    pdf.savefig(a,facecolor='white');pdf.savefig(b,facecolor='white')
plt.close('all')
print('PASS: 84 cells, 342 first reports, 2,178 without first report, 2,520 total conversations')
print('empty cells',int(summary.n_report.eq(0).sum()),'sparse cells (1-4)',int(summary.n_report.between(1,4).sum()))
