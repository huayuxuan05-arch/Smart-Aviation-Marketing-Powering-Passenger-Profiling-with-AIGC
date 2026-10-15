# 航旅智策五层架构

航旅智策——节假日航空智慧营销决策系统，以航空营销人员为使用对象。当前实现由本地 Python 服务、SQLite、训练模型、Qwen 和浏览器界面组成。

| 层 | 主要文件 | 输入与输出 |
| --- | --- | --- |
| 数据层 | data_layer.py、build_data.py | 三份 Excel → 校验后的全量 SQLite 索引 |
| 算法层 | marketing_ml.py、algorithm_layer.py | 截点前行为 → 需求分数、五群画像、渠道时机、历史航班候选 |
| AIGC层 | content_generation.py、local_generation.py、aigc_config.py | 默认规则/模板；可选本地模型提取条件、细化说明、生成文案与SVG配方 |
| 应用层 | personal_assistant.py、personal_app.py、marketing_app.py、server.py、web/ | 文字需求草稿、工具核验和确认后的个人方案；营销版本化名单、审核及模拟触达 |
| 评估层 | marketing_ml.py、marketing_app.py、evaluation_layer.py | 固定测试集与未来行为 → 模型比较、活动复盘、历史漏斗 |

数据、算法和生成均在电脑本地运行，服务只监听 127.0.0.1。活动与素材存入独立营销数据库，不改写原始 Excel。改变名单或内容版本后，旧审批失效，需重新审核。

完整发布包负责分发原始数据、训练产物及语言模型；首次准备仅重建索引，不重新训练。配置入口为 configs/project.json，使用方法见[仓库首页](../README.md)。

## 当前航班适配

flight_quotes.py负责代理强制、后台队列、当前报价、观测持久化、Web投影和预算预览；personal_app.py负责本人确认后另存方案。web/flight-quotes.js嵌入原旅行方案区域并自动查询和刷新。依赖固定到AdvSearchFlights 7adb330及flights 0.9.0，仅复用解析、机场展开及组合能力，不调用其启动网络探测，不使用其10,000条历史清理策略。原2024航班数据和训练流程保留为离线来源。
