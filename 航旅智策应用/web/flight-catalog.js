'use strict';
function catalogMatches(leg,p,s){
 const constraints=p.preference_constraints||{},segments=leg.segments||[];
 const code=f=>String(f.flight_number||'').match(/^([A-Z0-9]{2})/)?.[1]||f.airline_code||'';
 if(segments.some(f=>constraints.excluded_airlines?.includes(code(f))))return false;
 if(constraints.required_airlines?.length&&segments.some(f=>!constraints.required_airlines.includes(code(f))))return false;
 if(segments.length-1>s.max_stops)return false;
 if((leg.layovers||[]).some(l=>l.minutes>360))return false;
 return true;
}
function catalogRows(p,s,direction){
 let rows=s.result?.catalog?.[direction]||[];
 if(s.catalogMode==='preferences')rows=rows.filter(leg=>catalogMatches(leg,p,s));
 if(s.catalogCarrier)rows=rows.filter(leg=>leg.segments.some(f=>String(f.flight_number||'').startsWith(s.catalogCarrier)));
 if(s.catalogStops==='direct')rows=rows.filter(leg=>leg.segments.length===1);
 if(s.catalogSearch){const text=s.catalogSearch.trim().toLowerCase();rows=rows.filter(leg=>leg.segments.some(f=>[f.flight_number,f.airline_zh,f.airline,f.origin_airport,f.destination_airport].some(v=>String(v||'').toLowerCase().includes(text))));}
 return rows;
}
function flightCatalogHtml(p,s){
 if(!s.result?.native_roundtrip||!s.result?.catalog)return '';
 const catalog=s.result.catalog,carriers=new Map();
 for(const leg of catalog.outbound||[])for(const f of leg.segments){const code=String(f.flight_number||'').slice(0,2);carriers.set(code,f.airline_zh||f.airline||code);}
 const controls=`<div class="catalog-controls"><label>显示范围<select data-catalog-filter="catalogMode"><option value="all" ${s.catalogMode!=='preferences'?'selected':''}>全部航班</option><option value="preferences" ${s.catalogMode==='preferences'?'selected':''}>按我的需求筛选</option></select></label><label>航空公司<select data-catalog-filter="catalogCarrier"><option value="">全部航司</option>${[...carriers].map(([c,n])=>`<option value="${esc(c)}" ${s.catalogCarrier===c?'selected':''}>${esc(n)}</option>`).join('')}</select></label><label>中转次数<select data-catalog-filter="catalogStops"><option value="all">全部航程</option><option value="direct" ${s.catalogStops==='direct'?'selected':''}>仅看直飞</option></select></label><label>搜索航班<input type="search" data-catalog-filter="catalogSearch" value="${esc(s.catalogSearch||'')}" placeholder="航班号或航司"></label></div>`;
 function table(direction){
  const all=catalog[direction]||[],rows=catalogRows(p,s,direction),size=10,pages=Math.max(1,Math.ceil(rows.length/size));
  const pageKey=direction+'Page';s[pageKey]=Math.max(0,Math.min(s[pageKey]||0,pages-1));
  const visible=rows.slice(s[pageKey]*size,(s[pageKey]+1)*size);
  return `<div class="catalog-count">已返回 ${all.length} 个航班 · 当前显示 ${rows.length} 个${s.result.coverage?.partial?' · 部分结果暂未完成':''}</div><div class="catalog-scroll"><table class="flight-catalog-table"><caption class="sr-only">${direction==='outbound'?'去程航班与往返起价':'所选去程对应的返程航班与往返总价'}</caption><thead><tr><th scope="col">航司航班</th><th scope="col">起降时间</th><th scope="col">航程</th><th scope="col">${direction==='outbound'?'往返起价':'往返总价'}</th><th scope="col">选择</th></tr></thead><tbody>${visible.map(leg=>{
   const eligible=catalogMatches(leg,p,s),selected=s.result.selected_outbound_id===leg.catalog_id;
   const departure=leg.departure_time.replace('T',' '),arrival=leg.arrival_time.replace('T',' ');
   const action=direction==='outbound'?`<button type="button" class="secondary small" data-live-action="returns" data-outbound="${esc(leg.catalog_id)}" ${s.busy?'disabled':''}>${selected?'已选去程':'选择去程'}</button>`:
    Number.isInteger(leg.option_index)?`<button type="button" class="secondary small" data-live-action="preview" data-option="${leg.option_index}" ${s.busy?'disabled':''}>比较预算</button>`:
    leg.price_cny==null?`<button type="button" class="secondary small" data-live-action="quote" data-outbound="${esc(s.result.selected_outbound_id)}" data-inbound="${esc(leg.catalog_id)}" ${s.busy?'disabled':''}>查询总价</button>`:
    `<span class="catalog-note">${!eligible?'不符偏好条件':'不符预算条件'}</span>`;
   const href=typeof leg.google_url==='string'&&leg.google_url.startsWith('https://www.google.com/travel/flights')?leg.google_url:null;
   return `<tr data-catalog-row="${esc(leg.catalog_id)}" ${selected?'class="catalog-selected"':''}><td>${leg.segments.map(f=>`<strong>${esc(f.airline_zh||f.airline||'')} ${esc(f.flight_number)}</strong>`).join('')}<small>${esc(leg.origin_airport||leg.segments[0].origin_airport)} → ${esc(leg.destination_airport||leg.segments.at(-1).destination_airport)}</small></td><td><span>${esc(departure)}</span><small>${esc(arrival)}</small></td><td>${leg.segments.length===1?'直飞':leg.segments.length-1+'次中转'}${!eligible?'<small>不符当前偏好</small>':''}</td><td class="catalog-amount">${leg.price_cny==null?'—':'¥'+fareFmt(leg.price_cny)+(direction==='outbound'?' 起':'')}</td><td>${action}${href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">查看 Google</a>`:''}</td></tr>`;
  }).join('')||'<tr><td colspan="5">当前筛选条件下没有航班；可切换为全部航班。</td></tr>'}</tbody></table></div><div class="catalog-pagination"><button type="button" class="secondary small" data-catalog-page="${direction}" data-step="-1" ${s[pageKey]===0?'disabled':''}>上一页</button><span>第 ${s[pageKey]+1} / ${pages} 页</span><button type="button" class="secondary small" data-catalog-page="${direction}" data-step="1" ${s[pageKey]===pages-1?'disabled':''}>下一页</button></div>`;
 }
 const selected=(catalog.outbound||[]).find(leg=>leg.catalog_id===s.result.selected_outbound_id);
 return `<div class="flight-catalog" data-flight-catalog><h4>去程航班</h4><p class="card-sub">先浏览本次返回的航班，再选择去程查询对应返程。起价为 ${s.adults} 名成人的往返起价。</p>${controls}${table('outbound')}${s.busy?'<p role="status">正在查询航班，请稍候…</p>':''}${selected?`<section class="catalog-inbound"><h4>返程航班</h4><p>已选去程：${selected.segments.map(f=>esc(f.flight_number)).join(' / ')} · ${esc(selected.departure_time.replace('T',' '))}</p>${table('inbound')}<p class="card-sub">“—”表示本次接口未返回金额，不代表 Google 页面没有报价。可在 Google 核对所选往返航班。</p></section>`:''}</div>`;
}
let catalogPaintPending=false;
function paintCatalog(){
 if(catalogPaintPending)return;catalogPaintPending=true;
 setTimeout(()=>{catalogPaintPending=false;paintFlights();},0);
}
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-catalog-filter]')||!e.target.closest('[data-current-flights]')||!tripPlan)return;
 const s=flightView(tripPlan);s[e.target.dataset.catalogFilter]=e.target.value;s.outboundPage=s.inboundPage=0;paintCatalog();
});
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-catalog-page]');if(!button||!tripPlan)return;
 const s=flightView(tripPlan),key=button.dataset.catalogPage+'Page';s[key]=(s[key]||0)+Number(button.dataset.step);paintFlights();
});
