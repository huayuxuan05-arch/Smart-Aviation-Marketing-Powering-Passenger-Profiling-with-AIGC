'use strict';
const personalActivityTimes=new Map();
function recordPersonalActivity(event){
 if(!personalState?.collection?.enabled)return;
 const key=JSON.stringify(event),last=personalActivityTimes.get(key)||0;
 if(Date.now()-last<60000)return;personalActivityTimes.set(key,Date.now());
 personalApi('activity',event).catch(()=>{});
}
const personalActivitySections={'assistant':'assistant','trip-budget':'budget','trip-每日行程':'daily',
 'trip-住宿安排':'lodging','trip-调整方案':'backup','trip-行前清单':'checklist','trip-ai':'trip-ai'};
document.addEventListener('click',e=>{
 const summary=e.target.closest('summary');
 if(summary){const details=summary.parentElement;if(details.open)return;const raw=details.dataset.personalSection;
  const section=personalActivitySections[raw]||raw||(details.classList.contains('personal-airline-tags')?'airlines':details.classList.contains('personal-more')?'details':null);
  if(section)recordPersonalActivity({kind:'section_view',section});
 }
 const b=e.target.closest('button');if(!b||b.disabled)return;
 const action=b.dataset.personalAction||b.dataset.liveAction||b.dataset.action;
 if(['open-plan','apply-date','trip-export','trip-print','trip-ai','preview'].includes(action))recordPersonalActivity({kind:'workspace_action',action});
 if(b.id==='assistant-cancel')recordPersonalActivity({kind:'workspace_action',action:'cancel-draft'});
});
document.addEventListener('change',e=>{
 if(e.target.matches('#personal-preferences [name=destination]'))recordPersonalActivity({kind:'destination_view',destination:e.target.value});
 if(e.target.matches('[data-personal-sharing]')&&e.target.checked)setTimeout(()=>recordPersonalActivity({kind:'section_view',section:'page'}),500);
});
document.addEventListener('submit',e=>{if(e.target.id==='assistant-request')recordPersonalActivity({kind:'workspace_action',action:document.querySelector('[name=assistant-kind]:checked')?.value==='feedback'?'feedback-draft':'request-draft'});});
document.addEventListener('personal-ready',()=>recordPersonalActivity({kind:'section_view',section:'page'}));
