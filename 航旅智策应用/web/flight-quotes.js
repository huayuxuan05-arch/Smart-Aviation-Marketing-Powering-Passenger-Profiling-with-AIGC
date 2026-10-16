'use strict';
const flightViews=new Map();
function flightViewKey(p){return [p.audience,p.id||p.user_id,p.origin,p.destination,p.start_date,p.end_date].join('|');}
function flightView(p){const key=flightViewKey(p);if(!flightViews.has(key))flightViews.set(key,{adults:p.live_flights?.adults||1,max_stops:0,busy:false,started:false,attempts:0,result:null,history:[],preview:null});return flightViews.get(key);}
function currentTravelDate(){const d=new Date();d.setDate(d.getDate()+7);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);}
function paintFlights(){if(typeof personalMeta!=='undefined')renderPersonal();else if(['trips','routes'].includes(page()))render();}
function flightBody(p,s){return p.audience==='personal'?{plan_id:p.id,adults:s.adults,max_stops:s.max_stops}:{user_id:p.user_id,settings:{...tripSettings,start_date:p.start_date,days:p.days},adults:s.adults,max_stops:s.max_stops};}
async function flightApi(p,path,body){const prefix=p.audience==='personal'?'personal':'mkt',r=await fetch('/api/'+prefix+'/flights/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.error||'请求未完成');return value;}
function flightLegHtml(label,leg){return `<div class="current-flight-leg"><strong>${label} · ¥${fmt(leg.price_cny)}</strong>${leg.segments.map(f=>`<span>${esc(f.airline_zh||f.airline)} ${esc(f.flight_number)}</span><small>${esc(f.origin_airport_name_zh||f.origin_airport)} → ${esc(f.destination_airport_name_zh||f.destination_airport)}</small><small>${esc(f.departure_time.replace('T',' '))} — ${esc(f.arrival_time.replace('T',' '))}</small>`).join('')}</div>`;}
function flightLegKey(leg){return JSON.stringify([leg.price_cny,leg.segments.map(f=>[f.flight_number,f.origin_airport,f.destination_airport,f.departure_time,f.arrival_time])]);}
function flightChoiceGroups(options){
 const seen=new Set(),groups=new Map();let count=0;
 for(const [index,option] of options.entries()){
  const outboundKey=flightLegKey(option.outbound),key=JSON.stringify([outboundKey,flightLegKey(option.inbound),option.total_price_cny]);
  if(seen.has(key))continue;seen.add(key);
  if(!groups.has(outboundKey))groups.set(outboundKey,{outbound:option.outbound,choices:[]});
  groups.get(outboundKey).choices.push({option,index});if(++count===3)break;
 }
 return [...groups.values()];
}
function liveFlightPanel(p){
 const s=flightView(p),validDate=p.start_date>=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 if(!s.started&&validDate){s.started=true;queueMicrotask(()=>matchFlights(p,false));}
 const selected=p.live_flights&&Date.now()-Date.parse(p.live_flights.observed_at)<15*60*1000?p.live_flights:null,options=s.result?.fresh&&Date.now()-Date.parse(s.result.requested_at)<15*60*1000?s.result.options||[]:[];
 const controls=validDate?`<div class="current-flight-controls"><label>成人人数 <select data-flight-adults ${s.busy?'disabled':''}>${Array.from({length:9},(_,i)=>`<option value="${i+1}" ${s.adults===i+1?'selected':''}>${i+1}人</option>`).join('')}</select></label><label>航程 <select data-flight-stops ${s.busy||p.preference_constraints?.fallback_policy==='只接受直飞'?'disabled':''}><option value="0" ${s.max_stops===0?'selected':''}>直飞</option><option value="1" ${s.max_stops===1?'selected':''}>最多一次中转</option></select></label><button type="button" class="secondary small" data-live-action="refresh" ${s.busy?'disabled':''}>${s.busy?'正在匹配航班…':'刷新航班'}</button></div>`:'';
 const choices=flightChoiceGroups(options).map(group=>`<div class="current-flight-option current-flight-group"><div data-flight-outbound>${flightLegHtml('去程',group.outbound)}</div><div class="current-flight-returns">${group.choices.map(({option:o,index},i)=>`<section class="current-flight-return" data-flight-return-choice>${flightLegHtml(group.choices.length>1?'返程 '+(i+1):'返程',o.inbound)}<div class="current-flight-total"><strong>${s.adults}名成人往返 ¥${fmt(o.total_price_cny)}</strong><button type="button" class="secondary small" data-live-action="preview" data-option="${index}">比较预算</button>${p.audience==='personal'?`<button type="button" class="secondary small" data-live-action="reject" data-option="${index}" ${s.rejected?.includes(index)?'disabled':''}>${s.rejected?.includes(index)?'已排除':'不考虑'}</button>`:''}</div></section>`).join('')}</div></div>`).join('');
 const chosen=selected?`<div class="current-flight-selected"><span class="badge green">已选航班</span><strong>${selected.adults}名成人往返 ¥${fmt(selected.option.total_price_cny)}</strong><div class="current-flight-option">${flightLegHtml('去程',selected.option.outbound)}${flightLegHtml('返程',selected.option.inbound)}</div><small>查询于 ${esc(new Date(selected.observed_at).toLocaleString('zh-CN'))}</small></div>`:'';
 const proposal=s.preview?`<div class="current-flight-preview"><h4>确认预算变化</h4><p>每名成人全程估算：${p.budget.estimated_total===null?'非机票费用另计':'¥'+fmt(p.budget.estimated_total)+' → '}¥${fmt(s.preview.budget.estimated_total)}。${s.preview.budget.difference>0?'高于所填预算 ¥'+fmt(s.preview.budget.difference)+'。':''}住宿、餐饮和活动仍为估算。</p><label><input type="checkbox" data-flight-confirm> 已核对人数、日期和费用</label><div class="actions"><button type="button" class="primary small" data-live-action="apply" disabled>${p.audience==='personal'?'确认并保存新方案':'确认用于当前方案'}</button><button type="button" class="secondary small" data-live-action="cancel">取消</button></div></div>`:'';
 const observations=s.history.filter(x=>x.minimum_total_cny!==null);
 const history=observations.length?`<details class="current-price-history"><summary>已采集的价格变化</summary><p class="card-sub">同一日期、人数和航程条件的查询记录。</p>${observations.slice(0,12).map(x=>`<div><time>${esc(new Date(x.observed_at).toLocaleString('zh-CN'))}</time><strong>往返 ¥${fmt(x.minimum_total_cny)}</strong></div>`).join('')}</details>`:'';
 return `<section class="current-flight-panel" data-current-flights><div class="row"><h3>本次航班</h3>${options.length?'<span class="badge green">'+(s.result?.source?.startsWith('QA')?'验收数据':'Google Flights')+'</span>':''}</div>${controls}${chosen}${choices?`<details class="current-flight-choices" ${selected?'':'open'}><summary>比较航班组合</summary><small>查询于 ${esc(new Date(s.result.requested_at).toLocaleString('zh-CN'))} · ${s.adults}名成人</small>${choices}</details>`:''}${proposal}${history}${selected||options.length?'<p class="card-sub">往返由两段单程报价组合；预订时核对税费、行李、退改条件和最终价格。</p>':''}</section>`;
}
async function matchFlights(p,refresh=true){
 const s=flightView(p);if(s.busy)return;s.busy=true;s.preview=null;s.rejected=[];s.attempts++;paintFlights();
 try{let value=await flightApi(p,'queries',{...flightBody(p,s),refresh});for(let i=0;['queued','running'].includes(value.status)&&i<150;i++){await new Promise(r=>setTimeout(r,1800));value=await flightApi(p,'queries/'+value.id);}s.result=value.status==='success'&&value.fresh?value:null;
  const q=new URLSearchParams(p.audience==='personal'?{plan_id:p.id,adults:s.adults,max_stops:s.max_stops}:{origin:p.origin,destination:p.destination,start_date:p.start_date,end_date:p.end_date,adults:s.adults,max_stops:s.max_stops});s.history=(await flightApi(p,'history?'+q)).items;
 }catch{s.result=null;}finally{s.busy=false;paintFlights();}
 if(!s.result&&s.attempts<3)setTimeout(()=>{if(tripPlan&&flightViewKey(tripPlan)===flightViewKey(p))matchFlights(p,true);},30000);
}
document.addEventListener('change',e=>{const section=e.target.closest('[data-current-flights]');if(!section||!tripPlan)return;const s=flightView(tripPlan);if(e.target.matches('[data-flight-confirm]')){section.querySelector('[data-live-action=apply]').disabled=!e.target.checked;return;}if(e.target.matches('[data-flight-adults],[data-flight-stops]')){s.adults=Number(section.querySelector('[data-flight-adults]').value);s.max_stops=Number(section.querySelector('[data-flight-stops]').value);s.result=null;s.history=[];s.preview=null;if(!s.busy)matchFlights(tripPlan,true);}});
document.addEventListener('click',async e=>{const button=e.target.closest('[data-live-action]');if(!button||!tripPlan)return;const p=tripPlan,key=flightViewKey(p),s=flightView(p),action=button.dataset.liveAction;
 try{if(action==='refresh')return void matchFlights(p,true);if(action==='cancel'){s.preview=null;return paintFlights();}
  const body={...flightBody(p,s),query_id:s.result?.id,option_index:Number(button.dataset.option??s.option)};
  if(action==='reject'){button.disabled=true;await flightApi(p,'reject',{...body,confirmed:true});s.rejected=[...(s.rejected||[]),body.option_index];if(tripPlan&&flightViewKey(tripPlan)===key)paintFlights();}
  if(action==='preview'){s.option=Number(button.dataset.option);s.preview=await flightApi(p,'preview',body);if(tripPlan&&flightViewKey(tripPlan)===key)paintFlights();}
  if(action==='apply'&&s.preview){const confirmed=button.closest('[data-current-flights]').querySelector('[data-flight-confirm]').checked;if(!confirmed)return;button.disabled=true;
   const updated=p.audience==='personal'?await flightApi(p,'apply',{...body,confirmed:true,expected_revision:personalState.revision}):s.preview;
   if(tripPlan&&flightViewKey(tripPlan)===key){tripPlan=updated;if(p.audience==='personal')await refreshPersonal();else render();}s.preview=null;
  }
 }catch{s.preview=null;paintFlights();matchFlights(p,true);}
});
setInterval(()=>{if(typeof tripPlan!=='undefined'&&tripPlan&&flightView(tripPlan).started)matchFlights(tripPlan,true);},12*60*1000);
