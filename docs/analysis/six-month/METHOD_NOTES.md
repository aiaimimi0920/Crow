# Crow 六个月房价预测：可追溯方法笔记（已对齐107篇目录；非全文精读）

日期：2026-11-18。状态：方法设计草案，不是完成107篇全文阅读的声明，不含训练结果。

## 阅读与证据边界
现已读取Library交付的report.md（874行）和catalog.csv（107篇论文+6份资料）。本轮完成的是目录和报告的方法提炼，并未新增论文全文阅读。下列S来源为此前独立核验背景，107篇主追溯以文末P编号映射为准。网页存在、摘要可读、正文部分核验、全文精读是不同等级；下表严格采用较保守描述。

|来源ID|原始来源|已完成的阅读深度|可以支持什么 / 不支持什么|
|---|---|---|---|
|S01|Local Housing Market Sentiments and Returns: Evidence from China, https://pmc.ncbi.nlm.nih.gov/articles/PMC9716533/ |此前读取正文数据及指数构造相关内容，非逐节全文精读；本笔记未重新逐页核对|房屋属性与小区固定效应的质量调整指数思路；不能证明Crow法拍提前六个月|
|S02|Forecasting House Prices: The Role of Market Interconnectedness, Journal of Forecasting, https://doi.org/10.1002/for.70121 |此前读取出版商索引正文/结果相关内容，非全文精读|城市面板、不同预测期及简单自回归竞争基准；不能推断当前Crow上某模型必胜|
|S03|Wei & Cao (2017), Forecasting house prices using dynamic model averaging approach: Evidence from China, https://doi.org/10.1016/j.econmod.2016.12.002 |出版商摘要核验；未验证全文模型细节及具体预测期|动态模型平均可作候选；不能复刻未读公式或承诺性能|
|S04|Xia Gao (2025), Bayesian Forecasting of China's Housing Prices: Dynamic Factor Identification and Predictive Evaluation, https://es.re.kr/eng/upload/25Q3_3.pdf |此前摘要及目标/结果概览；不声称全文精读|贝叶斯变量选择候选；全国新房同比指标不能直接替代小区二手房未来六个月收益|
|S05|国家统计局住宅价格指数介绍, https://www.stats.gov.cn/zs/tjws/zytjzbqs/zzxsjgzs/202501/t20250121_1958389.html |官方方法网页核验|新房/二手房数据口径区分；城市指数不是逐套市场价格|
|S06|第一财经2025城市分级, https://www.yicai.com/news/102638963.html |网页及完整原始榜单图像实际核验|冻结城市分层抽样的非官方商业口径；不是预测文献|
|S07|上海2025年11月货币信贷报告, https://jrj.sh.gov.cn/SCGK194/20251216/fc965f0df8ca422fb235c89757df7b3c.html |官方正文核验|证明观测期与公布日不同：11月数据12月16日发布；住户中长期贷款不是纯按揭|

## 可执行方法卡

### M01 标签定义与标签血缘
- 来源：S01、S04、S05；以下工程方案为据此提出的设计，不是原文结论。
- V1主目标（2026-11-18最新用户口径）：预测小区/地段在六个月后的典型普通实际成交单价（元/㎡），同时报告相对当前典型单价的变化。稳健聚合规则须训练内预登记并冻结；误差由时间及跨城验证判断。恒定质量住宅指数及其六个月对数涨跌保留为后续对照，不是V1强制门禁。
- 禁止混用：挂牌价、法拍评估价、竞拍起价、法拍竞得价、普通成交价、新房价格、未来同比。
- 逐套源必须有transaction_date、price_type、amount/unit、area及来源证据。公布价如是税务核价或网签合同价而非全部成交对价，单独标注。
- 验证：抽样人工核对来源记录；检查总价/面积与单价一致性；对六个月标签计算手工复算；同一目标版本在B/C实验完全一致。

