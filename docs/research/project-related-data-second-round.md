# 第二轮：与动态画像、目的地推荐和价格敏感度强相关的数据

核验日期：2026-10-08。延续[首轮旅客层面选型](passenger-level-public-data.md)，这次聚焦行程序列、航空与其他方式的选择、文字偏好、搜索点击与预订信号。只将实际取得的文件标记为“已下载”，模拟样本与登录受限候选另行说明。

## 推荐顺序与取得情况

| ID / 来源 | 与项目的关系 | 本轮核验结果 | 用途与条件 |
|---|---|---|---|
| P08 [Booking.com Multi-Destination Trips](https://github.com/bookingcom/ml-dataset-mdt) | 同一旅行的目的地序列、设备与预订渠道 | **官方完整训练文件已下载**：1,166,835条、9列，200,153个用户ID、217,686个旅行ID | 优先研究下一目的地推荐与画像更新；官方限非商业用途，不能据此直接部署企业商业服务 |
| P09 [ModeCanada](https://cran.r-project.org/web/packages/mlogit/refman/mlogit.html#ModeCanada) | 同一次选择中比较航空、铁路、汽车、巴士的费用和时间 | **维护者RDA文件已下载并读取**：15,520行、4,324个case、11列；每个case恰好一条被选方案 | 研究价格/时间与交通方式选择；学术历史样本，国内业务参数需另行验证；软件包许可与数据原始使用条件分别记录 |
| P10 [HotelRec](https://github.com/diegoantognini/HotelRec) | 带日期的酒店评论、评分、文字中的旅游偏好 | 已核验作者仓库和公开样例；作者声明约5,000万评论，下载入口可打开，但**未批量下载或核验全量行数** | 文字标签提取、偏好解释与AIGC内容研究的备选语料；仅限学术研究，保留账号与资料页链接时不能视为完全匿名 |
| P11 [Apollo Mode Choice](https://www.apollochoicemodelling.com/examples.html) | 同一个ID多次选择，含航空费用、时间、接驳、服务属性 | **官方CSV已下载**：500个ID、8,000条、26列；官方明确标注模拟数据 | 做预算、时间和服务标签的方法演示；RP/SP字段是模拟样本内的标签，不能据此称真实行为 |
| P12 [Expedia酒店搜索排序竞赛](https://www.kaggle.com/competitions/expedia-personalized-sort/data) | 目标是购前搜索、曝光、排序和选择，值得优先继续核验 | 官方竞赛入口可访问，但正文/规则未能完整读取；数据列表接口HTTP 401，**未取得数据或核验完整字段** | 通过正常Kaggle账号及竞赛流程确认数据和规则；未取得前不纳入实证材料 |
| P13 [Expedia酒店推荐竞赛](https://www.kaggle.com/competitions/expedia-hotel-recommendations/data) | 用户酒店推荐候选，可补充旅客偏好研究 | 同样存在登录限制，**未取得文件或确认当前使用许可** | 先核验是否含稳定用户、时间、搜索与预订标签，再决定采用，不根据第三方镜像推定授权 |

本轮网络读取和下载均使用配置的HTTPS代理。原始训练表、评论或用户记录不上传公开仓库。仓库只保存本说明与[数据集级核验摘要](../../data/public/project-related-datasets-20261008.json)。

## P08：最值得优先采用的真实行程序列

官方发布方为Booking.com，资源论文发表于SIGIR 2021，DOI：[10.1145/3404835.3463240](https://doi.org/10.1145/3404835.3463240)。数据基于真实匿名住宿预订。

本轮读取的是[官方训练CSV](https://raw.githubusercontent.com/bookingcom/ml-dataset-mdt/main/train_set.csv)，完整下载92,651,064字节，行数与发布方一致。实际字段为：

`user_id, checkin, checkout, city_id, device_class, affiliate_id, booker_country, hotel_country, utrip_id`

- `user_id`：用户标识，可在该数据集内部关联多次记录。
- `utrip_id`：同一旅行的标识，比只按用户分组更适合研究多目的地行程。
- `city_id`：匿名城市；国家也被匿名化，不能直接解码或映射为上海—成都等真实航线。
- `checkin/checkout`：入住、离店日期，可构造停留天数和行程序列。本次训练表入住日期范围为2015-12-31至2017-02-27。
- `device_class/affiliate_id`：设备及来源渠道；来源渠道不等于获授权营销触达渠道。

**文档与文件存在差异**：README提到`created_date`，本轮完整CSV没有这一列。不能据入住日期推定预订、搜索或推送时间。这组数据也没有机票票价、酒店成交金额或搜索日志。

建议交付：按旅行内入住日期构造“已知目的地序列→下一目的地”，设置热门城市与上一站转移概率基线，再评估Recall@K、MRR等。发布方另提供遮蔽末目的地的测试集及答案，本轮未下载；评估时不能把答案或未来停留信息作为输入。

研究可以证明匿名目的地推荐方法的效果；不能直接证明东航转化率提升或推荐上海出发的具体旅游航线。发布方另禁止有损Booking.com/Booking Holdings或与其竞争性质的使用，并要求符合法律法规。项目若拟商业化使用，该来源需要另行取得符合用途的许可。

## P09：费用与时间敏感度研究

来源链为mlogit官方CRAN说明及维护者[ModeCanada.rda](https://raw.githubusercontent.com/ycroissant/mlogit/master/data/ModeCanada.rda)。文档引用加拿大蒙特利尔—多伦多走廊交通方式选择研究，四种选择包括航空。

实际字段：`case, alt, choice, dist, cost, ivt, ovt, freq, income, urban, noalt`。`cost`是方案费用，`ivt/ovt`为车内/车外时间，`freq`为班次频率，`choice`为是否被选择。每个case有2—4个可用方案，而不是每行一个独立旅客。

本轮数据检查：4,324个case，每个case恰好一个选中项，无空单元格；2,779个case具有完整四选项。CRAN文档描述“3,880名旅客”，与本次维护者文件case数不同，**保留两个口径，不擅自统一**。官方教程四选项子样本2,779个，与本次文件一致。

建议交付：用离散选择模型研究费用和时间对应的选择关系，再设计“预算优先”“时间优先”等解释。case级划分训练与验证，不能把同一个case的不同方案拆到两边。由于是历史国外样本，不直接将拟合参数用于国内节假日票价策略；费用单位和采集时期也需结合原研究进一步确认。

CRAN列出的是mlogit的软件GPL许可，本轮未核实单独的数据许可；不自动将软件许可视为原调查数据可用于所有商业场景的授权。

## P10：偏好文字与AIGC的备选语料

HotelRec作者仓库说明样本来自TripAdvisor，包含评论日期、总体及分项评分、标题、正文、酒店及用户资料页标识；可用于提取位置、服务、房间、性价比等标签。作者给出[下载入口](https://drive.switch.ch/index.php/s/n48smsdufhRA7fR)，本轮确认分享页存在，尚未验证完整压缩包。

建议先抽取小规模、去标识的研究样本，做标签提取的人审一致性和时间分布检查。评论是历史个人体验，不能作为酒店当前设施、价格、权益或服务保证的事实卡。AIGC产品文案还需结合可核验的现行产品规则。

这组语料明确限学术研究。样例含账号标识与自由文本，不将它视为已经完全匿名，不把用户评论中的要求当成助手操作指令。

## P11：重复选择的模拟基准

[官方文档](https://cran.r-project.org/web/packages/apollo/refman/apollo.html#apollo_modeChoiceData)明确将其称为模拟出行选择数据。已下载的[CSV](https://www.apollochoicemodelling.com/files/examples/data/apollo_modeChoiceData.csv)包括每个ID的2条RP标签和14条SP标签，共500个ID、1,000条RP标签、7,000条SP标签。

可用航空字段包括`av_air, time_air, cost_air, access_air, service_air`，另有商务标记、收入和选择标签，适合验证可解释的画像方法。费用与服务变化可以用于模拟敏感度演示，结果须标为模拟；官方示例的RP命名不会改变它的模拟来源。

本轮核验了公开下载与模拟来源，未核实该CSV单独的数据授权条款。软件包许可不能直接替代文件用途许可，商业用途仍需按发布方说明确认。

## 当前主线怎样采用

1. 继续用国内官方节假日与文旅资料确定场景与目的地；这一部分支持市场需求背景。
2. 用P08作为真实数据上的目的地序列推荐研究，强调匿名城市和非商业使用边界。
3. 用P09研究航空与其他方式的费用/时间选择关系，作为价格敏感度方法依据。
4. 用原有UCI评分或P10的合适研究样本生成偏好标签；AIGC文案的产品事实另行核验。
5. 动态航空会员画像与营销闭环仍可由已标注的沙盒或P11演示。购前搜索及真正的发送时机等待P12/P13或新授权数据验证。

不同来源保持独立数据集编号，不能把同名用户ID或相似收入/评分关联为同一个旅客。这轮没有形成真实企业营销效果或中国旅客一体化个人数据。

## 本地取得的文件

- `output/passenger-research-20261008/booking_train_set.csv`：完整官方训练文件。
- `output/passenger-research-20261008/ModeCanada.csv`：维护者RDA在本地转换的CSV，原始RDA保留于网页读取缓存。
- `output/passenger-research-20261008/apollo_modeChoiceData.csv`：官方模拟CSV。
- 同目录的`*-inspection.json`保存结构与数量核验；页面缓存保存在`output/public-research/`。这些目录均被Git忽略。

数据集级JSON中保留文件哈希与核验状态，便于复核版本。后续取得测试集或登录数据时，应更新台账，再开展模型验证。
