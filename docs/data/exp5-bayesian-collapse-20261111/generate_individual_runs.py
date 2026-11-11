"""Render one K/D-surprisal line chart per independent experiment-5 dialogue."""
from pathlib import Path
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color

HERE=Path(__file__).resolve().parent
OUT=HERE/'individual_runs'
OUT.mkdir(exist_ok=True)
data=pd.read_csv(HERE/'kd_surprisal/kd_surprisal.csv.gz').sort_values(['trial_id','round'])
assert len(data)==25200 and data.trial_id.nunique()==2520 and data.first_event.sum()==342
models=['gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-6.1-sol']
efforts=['low','medium','high']
conditions=[('obj','cards'),('obj','cats'),('seq','cards'),('seq','cats')]
blue=HexColor('#2878ad');red=HexColor('#cc2936');grid=HexColor('#d8e1e9');ink=HexColor('#293b4b')
width,height=1080,1440
YMAX=7.0

def star(c,cx,cy,outer=6,inner=2.5):
    path=c.beginPath()
    for i in range(10):
        r=outer if i%2==0 else inner
        angle=math.pi/2+math.pi*i/5
        x,y=cx+r*math.cos(angle),cy+r*math.sin(angle)
        if i==0:path.moveTo(x,y)
        else:path.lineTo(x,y)
    path.close()
    c.setFillColor(red);c.setStrokeColor(HexColor('#ffffff'));c.setLineWidth(.5)
    c.drawPath(path,stroke=1,fill=1)

def panel(c,g,x0,y0,w,h):
    ybase=y0+36; ytop=y0+h-25; left=x0+42;right=x0+w-13
    c.setFillColor(ink);c.setFont('Helvetica-Bold',10)
    event=g[g.first_event]
    caption='first transition: round '+str(int(event['round'].iloc[0])) if len(event) else 'no transition by round 10'
    c.drawString(x0+2,y0+h-12,f"{g.case_id.iloc[0]}  |  {caption}")
    c.setLineWidth(.4);c.setStrokeColor(grid);c.setFillColor(ink);c.setFont('Helvetica',7)
    for tick in [0,2,4,6]:
        y=ybase+(ytop-ybase)*tick/YMAX;c.line(left,y,right,y);c.drawRightString(left-5,y-2,str(tick))
    xs=np.linspace(left,right,10)
    yy=ybase+(ytop-ybase)*g.surprisal_round_bits.to_numpy()/YMAX
    c.setStrokeColor(blue);c.setLineWidth(1.3);path=c.beginPath();path.moveTo(xs[0],yy[0])
    for x,y in zip(xs[1:],yy[1:]):path.lineTo(x,y)
    c.drawPath(path,stroke=1,fill=0);c.setFillColor(blue)
    for x,y in zip(xs,yy):c.circle(x,y,1.6,fill=1,stroke=0)
    for x,y,is_event in zip(xs,yy,g.first_event):
        if is_event:star(c,x,y)
    c.setFillColor(ink);c.setFont('Helvetica',7)
    for i,(x,route) in enumerate(zip(xs,g.route)):
        c.drawCentredString(x,ybase-11,str(i+1))
        c.drawCentredString(x,ybase-21,str(route))
    c.setFont('Helvetica',6.5);c.drawRightString(left-5,ybase-20,'K/D:')