### M02 可比匹配与质量调整
- 来源：S01正文方法相关阅读；设计扩展为Crow的匹配协议。
- 小区名称别名、行政区划历史变更、坐标系分别标准化，保留原字段及匹配置信度。
- V1同小区/地段可比优先，不要求同户型；不因户型或住宅细分类缺失自动剔除。明确非住宅排除，用途未知保留并标记，按城市/月份/空间层级报告未知占比。面积作为结构控制，楼龄、楼层、电梯等可得时辅助控制。户型用于敏感性分析而非门禁。邻近板块仅作标记回退，不把距离近视为市场相同。严格同用途/同户型质量调整属于后续对照研究。
- 用普通成交构造质量调整指数。训练折拟合属性模型；指数构造/修订策略须版本化，避免用后来样本改变当时已知价格。
- 验证：人工检查分层匹配对；报告匹配率、距离、属性差异、拒配率；比较未调整均值与调整指数，不以拟合更好作为唯一选择标准。

### M03 法拍折价不等于领先信号
- 来源：本轮尚无已核验的专门法拍文献；这是待与107篇补证的研究假设与识别检查，不能标记为文献共识。
- 特征候选：法拍成交价相对同一预测时点已知普通市场可比价的对数差。禁止用未来普通成交作为当时法拍折价分母。
- 税费、占用/腾退、租约、产权份额、拍卖轮次、处置时长、资产用途分别控制；同一资产多轮拍卖须串联去重。
- 成功成交样本存在选择偏差。缺流拍/撤拍/全部上拍分母时，不计算成交率，也不把成功样本代表全部受压供给。
- 验证：按产权/占用/轮次分组；含与不含问题资产消融；成功选择模型只有取得完整风险集且识别条件可辩护才使用，不能靠IPW自动修复未知遗漏。

### M04 特征可得性及推理合同
- 来源：S07发布滞后事实；以下为工程防泄漏设计。
- 每字段保存observed_period、published_at、first_seen_at、effective_at、retrieved_at、revision_id。回测采用forecast_origin时已公开且许可允许的数据。
- 特征组：普通价格动量/量、挂牌供需（显式挂牌）、法拍折价/成交量/竞拍活跃、政策和信贷。
- 历史初始发布时间不明的数据，标记availability_unverified；禁止用“今天下载得到”假定历史实时可用。
- 验证：对每预测行做as-of断言；删除预测日后的所有数据重跑，结果应不变；政策成文、发布、生效三日期分列。

### M05 直接六个月预测与模型阶梯
- 来源：S02预测期/基准研究、S03摘要候选、S04目标差异；具体方案是建议。
- A：不变价格/历史自回归。B：普通市场+宏观供需。C：与B相同学习器/窗口/调参预算，加法拍特征。
- 首轮使用正则化线性/AR基准；样本足够再加LightGBM。动态平均/贝叶斯模型为后续竞争者，不先宣布获胜。
- 以直接六个月为主任务；1/3/9/12个月作为预先登记的辅助任务，只能训练内选择。不要在最终测试上找最显著领先期。
- 验证：同折同目标比较C-B；方向准确率之外报告MAE及区间覆盖/宽度；将所有失败和无增益实验保留。

### M06 时间验证与重叠标签
- 来源：S02、S03存在样本外评估思路；以下严格实现细节为本项目设计，待107篇专门方法文献补证。
- 按真实预测发起日滚动。训练标签必须在该日已经成熟并可得。六个月标签重叠，不能随机拆行。
- 所有清洗阈值、缺失填补、标准化、特征选择和超参数在训练折中估计。
- 验证：训练label_available_at<=origin；预先冻结最终时段；对重叠误差使用时间块重采样或适当序列相关稳健推断，不能把城月当独立观测。

### M07 跨城完全留出
- 来源：S06仅支持城市分组；抽选及验证设计为本项目协议，不冒充榜单研究结论。
- 固定种子20261117的结果：训练北京/武汉/温州/宜昌，留出上海/佛山/金华/淮安。完整候选池和脚本见相邻housing_city_split目录。
- 留出城不得参与拟合、调参、特征筛选及预处理拟合。允许按已冻结规则读取留出城预测时点前的历史特征。
- 注意：用留出城历史成交拟合一个城市特有hedonic模型也属于拟合。若要严格完全留出，需使用独立官方/外部预定义标签，或冻结的训练城属性模型/预登记纯确定性指数规则；不得悄悄用测试城拟合标签模型再称“完全未拟合”。
- 验证：逐阶段审计城市集合；独立测试结果只在方案冻结后查看；缺少合法标签则报告不可评估，不因效果差换城。

