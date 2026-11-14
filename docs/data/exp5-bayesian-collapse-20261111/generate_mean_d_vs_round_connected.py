"""Connect low/medium/high points within each model and condition.

Reads the existing published cell summary; the means and intervals are not
recomputed. Missing neighbouring effort levels break the line. No model calls.
"""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
OUT=HERE/'mean_d_vs_round'
summary=pd.read_csv(OUT/'mean_d_and_round.csv')
assert len(summary)==84 and summary.n_report.sum()==342 and summary.n_no_report.sum()==2178
MODELS=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
EFFORTS=['low','medium','high']
COLORS={'gpt-5.6-luna':'#586f82','gpt-5.6-terra':'#ad6822','gpt-5.6-sol':'#2867a5',
        'gpt-6-luna':'#ae557f','gpt-6-sol':'#688831','gpt-6-astra':'#cc483b','gpt-6.1-sol':'#7850a2'}
MARKERS={'low':'o','medium':'s','high':'^'}
font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10,
                     'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})

fig,axes=plt.subplots(2,2,figsize=(19,13),sharex=True,sharey=True)
fig.subplots_adjust(left=.08,right=.975,bottom=.13,top=.75,wspace=.13,hspace=.24)
fig.suptitle('첫 공동 보고의 평균 라운드와 평균 누적 D',fontsize=21,fontweight='bold',y=.98)
fig.text(.5,.941,'같은 색의 선 = 같은 모델의 LOW → MEDIUM → HIGH  ·  점 옆 숫자 = 첫 보고가 나온 대화 수 / 30',ha='center',fontsize=11.5)
fig.text(.5,.916,'보고가 없었던 수준은 점과 선을 비움. 각 점은 서로 다른 대화의 평균이며, 선은 인과효과나 개인의 변화가 아님.',ha='center',fontsize=10.5,color='#526478')
fig.text(.5,.892,'가로·세로선은 각 축의 점별 95% 사례 부트스트랩 구간(n≥5). 동시 신뢰영역이나 차이 검정은 아님.',ha='center',fontsize=10,color='#526478')
handles=[Line2D([0],[0],color=COLORS[m],marker='o',linestyle='-',markeredgecolor='white',markersize=8,label=m) for m in MODELS]
fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.87),ncol=7,frameon=False,fontsize=9)
markerhandles=[Line2D([0],[0],marker=MARKERS[e],linestyle='none',color='#40576b',markersize=7,label=e.upper()) for e in EFFORTS]
fig.legend(handles=markerhandles,loc='upper center',bbox_to_anchor=(.5,.832),ncol=3,frameon=False,fontsize=9,title='추론 수준',title_fontsize=9)

edges=[]
panels=[('obj','cards','obj · 카드'),('seq','cards','seq · 카드'),
        ('obj','cats','obj · 고양이'),('seq','cats','seq · 고양이')]
for ax,(kind,frame,title) in zip(axes.flat,panels):
    s=summary[(summary.kind==kind)&(summary.frame==frame)]
    n_zero=int(s.n_report.eq(0).sum());n_events=int(s.n_report.sum());n_sparse=int(s.n_report.between(1,4).sum())
    ax.set_title(f'{title}  |  첫 보고 {n_events}/630개 대화 · 보고 없는 조합 {n_zero}/21',fontsize=11,fontweight='bold')
    for model in MODELS:
        pair=s[s.model.eq(model)].set_index('effort').reindex(EFFORTS)
        for start,end in zip(EFFORTS[:-1],EFFORTS[1:]):
            a,b=pair.loc[start],pair.loc[end]
            drawn=bool(a.n_report>0 and b.n_report>0)
            edges.append(dict(model=model,frame=frame,kind=kind,start=start,end=end,
                              n_start=int(a.n_report),n_end=int(b.n_report),drawn=drawn))
            if drawn:
                ax.plot([a.mean_report_round,b.mean_report_round],[a.mean_D_at_first_report,b.mean_D_at_first_report],
                        color=COLORS[model],lw=1.5,alpha=.7,zorder=1)
    for i,r in enumerate(s.itertuples(index=False)):
        if r.n_report==0:continue
        x,y=r.mean_report_round,r.mean_D_at_first_report;color=COLORS[r.model]
        if pd.notna(r.round_ci_low):
            ax.hlines(y,r.round_ci_low,r.round_ci_high,color=color,alpha=.4,lw=.9,zorder=2)
            ax.vlines(x,r.D_ci_low,r.D_ci_high,color=color,alpha=.4,lw=.9,zorder=2)
        ax.scatter(x,y,s=55,c=color,marker=MARKERS[r.effort],edgecolors='white',linewidths=.55,alpha=.95,zorder=3)
        offset=[(5,5),(5,-9),(-18,5),(-18,-9)][i%4]
        ax.annotate(str(r.n_report),(x,y),xytext=offset,textcoords='offset points',fontsize=8,color=color,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.65,'pad':.3},zorder=4)
    ax.set_xlim(.8,10.3);ax.set_ylim(-.6,24);ax.set_xticks(range(1,11));ax.set_yticks([0,5,10,15,20]);ax.grid(alpha=.22)
    ax.text(.02,.965,f'보고 1~4개 조합: {n_sparse}개 (구간 미표시)',transform=ax.transAxes,ha='left',va='top',fontsize=8.5,color='#5d7082')
fig.text(.5,.06,'첫 공동 보고 라운드의 평균',ha='center',fontsize=12)
fig.text(.018,.46,'첫 공동 보고 시점의 평균 누적 D (bits)',rotation=90,va='center',fontsize=12)
fig.savefig(OUT/'mean_d_vs_mean_round_connected.png',dpi=160,facecolor='white')
fig.savefig(OUT/'mean_d_vs_mean_round_connected.pdf',facecolor='white')
plt.close(fig)
edge_df=pd.DataFrame(edges)
assert len(edge_df)==56 and ((edge_df.n_start>0)&(edge_df.n_end>0)).equals(edge_df.drawn)
edge_df.to_csv(OUT/'connected_edges.csv',index=False)
print('PASS: 84 existing cells unchanged; 56 potential adjacent-effort links;',int(edge_df.drawn.sum()),'shown')