def report(cfg):
    subset=data[data.configuration_id.eq(cfg)]
    out=OUT/(cfg+'.pdf');c=canvas.Canvas(str(out),pagesize=(width,height),pageCompression=1)
    c.setTitle(f'{cfg} individual K/D surprisal trajectories')
    page_count=0;total=0;marked=0
    for kind,frame in conditions:
        part=subset[(subset.kind==kind)&(subset.frame==frame)]
        groups=[g for _,g in part.groupby('trial_id',sort=True)]
        assert len(groups)==30
        for page in range(3):
            chunk=groups[page*10:(page+1)*10]
            c.setFillColor(ink);c.setFont('Helvetica-Bold',19)
            c.drawString(45,height-42,f'{cfg}  |  {kind.upper()} / {frame.upper()}')
            c.setFont('Helvetica',10)
            c.drawString(45,height-62,f'One dialogue per chart; page {page+1}/3 in this condition. Blue: round surprisal. Red star: first joint report.')
            c.drawString(45,height-77,'Y: surprisal (bits), 0-7. X: round 1-10. Two K/D labels under each round show that round\'s feedback.')
            grid_top=height-100; grid_bottom=33; gap_x=22; gap_y=12
            cellw=(width-90-gap_x)/2;cellh=(grid_top-grid_bottom-4*gap_y)/5
            for i,g in enumerate(chunk):
                col=i%2;row=i//2;x=45+col*(cellw+gap_x);y=grid_top-(row+1)*cellh-row*gap_y
                panel(c,g,x,y,cellw,cellh)
                total+=1;marked+=int(g.first_event.sum())
            c.showPage();page_count+=1
    c.save();assert total==120 and page_count==12
    return total,marked,page_count

font=font_manager.FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10})
def preview(cfg):
    subset=data[data.configuration_id.eq(cfg)];fig,axes=plt.subplots(2,2,figsize=(14,9),sharey=True)
    fig.subplots_adjust(left=.07,right=.98,bottom=.12,top=.84,hspace=.55,wspace=.18)
    fig.suptitle(f'{cfg} | 시행 하나당 그래프 하나',fontsize=19,fontweight='bold',y=.97)
    fig.text(.5,.915,'각 패널은 대화 한 개의 10라운드 · 별은 통제 판단의 첫 전환',ha='center',fontsize=11)
    fig.text(.5,.885,'예시는 각 조건에서 전환된 대화가 있으면 그중 하나를 선택. 전체 120개 대화는 PDF에 수록.',ha='center',fontsize=10,color='#52687b')
    for ax,(kind,frame) in zip(axes.flat,conditions):
        part=subset[(subset.kind==kind)&(subset.frame==frame)]
        groups=[g for _,g in part.groupby('trial_id',sort=True)]
        events=[g for g in groups if g.first_event.any()]
        g=events[0] if events else groups[0]
        x=g['round'].to_numpy();y=g.surprisal_round_bits.to_numpy()
        ax.plot(x,y,color='#2878ad',lw=1.8,marker='o',markersize=3)
        ev=g[g.first_event]
        if len(ev):ax.scatter(ev['round'],ev.surprisal_round_bits,marker='*',s=170,c='#cc2936',edgecolors='white',linewidths=.5,zorder=4)
        title=f"{kind} · {'카드' if frame=='cards' else '고양이'} · {g.case_id.iloc[0]}"
        title+=f" · 전환 {int(ev['round'].iloc[0])}라운드" if len(ev) else ' · 10라운드 내 전환 없음'
        ax.set_title(title,fontsize=11);ax.set_xlim(.7,10.3);ax.set_ylim(-.1,7.3)
        ax.set_xticks(x,[f'{r}\n{kd}' for r,kd in zip(x,g.route)]);ax.set_yticks([0,2,4,6]);ax.grid(alpha=.2)
        ax.tick_params(axis='x',labelsize=8)
    fig.text(.02,.47,'그 라운드의 surprisal 합 (bits)',rotation=90,va='center',fontsize=11)
    fig.text(.5,.04,'라운드 및 K/D',ha='center',fontsize=11)
    fig.savefig(OUT/(cfg+'-example.png'),dpi=140,facecolor='white');plt.close(fig)

total=events=pages=0
for model in models:
    for effort in efforts:
        cfg=f'{model}-{effort}';n,e,pages_one=report(cfg);preview(cfg)
        total+=n;events+=e;pages+=pages_one
        print(cfg,n,e,pages_one,flush=True)
assert total==2520 and events==342 and pages==252
print(f'PASS: {total} individual charts; {events} first transitions; {pages} pages')