### M08 稀疏市场与回退
- 来源：目前未核验专门稀疏处理论文；明确为工程候选，后续精读补证。
- 小区→板块→区→市的分层回退，输出实际使用层级与有效样本数。训练内设门槛，不用测试城误差调门槛。
- 可比较分层收缩/部分池化、合并时间窗口与拒绝预测；不把无成交填成零价或自动断言房价持平。
- 报告小区覆盖率、被回退比例、拒绝率、各样本密度下误差/区间。六个月窗口内交易成分变化要独立检查。
- 验证：训练数据人为降采样压力测试；仅训练城选回退规则；测试城一次应用。

## 107篇目录到位后的最小补齐表
paper_id | title | DOI/URL | access_level | actually_read_sections | target_and_horizon | geography_period | relevant_method_ids | exact_claim | limitations | Crow_adaptation | test_plan

不得把综述引述的论文算已读原始论文；不得把摘要性能结论算复现；不得把横截面估价准确率解释成六个月预测准确率。


## 已交付107篇的正式编号映射与阅读深度

本节阅读深度照录交付目录，不因本轮读取报告而升级。原报告统计：23篇题录、45篇摘要片段、32篇完整摘要、7篇关键方法章节；全文逐页深读并复现0篇。S01不在该107篇目录中，仅是额外背景。S02=P019、S03=P043、S04=P096；原目录P043/P096仅为摘要片段，独立线程较宽的既往阅读描述不能覆盖目录审计记录。

