# 在另一台电脑继续工作

最新源码在仓库 main；数据与模型按 SHA256 校验，从 GitHub Release 按需还原。支持 Windows x64，推荐使用本次已验证的 Python 3.12。将项目放到 D 盘等非 C 盘位置，先配置该电脑自己的 HTTPS_PROXY 或 https_proxy；所有下载使用该代理。

## 安装和选择模型

下载或克隆仓库最新 main 后，双击根目录“准备并启动Demo.cmd”，选择：

| 选项 | 模型与运行方式 | 适用条件 |
| --- | --- | --- |
| 1 | Qwen3-4B，CPU | 默认方式，无需独立显卡 |
| 2 | Qwen3-4B，Vulkan | 兼容 Vulkan 的显卡；默认设备 Vulkan0 |
| 3 | Qwen3.5-9B，NVIDIA CUDA | 兼容 CUDA 13.4 的 NVIDIA 驱动和足够显存 |
| 4 | 网站及训练数据 | 暂不启用语言模型 |

脚本安装依赖，恢复三份原始 Excel、已训练需求模型，校验所选权重和推理程序并建立索引。4B 权重约2.5GB，9B约5.7GB；每次只准备所选模型，已经校验的文件复用。两个模型均可留在本机，重新运行安装入口可切换，原权重保留；切换时会先停止本项目原服务，然后使用新配置启动。CPU推理耗时与GPU不同。

4B包见[便携发布](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/portable-2026-10-16)，9B继续使用[原模型发布](https://github.com/huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC/releases/tag/demo-2026-10-12)。安装脚本自动处理分卷，无需手动合并。两种模型及其许可证和固定来源都保留。

也可在应用目录执行：

```powershell
./Prepare-Demo.ps1 -EnableLocalModel -Model 4b -Backend CPU
./Prepare-Demo.ps1 -EnableLocalModel -Model 4b -Backend Vulkan
./Prepare-Demo.ps1 -EnableLocalModel -Model 9b -Backend CUDA
```

## 航班服务与账号

在应用目录运行 Configure-Flight-Service.ps1，在本机遮罩窗口输入自己的 SerpApi API Key。密钥按当前 Windows 用户加密，旧电脑的加密配置不能直接在另一台电脑解密使用。默认地区、币种见[航班服务示例](../configs/flight-service.example.json)：日本地区、日元查询用于复现本项目验证条件；网页只显示人民币。可在本机 runtime/flight-provider/serpapi.json 调整地区、语言、币种和本机查询上限。

启动后访问 http://127.0.0.1:8765/ 。新电脑会独立生成管理账号文件 runtime/marketing-admin.txt，旅客自行注册。GitHub发布包不含真实用户账号、个人画像数据库、共享同意、私有问卷、API密钥或运行日志。要继续使用旧电脑已采集的真实案例，需要通过私有方式迁移数据库并遵守原共享同意；不要把这些资料提交到公开仓库。

## 已保留的数据范围

发布包包含原有三份模拟/历史工作簿及冻结训练产物，网站源码、实验脚本、验收记录和五层文档来自 main。2024航班仍只用于训练和离线评估，网页重新联网查询当前航班。distribution 中标明 local_only 或 release_published=false 的额外实验数据不属于既有发布资产；可以使用仓库脚本重新开展实验，但不能把旧的验收报价当成新的实时结果。

常用后续启动入口是应用目录“启动本地测试版.cmd”，自动读取上次选择的模型。无需每次重新安装，也不需要其他项目的目录。
