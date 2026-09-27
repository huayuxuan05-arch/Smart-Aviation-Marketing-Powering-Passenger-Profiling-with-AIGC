# 数据契约与特征体系

## 当前Demo输入

由 `synthetic_passengers(count=120, seed=42)` 构造嵌套对象，当前不提供真实数据上传入口。导出命令 `python scripts/export_demo.py` 可获取实际JSON与特征CSV示例。

| 字段 | 类型 | 语义与约束 |
|---|---|---|
| id | string | `SYN-0001`形式的虚拟身份，非手机号/证件 |
| origin | string | 合成出发城市，候选航线需要匹配 |
| budget | number | 合成预算，人民币；排序因素而非真实支付能力判断 |
| events | array | event_type/destination/occurred_at；带时区ISO时间 |
| consent | boolean | 演示营销授权，真实版必须有独立授权账本 |
| channels | string[] | app/email演示渠道偏好 |
| preferred_hour | integer | 上海时区偏好小时；真实版还需静默时段/时区 |
| contacts_7d | integer | 固定演示窗口已有联系次数；另累计SQLite中的模拟次数 |
| has_booking | boolean | 已购票排除标记；真实版需对齐航线及旅行窗口 |
| data_source | string | 必须明确 synthetic / authorized_real 等来源 |

## 企业事件表（设计，尚未接入）

建议分开存储 `behavior_events`、`consent_ledger`、`bookings`、`route_inventory` 与 `delivery_feedback`，不要在合成旅客文件中直接塞入实名数据。

| 表 | 关键字段 | 质量验收 |
|---|---|---|
| behavior_events | event_id, pseudonymous_id, event_type, topic, destination, event_time, ingest_time, region, source, purpose | 去重、时区、用途授权、无未来事件、可追溯来源；搜索/景区/酒店/价格/攻略字段覆盖 |
| consent_ledger | subject_id, purpose, channel, granted_at, revoked_at, policy_version | 撤回及时同步，发送前复核，缺授权即拒绝 |
| bookings | booking_id, subject_id, route_id, booking_time, departure_time, status, contribution_margin | 订单去重，退改状态，时间归因窗口一致 |
| route_inventory | route_id, origin, destination, departure_time, available_seats, fare, currency, queried_at, product_terms | 库存/价格时效，产品条款，禁止使用陈旧促销事实 |
| delivery_feedback | event_id, campaign_id, experiment_id, arm, subject_id, action, event_time, channel, cost | 幂等、送达与点击区分、机器人点击过滤、退订护栏 |

身份映射单独保管；随机哈希不等于匿名化。外部数据是否可获得尚未确认，不采集未授权跨平台个人轨迹。

## 特征、标签与验证

- 时点特征：`as_of`前7/14/30天搜索次数、兴趣目的地、价格关注比例、行为新近性、访问时间分布、跨渠道偏好与频控余额。
- 当前意向分：有效30天事件权重 `exp(-age_days/7)` 的总和除以6，上限1；高意向阈值0.5。参数是工程基线，需要真实验证。
- 标签候选：`as_of`后7/14天目标航线购票（业务确认窗口）；历史订单只用于截点前特征，未来订单只用于标签。
- 切分：按时间顺序训练/验证/测试，注意同一旅客跨集合及同一节日重复观测；在验证集选阈值，不在测试集调参。
- 推荐目标：候选航线真实可售、目标时间匹配，结合意向与边际收益；不能用未知真实标签替代模型输入。
- 合成数据只验证接口和不变量，不用于声称模型准确率、企业画像质量或真实业务收益。

## 输出对象

画像含 segment/intent_score/interests/reasons/as_of/model_type/data_source。活动含 id/passenger_id/status/route/decision/content/result。草稿状态为 draft→approved→simulated；模拟执行记录 real_messages_sent=0。真实集成需扩展 generation_id、模型/知识/策略版本、审核人、reviewed_at、授权快照与订单归因链。
