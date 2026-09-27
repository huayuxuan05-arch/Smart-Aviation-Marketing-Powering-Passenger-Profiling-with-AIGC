# 当前数据计划与契约

采用公开聚合信息研究与沙盒验证两条数据路线。企业不提供真实数据按补充攻略作为当前规划前提，正式口径后续核对。不预设平台开放个人浏览、搜索、收藏、订单或联系方式。

## 来源台账

| 字段 | 用途 |
|---|---|
| source_id 与 source_url | 追溯原始页面/资料 |
| publisher 与 published_at | 发布者和发布日期 |
| collected_at 与 time_range | 获取时点和统计期间 |
| access_method 与 usage_scope | 获取方式、许可/用途及公开边界 |
| granularity 与 definition | 地区/日期/主题粒度和指标口径 |
| limitations | 样本偏差、缺失、不可比性 |

候选是搜索趋势、公开内容主题统计、旅游统计和产品信息，是否可得需试查，不以“公开可见”推定可追踪个人。

## 聚合需求面板

建议字段为region、date、destination、topic、signal_type、signal_value、unit、source_id、quality_flag。不同平台值先按各自口径标准化，原始值保留；不直接混加不可比指数。没有个人订单标签时，结果只描述市场需求代理信号。

## 产品事实卡

建议字段为product_id、origin、destination、travel_window、fare_terms、valid_until、source_id、queried_at。无实时库存接口时不标称即时可售；缺失价格或权益不交给模型补齐。

## 沙盒契约

虚拟旅客含synthetic_id、origin、interest_events、budget_scenario、consent、channels、contacts_window、as_of、generation_seed、assumptions、data_source=synthetic。反馈中的转换概率也标为人工设定；不冒充市场热度对应的实际个人行为。

可用原型生成示例：在prototypes/offline-demo/运行`python scripts/export_demo.py`。导出只证明工程链路。原始材料与不可公开数据不上传GitHub。

未来如获得许可的企业数据，再参考[企业字段设计](reference/enterprise-data-contracts.md)，当前不依赖该契约完成研究。
