"""Offline display of recorded endpoints; no inference or new estimation."""
import csv
import json


def create(output):
    with (output / 'tables/trials.csv').open(newline='') as handle:
        trials = list(csv.DictReader(handle))
    data = json.dumps(trials, ensure_ascii=True).replace('<', '\\u003c')
    template = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Experiment 2 endpoint explorer</title>
<style>body{font:16px system-ui;color:#18232d;max-width:1100px;margin:32px auto;padding:0 20px}label{display:inline-block;margin:8px 16px 8px 0}select{font:inherit;padding:5px}svg{width:100%;height:auto;background:#f7f9fb;border-radius:8px}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}.note{color:#526171}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}</style>
<h1>Experiment 2: endpoint explorer</h1>
<p>Round 1 → questions → Round 2 → questions → Round 3 → questions → disclosure → final questions.</p>
<label>Configuration <select id="config"></select></label>
<label>Frame <select id="frame"><option value="all">Cards and cats</option><option value="cards">Cards</option><option value="cats">Cats</option></select></label>
<p id="counts"></p><div class="plots" id="plots"></div>
<p class="note">Means use valid endpoints at each occasion. Counts can differ; missing scores are not imputed. These display means are not paired contrasts. Frozen case-cluster estimates and nominal pointwise intervals are in estimates.csv and REPORT.md. There are ten shared starting-case clusters, no unrepeated control, and no model-ranking claim.</p>
<h2>Recorded trial endpoints</h2><p class="note">Each cell is freedom / impact / counterfactual. An em dash denotes a missing endpoint.</p>
<div style="overflow:auto"><table id="trials"></table></div>
<p><a href="index.html">All prespecified figures</a> · <a href="REPORT.md">English report</a> · <a href="tables/trials.csv">Trial CSV</a> · <a href="tables/estimates.csv">Estimates and intervals</a> · <a href="tables/choices.csv">Recorded choices</a></p>
<script>
const DATA=__DATA__;
const selector=document.getElementById('config'),frames=document.getElementById('frame');
const configs=[...new Set(DATA.map(r=>r.configuration_id))].sort();
configs.forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;selector.append(o)});
selector.value=configs.includes('gpt-6.1-sol-high')?'gpt-6.1-sol-high':configs[0];
const labels=['R1','R2','R3','Post'];
function number(r,m,key){const value=r['m'+m+'_'+key];if(value===''||value===undefined)return null;return key==='counterfactual'?(value==='yes'?1:0):Number(value)}
function panel(rows,key,title){
 const values=[1,2,3,4].map(m=>{const a=rows.map(r=>number(r,m,key)).filter(v=>v!==null);return {mean:a.length?a.reduce((a,b)=>a+b,0)/a.length:null,n:a.length}});
 const max=key==='counterfactual'?1:100,x=i=>62+i*100,y=v=>260-(v/max)*205;
 let svg='<svg viewBox="0 0 430 325" role="img" aria-label="'+title+'"><text x="20" y="25" font-size="17">'+title+'</text>';
 [0,.25,.5,.75,1].forEach(f=>{let v=max*f;svg+='<line x1="52" x2="375" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#d7dfe7"/><text x="44" y="'+(y(v)+4)+'" text-anchor="end" font-size="12">'+(key==='counterfactual'?Math.round(f*100)+'%':v)+'</text>'});
 values.forEach((v,i)=>{svg+='<text x="'+x(i)+'" y="292" text-anchor="middle" font-size="13">'+labels[i]+'</text><text x="'+x(i)+'" y="313" text-anchor="middle" font-size="12">n='+v.n+'</text>';if(v.mean===null)return;let previous=values[i-1];if(previous&&previous.mean!==null)svg+='<line x1="'+x(i-1)+'" y1="'+y(previous.mean)+'" x2="'+x(i)+'" y2="'+y(v.mean)+'" stroke="#356db4" stroke-width="3"/>';svg+='<circle cx="'+x(i)+'" cy="'+y(v.mean)+'" r="5" fill="#356db4"/><text x="'+x(i)+'" y="'+(y(v.mean)-10)+'" text-anchor="middle" font-size="12">'+(key==='counterfactual'?(v.mean*100).toFixed(1)+'%':v.mean.toFixed(1))+'</text>'});
 return svg+'</svg>';
}
function update(){
 const rows=DATA.filter(r=>r.configuration_id===selector.value&&(frames.value==='all'||r.frame===frames.value));
 document.getElementById('counts').textContent=rows.length+' assigned trials; '+rows.filter(r=>r.status==='complete').length+' complete; '+rows.filter(r=>r.status!=='complete').length+' other terminal outcomes.';
 document.getElementById('plots').innerHTML=panel(rows,'impact','Impact (1–100)')+panel(rows,'freedom','Freedom (1–100)')+panel(rows,'counterfactual','Counterfactual yes');
 const table=document.getElementById('trials');table.replaceChildren();
 const header=document.createElement('tr');['Case / frame','Status',...labels].forEach(t=>{const c=document.createElement('th');c.textContent=t;header.append(c)});table.append(header);
 rows.sort((a,b)=>(a.case_id+a.frame).localeCompare(b.case_id+b.frame)).forEach(r=>{const line=document.createElement('tr');const cells=[r.case_id+' / '+r.frame,r.status,...[1,2,3,4].map(m=>['freedom','impact','counterfactual'].map(k=>r['m'+m+'_'+k]||'—').join(' / '))];cells.forEach(t=>{const c=document.createElement('td');c.textContent=t;line.append(c)});table.append(line)});
}
selector.addEventListener('change',update);frames.addEventListener('change',update);update();
</script></html>'''
    (output / 'explorer.html').write_text(template.replace('__DATA__', data))
