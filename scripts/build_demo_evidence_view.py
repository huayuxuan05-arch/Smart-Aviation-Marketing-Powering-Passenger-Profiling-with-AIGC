"""从实际实验结果生成统计图及可离线交互的演示页，不改变应用。"""
from pathlib import Path
import base64
import json
import os

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '航旅智策应用/runtime/evidence'
os.environ['MPLCONFIGDIR'] = str(OUT / 'qa/matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


def main():
    report = json.loads((OUT / 'results.json').read_text(encoding='utf-8'))
    figs = OUT / 'figures'
    figs.mkdir(exist_ok=True)
    font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family': 'Microsoft YaHei', 'font.size': 10, 'axes.unicode_minus': False,
                         'axes.spines.top': False, 'axes.spines.right': False, 'savefig.facecolor': 'white'})
    colors = ['#6157d9', '#a399e8', '#83b5bd', '#51a3a3', '#a8b4cc', '#c1c7d2', '#d4d9e2']

    def save(fig, name):
        fig.savefig(figs / (name + '.png'), dpi=240, bbox_inches='tight')
        fig.savefig(figs / (name + '.svg'), bbox_inches='tight')
        plt.close(fig)

    for scope, name in [('固定测试', 'ranking-frozen'), ('国庆专项', 'ranking-national')]:
        table = report['ranking']['results'][scope]['metrics']
        fig, axes = plt.subplots(1, 2, figsize=(10.7, 4.0), layout='constrained')
        for ax, metric in zip(axes, ['Recall@3', 'NDCG@3']):
            y = np.arange(len(table))
            ax.barh(y, [r[metric] for r in table], color=colors)
            ax.set_yticks(y, [r['method'] for r in table])
            ax.invert_yaxis()
            ax.set_xlim(0, 1.08)
            ax.set_xlabel(metric)
            ax.grid(axis='x', alpha=.15)
            ax.set_axisbelow(True)
            for i, row in enumerate(table):
                ax.text(row[metric] + .012, i, f'{row[metric]:.4f}', va='center', fontsize=9)
        fig.suptitle(scope + '  同一旅客 同一目的地 同一未来窗口', fontsize=13)
        save(fig, name)

    fig, ax = plt.subplots(figsize=(8.7, 3.9), layout='constrained')
    labels, points, lo, hi = [], [], [], []
    for scope in ['固定测试', '国庆专项']:
        for baseline in ['近30天频次', '14天时间衰减']:
            row = next(v for v in report['ranking']['results'][scope]['paired_differences'] if v['baseline'] == baseline and v['metric'] == 'Recall@3')
            labels.append(scope + ' 对比 ' + baseline)
            points.append(row['difference'] * 100)
            lo.append((row['difference'] - row['ci95'][0]) * 100)
            hi.append((row['ci95'][1] - row['difference']) * 100)
    ax.errorbar(points, np.arange(4), xerr=[lo, hi], fmt='o', color='#6157d9', capsize=5)
    ax.set_yticks(np.arange(4), labels)
    ax.invert_yaxis()
    ax.axvline(0, color='#999', lw=1)
    ax.set_xlabel('动态模型的Recall@3差值  百分点  配对95%区间')
    ax.set_title('按旅客整体重采样2000次  仅反映当前模拟样本的不确定性')
    ax.grid(axis='x', alpha=.15)
    save(fig, 'ranking-differences')

    table = report['decision']['results']['未退订全量同群']['metrics']
    fig, axes = plt.subplots(1, 2, figsize=(9.7, 3.9), layout='constrained')
    for ax, key, title in zip(axes, ['historical_matches', 'business_ready'], ['有历史匹配候选', '当次业务条件满足']):
        bars = ax.bar(['只取兴趣首选', '同候选内约束选择'], [r[key] for r in table], color=['#a8b4cc', '#6157d9'], width=.55)
        ax.bar_label(bars, padding=4)
        ax.set_ylim(0, max(r[key] for r in table) * 1.18)
        ax.set_title(title + '  分母9799人')
        ax.set_ylabel('人数')
        ax.grid(axis='y', alpha=.15)
        ax.set_axisbelow(True)
    fig.suptitle('全量同群对照有改善  共同前300人名单无改善', fontsize=13)
    save(fig, 'decision-comparison')

    dynamic = report['cases']['dynamic']
    fig, ax = plt.subplots(figsize=(8.6, 3.8), layout='constrained')
    for city, color in [('长沙', '#83b5bd'), ('成都', '#6157d9')]:
        values = [next(v['share'] for v in s['profile']['destinations'] if v['name'] == city) for s in dynamic['snapshots']]
        ax.plot(['9月23日', '9月26日', '9月30日'], values, marker='o', lw=2, label=city, color=color)
        for x, value in enumerate(values):
            ax.annotate(f'{value:.1f}%', (x, value), xytext=(0, 8), textcoords='offset points', ha='center')
    ax.set_ylim(0, 60)
    ax.set_ylabel('30天时间衰减关注占比  %')
    ax.set_title('SIMU_00748  当时可见证据的画像变化  非购票概率')
    ax.legend(frameon=False)
    ax.grid(alpha=.15)
    save(fig, 'dynamic-profile')

    images = {p.stem: 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode('ascii') for p in figs.glob('*.png')}
    payload = json.dumps({'report': report, 'images': images}, ensure_ascii=False).replace('<', '\\u003c')
    html = TEMPLATE.replace('__PAYLOAD__', payload)
    html = html.replace('<section id="decision" hidden></section>', '<section id="decision" hidden></section><section id="selection" hidden></section>')
    html = html.replace("['decision','业务决策对照']", "['decision','业务决策对照'],['selection','名单策略优化']")
    policy_script = r"""const policies=r.decision.selection_policy_exploration;$('#selection').innerHTML=`<div class="notice">${esc(policies.status)}。${esc(policies.basis)}。</div><div class="card"><h2>同一预算下如何改善名单可用性</h2>${table(['名单策略','实际选中','未完成配额','历史匹配','业务条件满足','后7天持续关注'],policies.metrics.map(x=>[x.policy,x.selected,x.shortfall,x.historical_matches,x.business_ready,x.future_continue]))}<p>原兴趣前300人、产品条件优先和完整业务资格优先，允许选中不同旅客，但使用同一个9799人池、最多300人名额和150元情景费用上限。</p><p class="notice">${esc(policies.capacity_note)}。合格人数改善不等于真实购票提升，后续持续关注也是模拟代理。</p><p>当前可操作的优化是把历史产品或当次业务条件放在名单截取之前。业务资格优先只能选出150人，剩余150个名额需补充需求或产品条件，不能用未知预算旅客凑满。</p></div>`;"""
    html = html.replace('</script></body>', policy_script + '</script></body>')
    (OUT / '案例与实验演示.html').write_text(html, encoding='utf-8')
    print('CHARTS_AND_INTERACTIVE_VIEW_READY', OUT)


