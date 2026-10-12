# 航旅智策五层架构

航旅智策——节假日航空智慧营销决策系统，以航空营销人员为使用对象。当前实现由本地 Python 服务、SQLite、训练模型、Qwen 和浏览器界面组成。

| 层 | 主要文件 | 输入与输出 |
| --- | --- | --- |
| 数据层 | data_layer.py、build_data.py | 三份 Excel → 校验后的全量 SQLite 索引 |
| 算法层 | marketing_ml.py、algorithm_layer.py | 截点前行为 → 需求分数、五群画像、渠道时机、历史航班候选 |
| AIGC层 | local_generation.py、aigc_config.py | 事实卡、兴趣主题 → 本地生成文案、SVG 配方及素材 |
| 应用层 | marketing_app.py、server.py、web/marketing/ | 营销任务 → 版本化名单、审核、模拟触达和操作记录 |
| 评估层 | marketing_ml.py、marketing_app.py、evaluation_layer.py | 固定测试集与未来行为 → 模型比较、活动复盘、历史漏斗 |

数据、算法和生成均在电脑本地运行，服务只监听 127.0.0.1。活动与素材存入独立营销数据库，不改写原始 Excel。改变名单或内容版本后，旧审批失效，需重新审核。

完整发布包负责分发原始数据、训练产物及语言模型；首次准备仅重建索引，不重新训练。配置入口为 configs/project.json，使用方法见[仓库首页](../README.md)。
