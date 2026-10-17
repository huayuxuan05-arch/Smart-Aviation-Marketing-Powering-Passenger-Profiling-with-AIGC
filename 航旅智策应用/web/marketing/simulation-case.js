'use strict';
// Loaded only by the isolated simulation server, never by the formal site.
(async()=>{
 const response=await fetch('/api/simulation-case');
 const study=await response.json();
 if(!response.ok||!study.is_synthetic)throw Error('模拟案例尚未就绪');
 const audience=study.campaign_members, example=study.example, e=study.case_evidence;
 const flightCache=new Map(),flightPending=new Set();
 window.simulationCaseStudy=study;
 window.getSimulationFlight=ident=>flightCache.get(ident);
 if(study.example_flights)flightCache.set(example.user_id,study.example_flights);
 function applyFlightBudget(plan,flight){
  plan.budget={...plan.budget,estimated_total:flight.estimated_total,difference:flight.budget_difference,
   components:flight.budget_components.map(c=>({...c,basis:'仿真预算'})),basis:'仿真机票与行程情景估算，金额按每名成人计算。'};
  plan.basis='本案例采用仿真数据。航班分别标注2024历史样本或仿真合成，行程与费用用于演示条件核验。';
 }
 function flightView(f){
  return `<section class="trip-subsection simulation-flight-details"><h3>仿真航班与票价明细</h3><p class="real-caption">每名成人 · 单程人民币；历史样本与合成记录分别标注。</p>${[['去程',f.outbound],['返程',f.inbound]].map(([label,leg])=>`<div class="trip-flight"><div><strong>${label}：${esc(leg.origin)} → ${esc(leg.destination)}</strong><small>${esc(leg.airline)} · ${esc(leg.flight_number)} · ${esc(leg.aircraft)}</small><small>${esc(leg.origin_airport)} → ${esc(leg.destination_airport)}</small><small>${esc(leg.departure)} → ${esc(leg.arrival)} · 直飞</small><small>${esc(leg.source_label)} · ${esc(leg.fare_basis)}</small>${leg.ground_transfer?`<small>${esc(leg.ground_transfer)}</small>`:''}</div><div><strong>¥${fmt(leg.price_cny)}</strong><small>${leg.within_airfare_cap?'机票上限内':'候选超出机票上限'}</small></div></div>`).join('')}<p><strong>往返机票合计 ¥${fmt(f.airfare_total)}；全程仿真预算 ¥${fmt(f.estimated_total)}</strong></p><p>原全程预算 ¥${fmt(f.specified_total)}；${f.budget_difference>0?'高出 ¥'+fmt(f.budget_difference)+'，保留原预算并提示调整':'当前估算在预算内'}。</p>${!f.within_airfare_caps?'<p class="notice amber">存在单程候选超出原机票上限，仅供比较，不作为合规推荐或已选航班。</p>':''}<p class="real-caption">合成航班编号以SIM-开头，供界面演示使用；覆盖数量不代表现实航班匹配率。</p></section>`;
 }
 const originalCampaignPanel=realCampaignPanel;
 realCampaignPanel=function(){return originalCampaignPanel()
  .replace('尚未发送消息。','本地模拟反馈已记录。')
  .replace('此处只生成本地执行准备包，外部渠道未接入。匿名画像共享不等于外部联系授权，不生成曝光、点击或订单。','本案例采用仿真数据与本地模拟通道，名单、素材和反馈均可按版本复核。')
  .replace('只观察活动准备后的本站行为；未发送外部消息，没有对照组，不能将自然变化归因于活动或推算转化收益。','后续关注与模拟触达反馈分开统计，各自保留事件来源和时间窗口。');};
 realCaseEvidence=function(){const c=study.flight_summary?.counts;return `<section class="card"><h2>仿真数据与预算核对</h2><p>10,000名虚拟旅客完成偏好录入；8,210名进入模拟共享范围，4,809份方案用于营销分析。</p>${c?`<p>${fmt(c.plans)}份已保存方案具有航班与费用明细：${fmt(c.historical_legs)}个航段引用2024历史样本，${fmt(c.synthetic_legs)}个航段由场景合成。</p><p>${fmt(c.within_airfare_caps)}份方案的往返候选均在单程机票上限内；${fmt(c.over_total_budget)}份全程估算高于原预算，页面提示调整并保留原条件。</p>`:''}<p class="real-caption">案例全部采用仿真数据；合成供给与反馈用于讲解网站流程，关注规则结果单独评价。</p></section>`;};
 const steps={
  trips:{number:1,title:'先核对旅客要去哪里、有哪些明确条件',result:`全部模拟用户10,000名，营销可见8,210名，其中4,809名已保存当前方案。`,
   purpose:'营销人员可以基于具体旅行需求准备服务，而不是只根据一个热门城市给所有人相同内容。',
   detail:`当前示例：${example.preferences.origin}至郑州，2024-10-01出发，3天，长者同行；每名成人全程5,000元、单程机票上限2,000元，仅选南方航空。这些条件在后续页面保留。`,next:'overview'},
  overview:{number:2,title:'看清分析范围，区分可以服务和仍需确认的人',result:'8,210名模拟共享用户：5,961名明确计划、1,576名探索灵感、673名暂缓出游。',
   purpose:'让营销人员先决定服务对象和任务优先级，暂缓者不进入本次行程服务活动。',
   detail:'三个目的地活动已完成本地准备。总人口、营销可见人数、已保存方案人数和活动人数采用不同口径，不能互相替代。',next:'insights'},
  insights:{number:3,title:'把兴趣、预算、同行方式和需求缺口放在一起看',result:'6,739名模拟共享用户有明确主题，1,471名未填写，保留未知状态。',
   purpose:'帮助营销人员选择合适的行程内容和待确认问题，避免将默认标签当成真实兴趣。',
   detail:'画像来自原模拟行为及明示场景赋值，不是受访者自报。预算和航司是约束，主题热度不能放宽这些约束。',next:'audience'},
  audience:{number:4,title:'从全体画像缩小到可复核的本次活动名单',result:`郑州活动选入${audience}名已保存方案、明确目的地的模拟用户。`,
   purpose:'把“有兴趣的人”转成有条件、有依据、有版本的服务准备名单，减少无差别推荐。',
   detail:'下表已限定郑州、明确计划与已保存方案；已选名单对应当前活动。可以查看每名虚拟旅客的偏好、历史行为及方案，不会自动把未共享者加入。',next:'routes'},
  routes:{number:5,title:'核对航司、日期与预算，查看仿真航班及费用',result:'5,829份已保存方案均补充去返程航班、机场、起降时间、票价和预算明细。',
   purpose:'防止把“适合推介的目的地”直接当成“符合条件且可以买的航班”。',
   detail:'示例保留南航、10月1日及2,000元单程上限。原表记录标注2024历史样本，补充场景以SIM-编号标注；超过机票或全程预算时保留原条件并提示调整。',next:'creative'},
  creative:{number:6,title:'让本地4B参与文案准备，同时固定事实来源',result:'三个活动分别实际调用Qwen3.5-4B选择素材版本，共3份素材；当前为“郑州行前准备”。',
   purpose:'将画像与行程转成服务内容，并通过程序填入事实、审核版本控制降低无依据描述的风险。',
   detail:'模型从核验过的文案版本选择，不编造票价、折扣或库存。本轮自动回放事实、模拟授权状态与边界三项检查，不能代替独立人工内容评价。',next:'delivery'},
  delivery:{number:7,title:'将名单与素材放入本地模拟发送队列',result:'三个活动模拟发送419条，模拟送达391条、失败28条。',
   purpose:'为后续经授权的渠道执行准备必要名单和素材，并把名单条件及审核状态绑定起来。',
   detail:'郑州141名、北京141名、兰州137名。消息仅进入本机模拟收件箱，不连接短信、邮件或微信；派发前复核名单和素材版本。模拟结果由明示概率生成。',next:'evaluation'},
  evaluation:{number:8,title:'分别复盘合成反馈和后续关注，核对分母与时间',result:'模拟阅读247名、点击70名、打开方案27名；另对418名有相关项的模拟成员计算关注Recall@3为0.9406。',
   purpose:'使营销人员知道哪些预测可以评价、采用什么分母，以及哪些结论仍缺少证据。',
   detail:'下方当前郑州活动为141名，Recall@3为0.9362。先在2024-09-24虚拟截点冻结，再导入原模拟后7天；该结果不是全体万人准确率、真实购买预测或营销因果效果。',next:'trips'}
 };
 const originalRender=renderRealMarketing;
 renderRealMarketing=function(){
  if(tripPlan&&flightCache.has(tripPlan.user_id))applyFlightBudget(tripPlan,flightCache.get(tripPlan.user_id));
  originalRender();
  if(!realData)return;
  const current=steps[page()]||steps.trips;
  const section=document.createElement('section');section.className='card simulation-step';
  section.innerHTML=`<div class="simulation-step-head"><span>模拟案例 · 第${current.number}/8步</span><a href="/case-study">完整案例说明</a></div><h2>${esc(current.title)}</h2><p><strong>${esc(current.result)}</strong></p><p>${esc(current.purpose)}</p><p class="real-caption">${esc(current.detail)}</p><a class="primary small simulation-next" href="#${current.next}">${current.number===8?'回到旅行方案':'下一步：'+titles[current.next]} →</a>`;
  const heading=document.querySelector('#app').firstElementChild;
  heading.after(section);
  // State changes were completed and stored by the replay; browsing stays read-only.
  document.querySelectorAll('[data-real-action="analyze"],[data-real-action="workflow-generate"],[data-real-action="workflow-approve"],[data-real-action="workflow-reject"],[data-real-action="workflow-package"],[data-real-action="workflow-forecast"],[data-action="new-campaign"]').forEach(b=>{b.disabled=true;b.title='本步已在模拟回放中完成，当前展示封存结果';});
  document.querySelectorAll('[data-review-check]').forEach(input=>{input.checked=!!realCampaign?.review?.checks?.[input.dataset.reviewCheck];input.disabled=true;});
  document.querySelectorAll('.simulation-next').forEach(a=>a.style.color='#fff');
  if(tripPlan){
   const ident=tripPlan.user_id,flight=flightCache.get(ident);
   document.querySelectorAll('[data-current-flights]').forEach(node=>node.outerHTML=flight?flightView(flight):'<p>正在载入仿真航班明细…</p>');
   if(!flight&&!flightPending.has(ident)){
    flightPending.add(ident);fetch('/api/simulation-flights/'+encodeURIComponent(ident)).then(r=>r.json()).then(value=>{if(!value.error)flightCache.set(ident,value);if(tripPlan?.user_id===ident)renderRealMarketing();}).catch(()=>{});
   }
  }
  if(['delivery','evaluation'].includes(page())&&study.delivery){
   const d=study.delivery,counts=d.counts;
   const labels={sent:'模拟发送',delivered:'模拟送达',read:'模拟阅读',clicked:'模拟点击',plan_viewed:'模拟打开方案',delivery_failed:'模拟发送失败'};
   const local=d.campaigns.find(c=>c.id===realCampaign?.id);
   const panel=document.createElement('section');panel.className='card simulation-feedback';
   panel.innerHTML=`<div class="real-panel-heading"><h2>本地模拟触达与反馈</h2><button class="secondary small" data-sim-replay>重播模拟事件</button></div><p>三个活动合计；${local?esc(local.name)+'：模拟发送'+local.counts.sent+'条、送达'+local.counts.delivered+'条。':''}</p><div class="metric-grid">${Object.entries(labels).map(([key,label])=>`<div class="model-card"><span>${label}</span><strong data-sim-count="${key}">${fmt(counts[key])}</strong></div>`).join('')}</div><p class="real-caption">场景参数：送达94%，送达后阅读68%，阅读后点击28%，点击后打开方案45%。本案例采用仿真数据与本地模拟通道。</p><p class="real-caption" data-sim-replay-status>本地模拟结果已保存，可用约6秒重播虚拟事件。</p>`;
   section.after(panel);
   const button=panel.querySelector('[data-sim-replay]');
   button.addEventListener('click',async()=>{
    button.disabled=true;const frames=d.replay_frames;
    for(const frame of frames){
     if(!panel.isConnected)break;
     panel.querySelectorAll('[data-sim-count]').forEach(node=>node.textContent=fmt(frame.counts[node.dataset.simCount]||0));
     panel.querySelector('[data-sim-replay-status]').textContent='正在重播模拟事件 · 虚拟时间 '+new Date(frame.at).toLocaleString('zh-CN');
     await new Promise(resolve=>setTimeout(resolve,140));
    }
    if(panel.isConnected){button.disabled=false;panel.querySelector('[data-sim-replay-status]').textContent='模拟事件重播完成，已恢复本轮案例结果。';}
   });
  }
 };
 const originalFiltered=realFiltered;
 realFiltered=function(){return originalFiltered().filter(p=>p.has_saved_plan);};
 realCampaign=study.campaign;
 realObservation=study.observation;
 realForecast=study.forecast;
 realDecision=study.decision;
 realSelected.clear();for(const id of study.campaign.user_ids)realSelected.add(id);
 realDestination='郑州';realStage='明确计划';
 tripPlan=await api('real/plans/'+encodeURIComponent(example.user_id));
 document.body.dataset.simulationReady='true';
 if(realData)renderRealMarketing();
})().catch(error=>{const p=document.createElement('p');p.className='notice red';p.textContent='模拟案例说明未加载：'+error.message;document.querySelector('.main-shell').prepend(p);});
