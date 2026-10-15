# 华翼朝阳 · 个性化旅游定制

航旅智策——节假日航空智慧营销决策系统的当前实现，保留数据、算法、AIGC、应用、评估五层。

<img src="航旅智策应用/web/assets/huayi-chaoyang-logo.png" alt="华翼朝阳" width="76">

## 两个使用入口

| 入口 | 地址 | 当前功能 |
| --- | --- | --- |
| 个人旅客 | `/personal/` | 保存出游意向与个人偏好，生成、保存、导出自己的旅行方案 |
| 营销人员 | `/marketing/#trips` | 旅行方案、活动总览、需求洞察、画像、航线、创意、模拟触达、复盘 |

首页 `/` 选择入口。个人端以本次主动填写为依据，按独立浏览器会话保存偏好版本与历史方案。日期、天数、预算未确定时可仅保存意向；确定出游后支持2至8天、具体景点、住宿侧重、日期弹性、备选许可和超预算处理。

营销端服务全部10,000名模拟旅客，旅行规划不受营销名单限额或退订状态删减。逐人提供去返历史航线参考、逐日活动、住宿条件、预算、备选与核验清单；默认国庆历史场景中10,000人均有规划及往返参考，569人有目标日历史直飞。历史参考不等于当前可售机票。

界面使用直接功能名称，去除宣传式步骤说明、画像截至和规划范围公共栏。问卷只作后台补充，收集工具与空白问卷保留，不在网站单独设置统计页或导航入口。原始答卷、整理后逐人数据和个人方案不提交仓库。

## 本地运行

1. 下载或克隆本仓库，解压至D盘，安装Python 3.11或以上。
2. 双击根目录的“准备并启动Demo.cmd”。
3. 自动下载、校验并恢复原有数据与模型后，访问 `http://127.0.0.1:8765/`。

现有[发布资产](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12)提供三份模拟/历史原始Excel、需求模型和Qwen3.5-9B量化权重；最新网站源码以本仓库主分支为准。完整本地语言模型推理使用Windows x64与NVIDIA CUDA；仅准备网站数据时，在应用目录运行 `./Prepare-Demo.ps1 -DataOnly`。

后续通过应用目录中的“启动本地测试版.cmd”和“停止本地测试版.cmd”管理服务。网站无需云端模型密钥，不调用收费模型或真实营销平台。详见[应用使用说明](航旅智策应用/README.md)。

## 数据与模型

- 原模拟行为模型使用3,970,000条过程记录、10,000名旅客、41个目的地，按时间划分训练、验证和冻结测试。
- 营销候选先满足历史产品条件，再按名单配额选择；同次行程预算、原始航班日期、素材审核、业务资格、退订与跨活动频控分别核验。
- 本地Qwen解释已有结构化事实，生成可编辑建议、文案及SVG海报；没有用真实答卷微调Qwen权重。
- 问卷导入与偏好模型独立保存。最新人工整理版模型未超过热门基线，保留为对照；线上采用主动偏好、预算与航线约束，样本热度只作并列参考。
- 没有真实购票、实时库存、真实渠道授权和因果增益标签，不报告实际收入或转化提升。

真实问卷属于可选私有补充；其他使用者未导入问卷时，网站仍按用户主动选择与既有规则运行。问卷同意研究与复访不等于营销授权。方法和汇总结果见[问卷补充与验证](docs/survey-evidence.md)。

## 验证

```powershell
python scripts/validate_framework.py
python scripts/validate_dataset.py
cd 航旅智策应用
python -m unittest test_core test_marketing test_decisions test_travel_planner test_personal test_survey_evidence test_local_generation test_distribution -v
node entry_browser_check.cjs
node travel_browser_check.cjs
node decision_browser_check.cjs
```

先还原数据与模型再执行完整业务检查。三个浏览器脚本顺序执行，各自使用8769隔离服务与临时活动库，需要Chrome及Playwright；脚本支持本机运行时路径，未把无数据CI当作业务验收。

本次同步仓库源码在本机已核验的数据与模型上通过87项后端检查；开发版通过94项。双入口、逐页简化、活动状态、旅行与问卷、执行资格等浏览器验收通过。详情见[本次更新验收](experiments/results/local-demo-2026-10-15/README.md)。

## 五层及目录

| 层 | 说明 |
| --- | --- |
| 数据层 | [来源、字段与校验](docs/data-contracts.md) |
| 算法层 | [动态画像与约束推荐](docs/algorithms.md) |
| AIGC层 | [本地模型、事实及人工审核](docs/aigc.md) |
| 应用层 | [入口、操作与保存](docs/application.md) |
| 评估层 | [时间切分、代理标签及边界](docs/evaluation.md) |

`航旅智策应用/`包含网站与启动脚本；`问卷资料/`只包含空白收集工具与字段说明；`distribution/`保存发布清单与许可；`experiments/`保存训练及验收记录；`scripts/`提供仓库与发布校验。`runtime/`、数据库、下载缓存、密钥与真实逐人答卷均留在本机。
