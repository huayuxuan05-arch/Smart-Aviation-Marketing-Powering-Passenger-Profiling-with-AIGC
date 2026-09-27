# 本地API

这是可选原型的接口参考，当前主线为公开信息研究和整体方案。在`prototypes/offline-demo/`目录启动 `python -m app.server`，基址 `http://127.0.0.1:8000`。无需依赖、API Key 或身份登录，仅用于可信本地演示；端口可配置。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | /api/health | 离线模式健康检查 |
| GET | /api/overview | 合成旅客数量、可触达、高意向、群体与目的地分布 |
| GET | /api/profiles | 画像、推荐候选、触达决策 |
| GET | /api/campaigns | 所有活动，最新在前 |
| GET | /api/metrics | 当前可触达合成旅客的随机分组统计演示 |
| GET | /api/audit | 最近100条活动操作审计 |
| POST | /api/campaigns | `{ "passenger_id": "SYN-0002" }` 创建模板文案与SVG草稿 |
| POST | /api/campaigns/{id}/approve | `{}` 从draft变为approved |
| POST | /api/campaigns/{id}/simulate | `{}` 从approved变为simulated；先复核授权与频控 |

POST必须为JSON对象，Content-Type为application/json，请求体最大16KiB。400表示JSON、输入或业务状态错误，403跨站Origin被拒绝，404未知路径，413体积错误，415类型错误。浏览器Origin只允许实际端口的127.0.0.1同源；建议用README中的地址访问。

## 示例（PowerShell）

```powershell
$demoCampaign = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/campaigns' -Method Post -ContentType 'application/json' -Body '{"passenger_id":"SYN-0002"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/campaigns/$($demoCampaign.id)/approve" -Method Post -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/campaigns/$($demoCampaign.id)/simulate" -Method Post -ContentType 'application/json' -Body '{}'
```

建议每次录制使用新的数据库。SYN-0002的初始频控余额只有1次；重复创建/模拟会按累计记录被拦截。跨活动并发执行也无法绕过频控。

## 语义边界

审核接口记录状态，不认证审核人的企业权限。模拟接口没有调用渠道，也不会等待建议发送时段；它只是演示状态转换。metrics使用人为设定概率（对照0.12，实验0.18），不统计真实曝光或订单，不是单次活动效果归因。单次模拟把该时点的实验演示结果保存到活动result中，便于查看操作时的快照。
