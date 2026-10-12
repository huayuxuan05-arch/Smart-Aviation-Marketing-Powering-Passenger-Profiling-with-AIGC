# 航旅智策——节假日航空智慧营销决策系统

面向航空营销人员的本地交互 Demo，基于 10,000 名模拟旅客和 2024 年历史航班，实现“需求识别—旅客分群—内容生成—渠道触达—效果评估”的操作闭环。

## 换电脑运行

1. 下载本仓库并解压至 D 盘，安装 Python 3.11 或以上。
2. 双击根目录的“准备并启动Demo.cmd”。
3. 等待自动下载、校验及恢复数据和模型，浏览器打开 http://127.0.0.1:8765/ 。

[完整发布包](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12) 包含三份原始 Excel、已训练需求模型和 Qwen3.5-9B 量化权重，无需重新训练。项目虚拟环境、模型、下载缓存和临时文件都在项目盘内。

完整文案生成使用 Windows x64、NVIDIA 驱动及 llama.cpp CUDA 运行时。暂不使用语言模型时，在应用目录运行：

    ./Prepare-Demo.ps1 -DataOnly

GitHub 分发源码及发布文件，Python 网站和语言模型在本机运行。后续启动、停止分别双击应用目录中的“启动本地测试版.cmd”和“停止本地测试版.cmd”。

## 使用流程

1. 在活动总览查看热点，新建营销活动；在需求洞察调整假期、区域、目的地和客群。
2. 在潜客与画像中查看证据、兴趣变化和预算，选择旅客并冻结名单。
3. 在航线与策略中检查出发城市、历史日期、价格、渠道和触达时段。
4. 在创意工坊调用本地 Qwen 生成文案和 SVG 海报，编辑并完成三项人工审核。
5. 在渠道触达执行本地模拟；在效果复盘查看未来七天的关注、机票查询及收藏代理结果。

“我的活动”支持删除、恢复；创意工坊支持删除待审核素材。完整操作见[应用说明](航旅智策应用/README.md)。

## 五层实现

| 层 | 当前能力 | 说明 |
| --- | --- | --- |
| 数据层 | 三份原始 Excel 流式导入、来源校验、SQLite 索引 | [数据层](docs/data-contracts.md) |
| 算法层 | 23 项特征、需求模型、五类聚类、航线约束、渠道时机预测 | [算法层](docs/algorithms.md) |
| AIGC层 | Qwen3.5-9B 本地生成、事实槽位、SVG 合成、人工审核 | [AIGC层](docs/aigc.md) |
| 应用层 | 七页营销流程、活动与素材持久化、频控、模拟触达 | [应用层](docs/application.md) |
| 评估层 | 时间切分、固定测试、基线比较、后续行为及历史漏斗 | [评估层](docs/evaluation.md) |

总体关系见[五层架构](docs/architecture.md)，训练及验收证据见[实验记录](experiments/results/local-demo-2026-10-12/README.md)。

## 数据与效果边界

训练覆盖 3,970,000 条模拟日行为，10,000 名旅客、41 个目的地。航班和价格为 2024 年历史记录，旅客行为、营销反馈及订单为模拟数据。模型分数表示后续关注代理，不能解释为真实购票概率、当前库存或实际新增收入。

Qwen 权重来自官方基础模型的 Unsloth GGUF 量化版本，未用旅客数据微调；视觉是 SVG 合成示意，不是扩散图像或景点实拍。没有实时旅游知识库、真实投放或因果业务增益验证。

## 检查

    python scripts/validate_framework.py
    python scripts/validate_dataset.py
    cd 航旅智策应用
    python -m unittest test_core test_marketing test_local_generation test_distribution -v

GitHub CI 验证源码、五层文档、数据与发布清单及发布包安全测试；全量业务测试需先还原数据和模型。

## 目录

| 目录 | 用途 |
| --- | --- |
| 航旅智策应用/ | 网站源码、启动脚本和测试 |
| 数据集/ | 原始工作簿还原位置、字段及来源说明 |
| distribution/ | 发布清单与模型许可 |
| docs/ | 当前五层实现说明 |
| experiments/ | 训练、验收和发布校验记录 |
| scripts/ | 仓库校验、打包和迁移验证工具 |
| configs/ | 当前场景和五层状态 |
