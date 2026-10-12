# 航旅智策本地营销 Demo

基于全量 10,000 名模拟旅客训练的节假日航空营销网站，提供需求洞察、画像、航线、创意、模拟触达及效果复盘。完整使用流程见[仓库首页](../README.md)。

## 首次准备与日常运行

将仓库解压到 D 盘，安装 Python 3.11 或以上，双击根目录的“准备并启动Demo.cmd”。自动建立项目虚拟环境，下载并校验三份 Excel、训练模型及 Qwen 权重，重建 SQLite 索引，无需重新训练。

也可执行 ./Prepare-Demo.ps1；仅准备画像、航线和需求模型时加 -DataOnly。当前完整推理程序为 Windows x64 CUDA 版，需要兼容驱动及本地内存、显存。运行网站不需要 Node 或云端 API 密钥。

完成后双击“启动本地测试版.cmd”，访问 http://127.0.0.1:8765/ 。重复启动复用服务；关闭浏览器不会停止。双击“停止本地测试版.cmd”停止网站和本地模型，保留数据。其他网站端口用 ./Start-Local.ps1 -Port 8766。

## 活动与素材管理

“我的活动”中点击删除并确认，活动进入“已删除活动”，可以恢复。删除当前活动后退出该活动，刷新不会重新打开。

在创意工坊选中“目的地 · 内容主题”素材，点击“删除待审核素材”并确认，仅移除所选素材。已审核素材不能直接删除；编辑内容、改变名单版本后需重新审核。活动、名单和其他素材保留。

模拟触达只生成本机记录，检查退订、8—22时限制和同一旅客同一情景日跨活动最多一次的频控。不会向真实平台发消息，不虚构曝光、点击或订单。

## 数据、模型和文件

- runtime/aviation.sqlite3：三份原始 Excel 的全量索引。
- runtime/models/：行为缓存、训练权重、训练报告及指纹。
- runtime/marketing.sqlite3：活动、素材、审核和模拟发送账本。
- runtime/local_aigc/：Qwen、CUDA 程序、缓存、日志及进程记录。
- runtime/tmp、runtime/browser-temp：项目内临时目录。

原始 Excel 位于上一级数据集目录，字段与随机填补规则见[数据说明](../数据集/README.md)。模型和数据库使用北京时间历史截点，不把未来事件回填到特征。历史价格不能作为当前可购票承诺，模拟结果不代表真实业务增益。

语言模型为官方 Qwen3.5-9B 基础模型的 Unsloth GGUF 量化版本，未用旅客数据微调。固定来源、许可、大小及 SHA256 见[发布清单](../distribution/manifest.json)。SVG 画面为合成示意，不是扩散图像或景点实拍；没有实时攻略知识库 RAG。

## 训练、复现与验收

已训练产物由准备脚本直接还原。需重新训练时先核对来源版本，停止服务，再运行 python build_data.py --rebuild 及 python marketing_ml.py。不要因换电脑而重新训练。固定训练协议和指标见[实验记录](../experiments/results/local-demo-2026-10-12/README.md)。

完整后端测试：

    python -m unittest test_core test_marketing test_local_generation test_distribution -v

浏览器验收需 Node、Playwright 和 Chrome；运行 marketing_browser_check.cjs、campaign_delete_browser_check.cjs、creative_delete_browser_check.cjs。可用 AEROLENS_TEST_URL 指定独立验收服务，PLAYWRIGHT_MODULE 指定已有模块路径，CHROME_PATH 指定浏览器，PYTHON 指定清理测试活动所用解释器。

浏览器检查只清理报告明确记录且核对名称的测试活动；清理主流程测试时运行 python cleanup_marketing_test.py。测试过程会调用真实本地 Qwen，截图和结果存入当前应用的 runtime。请在独立验收副本中执行，避免频控及用户活动影响。

仓库 CI 不含原始 Excel，验证源码、五层文档、发布清单及发布包安全测试；不能代替全量业务测试。
