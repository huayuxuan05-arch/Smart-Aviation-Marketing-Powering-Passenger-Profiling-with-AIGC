'use strict';
let assistantDraft=null;
function initAssistant(){
 $('#assistant-parse').disabled=false;
}
function assistantValue(value){return value===null||value===undefined||value===''?'尚未确定':Array.isArray(value)?value.map(v=>personalMeta?.airlines?.[v]||v).join('、')||'不限':String(value);}
function assistantPlanPreview(p){
 if(!p?.ai_planning?.content_generated)return '';
 return `<details class="assistant-inherited assistant-plan-preview"><summary>旅行草稿</summary><h4>每日行程</h4>${p.daily_itinerary.map(d=>`<h4>${esc(d.date)} · ${esc(d.title)}</h4><ul>${d.blocks.map(b=>`<li>${esc(b.time)} · ${esc(b.activity)}：${esc(b.detail)}</li>`).join('')}</ul>`).join('')}<h4>住宿安排</h4><p>${esc(p.lodging.area)} · ${esc(p.lodging.type)}</p><h4>费用预算</h4><p>每名成人全程 AI估算，非商户报价</p><ul>${p.budget.components.filter(c=>c.value!=null).map(c=>`<li>${esc(c.name)}：¥${fmt(c.value)}</li>`).join('')}</ul><h4>行前清单</h4><ul>${p.checklist.map(c=>`<li>${esc(c)}</li>`).join('')}</ul></details>`;
}
function renderAssistant(){
 const d=assistantDraft;if(!d){$('#assistant-draft').innerHTML='';return;}
 const metrics=(title,m)=>`<div class="assistant-metrics"><strong>${title}</strong>${m?`<p>${esc(m.destination)} · ${m.days}天 · ${esc(m.pace)}</p>${m.estimated_total!==null?`<p>每名成人情景总额 <b>¥${fmt(m.estimated_total)}</b></p><p>${m.budget_difference===null?'':m.budget_difference>0?'超出预算 ¥'+fmt(m.budget_difference):'估算未超出所填预算'}</p>`:'<p>非机票费用按行程安排估算。</p>'}`:'<p>暂无当前版本的已保存方案</p>'}</div>`;
 const c=d.comparison;
 $('#assistant-draft').innerHTML=`<div class="assistant-draft-head"><h3>${d.kind==='feedback'?'调整草稿':'需求草稿'}</h3><span>基于偏好版本 ${d.base_revision} · ${esc(d.engine.label)}</span></div>${d.notes.map(n=>`<p class="assistant-note">${esc(n)}</p>`).join('')}<div class="assistant-changes">${d.changes.map(x=>`<div data-assistant-field="${esc(x.field)}"><strong>${esc(x.label)}</strong><span>${d.base_revision?esc(assistantValue(x.before))+' → ':''}${esc(assistantValue(x.after))}</span><small>依据：${esc(x.evidence)}</small></div>`).join('')||'<p>暂未提取到明确调整。</p>'}</div>${d.inherited.length?`<details class="assistant-inherited"><summary>沿用已保存条件（${d.inherited.length}项）</summary><p>${d.inherited.map(esc).join('、')}。尚未保存的表单修改不自动纳入此草稿。</p></details>`:'<p class="assistant-note">首次需求：日期、天数、同行与预算口径需你明确确认。</p>'}
 ${d.defaults_applied.length?`<details class="assistant-inherited"><summary>未提及条件采用的默认安排（请核对）</summary><p>${d.defaults_applied.map(x=>`${esc(x.label)}：${esc(assistantValue(x.value))}`).join('；')}。需要调整时，可补充描述后重新解析。</p></details>`:''}
 ${d.questions.length?`<form id="assistant-clarify"><h3>补充信息</h3><div class="assistant-questions">${d.questions.map(q=>`<label class="assistant-question"><strong>${esc(q.label)}</strong><span>${esc(q.message)}</span>${q.options?`<select name="${esc(q.field)}" required><option value="">请选择</option>${q.options.map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select>`:`<input name="${esc(q.field)}" type="${q.type}" ${q.optional?'':'required'} ${q.type==='date'?"min='2024-01-01' max='2035-12-31'":q.field==='days'?"min='2' max='8' step='1'":"min='100' max='100000' step='any'"} placeholder="${q.optional?'尚未确定可留空':'请填写'}">`}${q.optional?'<small>留空并提交表示本次金额尚未确定。</small>':''}</label>`).join('')}</div><button type="submit" class="primary">补充信息并重新核验</button></form>`:''}
 ${d.error?`<p class="assistant-error">${esc(d.error)}；请修改描述后重新解析。</p>`:''}
 ${c.after?`<h3>方案预览</h3><div class="assistant-comparison">${metrics('原有方案',c.before)}${metrics('本次草稿',c.after)}</div>${c.estimated_delta!==null?`<p class="assistant-note">情景总额${c.estimated_delta===0?'未变化':c.estimated_delta>0?'增加 ¥'+fmt(c.estimated_delta):'减少 ¥'+fmt(-c.estimated_delta)}。这是同一规划工具的估算比较，不是实际节省证明。</p>`:''}<ul class="assistant-checks">${c.after.checks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
 ${assistantPlanPreview(d.preview)}<div class="assistant-confirmation">${d.can_confirm?`<label><input type="checkbox" id="assistant-consent"> 我已核对调整、沿用或默认条件；金额按每名成人口径。</label><button class="primary" type="button" id="assistant-confirm" disabled>${d.preview?'确认调整并保存新方案':'确认并保存出游意向'}</button>`:''}<button class="secondary" type="button" id="assistant-cancel">放弃草稿</button></div>`;
 compactPersonalNotes();
}
async function assistantRun(action){
 if(personalWorking)return;personalWorking=true;renderPersonal();$('#assistant-error').textContent='';$('#assistant-parse').textContent='正在理解需求并规划…';
 for(const b of document.querySelectorAll('.assistant-card button'))b.disabled=true;
 try{await action();}catch(e){$('#assistant-error').textContent=e.message;}finally{personalWorking=false;renderPersonal();$('#assistant-parse').disabled=false;$('#assistant-parse').textContent='理解需求并生成草稿';$('#assistant-example').disabled=false;renderAssistant();}
}
$('#assistant-request').addEventListener('submit',e=>{
 e.preventDefault();assistantRun(async()=>{
  const kind=$('[name=assistant-kind]:checked').value;
  if(kind==='feedback'&&!tripPlan)throw Error('请先生成或打开自己的旅行方案，再提出调整意见。');
  assistantDraft=null;
  assistantDraft=await personalApi('assistant/drafts',{text:$('#assistant-text').value,kind,expected_revision:personalState.revision,plan_id:kind==='feedback'?tripPlan.id:undefined});
 });
});
$('#assistant-example').addEventListener('click',()=>{
 $('#assistant-text').value=$('[name=assistant-kind]:checked').value==='feedback'?'行程太赶，想轻松一点，酒店太贵，日期不变。':`从北京出发去杭州，${personalState.preferences.start_date||'2026-11-15'}出发，玩四天，亲子出行，每名成人全程预算4000元，机票单程不超过1000元，想轻松一点，住宿安静。`;
 $('#assistant-text').focus();
});
$('#assistant-draft').addEventListener('change',e=>{if(e.target.id==='assistant-consent')$('#assistant-confirm').disabled=!e.target.checked;});
$('#assistant-draft').addEventListener('submit',e=>{
 if(e.target.id!=='assistant-clarify')return;e.preventDefault();const answers=Object.fromEntries(new FormData(e.target));
 assistantRun(async()=>{assistantDraft=await personalApi(`assistant/drafts/${assistantDraft.id}/clarify`,{version:assistantDraft.version,answers});});
});
$('#assistant-draft').addEventListener('click',e=>{
 if(e.target.id==='assistant-confirm'){
  if(!$('#assistant-consent')?.checked)return;
  assistantRun(async()=>{
   const result=await personalApi(`assistant/drafts/${assistantDraft.id}/confirm`,{version:assistantDraft.version,confirmed:true});
   if(result.plan)tripPlan=result.plan;assistantDraft=null;await refreshPersonal();renderPreferences();
   toast(result.plan?'调整已确认，已保存新方案和偏好版本':'出游意向已确认保存');
  });
 }
 if(e.target.id==='assistant-cancel')assistantRun(async()=>{await personalApi(`assistant/drafts/${assistantDraft.id}/cancel`,{version:assistantDraft.version});assistantDraft=null;toast('草稿已放弃，已保存内容未改变');});
});
if(personalMeta)initAssistant();
