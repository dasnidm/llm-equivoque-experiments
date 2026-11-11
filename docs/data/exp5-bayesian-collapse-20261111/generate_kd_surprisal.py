"""One Beta(1,1) K/D learner per conversation; plot round surprisal in bits."""
from pathlib import Path
import gzip
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables'
OUT=HERE/'kd_surprisal'
OUT.mkdir(exist_ok=True)
choice=pd.read_csv(BASE/'choices.csv')
ratings=pd.read_csv(BASE/'measurements.csv')
assert choice.groupby(['trial_id','round']).size().eq(2).all()
assert choice.groupby(['trial_id','round']).route.nunique().eq(1).all()
first=choice[choice.stage.eq(1)][['trial_id','round','route']]
df=ratings.merge(first,on=['trial_id','round'],validate='one_to_one').sort_values(['trial_id','round'])
assert len(df)==25200 and df.trial_id.nunique()==2520
assert df.groupby('trial_id').round.agg(list).apply(lambda x:x==list(range(1,11))).all()
assert df.route.str.fullmatch('[KD]{2}').all()

records=[]
for _,g in df.groupby('trial_id',sort=False):
    # One stream in temporal order: r1 stage1, r1 stage2, r2 stage1, ...
    k=d=0;seen=False
    for r in g.itertuples(index=False):
        k_before,d_before=k,d
        pks=[];pobs=[]
        for symbol in r.route:
            pk=(1+k)/(2+k+d)
            pks.append(pk)
            pobs.append(pk if symbol=='K' else 1-pk)
            if symbol=='K': k+=1
            else: d+=1
        s1,s2=-np.log2(pobs)
        records.append(dict(trial_id=r.trial_id,case_id=r.case_id,
            configuration_id=r.configuration_id,kind=r.kind,frame=r.frame,
            round=r.round,route=r.route,k_before=k_before,d_before=d_before,
            p_k_first=pks[0],p_first_observed=pobs[0],
            p_k_second=pks[1],p_second_observed=pobs[1],
            p_route=pobs[0]*pobs[1],surprisal_first_bits=s1,
            surprisal_second_bits=s2,surprisal_round_bits=s1+s2,
            joint=int(r.joint),first_event=bool(r.joint) and not seen))
        seen=seen or bool(r.joint)
data=pd.DataFrame(records)
assert data.first_event.sum()==342
assert data.surprisal_round_bits.ge(0).all()
assert data.groupby(['configuration_id','kind','frame']).trial_id.nunique().eq(30).all()

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,
                     'font.size':11,'axes.spines.top':False,'axes.spines.right':False,
                     'pdf.fonttype':42})
models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
efforts=['low','medium','high']
colors={'KK':'#1f77b4','KD':'#ea832d','DK':'#7852ad','DD':'#119879'}
handles=[Line2D([0],[0],color=c,lw=3,label=k) for k,c in colors.items()]
handles.append(Line2D([0],[0],marker='*',color='none',markerfacecolor='#cf2939',
                      markeredgecolor='white',markeredgewidth=.45,markersize=12,label='최초 공동 보고'))
max_y=np.ceil(data.surprisal_round_bits.max())

def make(cfg):
    d=data[data.configuration_id==cfg]
    assert d.trial_id.nunique()==120
    fig,axs=plt.subplots(2,2,figsize=(15,10),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.98,top=.78,bottom=.13,wspace=.12,hspace=.27)
    fig.suptitle(f'{cfg}  |  K/D 예측 위반과 통제 판단',y=.975,fontsize=20,fontweight='bold')
    fig.text(.5,.927,'선 하나 = 독립 대화 하나  ·  선 색 = 해당 라운드의 K/D  ·  ★ = 최초 통제 판단 전환',ha='center',fontsize=12)
    fig.text(.5,.895,'Y축은 그 라운드의 K/D 두 피드백에 대한 surprisal 합(bits). 높을수록 모델의 예상에서 벗어남.',ha='center',fontsize=10.5,color='#4c6073')
    fig.text(.5,.866,'대화마다 K/D를 50:50으로 시작해 발생 순서대로 갱신. 같은 궤적의 선과 별은 겹칠 수 있음.',ha='center',fontsize=10,color='#4c6073')
    panels=[('obj','cards','obj · 카드'),('obj','cats','obj · 고양이'),
            ('seq','cards','seq · 카드'),('seq','cats','seq · 고양이')]
    for ax,(kind,frame,label) in zip(axs.flat,panels):
        sub=d[(d.kind==kind)&(d.frame==frame)]
        for _,g in sub.groupby('trial_id',sort=False):
            y=g.surprisal_round_bits.to_numpy();x=g['round'].to_numpy();route=g.route.to_numpy()
            points=np.column_stack([x,y]);segments=np.stack((points[:-1],points[1:]),axis=1)
            ax.add_collection(LineCollection(segments,colors=[colors[s] for s in route[1:]],linewidths=1,alpha=.27))
            ax.scatter(x[0],y[0],s=8,c=colors[route[0]],alpha=.32,zorder=2)
        ev=sub[sub.first_event]
        ax.scatter(ev['round'],ev.surprisal_round_bits,s=125,marker='*',c='#cf2939',
                   edgecolors='white',linewidths=.5,zorder=5)
        ax.set(title=f'{label}  |  30개 대화 · 첫 전환 {len(ev)}개',xlim=(.75,10.25),ylim=(-.1,max_y+.3),xticks=range(1,11))
        ax.grid(color='#d9e1e8',linewidth=.7,alpha=.7,zorder=0)
    fig.text(.025,.48,'라운드별 surprisal 합 (bits)',rotation=90,fontsize=13,va='center')
    fig.text(.5,.08,'라운드',fontsize=13,ha='center')
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.025),ncol=5,frameon=False,fontsize=11)
    return fig

with (OUT/'kd_surprisal.csv.gz').open('wb') as file:
    with gzip.GzipFile(filename='',mode='wb',fileobj=file,mtime=0) as gz:
        gz.write(data.to_csv(index=False,lineterminator='\n').encode())
with PdfPages(OUT/'all_21_configurations.pdf') as pdf:
    for model in models:
        for effort in efforts:
            cfg=f'{model}-{effort}';fig=make(cfg)
            fig.savefig(OUT/(cfg+'.png'),dpi=150,facecolor='white')
            pdf.savefig(fig,facecolor='white');plt.close(fig);print(cfg,flush=True)
print('done 21 figures; observations',len(data),'first events',int(data.first_event.sum()),'global y max',max_y)
for kind in ['obj','seq']:
    sub=data[data.kind.eq(kind)]
    print(kind,'median event',sub.loc[sub.first_event,'surprisal_round_bits'].median(),
          'median no event',sub.loc[~sub.first_event,'surprisal_round_bits'].median())
