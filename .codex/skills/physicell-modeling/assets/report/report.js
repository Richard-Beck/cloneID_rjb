'use strict';
const D=JSON.parse(document.getElementById('reportData').textContent);
const $=id=>document.getElementById(id), C=Object.assign({stationary:'#0072b2',constant:'#d55e00',adaptation:'#009e73'},D.colors||{});
const escapeHTML=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cfg={responsive:true,displaylogo:false,toImageButtonOptions:{format:'png',scale:2}};
const layout=(extra={})=>Object.assign({font:{family:'system-ui',size:12,color:'#19313c'},margin:{l:70,r:24,t:45,b:70},paper_bgcolor:'white',plot_bgcolor:'white',hovermode:'closest',legend:{orientation:'h',y:1.15}},extra);
const group=()=>$('group').value;
const candidates=(scope='all')=>D.candidates.filter(c=>c.group===group()&&(scope!=='new'||!c.inherited));
const winner=m=>D.candidates.find(c=>c.group===group()&&c.stage===m&&c.id===D.best[group()+'_'+m]);
const fmt=n=>Number(n).toPrecision(5);
const table=(headers,rows)=>'<div class="table-scroll"><table><thead><tr>'+headers.map(h=>'<th>'+escapeHTML(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
function overview(){
 $('summaryTable').innerHTML=table(['Stage','Best PhysiCell loss','Change from '+D.models[0],'Candidate','Origin','New scored / starts'],D.models.map(m=>{const c=winner(m);if(!c)return [escapeHTML(m),'No scored candidate','—','—','—','—'];return ['<b style="color:'+C[m]+'">'+m+'</b>',fmt(c.loss),((winner(D.models[0])||{loss:0}).loss===0?'—':fmt(100*(c.loss/(winner(D.models[0])||{loss:0}).loss-1))+'%'),escapeHTML(c.id),c.inherited?'Inherited '+escapeHTML(c.source_stage):'New '+m+' fit',D.outcomes?D.outcomes[m][group()].scored+' / '+D.outcomes[m][group()].starts:''];}));
 $('summaryNote').textContent='Stage-best fits are ranked by PhysiCell loss against the same observations.';
}
function initFields(){
 const list=D.fields.filter(f=>f.group===group()),episodes=[...new Set(list.map(f=>f.episode))];
 $('fieldSelect').innerHTML=episodes.map(e=>'<option value="'+escapeHTML(e)+'">'+escapeHTML(e)+'</option>').join('');renderFields();
}
function renderFields(){
 const fields=D.fields.filter(f=>f.group===group()&&f.episode===$('fieldSelect').value).sort((a,b)=>a.time-b.time);
 const rank=Number($('rank').value);let sources=[];
 $('imageGrid').style.setProperty('--field-columns',D.models.length+2);
 $('fieldCaption').textContent=fields.length+' imaged timepoints · all stages · chronological order';
 $('imageGrid').innerHTML=fields.map(f=>{
  const sim=D.models.map(m=>f.simulations.find(s=>s.stage===m&&s.rank===rank)).filter(Boolean);
  const images=[{src:f.raw_image,title:'Raw microscopy',detail:f.passage_id+' · tile '+f.tile},{src:f.mask_image,title:'Observed cell labels',detail:f.observed.visible_cells+' visible labels'},...sim.map(s=>({src:s.image,title:s.stage+' · rank '+s.rank,detail:s.candidate+' · loss '+fmt(s.loss)+' · '+s.visible_cells+' labels · day '+s.time.toFixed(4)}))];
  sources.push('<h4>'+escapeHTML(f.passage_id)+'</h4><p>Raw: <code>'+escapeHTML(f.raw_path)+'</code><br>Mask: <code>'+escapeHTML(f.mask_path)+'</code><br>SHA256 raw: '+f.raw_sha256+'<br>SHA256 mask: '+f.mask_sha256+'</p>'+sim.map(s=>'<p>'+escapeHTML(s.stage)+' snapshot: <code>'+escapeHTML(s.snapshot)+'</code><br>Cell SHA256: '+s.cells_sha256+'</p>').join(''));
  return '<div class="field-timepoint"><h3>Day '+f.time.toFixed(3)+' · '+escapeHTML(f.passage_id)+'</h3><div class="image-grid">'+images.map(i=>'<figure><h4>'+escapeHTML(i.title)+'</h4><img loading="lazy" src="'+i.src+'" alt="'+escapeHTML(i.title+' '+i.detail)+'"><figcaption>'+escapeHTML(i.detail)+'</figcaption></figure>').join('')+'</div></div>';
 }).join('')||'<p>No accessible matched images.</p>';
 $('fieldSources').innerHTML=sources.join('');
 $('imageGrid').querySelectorAll('img').forEach(img=>img.onclick=()=>{$('lightboxImage').src=img.src;$('lightboxCaption').textContent=img.alt;$('lightbox').showModal();});
}
const pageSize=20;
function growthList(){return D.growth.filter(g=>g.group===group()&&($('growthArm').value==='all'||g.arm===$('growthArm').value));}
function initGrowth(){
 const available=key=>key==='count'||D.growth.some(g=>g.group===group()&&[g.metrics?.observed,...Object.values(g.metrics?.simulations||{})].some(v=>v?.[key]?.some(x=>Array.isArray(x)?x.some(Number.isFinite):Number.isFinite(x))));
 Array.from($('growthMetric').options).forEach(o=>o.disabled=!available(o.value));
 if(!available($('growthMetric').value))$('growthMetric').value='count';
 const list=growthList(),n=Math.ceil(list.length/pageSize);$('growthPage').innerHTML=Array.from({length:n},(_,i)=>'<option value="'+i+'">'+(i+1)+' of '+n+' · passages '+(i*pageSize+1)+'–'+Math.min((i+1)*pageSize,list.length)+'</option>').join('');renderGrowth();}
const axisTitle=text=>({text,font:{color:'#19313c',size:12},standoff:10});
function renderGrowth(){
 const metric=$('growthMetric').value,list=growthList().slice(Number($('growthPage').value)*pageSize,(Number($('growthPage').value)+1)*pageSize),traces=[];
 const labels=Object.assign({count:D.count_axis_label,area_quantiles:'Cell area / mean area',coverage:'Covered fraction',gap:'Gap (pixels)',clark_evans:'Clark–Evans index'},D.metric_axis_labels||{});
 $('metricNote').textContent=metric==='count'?'Counts use each candidate’s frozen count conversion. Lines connect saved simulation samples.':(D.passage_metric_note||'');
 const L=layout({grid:{rows:4,columns:5,pattern:'independent',xgap:.24,ygap:.32},margin:{l:70,r:20,t:65,b:60},annotations:[],height:1120,legend:{orientation:'h',y:1.06},showlegend:true});
 const rgba=(hex,a)=>'rgba('+[1,3,5].map(k=>parseInt(hex.slice(k,k+2),16)).join(',')+','+a+')';
 list.forEach((g,i)=>{
  const suffix=i===0?'':String(i+1),axis={xaxis:'x'+suffix,yaxis:'y'+suffix};
  const add=t=>traces.push(Object.assign(t,axis));
  D.models.forEach(m=>{
   const v=metric==='count'?g.simulations[m]:g.metrics?.simulations?.[m]?.[metric];if(!v)return;
   if(metric==='area_quantiles'){
    [[0,4,.10],[1,3,.22]].forEach(([lo,hi,alpha])=>{
     add({x:g.times,y:v.map(q=>q?.[lo]),type:'scatter',mode:'lines',line:{width:0},legendgroup:m,showlegend:false,hoverinfo:'skip'});
     add({x:g.times,y:v.map(q=>q?.[hi]),type:'scatter',mode:'lines',line:{width:0},fill:'tonexty',fillcolor:rgba(C[m],alpha),legendgroup:m,showlegend:false,hoverinfo:'skip'});
    });
   }
   add({x:g.times,y:metric==='area_quantiles'?v.map(q=>q?.[2]):v,mode:'lines',name:m,legendgroup:m,showlegend:i===0,line:{color:C[m],width:2},hovertemplate:'Day %{x:.3f}<br>%{y:.4g}<extra>'+m+'</extra>'});
  });
  const obs=metric==='count'?g.observed:g.metrics?.observed?.[metric];
  if(metric==='area_quantiles'&&obs){
   const ix=obs.map((q,j)=>q&&q.every(Number.isFinite)?j:-1).filter(j=>j>=0);
   add({type:'box',x:ix.map(j=>g.times[j]),q1:ix.map(j=>obs[j][1]),median:ix.map(j=>obs[j][2]),q3:ix.map(j=>obs[j][3]),lowerfence:ix.map(j=>obs[j][0]),upperfence:ix.map(j=>obs[j][4]),name:'Observed',legendgroup:'Observed',showlegend:i===0,boxpoints:false,line:{color:'#111',width:1.5},fillcolor:'rgba(255,255,255,.65)',width:Math.max(.035,(Math.max(...g.times)-Math.min(...g.times))*.025)});
  }else if(obs)add({x:g.times,y:obs,text:g.passage_ids,mode:'markers',type:'scatter',name:'Observed',legendgroup:'Observed',showlegend:i===0,marker:{color:'black',size:5},hovertemplate:'%{text}<br>Day %{x:.3f}<br>%{y:.4g}<extra>Observed</extra>'});
  L['xaxis'+suffix]={title:axisTitle('Days since seeding'),zeroline:false,tickfont:{size:10},nticks:4};
  L['yaxis'+suffix]={title:axisTitle(i%5===0?labels[metric]:''),type:$('countScale').value,zeroline:false,tickfont:{size:10},nticks:4,automargin:true};
  L.annotations.push({text:escapeHTML(g.plot_label || (g.arm+' · '+g.passage)),xref:'x'+suffix+' domain',yref:'y'+suffix+' domain',x:.5,y:1.08,showarrow:false,font:{size:12}});
 });Plotly.react('growthPlot',traces,L,cfg);
}
function renderLoss(){
 const bars=D.component_names.map((name,i)=>({type:'bar',name,x:D.models,y:D.models.map(m=>winner(m)?.components[name]??null),marker:{color:['#334f68','#7297b2','#a2c4d9','#c99755','#ead3a7'][i]},hovertemplate:'%{x}<br>'+name+': %{y:.4f}<extra></extra>'}));
 Plotly.react('componentBars',bars,layout({barmode:'stack',yaxis:{title:axisTitle('Weighted contribution to PhysiCell loss'),automargin:true},xaxis:{title:axisTitle('Best representative by stage')}}),cfg);
 const scope=$('lossScope').value,component=$('component').value,traces=[],parity=[];
 D.models.forEach(m=>{
  const list=candidates(scope).filter(c=>c.stage===m),w=winner(m);if(!w)return;
  const total=c=>D.component_groups[component]?D.component_groups[component].reduce((a,n)=>a+c.components[n],0):c.components[component];
  traces.push({type:'scatter',mode:'markers',name:m,x:list.map(c=>c.loss),y:list.map(total),text:list.map(c=>c.id+(c.inherited?' (inherited)':'')),marker:{color:C[m],size:6,opacity:.55},hovertemplate:'%{text}<br>Total %{x:.4f}<br>Component %{y:.4f}<extra>'+m+'</extra>'});
  traces.push({type:'scatter',mode:'markers',name:m+' best',showlegend:false,x:[w.loss],y:[total(w)],marker:{color:C[m],size:13,symbol:'diamond',line:{color:'#172c36',width:1}}});
  parity.push({type:'scatter',mode:'markers',name:m,x:list.map(c=>c.predicted),y:list.map(c=>c.loss),text:list.map(c=>c.id),marker:{color:C[m],size:6,opacity:.55},hovertemplate:'%{text}<br>Predicted %{x:.4f}<br>PhysiCell %{y:.4f}<extra>'+m+'</extra>'});
 });
 const vals=candidates(scope).flatMap(c=>[c.predicted,c.loss]).filter(Number.isFinite);if(vals.length){const lo=Math.min(...vals),hi=Math.max(...vals);parity.push({x:[lo,hi],y:[lo,hi],mode:'lines',name:'Equal loss',line:{color:'#888',dash:'dash'},hoverinfo:'skip'});}
 Plotly.react('componentScatter',traces,layout({title:{text:component+' contribution'},xaxis:{title:axisTitle('Total PhysiCell loss'),automargin:true},yaxis:{title:axisTitle('Weighted '+component.toLowerCase()+' loss'),automargin:true}}),cfg);
 Plotly.react('parityPlot',parity,layout({title:{text:'Approximation versus PhysiCell'},xaxis:{title:axisTitle('Approximation data loss'),automargin:true},yaxis:{title:axisTitle('PhysiCell data loss'),automargin:true}}),cfg);
}
function jitter(id){let h=2166136261;for(const c of id)h=Math.imul(h^c.charCodeAt(0),16777619);return ((h>>>0)%1000/1000-.5)*.12;}
function renderParameters(){
 const section=$('parameterSection').value,scope=$('parameterScope').value,all=candidates(scope),names=[];
 D.candidates.filter(c=>c.group===group()).forEach(c=>Object.entries(c.params).forEach(([n,v])=>{if(v.section===section&&!names.includes(n))names.push(n);}));
 let traces=[],counts=[];
 D.models.forEach((m,mi)=>{
  const best=winner(m),cut=Math.max(0,Number($('cutoff_'+m).value)||0);if(!best){counts.push(m+': no scored candidate');return;}let group=all.filter(c=>c.stage===m&&c.loss<=best.loss*(1+cut/100)+1e-12);
  counts.push(m+': '+group.length+' candidates within '+cut+'%');
  let x=[],y=[],text=[];group.forEach(c=>names.forEach((n,ni)=>{const v=c.params[n];if(!v)return;x.push(ni+(mi-(D.models.length-1)/2)*.23+jitter(c.id));y.push(v.log);text.push(n+'<br>'+m+' · '+c.id+(c.inherited?' · inherited from '+c.source_stage:'')+'<br>'+fmt(v.value)+' '+v.unit+'<br>PhysiCell loss '+fmt(c.loss));}));
  traces.push({type:'scatter',mode:'markers',name:m,x,y,text,marker:{color:C[m],size:5,opacity:.4},hovertemplate:'%{text}<extra></extra>'});
  const active=names.map((n,i)=>({n,i,v:best.params[n]})).filter(x=>x.v);
  traces.push({type:'scatter',mode:'markers',name:m+' best',x:active.map(a=>a.i+(mi-(D.models.length-1)/2)*.23),y:active.map(a=>a.v.log),text:active.map(a=>a.n+'<br>'+fmt(a.v.value)+' '+a.v.unit+'<br>'+best.id),marker:{color:C[m],size:12,symbol:'diamond',line:{color:'#132d38',width:1}},hovertemplate:'%{text}<extra>Stage best</extra>'});
 });
 $('parameterCounts').textContent=counts.join(' · ');
 Plotly.react('parameterPlot',traces,layout({height:540,margin:{l:75,r:20,t:60,b:165},xaxis:{tickvals:names.map((_,i)=>i),ticktext:names,tickangle:-35,range:[-.6,names.length-.4]},yaxis:{title:axisTitle('log10(parameter value)'),automargin:true,zerolinecolor:'#ccc'}}),cfg);
 $('parameterPlot').style.height='540px';
 $('parameterTable').innerHTML=table(['Stage-best parameter',...D.models],names.map(n=>[escapeHTML(n),...D.models.map(m=>{const v=winner(m)?.params[n];return v?escapeHTML(fmt(v.value)+' '+v.unit):'Not applicable';})]));
}
function all(){$('growthArm').value='all';overview();initFields();initGrowth();renderLoss();renderParameters();}

$('component').innerHTML=[...Object.keys(D.component_groups),...D.component_names].map(n=>'<option>'+n+'</option>').join('');
$('cutoffs').innerHTML=D.models.map(m=>'<label style="color:'+C[m]+'">'+m+' cutoff (%)<input id="cutoff_'+m+'" type="number" min="0" max="100" step="1" value="'+(D.default_cutoff_percent??5)+'"></label>').join('');
$('stageLinks').innerHTML=(D.links||[]).map(l=>'<p><a href="'+escapeHTML(l.href)+'">'+escapeHTML(l.label)+'</a></p>').join('');
$('group').innerHTML=D.groups.map(g=>'<option value="'+escapeHTML(g.id)+'">'+escapeHTML(g.label)+'</option>').join('');
$('growthArm').insertAdjacentHTML('beforeend',[...new Set(D.growth.map(g=>g.arm))].map(a=>'<option>'+escapeHTML(a)+'</option>').join(''));
$('reportTitle').textContent=D.title;
$('modelDefinitions').textContent=D.models.map(m=>m+': '+D.model_definitions[m]).join(' ');
['imageGeometry','imageSelection','lossDefinition','parameterTransforms'].forEach(id=>$(id).textContent=D.descriptions[id]);
$('protocolText').innerHTML=D.protocol.map(p=>'<p>'+escapeHTML(p)+'</p>').join('');
$('computeUsage').innerHTML=table(['Compute measure','Value'],Object.entries(D.compute_usage).map(([k,v])=>[escapeHTML(k),escapeHTML(v)]));
$('group').onchange=all;$('fieldSelect').onchange=renderFields;$('rank').onchange=renderFields;
$('growthMetric').onchange=renderGrowth;$('growthArm').onchange=initGrowth;$('growthPage').onchange=renderGrowth;$('countScale').onchange=renderGrowth;
$('component').onchange=renderLoss;$('lossScope').onchange=renderLoss;$('parameterSection').onchange=renderParameters;$('parameterScope').onchange=renderParameters;
D.models.forEach(m=>$('cutoff_'+m).onchange=renderParameters);
$('closeLightbox').onclick=()=>$('lightbox').close();$('lightbox').onclick=e=>{if(e.target===$('lightbox'))$('lightbox').close();};
all();window.reportReady=true;
