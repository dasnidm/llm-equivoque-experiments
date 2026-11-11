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

out=Path(__file__).resolve().parent
df=pd.read_csv(out/'bayesian_posterior_by_round.csv')
events=df[df.joint.eq(1)&~df.previously_joint].copy()
expected=df.groupby('trial_id').joint.max().sum()
assert len(events)==expected==342
assert events.trial_id.is_unique
events['prob_percent']=100*events.p_forced
events['condition']=events.kind
events.to_csv(out/'collapse_points.csv',index=False)

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,
 'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
efforts=['low','medium','high']
colors={'obj':'#2475ac','seq':'#e0782d'}
shapes={'cards':'o','cats':'^'}
leg=[Line2D([0],[0],marker='o',color='w',label='obj: 동일 목표',markerfacecolor=colors['obj'],markersize=8),
     Line2D([0],[0],marker='o',color='w',label='seq: 변동 목표',markerfacecolor=colors['seq'],markersize=8),
     Line2D([0],[0],marker='o',color='#555',label='카드',linestyle='none',markersize=6),
     Line2D([0],[0],marker='^',color='#555',label='고양이',linestyle='none',markersize=6)]

def x_jitter(s):
    v=int.from_bytes(hashlib.sha256(s.encode()).digest()[:4],'big')/(2**32-1)
    return (v-.5)*.40

def plot(ax,cfg,zoom=False):
    x=events[events.configuration_id==cfg]
    for (kind,frame),v in x.groupby(['kind','frame']):
        offset=np.array([x_jitter(s) for s in v.trial_id])
        ax.scatter(v['round']+offset,v.prob_percent,s=26,alpha=.65,
                   marker=shapes[frame],facecolors=colors[kind],edgecolors='white',linewidths=.25)
    ax.set_xlim(.5,10.5);ax.set_xticks([1,3,5,7,10]);ax.grid(axis='y',alpha=.2)
    if zoom: ax.set_ylim(90,100.5);ax.set_yticks([90,95,100])
    else: ax.set_ylim(0,103);ax.set_yticks([0,25,50,75,100])
    a=int(x.kind.eq('obj').sum());b=int(x.kind.eq('seq').sum())
    ax.text(.03,.07,f'obj {a}건  |  seq {b}건',transform=ax.transAxes,fontsize=9,color='#34475a')
    if not len(x): ax.text(.5,.52,'전환 없음',transform=ax.transAxes,ha='center',va='center',color='#7b8794',fontsize=12)

def make(zoom=False):
    fig,axs=plt.subplots(7,3,figsize=(16,25),sharex=True,sharey=True)
    fig.subplots_adjust(left=.13,right=.98,bottom=.055,top=.895,wspace=.12,hspace=.32)
    fig.suptitle('통제 판단이 처음 바뀐 시점의 강제 확률'+('  |  90–100% 확대' if zoom else ''),fontsize=20,fontweight='bold',y=.985)
    fig.text(.5,.957,'각 점 = 독립 대화 1개  ·  x축 = 첫 전환 라운드  ·  y축 = 베이지안 모델의 강제 확률',ha='center',fontsize=12)
    fig.text(.5,.938,'확률은 두 강제 가설의 합. 점 위치는 겹침을 줄이기 위해 라운드 축에서만 미세하게 이동.',ha='center',fontsize=10,color='#536475')
    if zoom: fig.text(.5,.92,'확대 그림은 90% 미만인 점을 표시하지 않음. 건수는 전체 전환 건수.',ha='center',fontsize=10,color='#9b4b21')
    for row,model in enumerate(models):
        for col,effort in enumerate(efforts):
            cfg=f'{model}-{effort}';ax=axs[row,col];plot(ax,cfg,zoom)
            if row==0: ax.set_title(effort.upper(),fontsize=13,fontweight='bold',pad=9)
            if col==0: ax.text(-.25,.5,model,transform=ax.transAxes,rotation=90,ha='center',va='center',fontsize=12,fontweight='bold')
    fig.text(.008,.5,'모델이 계산한 강제 확률 (%)',rotation=90,va='center',fontsize=13)
    fig.text(.5,.026,'처음 통제 판단이 바뀐 라운드',ha='center',fontsize=13)
    fig.legend(handles=leg,loc='lower center',ncol=4,bbox_to_anchor=(.5,.003),frameon=False,fontsize=10)
    return fig

full=make(False);full.savefig(out/'collapse_all.png',dpi=180,facecolor='white')
zoom=make(True);zoom.savefig(out/'collapse_zoom.png',dpi=180,facecolor='white')
with PdfPages(out/'collapse_plots.pdf') as pdf:
    pdf.savefig(full,facecolor='white');pdf.savefig(zoom,facecolor='white')
plt.close('all')
print('events',len(events),'obj',events.kind.eq('obj').sum(),'seq',events.kind.eq('seq').sum())
print('under_90',int(events.prob_percent.lt(90).sum()))
print('output',out)
