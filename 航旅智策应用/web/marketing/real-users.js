'use strict';
let realCohort="",realCampaign=null,realObservation=null,realForecast=null;
let realData=null,realWindow=30,realSearch='',realPage=1,realDecision=null,realBusy=false;
let realStage='',realAirline='',realDestination='',realPageSize=20,realSort='recent',realOnlyUnmatched=false;
const realSelected=new Set();
function realCarrierNames(codes){return (codes||[]).map(c=>realData.airline_names?.[c]||c).join('、')||'不限航司';}
function realEventLabel(e){return e.activity?.label||({preferences_confirmed:'确认偏好',plan_saved:'保存方案',plan_deleted:'删除方案',flight_search:'查询航班',flight_search_result:e.result?.status==='empty'?'未找到符合条件的航班':'已返回航班报价',flight_selected:'选择航班',flight_rejected:'排除航班',destination_view:'浏览目的地'})[e.kind]||e.kind;}
function realFiltered(){
 const q=realSearch.toLowerCase();
 return realData.profiles.filter(p=>(!q||[p.user_id,p.origin,p.destination,p.intent_stage,p.theme,p.party,p.preferences.lodging_priority,realCarrierNames(p.preferences.required_airlines)].some(x=>String(x||'').toLowerCase().includes(q)))
  &&(!realStage||p.intent_stage===realStage)&&(!realAirline||(p.preferences.required_airlines||[]).includes(realAirline))
  &&(!realDestination||p.destination===realDestination)&&(!realOnlyUnmatched||p.flight_search_result?.status==='empty'))
 .sort((a,b)=>realSort==='date'?(a.start_date||'9999').localeCompare(b.start_date||'9999'):realSort==='budget'?(a.preferences.trip_budget??Infinity)-(b.preferences.trip_budget??Infinity):b.last_active_at.localeCompare(a.last_active_at));
}
function realDistribution(values,limit=6){
 const rows=Object.entries(values||{}).sort((a,b)=>b[1]-a[1]).slice(0,limit),max=Math.max(1,...rows.map(x=>x[1]));
 return rows.length?`<div class="real-distribution">${rows.map(([label,count])=>`<div><span>${esc(label)}</span><div class="real-bar" aria-hidden="true"><i style="width:${count/max*100}%"></i></div><strong>${fmt(count)}</strong></div>`).join('')}</div>`:'<p class="real-empty">暂无记录，用户填写或浏览后更新。</p>';
}
function realButton(text,action,extra=''){return `<button type="button" class="secondary small" data-real-action="${action}" ${extra}>${text}</button>`;}
function realBlank(text='尚无已同意共享的真实旅客。旅客在个人页开启匿名共享后，偏好和交互将进入此处。'){return `<section class="card"><h2>真实客群</h2><p>${text}</p></section>`;}
function realHotspots(){
 if(!realData.hotspots.length)return '<p>当前窗口内尚无目的地关注记录。</p>';
 return `<div class="table-container"><table><thead><tr><th>目的地</th><th>关注旅客</th><th>近7天</th><th>较前7天</th></tr></thead><tbody>${realData.hotspots.map(h=>`<tr><td><strong>${esc(h.destination)}</strong></td><td>${fmt(h.users)}</td><td>${fmt(h.users_last_7d)}</td><td>${h.change_users_7d>0?'+':''}${h.change_users_7d}</td></tr>`).join('')}</tbody></table></div>`;
}
function realMetrics(){return `<div class="metric-grid real-metrics">${metric('共享用户',fmt(realData.population),'当前同意共享的用户')}${metric('明确意向',fmt((realData.intent_groups['明确计划']||0)+(realData.intent_groups['已比较航班']||0)),'已表达计划或比较航班')}${metric('近期活跃',fmt(realData.active_users),`近${realWindow}天有浏览或操作`)}${metric('待匹配需求',fmt(realData.unmatched_users),'偏好已保留，数据源未返回报价')}</div>`;}
function realIntentGroups(){return realDistribution(realData.intent_groups);}
function realAirlines(){return `<section class="card"><div class="real-panel-heading"><h2>航司偏好</h2><span>本人主动选择 · 可多选</span></div>${realData.airline_preferences.length?`<div class="table-container"><table><thead><tr><th>航空公司</th><th>指定</th><th>排除</th><th>待匹配</th></tr></thead><tbody>${realData.airline_preferences.map(a=>`<tr><td>${realButton(a.name,'filter-airline',`data-code="${esc(a.code)}"`)}</td><td>${a.preferred_users}</td><td>${a.excluded_users}</td><td>${a.unmatched_users}</td></tr>`).join('')}</tbody></table></div>`:'<p class="real-empty">尚无主动指定或排除的航司。</p>'}<p class="real-caption">无报价保留偏好，不自动改推其他航司。</p></section>`;}
function realPortrait(){return `<div class="real-profile-grid">${[['兴趣主题','theme'],['同行方式','party'],['住宿要求','lodging_priority'],['日期弹性','date_flexibility']].map(([title,key])=>`<section class="card"><h2>${title}</h2>${realDistribution(realData.profile_dimensions[key])}</section>`).join('')}<section class="card"><h2>预算分布</h2>${realDistribution(realData.budget_groups)}<p class="real-caption">用户填写的每名成人全程预算</p></section><section class="card"><h2>浏览操作</h2>${realDistribution(realData.behavior_groups)}<p class="real-caption">观察窗口内记录次数；不等于成交</p></section></div>`;}
function realDecisionView(){return `<section class="card"><div class="row"><h2>决策建议</h2>${realButton(realBusy?'正在整理…':'整理客群建议','analyze',realBusy||!realData.population?'disabled':'')}</div>${realDecision?`<p>${esc(realDecision.summary)}</p><ul>${realDecision.actions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><small>${realDecision.model_called?'本地模型整理':'规则整理'} · ${esc(realDecision.status)}</small>`:'<p>结合真实意向阶段、近期目的地关注和主动偏好，整理营销决策草稿。</p>'}</section>`;}
function realOverview(){return realMetrics()+`<div class="real-overview-grid"><section class="card"><div class="real-panel-heading"><h2>客群画像</h2>${realButton('查看全部','navigate','data-to="insights"')}</div><div class="real-summary-grid"><div><h3>兴趣主题</h3>${realDistribution(realData.profile_dimensions.theme,4)}</div><div><h3>同行方式</h3>${realDistribution(realData.profile_dimensions.party,4)}</div></div></section><section class="card"><h2>意向阶段</h2>${realIntentGroups()}</section><section class="card"><h2>近期热门</h2>${realHotspots()}</section><section class="card"><h2>浏览操作</h2>${realDistribution(realData.behavior_groups,5)}</section></div>`+realDecisionView();}
function realFilters(){return `<div class="real-audience-filters"><label class="field real-search"><span>检索用户</span><input id="real-audience-search" aria-label="搜索真实旅客" value="${esc(realSearch)}" placeholder="编号、城市、兴趣或航司"></label>${[['意向阶段','stage',realStage,Object.keys(realData.intent_groups).map(v=>[v,v])],['指定航司','airline',realAirline,Object.entries(realData.airline_names)],['目的地','destination',realDestination,[...new Set(realData.profiles.map(p=>p.destination).filter(Boolean))].sort().map(v=>[v,v])]].map(([label,key,value,options])=>`<label class="field"><span>${label}</span><select data-real-filter="${key}"><option value="">全部</option>${options.map(([v,t])=>`<option value="${esc(v)}" ${value===v?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`).join('')}<label class="field"><span>排列顺序</span><select data-real-filter="sort">${[['recent','最近活跃'],['date','出发日期'],['budget','预算从低到高']].map(([v,t])=>`<option value="${v}" ${realSort===v?'selected':''}>${t}</option>`).join('')}</select></label></div>`;}
function realAudience(forDelivery=false){
 const items=realFiltered();realPage=Math.min(realPage,Math.max(1,Math.ceil(items.length/realPageSize)));const visible=items.slice((realPage-1)*realPageSize,realPage*realPageSize);
 return `<section class="card real-audience ${forDelivery?'delivery-audience':''}"><div class="real-panel-heading"><h2>${forDelivery?'触达名单':'用户画像'}</h2><span>${fmt(items.length)} 位匹配 / ${fmt(realData.population)} 位共享用户</span></div>${realFilters()}<div class="real-list-tools"><label><input type="checkbox" data-real-unmatched ${realOnlyUnmatched?'checked':''}> 仅看待匹配需求</label><span>已选 <b data-real-selection-count>${realSelected.size}</b> 位</span><div>${realButton('选择本页','select-page')}${realButton('清空选择','clear-selection')}${realButton('重置筛选','reset-filters')}</div></div><div class="table-container" tabindex="0" aria-label="用户画像明细，可横向滚动"><table><thead><tr>${forDelivery?'<th>选择</th><th>旅客 / 行程</th><th>日期 / 预算</th><th>意向 / 航司</th><th>操作</th>':'<th>选择</th><th>匿名用户 / 兴趣</th><th>出行方向 / 同行</th><th>航司 / 意向</th><th>日期 / 预算</th><th>浏览操作 / 状态</th><th>操作</th>'}</tr></thead><tbody>${visible.map(p=>forDelivery?realDeliveryRow(p):`<tr data-real-user="${esc(p.user_id)}"><td><input type="checkbox" data-real-select="${esc(p.user_id)}" aria-label="选择${esc(p.user_id)}" ${realSelected.has(p.user_id)?'checked':''}></td><td><strong>${esc(p.user_id)}</strong><small>${esc(p.theme||'兴趣待确认')}</small></td><td>${esc(p.origin||'待确认')} → ${esc(p.destination||'待确认')}<small>${esc(p.party||'同行待确认')} · ${esc(p.preferences.pace||'节奏待确认')}</small></td><td class="real-wrappable">${esc(realCarrierNames(p.preferences.required_airlines))}<small>${esc(p.intent_stage)}</small></td><td>${esc(p.start_date||'待确认')}<small>${p.preferences.trip_budget==null?'预算待确认':'每名成人 ¥'+fmt(p.preferences.trip_budget)}</small></td><td>${fmt(Object.values(p.events_30d).reduce((a,b)=>a+b,0))} 次<small>${p.flight_search_result?.status==='empty'?'偏好已存 · 航班待匹配':esc(new Date(p.last_active_at).toLocaleDateString('zh-CN'))}</small></td><td>${realButton('查看画像','profile',`data-user="${esc(p.user_id)}"`)}</td></tr>`).join('')||`<tr><td colspan="${forDelivery?5:7}" class="delivery-table-empty">${realData.population?'当前筛选没有匹配旅客':'暂无已共享旅客'}</td></tr>`}</tbody></table></div><div class="pagination real-pagination"><label>每页 <select data-real-page-size>${[10,20,50].map(n=>`<option value="${n}" ${n===realPageSize?'selected':''}>${n} 位</option>`).join('')}</select></label><span>第 ${realPage} / ${Math.max(1,Math.ceil(items.length/realPageSize))} 页</span><div>${realButton('上一页','prev',realPage===1?'disabled':'')}${realButton('下一页','next',realPage*realPageSize>=items.length?'disabled':'')}</div></div></section>`;
}
function realTrips(){
 const travelers=realData.profiles.filter(p=>p.has_saved_plan);
 if(!travelers.length)return realBlank('尚无已共享的旅行方案。旅客确认保存后，可在此查看真实条件并核验实时航班。');
 return `<div class="trip-layout"><aside class="card trip-traveler-list"><h3>旅客方案</h3><div class="trip-user-list">${travelers.map(p=>`<button type="button" class="trip-user ${tripPlan?.user_id===p.user_id?'active':''}" data-real-action="plan" data-user="${esc(p.user_id)}"><strong>${esc(p.origin)} → ${esc(p.destination)}</strong><span>${esc(p.user_id)}</span><small>${esc(p.start_date||'日期待确认')} · ${esc(p.intent_stage)}</small></button>`).join('')}</div></aside>${tripPlan?tripDetail():'<section class="card"><p>选择旅客查看本人已保存的旅行方案。</p></section>'}</div>`;
}
function realDelivery(){
 return `<div class="delivery-context"><span>共享旅客 <strong>${fmt(realData.population)}</strong></span><span>已建活动 <strong>${fmt(realData.campaigns.length)}</strong></span><span class="delivery-status"><i aria-hidden="true"></i>名单准备</span></div><div class="delivery-workspace">${realAudience(true)}<aside class="delivery-sidebar" aria-label="触达准备"><section class="card delivery-selection" data-delivery-selection>${realDeliverySelection()}</section>${realData.campaigns.length?`<section class="card delivery-recent"><div class="real-panel-heading"><h3>最近活动</h3>${realButton('查看全部','campaign-list')}</div><ul>${realData.campaigns.slice(0,3).map(c=>`<li><strong>${esc(c.name)}</strong><span>${fmt(c.user_ids.length)} 位旅客 · ${esc(c.status)}</span></li>`).join('')}</ul></section>`:''}</aside></div>`;
}
function realDeliveryRow(p){
 return `<tr data-real-user="${esc(p.user_id)}"><td><input type="checkbox" data-real-select="${esc(p.user_id)}" aria-label="选择${esc(p.user_id)}" ${realSelected.has(p.user_id)?'checked':''}></td><td><strong>${esc(p.origin||'待确认')} → ${esc(p.destination||'待确认')}</strong><small>${esc(p.user_id)} · ${esc(p.party||'同行待确认')}</small></td><td>${esc(p.start_date||'日期待确认')}<small>${p.preferences.trip_budget==null?'预算待确认':'每名成人 ¥'+fmt(p.preferences.trip_budget)}</small></td><td><span class="delivery-intent">${esc(p.intent_stage)}</span><small>${esc(realCarrierNames(p.preferences.required_airlines))}</small></td><td>${realButton('查看画像','profile',`data-user="${esc(p.user_id)}"`)}</td></tr>`;
}
function realDeliverySelection(){
 const selected=realData.profiles.filter(p=>realSelected.has(p.user_id)),destinations={};
 selected.forEach(p=>{const city=p.destination||'目的地待确认';destinations[city]=(destinations[city]||0)+1;});
 return `<div class="delivery-selection-head"><h2>已选旅客</h2><span class="delivery-count" data-delivery-selected-count aria-live="polite">${fmt(selected.length)}<span>位</span></span></div><div class="delivery-picked">${selected.length?`<ul>${Object.entries(destinations).sort((a,b)=>b[1]-a[1]).slice(0,4).map(([city,n])=>`<li><span>${esc(city)}</span><strong>${fmt(n)} 位</strong></li>`).join('')}</ul>`:'<p class="delivery-empty">从名单中勾选旅客</p>'}</div><dl class="delivery-readiness"><div><dt>发送渠道</dt><dd>尚未接入</dd></div><div><dt>活动状态</dt><dd>保存后待审核</dd></div></dl><button type="button" class="primary delivery-create" data-real-action="new-campaign" ${selected.length?'':'disabled'}>创建活动 <span aria-hidden="true">↗</span></button>`;
}
function realEvaluation(){return realMetrics()+`<section class="card"><h2>观察结果</h2><p>${esc(realData.window_start.slice(0,10))} 至 ${esc(realData.updated_at.slice(0,10))}，共记录 ${fmt(realData.observed_events)} 次实际交互。</p>${realIntentGroups()}<p>实际订票、营销转化和收入尚未接入，暂不计算转化率或收益。</p></section>`;}
function renderRealMarketing(){
 if(!realData)return;
 const current=page();$('#page-title').textContent=titles[current]||titles.overview;
 $('#app').dataset.view=current;
 $$('[data-nav]').forEach(e=>e.classList.toggle('active',e.dataset.nav===current));
 $('#campaign-count').textContent=realData.campaigns.length;$('#active-campaign').hidden=true;
 const controls=`<div class="real-data-toolbar"><div><strong>真实用户画像</strong><small>${esc(new Date(realData.updated_at).toLocaleString('zh-CN'))} 更新 · 自动同步</small></div><label>观察窗口 <select id="real-window"><option value="7" ${realWindow===7?'selected':''}>近7天</option><option value="30" ${realWindow===30?'selected':''}>近30天</option><option value="90" ${realWindow===90?'selected':''}>近90天</option></select></label>${realData.cohort_options?.length?`<label>分析样本 <select id="real-cohort"><option value="">全部当前共享用户</option>${realData.cohort_options.map(c=>`<option value="${esc(c.id)}" ${realCohort===c.id?'selected':''}>${esc(c.label)}</option>`).join('')}</select></label>`:''}${realButton('导出案例','export-case')}${realButton('刷新数据','refresh')}${realData.campaigns.length?`<label>当前活动 <select id="real-current-campaign"><option value="">选择活动</option>${realData.campaigns.map(c=>`<option value="${esc(c.id)}" ${realCampaign?.id===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>`:''}</div>`;
 const views={overview:realOverview,insights:()=>realMetrics()+realPortrait()+`<div class="real-overview-grid">${realAirlines()}<section class="card"><h2>近期热门</h2>${realHotspots()}</section></div>`+realDecisionView(),audience:realAudience,trips:realTrips,
  routes:()=>tripPlan?`<section class="card"><h2>实时航班</h2><p>${esc(tripPlan.origin)} → ${esc(tripPlan.destination)}</p>${liveFlightPanel(tripPlan)}</section>`:realTrips(),
  creative:()=>realDecisionView()+realCampaignPanel(),delivery:()=>realDelivery()+realCampaignPanel(),evaluation:()=>realEvaluation()+realCaseEvidence()+realCampaignPanel()};
 const simulationEntry=!realData.population?'<section class="card"><h2>查看项目演示</h2><p>当前没有已共享的正式用户资料。万人模拟案例可展示八个页面的完整流程，数据与正式用户独立存放。</p><a class="primary small" href="http://127.0.0.1:8766/marketing/#trips" style="display:inline-block;text-decoration:none">打开万人模拟演示 →</a></section>':'';
 $('#app').innerHTML=heading(titles[current]||titles.overview)+simulationEntry+controls+(views[current]||realOverview)();
}
async function refreshRealMarketing(quiet=false){
 const fresh=await api('real/dashboard?window_days='+realWindow+'&cohort='+encodeURIComponent(realCohort)),valid=new Set(fresh.profiles.map(p=>p.user_id));
 for(const id of realSelected)if(!valid.has(id))realSelected.delete(id);
 if(tripPlan){const current=fresh.profiles.find(p=>p.user_id===tripPlan.user_id);if(!current||!current.has_saved_plan||current.revision!==tripPlan.profile_revision)tripPlan=null;}
 if(realData&&JSON.stringify(realData.profiles)!==JSON.stringify(fresh.profiles))realDecision=null;realData=fresh;meta.generation=fresh.generation;if(realCampaign)realCampaign=await api('real/campaigns/'+realCampaign.id);
 if(!quiet||(!modal.open&&!document.activeElement?.closest('form')&&!document.activeElement?.matches('input,select,textarea')))renderRealMarketing();
}
async function realMarketingAction(b){
 const action=b.dataset.realAction||b.dataset.action;
 if(action.startsWith('workflow-'))return realWorkflowAction(action);
 if(action==='close'){close();return;}
 if(action==='navigate'){location.hash=b.dataset.to;return;}
 if(action==='refresh'){await refreshRealMarketing();return;}
 if(action==='prev'||action==='next'){realPage+=action==='next'?1:-1;renderRealMarketing();return;}
 if(action==='select-page'){realFiltered().slice((realPage-1)*realPageSize,realPage*realPageSize).forEach(p=>realSelected.add(p.user_id));renderRealMarketing();return;}
 if(action==='clear-selection'){realSelected.clear();renderRealMarketing();return;}
 if(action==='reset-filters'){realSearch=realStage=realAirline=realDestination='';realOnlyUnmatched=false;realPage=1;renderRealMarketing();return;}
 if(action==='filter-airline'){realAirline=b.dataset.code;realStage=realDestination=realSearch='';realOnlyUnmatched=false;realPage=1;location.hash='audience';return;}
 if(action==='export-case'){const data=await api('real/export?window_days='+realWindow+'&cohort='+encodeURIComponent(realCohort));download('匿名用户案例_'+new Date().toISOString().slice(0,10)+'.json',JSON.stringify(data,null,2));toast('匿名画像、偏好更新和本站行为记录已导出');return;}
 if(action==='plan'){tripPlan=await api('real/plans/'+b.dataset.user);renderRealMarketing();return;}
 if(action==='profile'){
  const p=await api('real/profiles/'+b.dataset.user);
  const labels={origin:'出发地',destination:'目的地',start_date:'出发日期',days:'旅行天数',party:'同行方式',pace:'旅行节奏',theme:'兴趣主题',planning_stage:'出游阶段',trip_budget:'全程预算上限',trip_budget_min:'全程预算下限',airfare_cap:'单程机票上限',airfare_min:'单程机票下限',required_airlines:'指定航司',excluded_airlines:'排除航司',date_flexibility:'日期弹性',lodging_priority:'住宿要求',fallback_policy:'备选许可',overbudget_policy:'超预算处理',preferred_attractions:'景点偏好',flight_budget_policy:'航班预算规则'};
  const value=(key,v)=>['required_airlines','excluded_airlines'].includes(key)?(v?.length?realCarrierNames(v):'未限制'):v==null||v===''?'尚未表达':['trip_budget','trip_budget_min','airfare_cap','airfare_min'].includes(key)?'¥'+fmt(v):key==='days'?v+'天':Array.isArray(v)?v.join('、')||'未选择':String(v);
  open(`<div class="real-profile-heading"><h2>动态画像</h2><span class="badge green">${esc(p.intent_stage)}</span></div><p>${esc(p.user_id)} · ${esc(p.origin||'待确认')} → ${esc(p.destination||'待确认')}</p><div class="real-profile-next"><strong>下一步建议</strong><p>${esc(p.next_action)}</p>${p.flight_search_result?.status==='empty'?'<small>该数据源未返回符合条件的报价，用户偏好仍保留。</small>':''}</div><h3>主动偏好</h3><dl class="real-preference-grid">${Object.entries(labels).map(([key,label])=>`<div><dt>${label}</dt><dd>${esc(value(key,p.preferences[key]))}</dd></div>`).join('')}</dl><div class="real-profile-columns"><section><h3>偏好更新</h3>${p.profile_history.slice(0,20).map(h=>`<details class="real-history"><summary>${esc(new Date(h.at).toLocaleString('zh-CN'))} · 版本 ${h.revision}</summary><dl>${Object.entries(labels).map(([key,label])=>`<div><dt>${label}</dt><dd>${esc(value(key,h.preferences[key]))}</dd></div>`).join('')}</dl></details>`).join('')||'<p>暂无偏好更新。</p>'}</section><section><h3>行为轨迹</h3><ol class="real-timeline">${p.observations.slice(-60).reverse().map(e=>`<li><strong>${esc(realEventLabel(e))}</strong><small>${esc(new Date(e.at).toLocaleString('zh-CN'))} · ${esc(e.destination||'方向待确认')}</small>${e.result?`<small>${esc(realCarrierNames(e.result.required_airlines))} · ${esc(e.result.interpretation)}</small>`:''}</li>`).join('')||'<li>尚无本站行为记录。</li>'}</ol></section></div><p class="real-caption">展示近期60条行为和20次偏好更新，完整观察窗口记录可从“导出案例”获取。</p>`);return;
 }
 if(action==='analyze'){
  if(realBusy)return;realBusy=true;renderRealMarketing();
  try{realDecision=await api('real/analysis',{window_days:realWindow,cohort:realCohort});}finally{realBusy=false;renderRealMarketing();}return;
 }
 if(action==='new-campaign'){
  if(!realSelected.size){toast('请先在潜客与画像中选择真实旅客');location.hash='audience';return;}
  open(`<h2>创建活动</h2><form id="real-campaign-form">${field('活动名称','name','','text','required maxlength="80"')}<p>已选择 ${realSelected.size} 位真实旅客；保存时重新核验共享状态。</p><button class="primary" type="submit">保存决策名单</button></form>`);return;
 }
 if(action==='campaign-list'){open(`<h2>我的活动</h2>${realData.campaigns.map(c=>`<section><h3>${esc(c.name)}</h3><p>${c.user_ids.length} 位当前仍共享的旅客 · ${esc(c.status)} · 发送 ${c.sent} 次</p></section>`).join('')||'<p>尚无真实客群活动。</p>'}`);return;}
 if(action==='models'){open(`<h2>数据与模型</h2><p>正式客群：${realData.population} 位已同意共享的本站用户。</p><p>注册账号按固定用户编号关联画像；原匿名会话不自动转入新账号。原模拟用户用于训练和离线测试。</p><p>${esc(realData.algorithm)}</p><p>本地模型：${esc(realData.generation.label)}</p>`);return;}
 if(action==='trip-export'&&tripPlan){download('真实旅客旅行方案.json',JSON.stringify(tripPlan,null,2));return;}
 if(action==='trip-ai'){toast('此处查看旅客已确认方案；修改建议由旅客在个人页确认。');return;}
}
async function realMarketingSubmit(form){
 if(form.id==='real-campaign-form'){
  const created=await api('real/campaigns',{name:new FormData(form).get('name'),user_ids:[...realSelected]});realCampaign=await api('real/campaigns/'+created.id);realObservation=null;realForecast=null;close();await refreshRealMarketing();toast('真实客群决策名单已保存');
 }
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-real-action]');if(!b||b.disabled)return;e.preventDefault();realMarketingAction(b).catch(error=>toast(error.message));});
document.addEventListener('change',e=>{
 if(e.target.id==='real-forecast-snapshot'&&e.target.value)api('real/forecasts/'+e.target.value).then(f=>{realForecast=f;renderRealMarketing();}).catch(error=>toast(error.message));
 if(e.target.id==='real-current-campaign'){realCampaign=null;realObservation=null;realForecast=null;if(e.target.value)api('real/campaigns/'+e.target.value).then(c=>{realCampaign=c;renderRealMarketing();}).catch(error=>toast(error.message));else renderRealMarketing();}
 if(e.target.id==='real-cohort'){realCohort=e.target.value;realDecision=null;realSelected.clear();realPage=1;refreshRealMarketing().catch(error=>toast(error.message));}
 if(e.target.id==='real-window'){realWindow=Number(e.target.value);realDecision=null;refreshRealMarketing().catch(error=>toast(error.message));}
 if(e.target.matches('[data-real-select]')){e.target.checked?realSelected.add(e.target.dataset.realSelect):realSelected.delete(e.target.dataset.realSelect);const count=$('[data-real-selection-count]');if(count)count.textContent=realSelected.size;const panel=$('[data-delivery-selection]');if(panel)panel.innerHTML=realDeliverySelection();}
 if(e.target.matches('[data-real-filter]')){const k=e.target.dataset.realFilter,v=e.target.value;if(k==='stage')realStage=v;if(k==='airline')realAirline=v;if(k==='destination')realDestination=v;if(k==='sort')realSort=v;realPage=1;renderRealMarketing();}
 if(e.target.matches('[data-real-page-size]')){realPageSize=Number(e.target.value);realPage=1;renderRealMarketing();}
 if(e.target.matches('[data-real-unmatched]')){realOnlyUnmatched=e.target.checked;realPage=1;renderRealMarketing();}
});
document.addEventListener('input',e=>{if(e.target.id==='real-audience-search'){realSearch=e.target.value;realPage=1;const pos=e.target.selectionStart;renderRealMarketing();const input=$('#real-audience-search');input.focus();input.setSelectionRange(pos,pos);}});

function realCaseEvidence(){
 const e=realData.case_evidence;if(!e)return '';const p=e.people,f=e.feedback,q=e.interest_quality;
 return `<section class="section two-cols"><div class="card"><h2>查询流程</h2><p>${realData.cohort?esc(realData.cohort.label)+' · ':''}当前共享 ${fmt(e.population)} 个账号，以下各项按用户去重，可交叉。</p>${realDistribution({'已保存方案':p.saved_plan,'发起查询':p.search_requested,'返回有效报价':p.priced_result,'仅返回航班目录':p.unpriced_inventory,'数据源未返回报价':p.confirmed_empty,'查询未完成':p.query_failed,'请求暂不可用':p.unavailable_request,'比较候选':p.flight_previewed,'选择并保存':p.flight_selected,'主动排除候选':p.flight_rejected})}<p>兴趣已主动表达 ${fmt(q.explicit_people)} 人；未填写或历史待确认 ${fmt(q.unfilled_or_unverified_people)} 人。历史缺失操作不补造，选择不等于购票。</p></div><div class="card"><h2>使用评价</h2><p>另行同意共享评价 ${fmt(f.respondents)} 人；已评分 ${fmt(f.rating_respondents)} 人。${f.mean_rating==null?'尚无评分。':'平均方案评分 '+f.mean_rating.toFixed(2)+' / 5。'}</p>${realDistribution(f.suitability)}${realDistribution(f.nonadoption_reasons)}<p>仅计观察窗口内每人最新一份共享评价。未填写不解释为不满意，评分不代表购票转化。</p></div></section>`;
}

function realCampaignPanel(){
 if(!realCampaign)return '<section class="card"><h2>活动流程</h2><p>先创建活动，或从顶部选择已有活动，继续素材、审核和执行准备。</p></section>';
 const c=realCampaign,approved=c.review?.approved&&!c.stale;
 return `<section class="card real-campaign-workflow"><h2>活动流程</h2><p><strong>${esc(c.name)}</strong> · ${esc(c.status)} · 当前共享成员 ${fmt(c.user_ids.length)} 人 · 版本 ${c.revision}</p><div class="real-workflow-actions">${realButton('制作素材','workflow-generate',realBusy?'disabled':'')}${realButton('查看后续观察','workflow-observe')}${realButton('保存预测基线','workflow-forecast')}</div>${(c.materials||[]).map(m=>`<article class="real-material"><h3>${esc(m.title)}</h3><p>${esc(m.text)}</p><small>${esc(m.destination)} · ${esc(m.status)} · ${esc(m.model||'本地规则')} · ${esc(m.facts)}</small></article>`).join('')}${c.materials?.length?`<fieldset class="real-review-checks"><legend>素材审核</legend><label><input type="checkbox" data-review-check="facts_checked"> 已核对目的地与本人确认条件</label><label><input type="checkbox" data-review-check="consent_checked"> 已核对当前共享授权</label><label><input type="checkbox" data-review-check="boundary_checked"> 无虚构价格、优惠、预订或效果承诺</label></fieldset><div class="real-workflow-actions">${realButton('审核通过','workflow-approve')}${realButton('退回重做','workflow-reject')}${realButton('生成本地执行包','workflow-package',approved?'':'disabled')}</div>`:''}${c.execution_package?`<p>执行包已准备 ${fmt(c.execution_package.records.length)} 人，暂缓 ${fmt(c.execution_package.blocked.length)} 人；尚未发送消息。</p>${realButton('下载执行包','workflow-download')}`:''}${realObservation?`<section><h3>后续观察</h3><p>从 ${esc(new Date(realObservation.since).toLocaleString('zh-CN'))} 起观察 ${fmt(realObservation.currently_shared_members)} 名当前成员。</p>${realDistribution(realObservation.observed_people)}<p>${esc(realObservation.boundary)}</p></section>`:''}${c.forecast_snapshots?.length?`<label class="field"><span>已保存预测</span><select id="real-forecast-snapshot"><option value="">选择保存时点</option>${c.forecast_snapshots.map(f=>`<option value="${esc(f.id)}" ${realForecast?.id===f.id?'selected':''}>${esc(new Date(f.created_at).toLocaleString('zh-CN'))}</option>`).join('')}</select></label>`:''}${realForecast?`<section><h3>预测基线</h3><p>${esc(realForecast.status)}；可排序 ${fmt(realForecast.predictions.length)} 人，历史不足 ${fmt(realForecast.insufficient_history_people)} 人。</p><p>${esc(realForecast.target)}。截至 ${esc(new Date(realForecast.horizon_end).toLocaleString('zh-CN'))} 后验证。</p>${realButton('查看预测验证','workflow-forecast-result')}${realForecast.metrics?`<p>有相关后续行为 ${fmt(realForecast.metrics.eligible_people)} 人；Recall@3 ${realForecast.metrics.recall_at_3==null?'暂无可计算样本':pct(realForecast.metrics.recall_at_3)}。</p>`:''}</section>`:''}<p>此处只生成本地执行准备包，外部渠道未接入。匿名画像共享不等于外部联系授权，不生成曝光、点击或订单。</p></section>`;
}
async function realWorkflowAction(action){
 if(!realCampaign)return toast('请先选择活动');if(realBusy)return;
 const id=realCampaign.id,body={expected_revision:realCampaign.revision};
 if(action==='workflow-download'){realCampaign=await api('real/campaigns/'+id);if(!realCampaign.execution_package)return toast('授权或条件已变化，请重新审核');download('真实客群_本地执行包.json',JSON.stringify(realCampaign.execution_package,null,2));return;}
 if(action==='workflow-approve')for(const key of ['facts_checked','consent_checked','boundary_checked'])body[key]=document.querySelector('[data-review-check='+key+']')?.checked===true;
 realBusy=true;
 try{
  if(action==='workflow-generate')realCampaign=await api('real/campaigns/'+id+'/materials',body);
  if(action==='workflow-approve'||action==='workflow-reject')realCampaign=await api('real/campaigns/'+id+'/review',{...body,verdict:action==='workflow-approve'?'approve':'reject'});
  if(action==='workflow-package')realCampaign=await api('real/campaigns/'+id+'/package',{...body,confirmed:true});
  if(action==='workflow-observe')realObservation=await api('real/campaigns/'+id+'/observations');
  if(action==='workflow-forecast')realForecast=await api('real/campaigns/'+id+'/forecast',{});
  if(action==='workflow-forecast-result'&&realForecast)realForecast=await api('real/forecasts/'+realForecast.id);
  if(['workflow-generate','workflow-approve','workflow-reject','workflow-package'].includes(action))await refreshRealMarketing(true);
 }finally{realBusy=false;renderRealMarketing();}
}
