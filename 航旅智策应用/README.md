# 华翼朝阳本地应用（航旅智策项目）

项目名称：航旅智策——节假日航空智慧营销决策系统。当前本机网页使用Qwen3.5-4B-Q4_K_M与NVIDIA CUDA，直接使用基础量化模型；语言模型微调已取消。当前功能、参与者使用步骤与200人现场安排统一见[应用说明](../docs/application.md)。

## 运行

首次双击仓库根目录“准备并启动Demo.cmd”，选择4B CPU、Vulkan、NVIDIA CUDA或仅数据。已有本机环境双击“启动本地测试版.cmd”，访问 http://127.0.0.1:8765/ 。Start-Local.ps1默认auto：存在active_model.json时启用本地模型，否则使用明确标注的模板模式。需要显式启用时运行 `./Start-Local.ps1 -GenerationMode local-model`。

“停止本地测试版.cmd”停止网站与本地模型并保留数据。运行不需要Node或云端模型密钥；浏览器验收需要Node、Chrome与Playwright。只监听127.0.0.1，适合在本机轮流使用。

## 使用与数据

个人端自行注册账号，填写真实需求，核对模型草稿后保存；可调整、查看历史与导出方案。航司、日期、预算均由本人确认。实时航班查询失败不表示没有执飞，也不会回填历史票价。营销端使用独立管理账号，仅分析仍同意共享的真实用户；撤回后当前画像与热度同步移除。模拟用户与验收会话不进入正式真实客群。

- `runtime/personal.sqlite3`：账号、个人偏好、方案及共享记录。
- `runtime/marketing.sqlite3`：活动、素材与审核账本。
- `runtime/aviation.sqlite3`：三份原始工作簿的全量索引。
- `runtime/models/`：原始冻结需求模型及行为数组。
- `runtime/synthetic-users/`：唯一保留的30,000人模拟人口，26,000训练、2,000验证、2,000测试。
- `runtime/demand-models/`：当前人口上的需求预测候选及独立评估；候选未通过稳定提升门槛，未替换冻结基线。
- `runtime/local_aigc/`：唯一网页Qwen3.5-4B推理权重、CUDA运行程序及配置。
- `runtime/maintenance/`：清理与取消审计；运行数据均不提交仓库。

原始三份Excel、需求模型与Qwen许可、版本、SHA256按[分发说明](../distribution/README.md)管理。原始工作簿与用户活动不能作为缓存删除。历史价格与模拟关注仅用于对应离线任务，不证明真实购票或营销收益。

## 验证

在仓库根目录运行 `python scripts/validate_framework.py` 与 `python scripts/validate_dataset.py`。在应用目录运行：

```powershell
python -m unittest test_core test_marketing test_local_generation test_distribution -v
python -m unittest test_population_selection test_demand_forecast test_accounts test_real_travelers -v
python select_simulated_population.py
node entry_browser_check.cjs
node account_browser_check.cjs
```

实际本地Qwen可用 `AEROLENS_TEST_LOCAL_AI=1` 后运行ai_browser_check.cjs；需要当前active_model.json配置。测试使用隔离目录，不计为真实参与者。源码CI不含原始工作簿，不能替代本机全量业务验收。当前评估、数据隔离及效果边界见[评估层](../docs/evaluation.md)和[人口划分](../docs/current-cohorts-2026-10-16.md)。


2026-10-17真实案例改进：兴趣默认未填写，历史默认主题不作为主动兴趣；个人方案增加自愿评价与单独共享选择。营销端可选择固定首批200账号，在效果复盘查看查询流程、实际评分人数与共享评价。缺失操作不补造，不将选择保存解释为购票。详见应用说明。专项验收：`python -m unittest test_real_improvements -v`与`node real_improvements_browser_check.cjs`，全部使用隔离数据。