TEMPLATE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>华翼朝阳 案例与模拟实验</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f5fb;color:#172744;font:16px/1.7 'Microsoft YaHei',sans-serif}header{background:#172744;color:white;padding:26px max(5vw,20px)}header h1{margin:0;font-size:28px}header p{margin:6px 0 0;color:#cbd3e8}.wrap{max-width:1180px;margin:auto;padding:24px}nav{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px}button,.download{border:1px solid #d9ddeb;background:white;border-radius:9px;padding:11px 18px;cursor:pointer;color:#283955;font:inherit}button.active{background:#6157d9;color:white}section[hidden]{display:none}.card{background:white;border:1px solid #dfe3ee;border-radius:15px;padding:24px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.metric strong{display:block;font-size:30px;color:#6157d9}.muted{color:#67758c;font-size:14px}.notice{padding:14px 18px;background:#fff6e8;border-left:4px solid #c88731;border-radius:7px}.good{color:#14745a}.bad{color:#9a5720}h2{font-size:23px;margin:0 0 15px}h3{font-size:18px;margin:18px 0 8px}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;border:1px solid #dce1ed;text-align:left}th{background:#edf0fa}img.chart{width:100%;height:auto}input[type=range]{width:100%;accent-color:#6157d9}.split{display:grid;grid-template-columns:1fr 1fr;gap:18px}.poster svg{width:100%;height:auto;max-height:520px}pre{white-space:pre-wrap;word-break:break-word;background:#f4f6fa;padding:16px;font:14px/1.7 'Microsoft YaHei',sans-serif}.pill{display:inline-block;background:#eeecff;color:#5348b5;padding:4px 12px;border-radius:20px}.steps{counter-reset:step}.steps p::before{counter-increment:step;content:counter(step);display:inline-block;background:#6157d9;color:white;width:28px;text-align:center;border-radius:50%;margin-right:10px}footer{padding:20px 0;color:#67758c;font-size:13px}@media(max-width:700px){.grid,.split{grid-template-columns:1fr}.wrap{padding:14px}.card{padding:17px}header h1{font-size:23px}}
</style></head><body><header><h1>华翼朝阳 案例与模拟实验</h1><p>2024国庆历史回放 · 10,000名模拟旅客 · 模板模式 · 独立实验状态</p></header><main class="wrap"><nav id="tabs"></nav><section id="overview"></section><section id="workflow" hidden></section><section id="dynamic" hidden></section><section id="ranking" hidden></section><section id="decision" hidden></section><footer>仅验证模拟数据上的流程和方法。历史参考不代表当前可售；未生成真实曝光、点击或订单，未接入本地大模型。</footer></main><script id="payload" type="application/json">__PAYLOAD__</script><script>
const {report:r,images}=JSON.parse(document.getElementById('payload').textContent),c=r.cases;const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),pct=x=>(x*100).toFixed(2)+'%',pp=x=>(x*100).toFixed(3),metric=(name,value,note)=>`<div class="card metric">${name}<strong>${value}</strong><span class="muted">${note}</span></div>`,chart=(name,alt)=>`<img class="chart" src="${images[name]}" alt="${alt}">`,table=(heads,rows)=>`<div class="table-scroll"><table><thead><tr>${heads.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
const tabs=[['overview','实验概览'],['workflow','完整案例'],['dynamic','动态变化'],['ranking','需求排序对照'],['decision','业务决策对照']];$('#tabs').innerHTML=tabs.map(([id,title])=>`<button data-tab="${id}" class="${id==='overview'?'active':''}">${title}</button>`).join('');document.addEventListener('click',e=>{if(e.target.dataset.tab){for(const [id] of tabs)$('#'+id).hidden=id!==e.target.dataset.tab;for(const b of document.querySelectorAll('[data-tab]'))b.classList.toggle('active',b===e.target);window.scrollTo(0,0);}if(e.target.dataset.download){const blob=new Blob([JSON.stringify(r,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='实验结果.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);}});
const national=r.ranking.results['国庆专项'],diff=national.paired_differences.find(x=>x.baseline==='近30天频次'&&x.metric==='Recall@3');$('#overview').innerHTML=`<div class="notice">原始模拟行为、训练权重和用户活动库均未修改。案例用于解释机制，效果比较使用全量同群；不推断真实业务收益。</div><div class="grid">${metric('国庆动态模型 Recall@3',national.metrics[0]['Recall@3'].toFixed(4),'有效快照9998，另2人无相关目的地')}${metric('相比频次规则',pp(diff.difference)+' 个百分点','配对95%区间 '+diff.ci95.map(pp).join(' 至 '))}${metric('全量业务条件满足','127 → 150','固定分母9799名未退订模拟旅客')}</div><div class="card"><h2>三类证据已经运行</h2><div class="steps"><p>完整流程：两位模拟旅客，1人模拟触达，1人暂缓；重复执行新增0条。</p><p>动态机制：同一旅客三个截点，首选由长沙转为成都；不借用未来行为。</p><p>公平对照：固定测试复现、国庆专项、全量与共同300人业务对照。共同300人名单没有改善。</p></div><button data-download="results">下载实验结果 JSON</button><p class="muted">模型与数据SHA256、软件版本、随机种子及统计协议随结果保存。Word报告和CSV在同一材料目录。</p></div>`;
const p=c.positive,n=c.deferred,posMaterial=c.creatives.find(x=>x.user_id===p.user_id);$('#workflow').innerHTML=`<div class="card"><h2>完整案例 国庆航空营销流程</h2>${table(['旅客','方向','日期','本次机票上限','结果'],[[p.user_id,p.usual_departure_city+' → '+p.destination,p.travel_date,'¥'+p.budget,'本地模拟1条'],[n.user_id,n.usual_departure_city+' → '+n.destination,'情景日期，未确认','未知','暂缓，需确认日期和预算']])}<p>历史航班 ${esc(p.flight.航班号)}，样本价 ¥${p.flight.机票票价}，不代表当前可售价格。渠道 ${esc(p.channel)}，建议 ${p.hour}:00；访问习惯不等于转化最优。</p></div><div class="split"><div class="card"><h3>模板素材及事实槽位</h3><div class="poster">${posMaterial.poster_svg}</div></div><div class="card"><h3>实际流程记录</h3><div class="steps"><p>冻结两人名单，版本 ${c.steps[0].campaign_revision}。</p><p>两份模板素材完成脚本核验并提交三项审核确认。此处验证门控，不是独立人工质量评分。</p><p>首次执行新增1条，另一人因日期和预算缺失暂缓。</p><p>再次执行新增0条，频控阻止重复记录。</p><p>10月1至7日观察窗口：${Object.entries(c.evaluation.outcomes).map(([k,v])=>esc(k)+'='+v).join('，')}。</p></div><div class="notice">曝光、点击与支付字段均为 null。后续行为属于原模拟记录，不能归因于此次触达。</div><details><summary>展开带历史事实的文案</summary><pre>${esc(posMaterial.composed_text)}</pre></details></div></div>`;
$('#dynamic').innerHTML=`<div class="card"><h2>动态变化案例 ${esc(c.dynamic.user_id)}</h2><p>拖动观察截点，查看当时可见的画像和行为依据。关注占比是30天时间衰减份额，不是购票概率。</p><input type="range" id="date-slider" min="0" max="2" value="0" step="1" aria-label="选择观察截点"><div id="dynamic-detail"></div></div><div class="card">${chart('dynamic-profile','长沙与成都关注占比的变化')}</div>`;function dynamicView(){const s=c.dynamic.snapshots[Number($('#date-slider').value)];$('#dynamic-detail').innerHTML=`<h3>${esc(s.date)} <span class="pill">模型首选 ${esc(s.model_top1)}</span></h3>${table(['目的地','时间衰减关注占比','30天搜索过程数'],s.profile.destinations.slice(0,3).map(d=>[d.name,d.share+'%',d.count]))}<h3>最近可见行为</h3>${table(['时间','内容','来源记录'],s.profile.records.slice(0,4).map(x=>[x.search_at_cst,x.query_text,x.record_id]))}<p class="muted">每个截点单独遮蔽未来行为。案例按已观察变化选择，不代表总体提升。</p>`;}$('#date-slider').addEventListener('input',dynamicView);dynamicView();
$('#ranking').innerHTML=`<div class="notice">全部方法使用相同旅客、41个目的地和未来7天标签。主对照为动态模型与近30天频次，其余比较为探索性。</div>`+['固定测试','国庆专项'].map(scope=>{const v=r.ranking.results[scope];return `<div class="card"><h2>${scope}</h2><p>截点 ${v.dates.join('、')}。训练1至6月，验证7至9月；国庆专项截点晚于9月22日模型选择标签结束。</p>${table(['方法','Recall@3','NDCG@3','有效快照','无相关目的地'],v.metrics.map(x=>[x.method,x['Recall@3'].toFixed(4),x['NDCG@3'].toFixed(4),x.eligible_snapshots,x.no_relevant_snapshots]))}${chart(scope==='固定测试'?'ranking-frozen':'ranking-national',scope+'排序对照')}</div>`;}).join('')+`<div class="card"><h2>提升的不确定性</h2>${chart('ranking-differences','配对差值区间')}<p class="muted">同一旅客跨日期整组重采样2000次，种子20261015。区间仅反映当前模拟数据中的旅客抽样变化，不覆盖生成机制不确定性，不证明新用户泛化。</p></div>`;
$('#decision').innerHTML=`<div class="notice">同一模型排序、同一近期兴趣候选、同一日期与预算规则，只改变候选选择方式。两组均为离线对照，没有实际营销发送。</div>`+Object.entries(r.decision.results).map(([scope,v])=>`<div class="card"><h2>${scope}</h2>${table(['方法','固定分母','历史匹配人数','业务条件满足','暂缓人数'],v.metrics.map(x=>[x.method,x.users,x.historical_matches,x.business_ready,x.deferred]))}<p>历史匹配率差值 ${pp(v.paired_differences.matched.difference)} 个百分点；业务条件满足率差值 ${pp(v.paired_differences.ready.difference)} 个百分点。</p>${scope.includes('300')?'<p class="notice">共同前300人名单结果相同，应保留零提升结论，不能据全量结果宣称任意名单均获益。</p>':''}</div>`).join('')+`<div class="card">${chart('decision-comparison','业务约束对照')}<p class="muted">当前产品默认先筛历史候选再截取300人，其300/300不能与这里未前筛航班的共同300人相比较；全量覆盖仍以9799人为分母。</p></div>`;
</script></body></html>'''


if __name__ == '__main__':
    main()
