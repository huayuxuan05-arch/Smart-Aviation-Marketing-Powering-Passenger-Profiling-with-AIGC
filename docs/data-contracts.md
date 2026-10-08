# 数据层设计

数据层统一旅游搜索、航线、节假日、用户行为和营销反馈。主案例优先使用中国节假日数据，公开事实保留原始粒度；数据不足的功能以明确标注的合成事件演示。

## 五类数据

| 数据对象 | 核心字段 | 当前来源与缺口 |
|---|---|---|
| search_signal | origin_region destination query observed_at value unit platform | 已有少量平台汇总；逐日、上海地域趋势待补 |
| route_supply | origin_airport destination_airport departure_date query_at fare tax_included seats source_id | 已有热门城市对和部分运力计划；完整时刻、历史价格、库存待补 |
| holiday_calendar | holiday_id start_date end_date day_count workday_adjustments | 已核验2025国庆中秋8天；其他节日另核验 |
| behavior_event | synthetic_user_id event_id event_at event_type destination session_id | 计划生成搜索、浏览、收藏等合成事件；无企业个人日志 |
| marketing_event | campaign_id assignment_id event_id event_at event_type channel order_id | 计划生成曝光、点击、购票、退订等合成反馈；无真实投放记录 |

共有元数据：record_id、source_id、published_at、collected_at、available_at、period_start、period_end、geography_level、data_kind、quality_flag、usage_scope。data_kind取public_aggregate、authorized_individual或synthetic；预测、实绩、计划、派生值另存value_type。导入时不能仅凭文件名推断属性。

## 时间与关联

查询日是看到价格或热度的时点，出行日是航班或旅游发生时间，发表日决定历史上何时可用。published_at与实际观测截止日分开；历史回测只使用available_at不晚于决策截点的证据。时区统一Asia/Shanghai，来源时区另存。

画像以用户及as_of生成快照，推荐引用快照ID。反馈以活动、实验分配、内容版本关联，订单按order_id去重；没有合法关联键的外部数据不能拼成同一旅客。公开城市热度不能赋为某个合成用户的真实行为。

## 粒度与缺失

机场吞吐量、城市对销量、独立旅客、票数、平台指数分别定义。国庆8天合计不得均分伪造8条日数据；缺失保持null，零表示确实观测到零。城市对没有机场信息时保留城市级，成都双机场合计不得全部映射天府机场。未说明方向的热门航线名单不推断出发方向。

## 数据进入系统的步骤

1. 登记来源和使用范围，保留引用及获取时间，原始网页仅作本地核验。
2. 清洗日期、地点、单位及重复项，记录转换规则；原值与派生值分开。
3. 输出聚合事实、产品事实和个人事件三类版本，不跨粒度强行拼接。
4. 检查覆盖率、时间泄漏及质量，再允许进入模型或知识库。

现有入口为[节假日航空事实](../data/public/china-holiday-aviation-2025.json)及[调研说明](research/china-holiday-aviation-data.md)。其他公开旅客数据集作为方法研究候选，须确认地区、时间与许可，不能直接代表中国国庆客群。
