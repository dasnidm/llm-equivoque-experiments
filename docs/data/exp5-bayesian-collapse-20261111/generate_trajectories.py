"""Plot all experiment-5 conversations: per-round K/D, posterior, first event."""
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
OUT=HERE/'trajectories'
OUT.mkdir(exist_ok=True)
data=pd.read_csv(HERE/'bayesian_posterior_by_round.csv').sort_values(['trial_id','round'])
assert len(data)==25200 and data.trial_id.nunique()==2520
assert data.groupby('trial_id').round.agg(list).apply(lambda x:x==list(range(1,11))).all()
assert data.route.str.fullmatch('[KD]{2}').all()
data['first_event']=data.joint.eq(1)&~data.previously_joint
assert data.first_event.sum()==342
models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
efforts=['low','medium','high']
colors={'KK':'#1f77b4','KD':'#ea832d','DK':'#7852ad','DD':'#119879'}
font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,
                     'font.size':11,'axes.spines.top':False,'axes.spines.right':False,
                     'pdf.fonttype':42})
route_handles=[Line2D([0],[0],color=c,lw=3,label=k) for k,c in colors.items()]
route_handles.append(Line2D([0],[0],marker='*',color='none',markerfacecolor='#cf2939',
                            markeredgecolor='white',markeredgewidth=.45,markersize=12,label='최초 공동 보고'))

def make_figure(cfg):
    d=data[data.configuration_id==cfg]
    assert d.trial_id.nunique()==120
    fig,axs=plt.subplots(2,2,figsize=(15,10),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.98,top=.78,bottom=.13,wspace=.12,hspace=.27)
    fig.suptitle(f'{cfg}  |  대화별 확률 변화와 K/D 경로',y=.975,fontsize=20,fontweight='bold')
    fig.text(.5,.927,'선 하나 = 독립 대화 하나  ·  선 색 = 해당 라운드의 K/D  ·  ★ = 최초 통제 판단 전환',ha='center',fontsize=12)
    fig.text(.5,.895,'Y축은 임시 베이지안 모델이 계산한 강제 확률. 관측된 LLM의 내적 확신이나 답변 전환 확률은 아님.',ha='center',fontsize=10.5,color='#4c6073')
    fig.text(.5,.866,'K/D 색은 해당 라운드의 첫 단계와 둘째 단계 순서. 같은 궤적이 겹치면 선과 별도 겹쳐 보일 수 있음.',ha='center',fontsize=10,color='#4c6073')
    panels=[('obj','cards','obj · 카드'),('obj','cats','obj · 고양이'),
            ('seq','cards','seq · 카드'),('seq','cats','seq · 고양이')]
    for ax,(kind,frame,label) in zip(axs.flat,panels):
        sub=d[(d.kind==kind)&(d.frame==frame)]
        assert sub.trial_id.nunique()==30
        for _,g in sub.groupby('trial_id',sort=False):
            p=100*g.p_forced.to_numpy(); x=g['round'].to_numpy(); route=g.route.to_numpy()
            points=np.column_stack([x,p])
            segments=np.stack((points[:-1],points[1:]),axis=1)
            ax.add_collection(LineCollection(segments,colors=[colors[s] for s in route[1:]],
                                             linewidths=1.0,alpha=.26))
            ax.scatter(x[0],p[0],s=8,c=colors[route[0]],alpha=.3,zorder=2)
        ev=sub[sub.first_event]
        ax.scatter(ev['round'],100*ev.p_forced,s=125,marker='*',c='#cf2939',
                   edgecolors='white',linewidths=.5,zorder=5)
        ax.set(title=f'{label}  |  30개 대화 · 첫 전환 {len(ev)}개',xlim=(.75,10.25),ylim=(-2,104),
               xticks=range(1,11),yticks=[0,20,40,60,80,100])
        ax.grid(color='#d9e1e8',linewidth=.7,alpha=.7,zorder=0)
    fig.text(.025,.48,'강제 확률 (%)',rotation=90,fontsize=13,va='center')
    fig.text(.5,.08,'라운드',fontsize=13,ha='center')
    fig.legend(handles=route_handles,loc='lower center',bbox_to_anchor=(.5,.025),ncol=5,frameon=False,fontsize=11)
    return fig

cols=['trial_id','case_id','configuration_id','frame','kind','round','route','p_obj','p_seq','p_stable','p_forced','joint','first_event']
with gzip.GzipFile(filename='',mode='wb',fileobj=(OUT/'trajectories.csv.gz').open('wb'),mtime=0) as gz:
    gz.write(data[cols].to_csv(index=False,lineterminator='\n').encode())

with PdfPages(OUT/'all_21_configurations.pdf') as pdf:
    for model in models:
        for effort in efforts:
            cfg=f'{model}-{effort}'
            fig=make_figure(cfg)
            fig.savefig(OUT/(cfg+'.png'),dpi=150,facecolor='white')
            pdf.savefig(fig,facecolor='white')
            plt.close(fig)
            print(cfg,flush=True)

print('done:',len(models)*len(efforts),'figures',len(data),'rounds')
