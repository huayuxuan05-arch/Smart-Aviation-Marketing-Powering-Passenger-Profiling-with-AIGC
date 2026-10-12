# 航旅智策——节假日航空智慧营销决策系统

面向航空公司营销人员的可交互本地 Demo，将节假日需求洞察、潜客识别、旅客画像、航线推荐、创意生成、渠道触达和效果复盘组织成完整操作流程。

**2026-10-12 更新：已同步当前本地应用源码。** 使用全量 10,000 名模拟旅客训练需求识别、分群及渠道时机模型；创意工坊已接入 Qwen3.5-9B 本地 GPU 推理。原有五层设计、公开证据研究与 Word 指南保留，当前实现以本页及[应用使用说明](航旅智策应用/README.md)为准。

## 启动本地应用

下载或克隆本仓库至 **D 盘**，安装 Python 3.11 或以上，然后双击仓库根目录的 **`准备并启动Demo.cmd`**。脚本会在项目内安装依赖，从 [完整 Release](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12) 下载并校验三份原始 Excel、已训练需求模型及 Qwen3.5-9B 权重，重建索引并启动网站。**无需重新训练需求模型。**

也可以在 PowerShell 中执行：

```powershell
cd 航旅智策应用
./Prepare-Demo.ps1
```

只需画像和航线功能、暂不准备语言模型时使用 `./Prepare-Demo.ps1 -DataOnly`。完整创意生成功能仍需本地 Qwen 推理所需的内存、显存与 NVIDIA 驱动；当前推理程序为 Windows x64 CUDA 版。Python、模型和后端均在本地运行，GitHub 页面本身不托管这些进程。

完成后在浏览器打开 `http://127.0.0.1:8765/`。已有索引、训练产物与语言模型时无需重建；在 Windows 上双击应用目录中的 `启动本地测试版.cmd` 即可，停止时使用 `停止本地测试版.cmd`。在其他机器上需要先安装 Python 及依赖。

本机启动脚本复用既有 Python 安装；模型、CUDA 程序、推理缓存和临时文件写入应用的 `runtime/`。保持仓库在 D 盘即可将这些项目文件留在 D 盘。下载模型使用固定版本、断点续传和 SHA256 校验，不需要云端 API 密钥。

## 如何使用

1. **活动总览 / 需求洞察**：选择假期、区域、目的地及筛选条件，识别热点并新建营销活动。
2. **潜客与画像**：查看分群、搜索访问收藏证据、兴趣变化和预算，冻结或调整旅客名单。
3. **航线与策略**：按旅客常用出发城市、计划日期与预算匹配历史航班，查看推荐理由和缺失条件。
4. **创意工坊**：选择代表旅客生成个性化文案，编辑、导出海报并人工审核。可删除单条待审核素材。
5. **渠道触达**：核对审核素材覆盖、退订及跨活动频控后，执行本地模拟触达。
6. **效果复盘**：回放完整未来 7 天行为，查看关注、机票查询和收藏代理结果。

“我的活动”支持删除与恢复；素材删除保留活动和旅客名单。旧旅客体验保留在 `/traveler/`，旧研究界面在 `/research/`。

## 五层框架与已实现能力

| 层 | 当前实现 | 设计材料 |
| --- | --- | --- |
| 数据层 | 三份 Excel 流式导入、SQLite 索引、数据来源指纹、时间与证据校验 | [数据契约](docs/data-contracts.md) |
| 算法层 | 23 项特征、逻辑回归与梯度提升比较、5 类聚类、渠道和时间习惯预测、历史航班约束 | [算法方案](docs/algorithms.md) |
| AIGC层 | Qwen3.5-9B-Q4_K_M 本地 CUDA 推理、引用事实、风险初筛、人工审核、SVG 海报合成 | [生成方案](docs/aigc.md) |
| 应用层 | 七页营销工作流、活动持久化、素材版本、删除、频控与模拟触达 | [页面设计](docs/application.md) |
| 评估层 | 时间划分、固定测试集、同候选基线比较、后续行为复盘及独立历史反馈 | [评估协议](docs/evaluation.md) |

训练使用 3,970,000 条模拟日行为，覆盖同一批 10,000 名旅客。训练、验证和测试按时间阶段划分；提前节假日回放使用当时可用的规则，避免引用未来模型。训练报告与来源校验快照见[验收记录](experiments/results/local-demo-2026-10-12/README.md)。

语言模型采用官方 Qwen3.5-9B 基础模型的 **Unsloth GGUF 量化版本**，由 llama.cpp CUDA 在本机推理。预训练语言模型未用旅客数据微调；视觉为模型选取主题、配色后合成 SVG，尚未接入扩散图像模型。

## 数据与结果边界

航班是 2024 年历史记录；旅客行为与营销反馈全部为模拟数据。模型分数和复盘指标代表后续关注代理，不能解释为真实购票概率或实际新增收入。历史票价不代表当前库存与可售价格；不会向外部平台发送营销消息，也不生成虚构曝光、点击或订单。

原仓库的[2025 国庆中秋航空研究](docs/research/)与公开来源材料保留为独立资料，未混入当前 2024 模拟旅客模型。完整框架与 Word 指南仍见[项目实施指南](docs/project-plan.md)及 `deliverables/`；其中框架阶段的计划和场景应按其历史版本阅读。

## 检查与目录

仓库框架检查：

```powershell
python scripts/validate_framework.py
python scripts/validate_public_data.py
```

已有数据索引和训练产物时，在应用目录运行：

```powershell
python -m unittest test_core test_traveler test_marketing test_local_generation test_distribution -v
node --check web/marketing/app.js
node creative_delete_browser_check.cjs
```

后端共43项测试（含7项发布包安全与断点恢复测试）。浏览器专项验收需要本地服务、Chrome 与 Playwright；脚本中的既有安装路径适用于当前开发机，迁移时需调整。无原始工作簿的 GitHub CI 仅验证公开框架与资料，不声称运行全量业务验收。

```text
航旅智策应用/                 可运行源码、启动脚本、测试与使用说明
数据集/                       原始数据的还原位置与说明
distribution/                 完整发布清单与模型许可
experiments/results/          已执行训练及验收的可公开记录
configs/                      当前五层实现状态与历史研究场景
docs/                         框架设计、公开证据、报告与实施指南
data/public/                  原有公开来源台账和聚合事实
backend/、frontend/            原有分层设计约定
knowledge/、prompts/           原有知识与生成规范
deliverables/                 原有可编辑 Word 指南
```
