# 完整Demo发布文件

用户已授权将原始三份Excel及模型权重上传本仓库。原始Excel与需求模型先按1—4MiB分卷上传到本仓库的临时Git Blob，再由GitHub Actions按清单组装、校验并发布Release；大文件不进入main的提交树。原始工作簿没有修改，安装时按清单恢复到 `数据集/`。

完整包见[GitHub Release](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12)。包括：

- `demo-data-models.zip`：三份原始Excel、已训练需求模型、行为数组缓存、训练报告和来源校验清单，约258MB。
- `Qwen3.5-9B-Q4_K_M.gguf.part-*`：Qwen量化权重分卷，完整文件5,680,522,464字节，安装脚本自动合并校验。
- `release-manifest.json`：所有发布文件的大小、SHA256及固定来源版本。
- `LICENSE-Qwen3.5.txt` 和 `MODEL-NOTICE.txt`：Apache-2.0许可及Qwen/Unsloth来源说明。

Qwen权重由发布任务从固定Unsloth源版本取回并校验后上传GitHub Release，最终还原文件与本机现用权重的SHA256一致。用户活动数据库、名单导出、服务日志与进程信息不进入发布包。

换电脑使用：下载仓库源码到D盘，安装Python3.11或以上，双击仓库根目录的 `准备并启动Demo.cmd`。脚本在项目内建立虚拟环境，安装依赖，下载校验数据及权重，重建SQLite索引并打开网站。需求模型直接加载已训练产物，无需重新训练。

发布流程位于 `.github/workflows/publish-demo.yml`，只用GitHub Actions自带的仓库令牌上传当前仓库Release，不要求用户提供密钥。发布成功前，请勿将Release描述为已可下载。GitHub负责文件分发，Python服务与模型仍在本地运行。

首次发布的源分卷为临时组装材料；后续重新执行发布任务优先复用已经发布并校验的Release数据包，避免依赖临时对象的长期保存。


当前全年模拟数据、成功报价与逐人方案的版本、许可边界及SHA256见[current-cohorts-2026-10-16.json](current-cohorts-2026-10-16.json)，说明见[当前数据验收](../docs/current-cohorts-2026-10-16.md)。训练10,000人、验证2,000人、测试10,000人，共8,030,000条年度模拟行为。报价按36个查询条件复用，不作为22,000份独立航班证据。

本批大型数据仅保存在D盘runtime，尚未发布新Release。旧年度数据索引已标记退役；原始七项发布契约、Qwen许可、原始Excel及冻结模型不变。