### M01：目录证据
- **P069** [Within-City Spatial Distribution, Heterogeneity and Diffusion of House Price: Evidence from a Spatiotemporal Index for Beijing](https://doi.org/10.1111/1540-6229.12293)。目录深度：完整摘要。目录核查记录：已取得并阅读一手完整摘要；官方题录摘要核验；online 2019；非6月预测证据。目标/粒度：Beijing resale complex data; 2011–2015。
- **P071** [Estimating Census Tract House Price Indexes: A New Spatial Dynamic Factor Approach](https://doi.org/10.1007/s11146-023-09957-w)。目录深度：关键方法章节（非全文深读）。目录核查记录：已阅读方法相关章节，非全文逐节深读；全文相关章节核验；online 2023；指数构建非预测。目标/粒度：Manhattan 218 tracts; quarterly; ~15000 pairs。
- **P077** [An approach for constructing spatially paired pseudo repeat-sales housing price indices in China](https://doi.org/10.1007/s10901-024-10161-2)。目录深度：关键方法章节（非全文深读）。目录核查记录：已核原文§3、§4.1–4.2、§5.1–5.3；数据来自安居客在线挂牌口径的小区均价，不能当作已核实成交价；缺失值采用平均插补。比较AC(1)、波动率和HP趋势偏离等指数质量指标，不是未来6个月样本外预测；online 2024/卷期2025。。目标/粒度：合肥1000小区；2017-01至2021-12；安居客小区月度在线价格，非已核实成交价。
- **P096** [Bayesian Forecasting of China’s Housing Prices: Dynamic Factor Identification and Predictive Evaluation](https://doi.org/10.22812/jetem.2025.36.3.003)。目录深度：摘要片段。目录核查记录：期刊摘要片段核验；全文 https://es.re.kr/eng/upload/25Q3_3.pdf；非小区。目标/粒度：China new-home HPI YoY。

### M02：目录证据
- **P074** [Housing price indices for small spatial units](https://doi.org/10.1016/j.regsciurbeco.2018.02.005)。目录深度：完整摘要。目录核查记录：已取得并阅读一手完整摘要；大学题录/官方摘要核验。目标/粒度：Illinois neighborhoods/small MSAs。
- **P077** [An approach for constructing spatially paired pseudo repeat-sales housing price indices in China](https://doi.org/10.1007/s10901-024-10161-2)。目录深度：关键方法章节（非全文深读）。目录核查记录：已核原文§3、§4.1–4.2、§5.1–5.3；数据来自安居客在线挂牌口径的小区均价，不能当作已核实成交价；缺失值采用平均插补。比较AC(1)、波动率和HP趋势偏离等指数质量指标，不是未来6个月样本外预测；online 2024/卷期2025。。目标/粒度：合肥1000小区；2017-01至2021-12；安居客小区月度在线价格，非已核实成交价。
- **P087** [Private residential price indices in Singapore: A matching approach](https://www.sciencedirect.com/science/article/abs/pii/S0166046211000743)。目录深度：仅题录。目录核查记录：题录已核；此前可能参考检索摘要片段/他文引用链，完整一手摘要未核，不计摘要筛选或深读。方法、样本与粒度为候选信息，待一手核验。。目标/粒度：Singapore transactions 1995–2010。

### M03：目录证据
目录题名/方法/类别未检出专门法拍折价或法拍成功选择研究。因此M03只能是明确登记的待验证假设与风险检查，不能称107篇已支持“法拍领先六个月”。目录未命中不等于全部全文都不涉及法拍。

### M04：目录证据
- **P004** [Using Data on Seller Behavior to Forecast Short-run House Price Changes](https://www.federalreserve.gov/pubs/feds/2014/201416/index.html)。目录深度：关键方法章节（非全文深读）。目录核查记录：正文关键方法已核。目标/粒度：美国3都市区。
- **P013** [Search and Predictability of Prices in the Housing Market](https://doi.org/10.1287/mnsc.2023.4672)。目录深度：摘要片段。目录核查记录：摘要筛选。目标/粒度：美国全国/地区。
- **P095** [Short-term house prices forecasting approach with multi-source heterogeneous information and data traits](https://doi.org/10.12011/SETP2024-0969)。目录深度：摘要片段。目录核查记录：期刊摘要片段核验；45(11):3795–3812；预测期/时间切分待读。目标/粒度：China 70-city average。
- **P098** [A Real Estate Price Index Forecasting Scheme Based on Online News Sentiment Analysis](https://doi.org/10.3390/systems13010042)。目录深度：完整摘要。目录核查记录：已读摘要；新房/二手房；目标含现时预测，不能称6个月已验证。目标/粒度：Beijing Shanghai Guangzhou Shenzhen city HPI。
- **P106** [House price responses to monetary policy surprises: evidence from US listings data](https://www.bis.org/publications/working-paper-1212-house-price-responses-monetary-policy-surprises-evidence-us-listings-data)。目录深度：完整摘要。目录核查记录：BIS官方摘要及作者核验；2001–2019 MLS，ZIP周度指数与局部投影；不是6个月预测验证。目标/粒度：US ZIP-code weekly。

### M05：目录证据
- **P019** [Forecasting House Prices: The Role of Market Interconnectedness](https://doi.org/10.1002/for.70121)。目录深度：关键方法章节（非全文深读）。目录核查记录：正文关键方法已核。目标/粒度：澳洲城区/中国城市。
- **P043** [Forecasting house prices using dynamic model averaging approach: Evidence from China](https://doi.org/10.1016/j.econmod.2016.12.002)。目录深度：摘要片段。目录核查记录：摘要片段核验；增长率；全文待核预测期/样本外。目标/粒度：30 major Chinese cities。
- **P061** [Sub-City Real Estate Price Index Forecasting at Weekly Horizons Using Satellite Radar and News Sentiment](https://arxiv.org/abs/2602.18572)。目录深度：关键方法章节（非全文深读）。目录核查记录：已阅读方法相关章节，非全文逐节深读；全文方法部分核验；预印本；5年训练/6个月验证滚动；2–34周；非中国小区。目标/粒度：Dubai 19 master-project areas; weekly。
- **P096** [Bayesian Forecasting of China’s Housing Prices: Dynamic Factor Identification and Predictive Evaluation](https://doi.org/10.22812/jetem.2025.36.3.003)。目录深度：摘要片段。目录核查记录：期刊摘要片段核验；全文 https://es.re.kr/eng/upload/25Q3_3.pdf；非小区。目标/粒度：China new-home HPI YoY。

### M06：目录证据
- **P003** [Predicting Changes in Canadian Housing Markets with Machine Learning](https://www.bankofcanada.ca/wp-content/uploads/2023/09/sdp2023-21.pdf)。目录深度：关键方法章节（非全文深读）。目录核查记录：正文关键方法已核。目标/粒度：加拿大全国。
- **P019** [Forecasting House Prices: The Role of Market Interconnectedness](https://doi.org/10.1002/for.70121)。目录深度：关键方法章节（非全文深读）。目录核查记录：正文关键方法已核。目标/粒度：澳洲城区/中国城市。
- **P061** [Sub-City Real Estate Price Index Forecasting at Weekly Horizons Using Satellite Radar and News Sentiment](https://arxiv.org/abs/2602.18572)。目录深度：关键方法章节（非全文深读）。目录核查记录：已阅读方法相关章节，非全文逐节深读；全文方法部分核验；预印本；5年训练/6个月验证滚动；2–34周；非中国小区。目标/粒度：Dubai 19 master-project areas; weekly。

### M07：目录证据
- **P019** [Forecasting House Prices: The Role of Market Interconnectedness](https://doi.org/10.1002/for.70121)。目录深度：关键方法章节（非全文深读）。目录核查记录：正文关键方法已核。目标/粒度：澳洲城区/中国城市。
- **P062** [Spatiotemporal patterns and prediction of multi-region house prices via functional mixed effects model](https://doi.org/10.3846/ijspm.2025.23639)。目录深度：完整摘要。目录核查记录：已取得并阅读一手完整摘要；官方摘要核验；预测期与时序样本外待核。目标/粒度：San Francisco communities; ZHVI 2009-01–2024-04。
- **P063** [A LSTM and Graph CNN Combined Network for Community House Price Forecasting](https://doi.org/10.1109/MDM.2019.00-15)。目录深度：仅题录。目录核查记录：仅DBLP题录核验；IEEE DOI入口不可访问，未获取一手摘要。不能声称数据来自中国小区、预测6个月或已经证明有效。。目标/粒度：community; geography待核。

### M08：目录证据
- **P071** [Estimating Census Tract House Price Indexes: A New Spatial Dynamic Factor Approach](https://doi.org/10.1007/s11146-023-09957-w)。目录深度：关键方法章节（非全文深读）。目录核查记录：已阅读方法相关章节，非全文逐节深读；全文相关章节核验；online 2023；指数构建非预测。目标/粒度：Manhattan 218 tracts; quarterly; ~15000 pairs。
- **P072** [Data-sparse price indexes by spatio-temporal regularization and PCA: An application to the Australian housing market](https://doi.org/10.1111/1540-6229.12516)。目录深度：完整摘要。目录核查记录：已取得并阅读一手完整摘要；大学官方题录摘要核验；非预测验证。目标/粒度：Australian local markets; monthly。
- **P076** [Clustering correlated, sparse data streams to estimate a localized housing price index](https://www.imstat.org/publications/aoas/aoas_11_2/aoas_11_2.pdf)。目录深度：完整摘要。目录核查记录：已取得并阅读一手完整摘要；官方期刊/作者预印本摘要核验；2015预印本不重复计数。目标/粒度：Seattle census tracts; monthly。
- **P079** [Repeat Sales Index for Thin Markets: A Structural Time Series Approach](https://doi.org/10.1007/s11146-009-9203-1)。目录深度：仅题录。目录核查记录：题录已核；此前可能参考检索摘要片段/他文引用链，完整一手摘要未核，不计摘要筛选或深读。方法、样本与粒度为候选信息，待一手核验。。目标/粒度：Netherlands national down to postcode subsets。
- **P084** [A Real Estate Price Index for Thin Markets](https://doi.org/10.1023/A:1007719513787)。目录深度：完整摘要。目录核查记录：Springer一手完整摘要与题录已核；时间序列法利用前期交易改善薄市场指数，非未来6个月预测验证。。目标/粒度：thin real estate markets。

## 证据适用边界与下一步精读
- M01/M02：P077的中国场景最接近，但原报告明确其安居客在线小区价格不是核实成交价；其均值插补是被描述的方法，不是Crow应照抄的建议。P074只有摘要，P087只有题录，不能写出未经核验的匹配公式。
- M03：缺专门法拍论文，这是本次证据缺口；不得将普通市场可预测性替代法拍领先性的证据。
- M04：P004的提前信息部分来自补偿成交指数公布延迟，需分别测试nowcast与真正t到t+6预测。P098包含现时预测，不得包装成半年验证。
- M05：P019明确含6个月，可优先精读复现；P061是迪拜区域预印本、裁剪均价，不能将相对MAE下降写成方向准确率。P043/P096摘要不能支持具体实现公式。
- M06：滚动时间验证的具体purge、as-of及重叠标签检验是本项目协议，不应假称上述文章全部实施了相同严格隔离；原报告已提示P061远期标签隔离/独立调参尚待核。
- M07：目录没有已确认的“上述8城完全留出”实验。P063只有题录，不能以community字样证明中国小区半年预测；跨城留出是用户确定的新研究设计。
- M08：P071/P072/P076/P084支持稀疏指数研究方向，但指数构建并不证明半年预测有效。分层回退、拒绝预测及门槛仍需训练内检验。

## 工程接入验收（不触碰采集）
1. analysis层只读取脱敏/合法数据视图；原始采集不作任何修改。
2. 先提交target_schema、asof_feature_contract、city_split引用、rolling_fold_manifest四份配置，再接模型。
3. 每个模型输出包含方法卡ID、文献ID、证据深度、代码/配置版本、训练数据截止、预测时点、目标期限、空间层级、有效样本数和区间。
4. 必须有三类自动测试：未来数据扰动不改变过去预测；留出城ID不进入任何fit；去掉法拍特征能恢复完全一致的B基线。
5. 验证尚未运行，本文不能作为Crow增益、可预测性或准确率报告。

## 抽样复现补充
固定Python random.Random(20261117)单实例，按一线、新一线、二线、三线原榜单逐行左到右抽sample(range(n),2)，第一训练第二留出；n=4/15/30/70，下标[1,0]/[3,14]/[6,10]/[38,27]。无性能筛选或重抽。原始名单：https://imgcdn.yicai.com/uppics/images/2025/05/64daefdf154d5b39e23c5a345cadd7df.jpg 。2026官方报告停止发布分级：https://www.yicai.com/news/103204902.html 。每档仅一个留出城不足以证明全国泛化。


## 2026-11-18 最新用户方向覆盖说明（V1优先）
本节覆盖此前较严格的住宅/同户型/恒定质量标签要求，但不改写文献原始对象、来源和阅读深度。
- 目标为小区/地段典型普通实际成交元/㎡；面积为结构控制，户型为敏感性分析，误差由验证决定。
- 用途未知或住宅细分缺失不自动排除；明确非住宅排除，未知比例随每批及预测结果报告。以已知住宅子样本作敏感性对照，但不据其测试表现改门禁。
- 依赖持续Crow和快速自行可得的合规公开输入，不以购买外部微观数据为V1启动前提。不把挂牌价作为普通成交真值。
- 外部真值与预测输入分离：外部普通成交可作为独立评估标签，不代表获准或已经在历史预测时点作为输入可得。预测输入必须满足历史as-of及推理持续可得条件。
- 若独立普通成交真值暂缺，可推进输入清洗和预测管道，但结果只能标为未验证；不能用法拍成交自证普通市场预测有效。
- 原M01/M02/M08关于质量调整指数、严格匹配的内容是后续候选与敏感性对照，不是V1阻塞条件；实际成交目标、明确非住宅排除和防泄漏要求仍保留。