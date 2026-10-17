# 数据与模型分发

当前网页模型为Qwen3.5-4B-Q4_K_M，使用官方Qwen基础模型的Unsloth量化版本，未部署微调适配器。语言模型微调已取消。当前版本、来源、许可、大小与SHA256见[qwen4b-2026-10-17.json](qwen4b-2026-10-17.json)。本机只保留当前4B推理权重与CUDA运行程序；安装入口统一为4B，可选CPU、Vulkan或NVIDIA CUDA。

三份原始Excel、冻结需求模型、行为数组及训练报告仍按原始[manifest.json](manifest.json)与GitHub Release还原，保留全部校验。安装脚本下载校验后建立本机索引，不需要重新训练。数据包demo-data-models.zip约258MB。换电脑见[迁移说明](../docs/new-computer.md)。

当前30,000人模拟人口的汇总来源与SHA256见[selected-population-2026-10-17.json](selected-population-2026-10-17.json)，26,000训练、2,000验证、2,000测试。原始用户不重复导出一份，扩展片段与独立验证/测试放在本机runtime/synthetic-users。需求预测新候选产物位于runtime/demand-models，独立测试未通过稳定提升门槛，未替换冻结基线。这些新增人口和候选产物尚未发布新Release。

旧9B发布和[portable-manifest.json](portable-manifest.json)保留为已经发布的历史版本契约，不能当作当前活动模型。旧[current-cohorts-2026-10-16.json](current-cohorts-2026-10-16.json)已经退役；对应旧数据副本已清理，不代表当前人口与验收。

[LICENSE-Qwen3.5.txt](LICENSE-Qwen3.5.txt)及[MODEL-NOTICE.txt](MODEL-NOTICE.txt)保留Apache-2.0许可与原发布来源。大型文件通过GitHub Release分发，不提交main。原始三份Excel、需求模型和Qwen分发已经用户授权。

发布工具位于scripts/build_distribution.py与.github/workflows/publish-demo.yml。未执行或未成功的发布不能说成已经可下载。账号、真实共享画像、活动数据库、导出名单、原始聊天、密钥、运行日志与缓存均排除在发布包之外。
