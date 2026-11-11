"""Plot cumulative surprise from a chronological Bayesian K/D learner."""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
OUT=HERE/'temporal_kd_model'
OUT.mkdir(exist_ok=True)
data=pd.read_csv(OUT/'temporal_kd_rounds.csv.gz').sort_values(['trial_id','round'])
assert len(data)==25200 and data.trial_id.nunique()==2520 and data.first_event.sum()==342
assert data.groupby(['configuration_id','kind','frame']).trial_id.nunique().eq(30).all()
assert data.groupby('trial_id').round.agg(list).apply(lambda x:x==list(range(1,11))).all()
font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11,'pdf.fonttype':42,
                     'axes.spines.top':False,'axes.spines.right':False})
models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
efforts=['low','medium','high']
colors={'obj':'#2878ad','seq':'#e58631'}
handles=[Line2D([0],[0],color=colors['obj'],lw=2,label='obj · 동일 목표'),
         Line2D([0],[0],color=colors['seq'],lw=2,label='seq · 변동 목표'),
         Line2D([0],[0],marker='*',color='none',markerfacecolor='#cf2939',markeredgecolor='white',
                markeredgewidth=.5,markersize=11,label='첫 공동 보고')]

def make(cfg,frame):
    d=data[(data.configuration_id==cfg)&(data.frame==frame)]
    assert d.trial_id.nunique()==60
    fig,ax=plt.subplots(figsize=(13,8.5));fig.subplots_adjust(left=.105,right=.965,bottom=.21,top=.79)
    name='카드' if frame=='cards' else '고양이'
    fig.suptitle(f'{cfg} · {name} | 시간순 K/D 예측의 누적 surprisal',fontsize=18,fontweight='bold',y=.98)
    fig.text(.5,.925,'선 하나 = 독립 대화 하나  ·  빨간 별 = 통제 판단이 처음 바뀐 지점',ha='center',fontsize=11.5)
    fig.text(.5,.895,'60개 대화: obj 30개, seq 30개. 같은 선과 별은 겹쳐 보일 수 있음.',ha='center',fontsize=10.5,color='#4c6073')
    # Interleave obj and seq to reduce one colour systematically covering the other.
    obj=[g for _,g in d[d.kind.eq('obj')].groupby('trial_id',sort=True)]
    seq=[g for _,g in d[d.kind.eq('seq')].groupby('trial_id',sort=True)]
    assert len(obj)==len(seq)==30
    for a,b in zip(obj,seq):
        for g in (a,b):
            ax.plot(g['round'],g.cumulative_surprise_bits,color=colors[g.kind.iloc[0]],
                    linewidth=1.0,alpha=.23,zorder=1)
    ev=d[d.first_event]
    points=ev.assign(display_d=ev.cumulative_surprise_bits.round(6)).groupby(
        ['round','display_d'],as_index=False).size()
    assert int(points['size'].sum())==len(ev)
    ax.scatter(points['round'],points.display_d,marker='*',s=90,c='#cf2939',
               edgecolors='white',linewidths=.45,alpha=.9,zorder=5)
    for _,same_round in points[points['size']>1].groupby('round',sort=True):
        for idx,point in enumerate(same_round.sort_values('display_d').itertuples(index=False)):
            ax.annotate(f'×{point.size}',(point.round,point.display_d),xytext=(5,5+10*idx),
                        textcoords='offset points',fontsize=8,color='#a41f2b',fontweight='bold',
                        bbox={'facecolor':'white','edgecolor':'none','alpha':.75,'pad':.4},zorder=6)
    nobj=int(ev.kind.eq('obj').sum());nseq=int(ev.kind.eq('seq').sum())
    ax.text(.018,.96,f'첫 공동 보고: obj {nobj}/30 · seq {nseq}/30',transform=ax.transAxes,
            ha='left',va='top',fontsize=11,color='#33485a',bbox={'facecolor':'white','edgecolor':'none','alpha':.85})
    ax.set_xlim(.75,10.25);ax.set_ylim(-.5,25.5);ax.set_xticks(range(1,11));ax.set_yticks([0,5,10,15,20,25])
    ax.set_xlabel('라운드',fontsize=12,labelpad=8)
    ax.set_ylabel('누적 D = surprisal 합 (bits)',fontsize=12,labelpad=8)
    ax.grid(color='#d9e1e8',linewidth=.7,alpha=.8,zorder=0)
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.10),ncol=3,frameon=False,fontsize=10)
    fig.text(.5,.035,'별 옆 ×숫자 = 해당 위치에 겹친 전환 수. K/D 예측은 라운드 경계에서 초기화하지 않음.',
             ha='center',fontsize=9.5,color='#52687b')
    return fig

with PdfPages(OUT/'all_42_graphs.pdf') as pdf:
    for model in models:
        for effort in efforts:
            for frame in ['cards','cats']:
                cfg=f'{model}-{effort}';fig=make(cfg,frame)
                fig.savefig(OUT/(cfg+'-'+frame+'.png'),dpi=160,facecolor='white')
                pdf.savefig(fig,facecolor='white');plt.close(fig)
                print(cfg,frame,flush=True)
print('PASS: 42 graphs; 2,520 conversations; 342 first reports')
