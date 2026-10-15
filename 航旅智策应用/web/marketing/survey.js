'use strict';
const schema=JSON.parse(document.getElementById('schema').textContent),form=document.getElementById('survey');
const followupIds=new Set(schema.followup_ids),legacyVersion='TRAVEL_SURVEY_20261014_V1';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stageLabels=['不计划出游','只有兴趣或想法','正在比较','已有明确计划','已预订部分产品','暂不确定'];
const uuid=()=>crypto.randomUUID?crypto.randomUUID():`R${Date.now()}_${Math.random().toString(36).slice(2)}`;
const newCode=()=>'TR_'+[...crypto.getRandomValues(new Uint8Array(6))].map(x=>x.toString(16).padStart(2,'0')).join('');
let respondentCode=newCode(),codeReused=false;
document.getElementById('respondent-code').textContent=respondentCode;
let section='';
form.innerHTML=schema.questions.map(q=>{
 const heading=q.section!==section?`<h2 data-section="${esc(q.section)}">${esc(q.section)}</h2>`:'';section=q.section;
 return heading+`<fieldset id="${q.id}" data-question="${q.id}"><legend><span>${q.id}</span> ${esc(q.label)}${q.required?'<b class="required">必答</b>':''}</legend>${q.city_filter?'<p class="hint">网页版仅显示所选城市的景点及未确定选项。</p>':''}<div class="choices">${q.options.map((o,i)=>`<label data-option="${i+1}"><input name="${q.id}" type="${q.type==='single'?'radio':'checkbox'}" value="${i+1}"><span>${esc(o)}</span></label>`).join('')}</div></fieldset>`;
}).join('')+'<p id="form-status" role="status"></p><button type="submit">检查并下载本次答卷 JSON</button>';
document.getElementById('intro').textContent=schema.intro;
document.getElementById('longitudinal').textContent=schema.longitudinal_note;
const checked=id=>[...form.querySelectorAll(`[name="${id}"]:checked`)].map(el=>Number(el.value));
const selected=id=>checked(id)[0]??null;
function syncVisibility(){
 const followup=document.getElementById('wave').value==='followup',permitted=selected('Q01')===1&&selected('Q02')===1;
 for(const q of schema.questions){
  const field=document.getElementById(q.id);
  field.hidden=(followup&&!followupIds.has(q.id))||(!['Q01','Q02'].includes(q.id)&&!permitted)||(q.recent&&selected('Q03')===1);
  for(const el of field.querySelectorAll('input'))el.disabled=field.hidden;
  if(q.city_filter){
   const parent=schema.questions.find(p=>p.id===q.city_filter),cities=checked(parent.id).map(i=>parent.options[i-1]);
   for(const [i,city] of q.option_cities.entries()){
    const label=field.querySelector(`[data-option="${i+1}"]`),control=label.querySelector('input');
    label.hidden=!!city&&!cities.includes(city);control.disabled=field.hidden||label.hidden;if(label.hidden)control.checked=false;
   }
  }
 }
 for(const header of form.querySelectorAll('[data-section]'))header.hidden=!schema.questions.some(q=>q.section===header.dataset.section&&!document.getElementById(q.id).hidden);
 document.getElementById('form-status').textContent=!permitted?'请先确认自愿参与和年龄；不同意或未满18周岁时结束。':followup?'复测只需10题；请先导入上次答卷或编号凭证以沿用研究编号。':'共30题，全部勾选即可；下载后请自行交给研究负责人。';
}
form.addEventListener('change',event=>{
 const q=schema.questions.find(q=>q.id===event.target.name);
 if(q?.type==='multi'&&event.target.checked){
  const value=Number(event.target.value),exclusive=q.exclusive||[];
  for(const el of form.querySelectorAll(`[name="${q.id}"]`))if(el!==event.target&&(exclusive.includes(value)||exclusive.includes(Number(el.value))))el.checked=false;
 }
 syncVisibility();
});
document.getElementById('wave').addEventListener('change',syncVisibility);syncVisibility();
function answers(){
 const result={};
 for(const q of schema.questions){
  if(document.getElementById(q.id).hidden){result[q.id]=null;continue;}
  const values=checked(q.id),value=q.type==='single'?(values[0]??null):(values.length?values:null);
  if(q.max_choices&&values.length>q.max_choices)throw Error(`${q.id}最多选择${q.max_choices}项。`);
  if(q.required&&value===null)throw Error(`请完成必答题 ${q.id}。`);
  result[q.id]=value;
 }
 return result;
}
function save(name,value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
form.addEventListener('submit',event=>{
 event.preventDefault();const status=document.getElementById('form-status');
 try{
  if(selected('Q01')!==1||selected('Q02')!==1)throw Error('未同意研究使用或未满18周岁，不导出答卷。');
  const wave=document.getElementById('wave').value;
  if(wave==='followup'&&!codeReused)throw Error('复测请先导入上次答卷或编号凭证，自动沿用研究编号。');
  const response={schema_version:schema.version,response_id:uuid(),respondent_code:respondentCode,submitted_at:new Date().toISOString(),submitted_at_basis:'participant_device_clock',wave,data_origin:'self_report',measured_questions:schema.questions.filter(q=>!document.getElementById(q.id).hidden).map(q=>q.id),answers:answers()};
  save('旅行需求答卷_'+response.response_id+'.json',response);status.textContent='本次答卷已下载。请保存该文件供复测沿用编号，并自行交给研究负责人；本页没有上传回答。';
 }catch(error){status.textContent=error.message;status.scrollIntoView({behavior:'smooth',block:'center'});}
});
document.getElementById('random-code').addEventListener('click',()=>{respondentCode=newCode();codeReused=false;document.getElementById('respondent-code').textContent=respondentCode;document.getElementById('reuse-status').textContent='已生成新编号；这会作为另一份研究记录，不与原编号关联。';});
document.getElementById('save-code').addEventListener('click',()=>save('复测编号凭证_'+respondentCode+'.json',{kind:'travel_research_code',respondent_code:respondentCode}));
document.getElementById('reuse-code').addEventListener('change',async event=>{
 try{
  const raw=JSON.parse(await event.target.files[0].text()),code=raw.respondent_code;
  if(!/^[A-Za-z0-9_-]{6,24}$/.test(code||'')||!(raw.kind==='travel_research_code'||[schema.version,legacyVersion].includes(raw.schema_version)&&raw.answers?.Q01===1&&raw.answers?.Q02===1))throw Error('请选择上次有效答卷或编号凭证。');
  respondentCode=code;codeReused=true;document.getElementById('respondent-code').textContent=code;document.getElementById('reuse-status').textContent='已沿用原随机研究编号，无需手写。';
 }catch(error){document.getElementById('reuse-status').textContent=error.message;}
 event.target.value='';
});

// V1 raw answers stay unchanged. New codes are never interpreted using old question numbers.
const question=id=>schema.questions.find(q=>q.id===id);
const labelFor=(r,id)=>{const value=r.answers[id];return Number.isInteger(value)?question(id).options[value-1]??null:null;};
const valuesFor=(r,id)=>Array.isArray(r.answers[id])?r.answers[id].map(i=>question(id).options[i-1]):null;
const rangeFor=(r,id)=>{const i=r.answers[id],q=question(id);return Number.isInteger(i)&&q.option_ranges[i-1]?{label:q.options[i-1],lower:q.option_ranges[i-1][0],upper:q.option_ranges[i-1][1],upper_inclusive:id==='Q17'}:null;};
function plansFor(r){
 if(r.schema_version===legacyVersion)return (r.answers.Q51||[]).map(p=>({...p,cities_selection:p.cities,attractions_selection:p.attractions,date_period:null,days_band:null,budget_display:p.total_budget_per_adult==null?'未知':p.total_budget_per_adult+'元/成人（V1自报金额）',budget_band:null,measured_fields:['cities','cities_selection','attractions','attractions_selection','start_date','date_period','days','days_band','total_budget_per_adult','budget_band','budget_display','stage']}));
 const a=r.answers,year=Number.isInteger(a.Q11)?question('Q11').option_values[a.Q11-1]:null,holiday=Number.isInteger(a.Q12)?question('Q12').option_values[a.Q12-1]:null;
 if(!holiday)return [];
 const cities=valuesFor(r,'Q13'),attractions=valuesFor(r,'Q14'),budget=rangeFor(r,'Q18');
 const p={holiday_year:year,holiday_id:holiday,holiday_label:labelFor(r,'Q12'),cities:cities?.filter(c=>!['名单未列出的城市','尚未确定城市','不计划出游'].includes(c))??null,cities_selection:cities,attractions:attractions?.filter(c=>!['名单未列出的景点','暂不关注具体景点','尚未确定景点'].includes(c))??null,attractions_selection:attractions,start_date:null,date_period:labelFor(r,'Q15'),date_flexibility:labelFor(r,'Q16'),days:null,days_band:rangeFor(r,'Q17'),budget_band:budget,budget_display:labelFor(r,'Q18')||'未测量',total_budget_per_adult:null,airfare_cap_band:rangeFor(r,'Q19'),stage:Number.isInteger(a.Q06)?a.Q06-1:null,city_order_semantics:'unordered_selection',measured_fields:[]};
 for(const [id,fields] of Object.entries({Q13:['cities','cities_selection'],Q14:['attractions','attractions_selection'],Q15:['date_period','start_date'],Q16:['date_flexibility'],Q17:['days_band','days'],Q18:['budget_band','budget_display','total_budget_per_adult'],Q19:['airfare_cap_band'],Q06:['stage']}))if(a[id]!==null&&a[id]!==undefined)p.measured_fields.push(...fields);
 return [p];
}
let responses=new Map(),importLog=[],profileExport=null;
function validResponse(r){
 if(!r||![schema.version,legacyVersion].includes(r.schema_version)||typeof r.response_id!=='string'||!r.response_id.length||r.response_id.length>=150||!Number.isFinite(Date.parse(r.submitted_at))||r.data_origin!=='self_report'||r.answers?.Q01!==1||r.answers?.Q02!==1)return false;
 if(r.respondent_code&&!/^[A-Za-z0-9_-]{6,24}$/.test(r.respondent_code))return false;
 if(r.schema_version===legacyVersion)return r.answers.Q51==null||Array.isArray(r.answers.Q51)&&r.answers.Q51.every(p=>p&&Number.isInteger(p.holiday_year)&&p.holiday_year>=2024&&p.holiday_year<=2035&&typeof p.holiday_id==='string'&&[p.cities,p.attractions].every(v=>v==null||Array.isArray(v)&&v.every(x=>typeof x==='string')));
 return schema.questions.every(q=>{const value=r.answers[q.id];if(value===null||value===undefined)return true;const values=q.type==='multi'?value:[value];return Array.isArray(values)&&values.every(v=>Number.isInteger(v)&&v>=1&&v<=q.options.length)&&new Set(values).size===values.length&&(!q.max_choices||values.length<=q.max_choices)&&(!(q.exclusive||[]).some(v=>values.includes(v))||values.length===1);});
}
function aggregate(){
 const rows=[...responses.values()].sort((a,b)=>Date.parse(a.submitted_at)-Date.parse(b.submitted_at)),groups=new Map(),histories=new Map();
 for(const r of rows){
  if(r.respondent_code){if(!groups.has(r.respondent_code))groups.set(r.respondent_code,[]);groups.get(r.respondent_code).push(r);}
  for(const p of plansFor(r)){const key=(r.respondent_code||'unlinked:'+r.response_id)+'|'+p.holiday_year+'|'+p.holiday_id;if(!histories.has(key))histories.set(key,[]);histories.get(key).push({response_id:r.response_id,respondent_code:r.respondent_code,observed_at:r.submitted_at,source:'self_report',schema_version:r.schema_version,wave:r.wave,...p});}
 }
 const profiles=[...histories.values()].map(history=>{
  const effective={},field_observed_at={},changes=[];
  for(const snapshot of history){
   const changed=[];
   for(const key of snapshot.measured_fields){if(key in effective&&JSON.stringify(effective[key])!==JSON.stringify(snapshot[key]))changed.push(key);effective[key]=snapshot[key];field_observed_at[key]=snapshot.observed_at;}
   if(changed.length)changes.push({observed_at:snapshot.observed_at,changed_fields:changed});
  }
  const latest=history.at(-1);
  return {respondent_code:latest.respondent_code,holiday_year:latest.holiday_year,holiday_id:latest.holiday_id,linked:!!latest.respondent_code,snapshot_count:history.length,latest,effective,field_observed_at,history,changes};
 });
 const longitudinal=[...groups.values()].filter(g=>new Set(g.map(r=>r.submitted_at)).size>=2).length;
 profileExport={schema_version:schema.version,generated_at:new Date().toISOString(),response_count:rows.length,longitudinal_respondents:longitudinal,profile_scope:'保留各版本原答。预算档位不换算精确金额；未测字段沿用此前记录并标注来源时间。真实答卷不关联模拟身份。',profiles,responses:rows,import_log:importLog};
 document.getElementById('analysis').innerHTML=`<p><strong>${rows.length}</strong>份独立答卷 · <strong>${groups.size}</strong>个研究编号 · <strong>${longitudinal}</strong>名有不同时间复测 · <strong>${profiles.length}</strong>份假期画像</p>${profiles.map(p=>`<article class="profile"><h3>${esc(p.respondent_code||'未关联')} · ${esc(p.holiday_year??'年份未定')} ${esc(p.latest.holiday_label)}</h3><p>城市：${esc((p.effective.cities_selection||p.effective.cities)?.join('、')||'未知')}；景点：${esc((p.effective.attractions_selection||p.effective.attractions)?.join('、')||'未知')}</p><p>全程预算：${esc(p.effective.budget_display||'未知')}；阶段：${esc(stageLabels[p.effective.stage]||'未知')}；${p.snapshot_count}次快照</p>${p.changes.map(c=>`<p class="hint">${esc(c.observed_at)}：${c.changed_fields.includes('cities')?'城市变化；':''}${c.changed_fields.includes('attractions')?'景点变化；':''}${c.changed_fields.includes('budget_band')||c.changed_fields.includes('total_budget_per_adult')?'预算变化；':''}${c.changed_fields.includes('stage')?'计划阶段变化；':''}详细前后值保留在导出快照。</p>`).join('')}<p class="hint">未测量字段沿用上次已记录值，来源时刻保存在field_observed_at。</p></article>`).join('')}<p class="hint">${esc(importLog.join('；'))}</p>`;
 document.getElementById('export-profiles').disabled=!rows.length;
}
document.getElementById('imports').addEventListener('change',async event=>{
 for(const file of event.target.files){try{const raw=JSON.parse(await file.text()),rows=Array.isArray(raw)?raw:Array.isArray(raw.responses)?raw.responses:[raw];let accepted=0,duplicates=0,rejected=0;for(const r of rows){if(!validResponse(r)){rejected++;continue;}if(responses.has(r.response_id)){duplicates++;continue;}responses.set(r.response_id,r);accepted++;}importLog.push(`${file.name}：导入${accepted}，重复${duplicates}，无效${rejected}`);}catch{importLog.push(`${file.name}：非有效JSON`);}}
 aggregate();event.target.value='';
});
document.getElementById('export-profiles').addEventListener('click',()=>save('节假日动态画像与原始快照.json',profileExport));
