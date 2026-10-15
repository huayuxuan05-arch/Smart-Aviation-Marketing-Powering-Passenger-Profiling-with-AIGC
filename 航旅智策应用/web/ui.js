'use strict';
function compactApplicationUI(root=document){
 root.querySelectorAll('.card-sub,.metric-foot,.trip-basis,.assistant-intro,.personal-small,.personal-reference,.assistant-prompt,.portal-story-note,.entry-footnote,.selection-funnel>p.muted').forEach(e=>e.remove());
 const explanations=[
  /^模型已实际训练，需求分值/,/^当前假期早于模型冻结时间/,/分数用于筛选潜在关注，不等于真实购票意愿/,
  /^当前是预览名单。保存为营销活动后/,/^活动名单已冻结为版本.*更改名单会使旧素材审批失效/,
  /^持续关注分、机票查询分、收藏分/,/^文案：/,/^生成后仍需人工核对/,/^这份素材当前可覆盖/,
  /^真实发送资格：未就绪/,/^满足全部条件后才写入本地模拟记录/,/本地记录不能归因到原始营销文件/,
  /代理标签可验证名单与后续需求的关联/,/^已有12万次触达记录可以检查/,/没有实际成本、座位、客流与满意度标签/,
  /^费用是情景假设，不产生真实支出/,/^持续关注：未来7天同目的地/,/^内容制作方式：/,
  /三个分数均为模拟行为代理，不是购票概率/,/画像可以稳定或变化，不强制制造标签变化/
 ];
 root.querySelectorAll('.notice').forEach(e=>{if(explanations.some(rule=>rule.test(e.textContent.trim())))e.remove();});
}
compactApplicationUI();
