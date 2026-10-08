# 后端接口规划

以下接口是待实现契约，不是当前可调用API。统一前缀/api/v1，输入输出携带scenario_id、as_of、data_version和data_kind；时间为带时区的ISO格式。

| 方法与路径 | 输入 | 输出 |
|---|---|---|
| GET /sources | 场景、数据类型 | 来源、覆盖、单位、发布日期、使用范围 |
| POST /forecast-runs | 场景、目标、预测窗口、模型配置 | run_id、预测或数据不足状态、模型版本 |
| POST /profile-snapshots | 用户／客群标识、截点 | 标签、证据、置信度、快照ID |
| POST /recommendations | 快照、日期、预算情景 | 候选、约束、理由、未知项 |
| POST /strategy-plans | 候选、渠道、预算、约束 | 决策方案、成本假设、版本 |
| POST /knowledge/search | 目的地、主题、任务模式、截点 | 片段、来源、有效期、知识版本 |
| POST /content-drafts | 方案ID、事实卡、生成方式 | 文案、视觉任务、引用、生成记录 |
| POST /content-reviews | 草稿版本、审核结论 | 审核记录、允许的下一步 |
| POST /campaigns | 已审核方案、实验分配 | 活动ID、草稿或可执行状态 |
| POST /campaigns/{id}/simulate | 活动ID、幂等键、种子 | 模拟事件、状态、合成标记 |
| POST /campaigns/{id}/stop | 活动ID、原因 | 停止状态 |
| GET /experiments/{id} | 实验ID | 切分、模型对照、指标与限制 |

数据不足用明确业务状态返回，参数无效返回校验错误，资源缺失返回不存在，旧版本审核或重复冲突返回版本冲突。异步生成与训练返回run_id供查询，错误记录不含密钥或个人原文。实际实现需增加角色认证与权限；本框架不提供无保护的公网服务。
