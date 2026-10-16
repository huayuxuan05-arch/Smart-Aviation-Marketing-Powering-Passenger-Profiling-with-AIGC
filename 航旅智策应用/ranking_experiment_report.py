"""Audit local experiment outputs; publish only aggregate results and fingerprints."""
import argparse
import json
from pathlib import Path
from collections import Counter
import independent_cohort as cohort
import marketing_ml as ml


def run(root):
    root=Path(root).resolve();source=root/'lambdamart-v1';project=Path(__file__).resolve().parent.parent
    def read(name):return json.loads((source/name).read_text(encoding='utf-8'))
    ranking=read('report.json');quotes=read('quote_audit.json');expanded=read('expanded-quotes-v1/report.json')
    calibration=read('attention-calibration-v1/report.json');ready=read('real-choice-readiness/readiness.json')
    assert cohort.digest(ml.ROOT/'marketing_models.joblib')==ranking['protocol']['original_model_sha256']
    assert not ranking['online_weights_replaced'] and not ranking['promotion_gate_passed']
    counts=Counter();n=0
    for line in (source/'traveler_plans.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line);n+=1;counts[row['status']]+=1
        assert row['is_synthetic'] and row['accepted'] is False
        p=row['original_conditions'];assert len(row['daily_itinerary'])==p['days']
        selected=row['selected']
        if selected:
            assert selected['estimated_total']<=p['adult_trip_budget']['max']
            assert max(selected['option'][leg]['price_cny'] for leg in ['outbound','inbound'])<=p['one_way_airfare']['max']
    assert n==quotes['users']==10000 and dict(counts)==quotes['counts']
    feature_rows=0
    with (source/'prospective_itinerary_features.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);feature_rows+=1
            assert row['relevance_label'] is None and row['plan_adopted'] is None and row['is_synthetic']
    assert feature_rows==quotes['prospective_feature_rows']
    public=project/'experiments/results/lambdamart-2026-10-16';public.mkdir(parents=True,exist_ok=True)
    aggregates={'ranking_report.json':ranking,'training_provenance.json':read('training_provenance.json'),
        'quote_audit.json':{k:v for k,v in quotes.items() if k!='sources'},
        'expanded_quotes.json':expanded,'attention_calibration.json':calibration,
        'real_choice_readiness.json':ready,'quote_quality.json':read('quote_quality.json'),
        'transport_recheck.json':read('transport_classification_check.json')}
    for name,value in aggregates.items():cohort.write_json(public/name,value)
    artifacts=[]
    for path in sorted(source.rglob('*')):
        if path.is_file():artifacts.append(dict(path=path.relative_to(source).as_posix(),bytes=path.stat().st_size,sha256=cohort.digest(path)))
    index=dict(version='lambdamart-2026-10-16-v1',local_root='航旅智策应用/runtime/independent-evaluation/annual-2026-10-16-v1/lambdamart-v1',
        storage='local only; model/data/raw quote payloads not committed or released',artifacts=artifacts,
        original_source_license='retain original distribution licenses; no additional raw-data rights asserted',
        original_model_sha256=ranking['protocol']['original_model_sha256'])
    cohort.write_json(project/'distribution/lambdamart-2026-10-16.json',index)
    selected=ranking['selected_method'];old=ranking['holdout']['原冻结模型'];new=ranking['holdout'][selected]
    content=f'''# 行程排序与数据质量更新（2026-10-16）

本轮把既往模拟用户继续用于开发，完成 LambdaMART 对照、当前航班扩采、行程级特征和真实操作反馈链路。城市关注实验小幅提升，但未达到替换门槛；线上需求权重保留。候选行程采纳排序已具备训练入口，真实显式正负标签不足，尚未训练或上线。

## 样本与目标

- 复用原2024年10,000名模拟旅客，以及既往 training/test/confirmation 各按固定种子抽取4,000人，共22,000人。每人3个截点，共66,000组请求、2,706,000条用户—城市记录，36项特征。
- 既往 test/confirmation 已看过结果，本轮明确转作开发资料；原文件、旧实验报告及原模型不改写。
- 验证使用2,000名独立用户。验证选定模型后，另生成10,000名新模拟用户、每人365天行为，检查与全部旧批次无编号重叠，再执行固定3截点测试。
- 该实验仍以“未来7天同城市至少2次搜索”为标签，只验证城市关注排序，是行程排序中的兴趣子模块；不等于完成真实航班、酒店和行程采纳学习。
- 过去截点的训练特征不回填今天的航班价格。当前价格用于当前日期的约束检查和前瞻行程特征；2024航班仍只在原离线数据层保留。

## LambdaMART 对照

每个用户/截点的41个城市组成完整分组，比较3组固定树深度与配对策略；只按验证集选型。实现依据 [XGBoost 官方排序文档](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)，可选依赖固定为xgboost 3.4.1。

| 方法 | 新独立用户 Recall@3 | NDCG@3 |
| --- | ---: | ---: |
| 原冻结模型 | {old['recall_at_3']:.6f} | {old['ndcg_at_3']:.6f} |
| 14天衰减规则 | {ranking['holdout']['14天衰减']['recall_at_3']:.6f} | {ranking['holdout']['14天衰减']['ndcg_at_3']:.6f} |
| 验证选中：{selected} | {new['recall_at_3']:.6f} | {new['ndcg_at_3']:.6f} |

按用户平均的配对NDCG差值：相对原模型 {ranking['delta_against_original']['mean']:.6f}，95%区间 {ranking['delta_against_original']['ci95']}；相对验证选出的最强规则 {ranking['delta_against_best_rule']['mean']:.6f}，95%区间 {ranking['delta_against_best_rule']['ci95']}。配对统计按用户平均，表格按有正标签的截点平均，两者权重不同。预设门槛为同时超过原模型和规则至少0.005且区间下界大于0，并限制Recall退化。**本轮未通过，不替换线上权重。**

30,000个用户截点中27,071个有相关城市，2,929个无相关城市单列。分群结果完整保留。广泛探索组的浏览由模拟器随机生成，学习方法Recall约7.16%；其未来选择缺乏稳定信号，不能靠换模型保证命中。行为熵与集中度可提示补充偏好，本批10,000人中1,661人被标为需确认，仍保留在方案覆盖率分母中。

## 当前航班与预算

本轮新增96组查询：原范围重采72组，加6条航线×2个出发日×2种时长共24组。新增航线为武汉—上海、杭州—西安、西安—厦门、重庆—广州、南京—成都、长沙—北京；新增出发日2026-11-06与2026-11-13。新增24组有20组返回方案、4组无完整可用方案。连同上轮72组，共168条查询快照；多人复用同一查询，不视为独立航班观测。

在本轮原范围72组快照上，10,000名模拟旅客中1,702人保留原城市/日期/直飞条件找到预算内方案，2,198人取得需确认的备选，6,100人暂无可行报价，合计 **39.00%**。预算仍是先前固定的80%—120%模拟区间；不增加总预算或机票上限，不与过去56.46%直接解释为模型升降。非机票费用为三档情景估计及10%预留；原条件可行只指城市、日期、直飞及预算，上述费用档位变化仍需确认。新增24组不同日期的查询未强塞进原旅客±3天许可范围。

该批72组中有207次成功单程响应、10次有效空响应、191次失败尝试（含工具内部重试）。旧适配仅记录ValueError，不能追溯每次失败原因。后续抽查复现：HTTP200返回约325字节的`wrb.fr`错误包，业务载荷为null、错误码13；同一请求也曾返回约145KB的正常数据。可确认存在间歇性上游错误，不能进一步断言所有历史失败都由相同原因、限流或机场问题造成。

现已按原始字节解码，并记录参数、HTTP、协议解码、航班行等失败阶段及数值业务错误码；有失败航段且未返回完整方案的查询记failed，有效空响应才记empty。没有用历史票价补缺。这些处理改善可诊断性，并未证明已修复上游错误或提高市场覆盖。集成层使用 [AdvSearchFlights](https://github.com/suneveryday/AdvSearchFlights) 固定提交和其fli提供器，本地代理适配保留。所有报价在实际使用前重新查询。

## 候选行程训练与真实反馈

独立行程模块先检查报价时间、航班日期和预算上限，再排序。17项前瞻特征包括提前购票天数、改期天数、区间宽度、往返机票占总预算比例、中转、四个起降时段、飞行时长与报价年龄。输出10,000份逐日方案和11,378行候选特征；无报价者有待匹配日程，采纳标签全部为null，不伪造选择。

网站新增“不考虑”操作；比较预算只算preview，明确确认并保存航班才算choose，明确点击不考虑才算reject。修改偏好记录字段版本；删除方案及放弃草稿分别记录，不当作拒绝。数据与方案在相同本地事务中提交，保留会话归属和旧版本校验；未选中候选保持未标注，前后冲突判断排除。只在硬预算、直飞等约束满足的候选内构造显式正负排序分组。

真实行程排序训练入口按用户分组并按事件时间前推，先验证选型、后测试，提供简洁费用比例基线及按用户配对区间，模型不自动部署。当前显式正负配对请求为0，达不到预设至少50名独立用户、100组配对请求的启动门槛。模型因此未训练。这是最小启动规则，不保证统计功效或模型有效。

现有个人表单收集的是本人填写的预算上限；反馈特征采用该实际上限，未采集的下限保存null，**没有把上限或问卷档位冒充完整个人区间**。真实问卷仅作补充，不与模拟编号合并，不把城市意愿当方案采纳。还需后续收集实际区间、酒店选择和节奏调整，才能验证行程整体偏好。

## 已定义事件的概率校准

原模型分数用固定sigmoid校准，只在2,000名验证用户上拟合，再用另2,000名全新模拟用户、365天行为和3个截点评估。246,000个城市事件的正例占3.04%。Brier从{calibration['metrics']['uncalibrated']['brier']:.6f}降为{calibration['metrics']['sigmoid']['brier']:.6f}，10等宽箱ECE从{calibration['metrics']['uncalibrated']['ece_10_bins']:.6f}降为{calibration['metrics']['sigmoid']['ece_10_bins']:.6f}；按用户配对Brier改善区间为{calibration['ci95']}。单调变换保留原排序。实现依据 [概率校准说明](https://scikit-learn.org/stable/modules/calibration.html)。该分数只解释模拟的未来关注事件，不能解释购票或采纳概率；保留为离线影子产物。

## 复现与验收

可选实验依赖为`航旅智策应用/requirements-experiments.txt`。运行`lambdamart_evaluation.py`生成对照；结果存在即锁定，不重新选型。`attention_calibration.py`单独生成校准评估。`expanded_quote_collection.py`每次要求新目录并保留全部状态。`choice_ranker_training.py`在真实显式标签不足时只写就绪检查，不生成虚假模型。

完整后端172项通过；航班错误分类变更后相关37项复查通过。入口浏览器25项、航班浏览器12项通过，包含显式拒绝、人数均摊、会话隔离、手机布局及零JS异常。浏览器使用独立数据库和明确标注的航班夹具；实时报价采集属于另一组联网证据。五层框架与数据合同检查通过，原始数据和Qwen权重保留。

大型模型、年度行为、逐人方案、原始报价与真实操作数据库保留在D盘runtime，不提交。公开的仅为源码、汇总结果及SHA256索引，未创建新的大型数据Release。
'''
    (project/'docs/lambdamart-2026-10-16.md').write_text(content,encoding='utf-8')
    print(json.dumps(dict(audited_users=n,prospective_rows=feature_rows,local_artifacts=len(artifacts),public_results=len(aggregates)),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
