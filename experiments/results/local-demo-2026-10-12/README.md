# 本地 Demo 训练与验收记录

本目录保存 2026-10-12 本地已执行实验的报告快照，不包含旅客明细或本地活动数据。

- `training_report.json`：全量 10,000 名模拟用户的训练协议、特征、模型及测试指标。
- `artifact_manifest.json`：训练环境、随机种子、来源指纹和产物 SHA256。对应权重与数组已随完整 Release 发布，由准备脚本还原至 `runtime/models/`。
- `verification.json`：彻底清理后的36项后端测试、28项浏览器检查及全量数据重建记录，均在独立副本实际执行。旧入口对应测试已随功能移除，当前营销测试保留。
- `portable-restore-results.json`：全新目录还原三份工作簿、训练产物、重建索引及 10,000 人预测的验证结果。
- `release-verification.json`：完整 Release 的 10 个资产、下载地址及校验值，含公开发布清单下载验证。

需求预测、机票查询和收藏均为模拟行为代理。没有真实客座率、订单增量、客户满意度或因果 ROI 结果。完整定义以训练报告为准。本目录只维护当前营销 Demo 的复现记录。

复现时将仓库放在 D 盘，安装 Python 3.11 或以上并运行根目录的 `准备并启动Demo.cmd`。脚本从[完整 Release](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12) 下载并校验原始工作簿、已训练需求模型和 Qwen 权重，无需重新训练。语言模型未经过旅客数据微调。
