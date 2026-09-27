"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let profiles = [], selected = null, imageUrls = [];
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function showError(error) { $('error').textContent = error.message; $('error').hidden = false; }
function bars(target, data) {
  const max = Math.max(...Object.values(data), 1);
  $(target).innerHTML = Object.entries(data).map(([name, n]) => `<div class="bar-row"><span>${esc(name)}</span><div class="bar-track"><div class="bar" data-width="${n/max*100}"></div></div><span>${n}</span></div>`).join('');
  $(target).querySelectorAll('[data-width]').forEach(el => el.style.width = `${el.dataset.width}%`);
}
function renderRows() {
  const value = $('filter').value;
  const filtered = profiles.filter(p => value === 'all' || (value === 'eligible' ? p.contact.eligible : p.segment === '高意向待转化'));
  $('rows').innerHTML = filtered.map(p => `<tr class="${p.id === selected ? 'selected' : ''}"><td><button class="row-button" data-profile="${esc(p.id)}">${esc(p.id)}</button><br>${esc(p.origin)}</td><td>${esc(p.segment)}<br><span class="subtle">意向分 ${p.intent_score.toFixed(3)}</span></td><td>${p.contact.eligible ? '可触达' : esc(p.contact.reason)}</td></tr>`).join('');
  $('rows').querySelectorAll('[data-profile]').forEach(el => el.onclick = () => {selected = el.dataset.profile; renderRows(); renderProfile();});
}
function renderProfile() {
  const p = profiles.find(p => p.id === selected);
  if (!p) return;
  const route = p.recommendations[0];
  $('profile').innerHTML = `<h3>${esc(p.id)} · 动态画像</h3><span class="pill">${esc(p.segment)}</span><span class="pill">规则基线</span><p>兴趣：${Object.keys(p.interests).map(esc).join('、') || '暂无'}<br>预算：¥${p.budget} · 近7天触达：${p.contacts_7d}次</p><p class="subtle">${p.reasons.map(esc).join('；')}</p>${route ? `<div class="route"><strong>${esc(route.origin)} → ${esc(route.destination)}</strong><p>推荐分 ${route.score} · 演示票价 ¥${route.fare}</p><div class="subtle">${esc(route.reason)}</div></div>` : '<p>无匹配航线</p>'}<p>${p.contact.eligible ? `渠道：${esc(p.contact.channel)} · 建议 ${p.contact.hour}:00（上海时区）` : esc(p.contact.reason)}</p><button class="action" id="create" ${p.contact.eligible && route ? '' : 'disabled'}>生成文案与视觉草稿</button><p class="subtle">模板生成，必须人工审核后才能模拟。</p>`;
  $('create').onclick = () => perform('/api/campaigns', {passenger_id:p.id}, '活动草稿已生成，请审核内容。');
}
async function perform(path, body, message) {
  $('error').hidden = true;
  // 防止快速重复点击；后端另有状态转换和频控检查。
  document.querySelectorAll('button.action').forEach(el => el.disabled = true);
  try { await api(path, body); $('status').textContent = message; await load(); }
  catch (error) {showError(error); await load().catch(showError);}
}
function renderCampaigns(campaigns) {
  imageUrls.forEach(URL.revokeObjectURL); imageUrls = [];
  $('campaign-list').innerHTML = campaigns.length ? campaigns.map(c => {
    const url = URL.createObjectURL(new Blob([c.content.visual_svg], {type:'image/svg+xml'})); imageUrls.push(url);
    return `<article class="campaign"><div><span class="pill">${esc({draft:'待审核',approved:'已审核',simulated:'已模拟'}[c.status])}</span><span class="subtle">${esc(c.passenger_id)} · ${esc(c.decision.channel)}</span><h3>${esc(c.content.title)}</h3><p>${esc(c.content.body)}</p><p class="subtle">提供者：${esc(c.content.provider)} · 真实消息发送数：0</p>${c.status === 'draft' ? `<button class="action" data-action="approve" data-id="${c.id}">内容审核通过</button>` : ''}${c.status === 'approved' ? `<button class="action" data-action="simulate" data-id="${c.id}">模拟触达与评估</button>` : ''}</div><img src="${url}" alt="模板生成的目的地营销视觉，非真实促销"></article>`;
  }).join('') : '<div class="empty">选择可触达旅客，生成第一份营销草稿。</div>';
  $('campaign-list').querySelectorAll('[data-action]').forEach(el => el.onclick = () => perform(`/api/campaigns/${el.dataset.id}/${el.dataset.action}`, {}, el.dataset.action === 'approve' ? '审核已记录。' : '模拟已完成，未发送真实消息。'));
}
async function load() {
  const [overview, people, campaigns, metrics, audit] = await Promise.all(['/api/overview','/api/profiles','/api/campaigns','/api/metrics','/api/audit'].map(path => api(path)));
  profiles = people;
  $('cards').innerHTML = [['虚拟旅客',overview.passengers,'合成身份，无真实个人信息'],['可触达旅客',overview.eligible,'授权、频控与已购票排除'],['高意向旅客',overview.high_intent,'规则评分，尚未训练模型'],['活动草稿 / 已模拟',campaigns.length,`${campaigns.filter(c=>c.status==='simulated').length}次模拟 · 0次真实投放`]].map(([label,num,note]) => `<div class="card"><span>${esc(label)}</span><strong>${num}</strong><small>${esc(note)}</small></div>`).join('');
  bars('destinations', overview.destinations); bars('segments',overview.segments);
  if (!selected && profiles.length) selected = (profiles.find(p => p.contact.eligible) || profiles[0]).id;
  renderRows(); renderProfile(); renderCampaigns(campaigns);
  const pct = n => n === null ? '无样本' : `${(n*100).toFixed(1)}%`;
  $('metrics').innerHTML = `<div class="metric-grid">${Object.entries(metrics.groups).map(([name,g]) => `<div class="metric">${name==='control'?'对照组':'实验组'}<strong>${pct(g.conversion_rate)}</strong><span class="subtle">${g.converted} 次模拟转化 / ${g.assigned} 位随机分组旅客</span></div>`).join('')}</div><p>转化率差：${metrics.absolute_lift===null?'无样本':`${(metrics.absolute_lift*100).toFixed(1)} 个百分点`}</p><p class="subtle">${esc(metrics.note)} 当前统计针对全部可触达合成旅客演示，并非单条活动归因。</p>`;
  $('audit').textContent = JSON.stringify(audit, null, 2);
}
$('filter').onchange = renderRows;
load().catch(showError);
