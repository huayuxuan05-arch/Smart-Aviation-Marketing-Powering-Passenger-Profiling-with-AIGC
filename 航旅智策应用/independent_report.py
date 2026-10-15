"""Audit immutable cohort evidence and export a compact public acceptance report."""
from __future__ import annotations
import gzip
import json
from collections import Counter
from pathlib import Path
import independent_cohort as cohort
import marketing_ml as ml
from data_layer import connect


def build(root):
    root=Path(root).resolve();project=Path(__file__).resolve().parent.parent
    original=json.loads((root/'evaluation_report.json').read_text(encoding='utf-8'))
    new=json.loads((root/'new-method-v1'/'report.json').read_text(encoding='utf-8'))
    constraints=json.loads((root/'constraint-first-v1'/'report.json').read_text(encoding='utf-8'))
    intervals=json.loads((root/'budget-range-v1'/'report.json').read_text(encoding='utf-8'))
    dataset,base,manifest=cohort.load(root/'test')
    users={u['user_id']:u for u in dataset[1]}
    with connect() as c:old_ids={r[0] for r in c.execute('SELECT user_id FROM users')}
    assert len(users)==10000 and not users.keys()&old_ids
    assert dataset[0]['dest'].shape==(365,10000)
    for split in ['validation','training','confirmation']:
        others={json.loads(line)['user_id'] for line in (root/split/'users.jsonl').read_text(encoding='utf-8').splitlines()}
        assert not users.keys()&others
    for name,spec in manifest['files'].items():assert cohort.digest(root/'test'/name)==spec['sha256']
    with gzip.open(root/'test'/'behaviors.csv.gz','rt',encoding='utf-8') as f:
        assert sum(1 for _ in f)-1==3650000
    counts=Counter();proposals=0
    with (root/'constraint-first-v1'/'traveler_plans.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);assert row['user_id'] in users;counts[row['status']]+=1
            assert row['accepted'] is False
            assert len(row['daily_itinerary'])==users[row['user_id']]['days']
            pref=row['original_conditions'];selected=row.get('selected')
            if selected:
                assert selected['estimated_total']<=pref['adult_trip_budget']['max']
                for leg in ['outbound','inbound']:assert selected['option'][leg]['price_cny']<=pref['one_way_airfare']['max']
                assert len(row['daily_itinerary'])==users[row['user_id']]['days']
            proposed=row.get('budget_reallocation_proposal')
            if proposed:
                proposals+=1;assert proposed['requires_confirmation'] and not proposed['accepted']
                assert proposed['estimated_total']<=pref['adult_trip_budget']['max']
                assert proposed['requested_one_way_upper']>proposed['original_one_way_upper']
    assert sum(counts.values())==10000
    assert proposals==constraints['counts'].get('additional_budget_reallocation_proposals',0)
    assert cohort.digest(ml.ROOT/'marketing_models.joblib')==original['protocol']['original_model_sha256']
    public=project/'experiments/results/independent-2026-10-16';public.mkdir(parents=True,exist_ok=True)
    copies={'evaluation_report.json':original,'new_method_report.json':new,
        'constraint_report.json':constraints,'price_range_report.json':intervals,
        'protocol.json':original['protocol'],'test_manifest.json':manifest,
        'profile_manifest.json':json.loads((root/'profile_manifest.json').read_text(encoding='utf-8'))}
    for name,value in copies.items():cohort.write_json(public/name,value)
    files=[]
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name not in ['结果说明.md','artifact_manifest.json']:
            files.append(dict(path=path.relative_to(project).as_posix(),sha256=cohort.digest(path),bytes=path.stat().st_size))
    artifacts=dict(version='annual-independent-v1',seed=cohort.SEED,users=10000,days=365,behavior_rows=3650000,
        behavior_start=manifest['behavior_start'],behavior_end=manifest['behavior_end'],
        cohorts=dict(test=10000,validation=2000,training=6000,confirmation=10000),
        source_model_sha256=original['protocol']['original_model_sha256'],
        real_flight_source='Google Flights / fli',license='Synthetic output: project evaluation; no separate redistribution license specified. Original data/model notices remain applicable.',
        files=files,raw_files_local_only=True,source_holiday_notice=cohort.HOLIDAY_SOURCE)
    cohort.write_json(root/'artifact_manifest.json',artifacts)
    cohort.write_json(project/'distribution/independent-test-2026-10-16.json',artifacts)
    metrics=original['test'];lines=['# 新增全年模拟旅客：数据、模型与实时航班检验','',
        '本批新增10,000名独立模拟旅客，2025-10-16至2026-10-15每天一条搜索/访问过程，共3,650,000条。另建2,000名验证用户、6,000名训练用户和10,000名确认测试用户；编号与原训练用户互不重叠。生成历史是模拟，不是一年真实追踪。','',
        '数据包含365天行为数组、压缩CSV、旅客属性、机票与全程预算区间、120,000条月度画像快照，以及逐人当前报价/备选方案结果。六类场景覆盖稳定关注、兴趣迁移、临近出游变化、预算变化、广泛探索和多目的地比较。','',
        '节假日日历使用[国务院办公厅2026年安排（北京市政府转载）]('+cohort.HOLIDAY_SOURCE+')，发布日前的行为不提前使用该通知。','',
        '## 需求预测对照','',
        '| 方法 | Recall@3 | NDCG@3 |','| --- | ---: | ---: |']
    for name,value in metrics.items():lines.append(f"| {name} | {value['recall_at_3']:.4f} | {value['ndcg_at_3']:.4f} |")
    lines+=['','测试为三个固定观察截点，共30,000个用户快照；27,066个存在相关目的地，2,934个单列。模型预测的是未来七天重复关注，不是购票或成交。','',
        '原模型在“广泛探索”人群的Recall@3约0.077，不能用总分掩盖；该场景含大量独立随机探索。重新训练了成对学习排序、新数据梯度提升，并比较三个预定融合权重。选择仅看验证集，随后用另建10,000人确认测试。新梯度提升的确认测试Recall@3=0.9245、NDCG@3=0.9110，原模型分别为0.9216、0.9102；按用户配对的NDCG差值95%区间包含0，未通过预先约定的0.005提升门槛。新产物保留，不覆盖网站模型。','',
        '## 价格区间与可行性优先方法','',
        '价格区间为独立模拟场景：原金额为中心，端点约为80%—120%并按50/100元取整。下限是期望区间，下方低价仍可展示；上限在严格匹配中保持约束。年度机票预算区间保存为与365天行为数组逐条对应的文件。区间场景改变了预算假设，不是需求模型准确率提升。','',
        '| 检验口径 | 人数 | 比例 |','| --- | ---: | ---: |',
        '| 固定金额、原日期目的地与直飞 | 2,238 | 22.38% |',
        '| 区间预算、原日期目的地与直飞 | 3,164 | 31.64% |',
        '| 新增改期/目的地/中转备选，仍满足区间上限 | 2,482 | 24.82% |',
        '| 区间上限内候选合计 | 5,646 | 56.46% |',
        '| 另有总预算不变、需确认调整机票分项区间的建议 | 1,780 | 17.80% |',
        '| 含分项调配建议的候选总计 | 7,426 | 74.26% |','',
        '**56.46%是满足当前区间上限的候选比例，74.26%含需要改变机票分项区间的建议，二者都不是实际预订率。仍有2,574人没有在本次报价与总预算内找到候选；未达到90%。**','',
        '新方法先用实际采集的航班、日期、机票区间和全程上限筛选，再按当前动态画像排序；枚举住宿/餐饮/活动的三档情景费用，并加入10%机动预留。改期、换目的地、中转、费用档位及机票分项调配均保持待确认。不存在以高兴趣分抵消超预算的情况。','',
        '共采集72组查询快照（原条件32组、备选40组），同条件旅客共享查询，不能视为10,000条独立航班证据。原条件8条代表航线，备选另含西安、太原、重庆、武汉、昆明及向后3天日期；不代表全国航班覆盖。报价具有查询时间，可能过期，使用前需刷新。无结果与失败保留，不以2024机票补缺；非机票费用仍为情景估算。','',
        '## 可重现与文件','',
        '- 主测试数据：`航旅智策应用/runtime/independent-evaluation/annual-2026-10-16-v1/test/`。',
        '- 全年行为：`behaviors.csv.gz`；属性：`users.jsonl`；数组：`behavior_arrays.npz`。',
        '- 动态画像：`profile_snapshots.jsonl`；价格区间：`budget-range-v1/`。',
        '- 每位旅客方案、逐日活动和差额：`constraint-first-v1/traveler_plans.jsonl`。',
        '- 指纹与版本：[独立数据清单](../distribution/independent-test-2026-10-16.json)。大文件与原始航班响应仅本地保存，不进入Git提交。',
        '- 结果：[原模型对照](../experiments/results/independent-2026-10-16/evaluation_report.json)、[新方法确认测试](../experiments/results/independent-2026-10-16/new_method_report.json)、[可行性检验](../experiments/results/independent-2026-10-16/constraint_report.json)。','',
        '应用目录运行：','',
        '```text',
        'python independent_evaluation.py evaluate --anchor 2026-10-16',
        'python independent_evaluation.py profiles --anchor 2026-10-16',
        'python independent_evaluation.py flights --anchor 2026-10-16',
        'python new_method_evaluation.py runtime/independent-evaluation/annual-2026-10-16-v1',
        'python price_range_evaluation.py runtime/independent-evaluation/annual-2026-10-16-v1',
        'python feasibility_benchmark.py all runtime/independent-evaluation/annual-2026-10-16-v1',
        '```','',
        '联网命令需要已有HTTPS代理。重新采集只追加快照；日期已过去时创建新版本，不改写旧日期。模型对照与确认结果已锁定，重复执行不根据测试结果调参。2024原始数据、训练权重、活动、个人方案及网站视觉均保留。','',
        '验收：核心/营销/本地生成/分发37项、旅行规划13项、独立数据与约束方法17项；双入口隔离浏览器25项。指纹、365万CSV行数、用户隔离、未来特征遮蔽、实际报价关联与逐人预算上限另作数据审计。']
    text='\n'.join(lines)+'\n'
    # Price refreshes may change feasibility. Never freeze acceptance counts in prose.
    fixed=intervals['scenarios']['fixed_direct']['feasible']
    direct=intervals['scenarios']['range_direct']['feasible']
    strict=constraints['counts'].get('original_conditions_feasible',0)+constraints['counts'].get('alternative_requires_confirmation',0)
    alternative=constraints['counts'].get('alternative_requires_confirmation',0)
    proposals=constraints['counts'].get('additional_budget_reallocation_proposals',0)
    any_proposal=strict+proposals
    substitutions={'2,238':f'{fixed:,}','22.38%':f'{fixed/100:.2f}%',
        '3,164':f'{direct:,}','31.64%':f'{direct/100:.2f}%',
        '2,482':f'{alternative:,}','24.82%':f'{alternative/100:.2f}%',
        '5,646':f'{strict:,}','56.46%':f'{strict/100:.2f}%',
        '1,780':f'{proposals:,}','17.80%':f'{proposals/100:.2f}%',
        '7,426':f'{any_proposal:,}','74.26%':f'{any_proposal/100:.2f}%',
        '2,574':f'{10000-any_proposal:,}'}
    for old,value in substitutions.items():text=text.replace(old,value)
    (project/'docs/independent-evaluation-2026-10-16.md').write_text(text,encoding='utf-8')
    local=text.replace('../distribution/independent-test-2026-10-16.json',str((project/'distribution/independent-test-2026-10-16.json').resolve()).replace('\\','/'))
    (root/'结果说明.md').write_text(local,encoding='utf-8')
    print('ANNUAL_EVIDENCE_AUDITED',len(users),3650000,len(files),flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);build(p.parse_args().root)
