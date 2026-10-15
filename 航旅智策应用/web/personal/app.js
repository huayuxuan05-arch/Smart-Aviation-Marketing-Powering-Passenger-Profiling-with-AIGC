'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('zh-CN',{maximumFractionDigits:0});
let personalState=null,personalMeta=null,personalWorking=false;
let personalDeleteId=null,personalDeleting=false;
const personalEmptyResult=$('#personal-result').innerHTML;
function button(text,action,cls='primary',extra=''){return `<button class="${cls}" data-action="${action}" ${extra}>${text}</button>`;}
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('visible'),3500);}
function download(name,content,type='application/json;charset=utf-8'){const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);}
async function personalApi(path,body){const r=await fetch('/api/personal/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}),value=await r.json();if(!r.ok)throw Error(value.error||'操作未完成');return value;}
function choice(label,name,value,values){return `<label class="field"><span>${label}</span><select name="${name}">${values.map(o=>{const [v,t]=Array.isArray(o)?o:[o,o];return `<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(t)}</option>`;}).join('')}</select></label>`;}
function input(label,name,value,type,attrs=''){return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${attrs}></label>`;}
function renderPreferences(){
 const p=personalState.preferences,m=personalMeta;
 $('#preference-fields').innerHTML=choice('从哪里出发','origin',p.origin,m.cities)+choice('想去哪里','destination',p.destination,['为我推荐',...m.destinations])+input('计划出发日期','start_date',p.start_date,'date',"min='2024-01-01' max='2035-12-31' required")+choice('旅行天数','days',p.days,[2,3,4,5,6,7,8].map(d=>[d,`${d}天${d-1}晚`]))+choice('与谁同行','party',p.party,m.parties)+choice('旅行节奏','pace',p.pace,m.paces)+choice('感兴趣的主题','theme',p.theme,m.themes)+input('每名成人全程预算 / 元','trip_budget',p.trip_budget??'','number',"min='100' max='100000'")+input('每名成人单程机票上限 / 元','airfare_cap',p.airfare_cap??'','number',"min='100' max='100000'")+`<details class="personal-more"><summary>细化我的需求 · 景点、住宿与备选</summary><div id="attraction-choices"></div>${choice('日期可以怎样调整','date_flexibility',p.date_flexibility,m.date_flexibilities)}${choice('住宿最重视什么','lodging_priority',p.lodging_priority,m.lodging_priorities)}${choice('可以展示哪些备选','fallback_policy',p.fallback_policy,m.fallback_policies)}${choice('超预算时先怎样处理','overbudget_policy',p.overbudget_policy,m.overbudget_policies)}</details>`;
 renderAttractions(p.destination,p.preferred_attractions||[]);
 $('#preference-fields').insertAdjacentHTML('afterbegin',choice('我现在的出游阶段','planning_stage',p.planning_stage,m.planning_stages));
 const unknown=document.createElement('option');unknown.value='';unknown.textContent='天数尚未确定';$('#preference-fields [name=days]').prepend(unknown);if(p.days===null)$('#preference-fields [name=days]').value='';
 updatePlanningStage();
}
function updatePlanningStage(){const intent=$('#personal-preferences [name=planning_stage]').value!=='制定行程';$('#personal-preferences [name=start_date]').required=!intent;$('#personal-preferences [type=submit]').textContent=intent?'保存我的出游意向':'生成我的旅行方案 ↗';}
function renderAttractions(destination,selected=[]){$('#attraction-choices').innerHTML=`<div class="field"><span>具体想去的景点 · 最多选3项</span>${(personalMeta.attractions[destination]||[]).map(x=>`<label class="attraction-option"><input type="checkbox" name="preferred_attractions" value="${esc(x)}" ${selected.includes(x)?'checked':''}>${esc(x)}</label>`).join('')||'<p class="personal-small">选定目的地后，可进一步选择景点。</p>'}</div>`;}
document.addEventListener('change',event=>{if(!event.target.closest('#personal-preferences'))return;if(event.target.name==='planning_stage')updatePlanningStage();if(event.target.name==='destination')renderAttractions(event.target.value);if(event.target.name==='preferred_attractions'&&document.querySelectorAll('#personal-preferences [name=preferred_attractions]:checked').length>3){event.target.checked=false;toast('具体景点最多选择3项');}});
function renderPersonal(){
 const labels={origin:'出发地',destination:'目的地',start_date:'日期',days:'天数',party:'同行',pace:'节奏',theme:'兴趣',trip_budget:'全程预算',airfare_cap:'机票上限',date_flexibility:'日期弹性',lodging_priority:'住宿偏好',fallback_policy:'备选许可',overbudget_policy:'超预算处理',preferred_attractions:'具体景点'};
 $('#personal-history').innerHTML=personalState.plans.length?personalState.plans.map(p=>`<div class="personal-history-item"><div class="personal-history-row"><button type="button" class="${tripPlan?.id===p.id?'active':''}" data-personal-action="open-plan" data-id="${esc(p.id)}"><strong>${esc(p.origin)} → ${esc(p.destination)}</strong><small>${esc(p.start_date)} · ${p.days}天 · 偏好版本${p.profile_revision}</small></button><button type="button" class="personal-plan-delete" data-personal-action="delete-plan" data-id="${esc(p.id)}" aria-label="删除${esc(p.origin)}至${esc(p.destination)} ${esc(p.start_date)}的方案" ${personalDeleting?'disabled':''}>删除</button></div>${personalDeleteId===p.id?`<div class="personal-delete-confirm" role="group" aria-label="删除方案确认"><span>删除此方案？</span><button type="button" class="personal-plan-delete" data-personal-action="confirm-delete-plan" data-id="${esc(p.id)}" ${personalDeleting?'disabled':''}>${personalDeleting?'删除中…':'确认删除'}</button><button type="button" data-personal-action="cancel-delete-plan" ${personalDeleting?'disabled':''}>取消</button></div>`:''}</div>`).join(''):'<p class="muted">暂无方案</p>';
 labels.planning_stage='出游阶段';$('#personal-profile').innerHTML=`<p>当前偏好版本 ${personalState.revision} · 来源：你主动填写的选择。</p><p>当前阶段：${esc(personalState.preferences.planning_stage)}${personalState.preferences.planning_stage!=='制定行程'?'；可留空日期和天数，仅保存意向，既有方案保留为历史版本。':''}</p>${personalState.profile_history.slice(0,3).map(p=>`<p>${esc(new Date(p.recorded_at).toLocaleString('zh-CN'))}<br>更新了${p.changed_fields.map(k=>labels[k]).join('、')}</p>`).join('')}`;
 if(tripPlan)$('#personal-result').innerHTML=tripDetail()+(tripPlan.date_comparisons?.length?`<section class="card personal-date-comparisons"><h3>按你的日期弹性比较</h3><p class="card-sub">选择日期后，生成新方案。</p>${tripPlan.date_comparisons.map(d=>`<div class="trip-alternative"><strong>${esc(d.start_date)}</strong><button type="button" class="secondary small" data-personal-action="apply-date" data-date="${esc(d.start_date)}">填入这个日期</button></div>`).join('')}</section>`:'');
 else $('#personal-result').innerHTML=personalEmptyResult;
 updatePersonalDisclosures();
 for(const b of document.querySelectorAll('#personal-preferences button'))b.disabled=personalWorking;
}
async function refreshPersonal(){personalState=await personalApi('state');renderPersonal();}
function currentPreferences(){const form=new FormData($('#personal-preferences'));return {...Object.fromEntries(form),preferred_attractions:form.getAll('preferred_attractions')};}
$('#personal-preferences').addEventListener('submit',async event=>{
 event.preventDefault();if(personalWorking)return;personalWorking=true;$('#personal-error').textContent='';renderPersonal();
 try{const preferences=currentPreferences(),intent=preferences.planning_stage!=='制定行程';const result=await personalApi(intent?'preferences':'plans',{preferences,expected_revision:personalState.revision});if(result.plan)tripPlan=result.plan;await refreshPersonal();toast(intent?'出游意向已保存，确定日期后再安排旅程':'旅行方案已生成并保存');if(!intent&&innerWidth<781)$('#personal-result').scrollIntoView({behavior:'smooth',block:'start'});}
 catch(error){$('#personal-error').textContent=error.message;}finally{personalWorking=false;renderPersonal();}
});
document.addEventListener('click',async event=>{
 const b=event.target.closest('[data-personal-action],[data-action]');if(!b)return;
 try{
  if(b.dataset.personalAction==='save-preferences'){
   if(personalWorking)return;personalWorking=true;renderPersonal();try{await personalApi('preferences',{preferences:currentPreferences(),expected_revision:personalState.revision});await refreshPersonal();toast('偏好已保存，下次生成将使用新偏好');}finally{personalWorking=false;renderPersonal();}
  }
  if(b.dataset.personalAction==='open-plan'){tripPlan=await personalApi('plans/'+b.dataset.id);renderPersonal();}
  if(b.dataset.personalAction==='delete-plan'){if(personalDeleting)return;personalDeleteId=b.dataset.id;renderPersonal();}
  if(b.dataset.personalAction==='cancel-delete-plan'){if(personalDeleting)return;personalDeleteId=null;renderPersonal();}
  if(b.dataset.personalAction==='confirm-delete-plan'){
   if(personalDeleting||personalDeleteId!==b.dataset.id)return;
   const id=b.dataset.id;personalDeleting=true;renderPersonal();
   try{personalState=await personalApi('plans/'+id+'/delete',{confirmed:true});if(tripPlan?.id===id)tripPlan=personalState.latest_plan;personalDeleteId=null;flightViews.forEach((view,key)=>{if(key.split('|')[1]===id)flightViews.delete(key);});toast('旅行方案已删除');}
   finally{personalDeleting=false;renderPersonal();}
  }
  if(b.dataset.personalAction==='apply-date'){$('#personal-preferences [name=start_date]').value=b.dataset.date;toast('已填入日期；点击生成后才保存新方案');$('#personal-preferences').scrollIntoView({behavior:'smooth',block:'start'});}
  if(b.dataset.action==='trip-ai'){
   if(tripBusy||!tripPlan)return;personalSectionState.set('trip-ai',true);tripBusy=true;const id=tripPlan.id;renderPersonal();try{const plan=await personalApi('plans/'+id+'/explain',{});if(tripPlan?.id===id)tripPlan=plan;toast('本地AI说明已保存，可继续编辑或导出');}finally{tripBusy=false;renderPersonal();}
  }
  if(b.dataset.action==='trip-export')download('华翼朝阳_我的旅行方案.json',JSON.stringify(tripPlan,null,2));
  if(b.dataset.action==='trip-print')download('华翼朝阳_我的旅行方案.html',`<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>华翼朝阳 我的旅行方案</title><style>body{max-width:850px;margin:35px auto;padding:20px;font:16px/1.85 'Microsoft YaHei',sans-serif;color:#27314b}pre{white-space:pre-wrap;font:inherit}button{padding:10px 18px}@media print{button{display:none}}</style><button onclick="window.print()">打印或保存PDF</button><pre>${esc(tripText(tripPlan))}</pre></html>`,'text/html;charset=utf-8');
 }catch(error){toast(error.message);$('#personal-error').textContent=error.message;}
});
(async()=>{try{personalMeta=await personalApi('bootstrap');personalState=personalMeta;tripPlan=personalMeta.latest_plan;renderPreferences();if(location.hash==='#assistant-text')personalSectionState.set('assistant',true);renderPersonal();if(typeof initAssistant==='function')initAssistant();if(location.hash==='#assistant-text'){$('#assistant-text').focus({preventScroll:true});$('#assistant-text').scrollIntoView({block:'center'});}}catch(error){$('#personal-error').textContent=error.message;}})();
