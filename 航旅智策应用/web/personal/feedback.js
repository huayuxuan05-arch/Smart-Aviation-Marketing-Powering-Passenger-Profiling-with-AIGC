'use strict';
function renderPlanFeedback(){
 if(!tripPlan?.id)return '';
 const previous=(personalState.plan_feedback||[]).find(f=>f.plan_id===tripPlan.id),options=personalMeta.feedback_options;
 if(!options)return '';
 const share=personalState.collection?.enabled;
 return `<section class="card personal-feedback"><h3>使用评价</h3><p>自愿填写，可直接跳过，不影响方案使用。</p><form id="plan-feedback" data-plan-id="${esc(tripPlan.id)}"><div class="personal-feedback-grid"><label class="field"><span>方案评分（可选）</span><select name="rating"><option value="">未评分</option>${[1,2,3,4,5].map(n=>`<option value="${n}" ${previous?.rating===n?'selected':''}>${n}分</option>`).join('')}</select></label><label class="field"><span>是否符合需求（可选）</span><select name="suitability"><option value="">未填写</option>${options.suitability.map(s=>`<option value="${esc(s)}" ${previous?.suitability===s?'selected':''}>${esc(s)}</option>`).join('')}</select></label></div><fieldset class="airline-tags"><legend>如未采用方案，可选原因</legend><div>${options.reasons.map(r=>`<label><input type="checkbox" name="reasons" value="${esc(r)}" ${previous?.reasons.includes(r)?'checked':''}><span>${esc(r)}</span></label>`).join('')}</div></fieldset><label class="personal-sharing"><input type="checkbox" name="share_feedback" ${share&&previous?.share_feedback?'checked':''} ${share?'':'disabled'}> 自愿匿名共享这份评价，用于项目案例分析</label>${share?'':'<p>如希望共享评价，可先在“偏好更新”中开启匿名画像共享；不共享也能保存评价。</p>'}<p class="feedback-status" role="status">${previous?'已有评价；再次提交会保留新的评价记录。':''}</p><button type="submit" class="secondary">保存评价</button></form></section>`;
}
document.addEventListener('submit',async event=>{
 const form=event.target;if(form.id!=='plan-feedback')return;event.preventDefault();
 const button=form.querySelector('[type=submit]'),status=form.querySelector('.feedback-status');if(button.disabled)return;
 const values=new FormData(form);button.disabled=true;status.textContent='正在保存…';
 try{const body={submission_id:form.dataset.submissionId||(form.dataset.submissionId=crypto.randomUUID()),rating:values.get('rating')?Number(values.get('rating')):null,suitability:values.get('suitability')||null,reasons:values.getAll('reasons'),share_feedback:values.get('share_feedback')==='on'};
  await personalApi('plans/'+form.dataset.planId+'/feedback',body);personalSectionState.set('feedback',true);await refreshPersonal();toast('评价已保存，谢谢你的反馈');
 }catch(error){status.textContent=error.message;button.disabled=false;delete form.dataset.submissionId;}
});
