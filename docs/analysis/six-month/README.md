# Crow 六个月分析引擎：可运行离线框架

2026-11-18，按用户最新口径：先跑通框架，使用现有 Crow 数据，不要求用户补采户型/细分用途。
**尚未用真实普通成交真值训练或核验准确率，不是上线预测产品。**

## 已实现

- 独立入口 `python -m src.analysis.six_month`，不接现网服务、不改采集代码/配置/流程，不重启 Crow。
- 真实旧中文/新嵌套 JSON 只读解析，按八城、小区、月份聚合法拍成交单价。
- 日期来自交易字段，不拿归档目录当交易日；按拍品ID去重，冲突拒收；这不是已完成资产去重。
- 聚合保留用途未知记录，明确非住宅类型排除。不要求户型。
- 总价/面积与已有单价不一致超过5%时隔离，不猜元/万元。5%是固定工程保护阈值，非验证出的最优阈值。
- 默认 crow_only：推理特征仅依赖法拍历史、已有面积等；普通成交只用作监督标签和事后评分。
- 可选 market_augmented：有稳定可得的普通市场历史时，在同标签同算法同折做 B无额外法拍 / C加法拍对照。
- Crow-only不能冒称做了无任何法拍输入的对照：其基准也依赖法拍，因此单独命名，不声称法拍增益已被证明。
- 无真实真值时可跑读取/聚合以及明确标记的合成端到端训练、预测、留出回测。
- Ridge岭回归已实测；LightGBM/CatBoost是可选懒加载接口，环境未装、未实测，不动全局依赖。

## 运行

从仓库根执行，已有环境 `venv/Scripts/python.exe`：

```powershell
venv/Scripts/python.exe -m src.analysis.six_month aggregate --archive datas/archive --output artifacts/analysis/crow-community-month-v1.json
venv/Scripts/python.exe -m src.analysis.six_month demo --output artifacts/analysis/synthetic-e2e-v1.json
venv/Scripts/python.exe -m pytest tests/analysis/test_six_month.py -q
venv/Scripts/python.exe -m ruff check src/analysis tests/analysis
```

输出仅限 `artifacts/analysis/`，拒绝覆盖已有证据。再次运行请选新文件名。
`aggregate`产物是实际Crow聚合，不是预测值；`demo`是全合成8城数据，不含真实准确率。

## 归档法拍价格证据口径（2026-11-22）

audit、aggregate、current-input 都带 `auction_result_evidence`，标明目前仅使用历史兼容的归档布尔代理，不认证竞得或其后实际履约。分析仍要求 `是否成交` 是布尔 `true`。但是淘宝采集适配器 `src/collection/adapters/taobao_judicial.py` 的 `preserve_seed_values` 可把 `done / 成交 / ended / finished / 结束` 都写为真；仅结束不证明有人竞得。它还可从列表 `auction_date` 和 `currentPrice` 填入交易时间和成交价格列；该时间不是付款或裁定时间，价格不自动等于买方最终实际支付额。

`is_processed` 只说明详情采集/分析产物处理完成。`actual_paid_price` 在采集合约中允许为成交价加税费、欠费的成本估计，并非付款凭证，不替代落槌金额。采集合约及本次读取样本中，未见能确认尾款支付、裁定送达或撤销的适用结构化时间证据。历史字段可得性继续独立核验：归档日、文件更新时间、交易/竞价结束时间不可当作信息首次可得日。

复核抽样：六个预先固定的日归档（2024 至 2026），只检查训练四城 36 行，均布尔为真、无原始状态值，未见上述后续事件时间。该小样本不是全量或随机样本，不说明异常频率。最高人民法院的[网络司法拍卖规定](https://www.court.gov.cn/zixun/xiangqing/24391.html) 第22、24、25、31条分别区分平台确认和裁定送达、悔拍、尾款交付及撤销。本段仅解释数据证据阶段，不判断具体拍卖的法律状态。适配器行为、入选门槛、默认特征和普通实际成交标签均不变。

## 预测与验证合同

目标是六个**日历月**后对应月份的小区典型普通实际成交元/平方米，非挂牌/评估/起拍价。
V1是中位单价，不是同户型或质量调整指数。户型可缺；面积在有值时作结构控制，缺失显式标记。
用途/完整产权未知保留；已确认非住宅或部分产权在规范训练输入中排除。
原始默认ownership_share_ratio=1并不认证完整产权。必要风险标记保留，不扩张为补采任务。

时间：预测日按当地日末。输入交易日与该版本最迟可得日期均不晚于预测日。
当前与前期窗口各3个月，法拍窗口6个月。每窗口3笔为固定工程门槛，不足则拒报小区，不填零、不暗中换城市。
训练标签必须整个目标月结束且标签全部可得。标准化仅训练折拟合，不随机拆行。
已有归档没有历史字段可得日期时，只做真实聚合，不谎称历史实时回测。

训练城北京/武汉/温州/宜昌；最终留出上海/佛山/金华/淮安。
切分 `yicai2025-seed20261117-v1`，第一财经2025商业分级，非政府分级。抽样过程见 METHOD_NOTES.md。
留出城不拟合、不调参、不筛特征，不能拟合该城专属hedonic标签后自称完全留出。
缺真值不换城；城市级官方指数只能另作城市对照，不替代小区真值。

## 接入规范输入（真值可后接）

`evaluate`读取独立分析JSON数组。示例（只展示格式，非真实数据）：

```json
[{"record_id":"source:deal-001","property_id":"verified:asset-001","kind":"auction",
  "city":"北京","district":"已核行政区","community":"已核小区ID","house_type":null,
  "traded_at":"2022-01-12","available_at":"2022-01-15","unit_price":10000,
  "area_sqm":90,"source":"合规来源及版本引用","sold":true,
  "residential":null,"full_ownership":null,"synthetic":true}]
```

kind=resale仅用于真实普通成交，不得塞入挂牌或法拍评估价。
规范property_id用于审核后资产去重；原始拍品聚合无需先完成这项即可运行。
available_at是该版本各字段最迟可得日，不能随意用交易日代替。
真实与合成禁止混合；同事件冲突版本拒绝，不按输入顺序吞掉。

```powershell
venv/Scripts/python.exe -m src.analysis.six_month evaluate --input artifacts/analysis/curated.json --origins 2022-07-31,2022-10-31,2023-07-31 --cutoffs 2023-07-31 --as-of 2024-02-01 --input-mode crow_only --output artifacts/analysis/run-v1.json
```

当前没有成熟训练真值时返回数据不足状态，不编造市场预测。
加入 `--input-mode market_augmented` 才使用可选普通市场历史并启用严格B/C消融。
最终 `--holdout --frozen-protocol protocol.json` 要求预先冻结：

```json
{"split_version":"yicai2025-seed20261117-v1","backend":"ridge","cutoffs":"2023-07-31",
 "origins":["2022-07-31","2022-10-31","2023-07-31"],"evaluation_asof":"2024-02-01",
 "input_mode":"crow_only","label_definition":"resale_cell_median_month_t_plus_6_v1"}
```

按去重、升序的 ISO 日期数组冻结实际预测起点 origins，并以 evaluation_asof 冻结标签可得性截止日。旧协议缺这两项不能直接运行。预检失败（包括没有匹配且在截止日已成熟的留出标签）不消耗最终测试。模型的两条预测路径均成功后，在计算或输出评分前独占保存唯一 receipt，拒绝重复最终测试。仅需预测时走下文 train / predict，不使用最终留出评分。
输出不能使用任一留出 receipt 的保留路径。回执记录实际 origins 和 evaluation_asof，与报告和冻结协议哈希对应。回执与报告不是同一事务；如果评分已开始但报告写入失败，也不删除 receipt 重新自称首次留出。底层backtest函数仅供分析与测试，不是防篡改权限服务。

## 尚未完成

真实普通成交标签接入/准确率验证；可靠区间、质量调整、部分池化、序列相关显著性检验、在线API。JSON ridge模型持久化已完成，见下节。
不能把合成测试成功表述为法拍能预测未来或全国泛化成功。
方法来源与阅读深度见 METHOD_NOTES.md / method_source_map.json；107篇并非全文精读，法拍领先半年缺专门证据。

## 第二片：独立训练、保存模型、后续法拍推理

新增 `train` / `predict`，真实普通成交只在训练文件作监督真值；预测文件必须只有auction。
安全JSON保存ridge系数/标准化/模式/城市/截止日，禁止可执行pickle加载。
没有成熟普通成交标签时train明确拒绝；不能拿合成模型套真实Crow数据产生伪真实预测。

```powershell
venv/Scripts/python.exe -m src.analysis.six_month train --input artifacts/analysis/standalone-synthetic-train-v1.json --origins 2022-07-31,2022-10-31 --cutoff 2023-07-31 --output artifacts/analysis/standalone-synthetic-model-v2.json
venv/Scripts/python.exe -m src.analysis.six_month predict --model artifacts/analysis/standalone-synthetic-model-v2.json --input artifacts/analysis/standalone-synthetic-auctions-v1.json --origin 2023-07-31 --output artifacts/analysis/standalone-synthetic-predictions-v2.json
```

上述文件名含synthetic，演示数据而非真实价格。已实跑分进程train→JSON→predict，输出2个合成城市的小区预测。
使用真实数据须先有真实训练模型，预测文件仍无需普通成交真值。
当前规范输入通过来源/资产/可得时点合同；旧归档只有拍品ID时，不臆测同址为同房，也不伪造历史可得时间。
原始Crow读取聚合可单独持续运行，不能将拍卖小区月聚合误称已核验市场预测。

## 当前真实归档输入预览与拒报

```powershell
venv/Scripts/python.exe -m src.analysis.six_month current-input --archive datas/archive --output artifacts/analysis/current-crow-input-v2.json
```

直接只读已有归档，按实际交易日构造当前Crow-only候选特征。只记录本次观察日期，不接受人为指定历史预测日；拍品ID只是未核资产的代理，不声称已完成物理房产去重。此接口输出特征预览而非训练文件或普通市场报价，没有真实校准模型就不给市场价格。
2026-11-18实际运行：可用最新成交2026-02-28，当前窗口不足，返回refused_no_recent_crow_history，候选0条。不会把八个月前价格冒充当前输入。需要分析侧只读接入新采集产物；不要求修改采集引擎。
原始输入中的inf/nan或派生零单价现已拒绝，避免非有限值污染聚合。


## 只读 worker-final 输入（2026-11-18）

`aggregate` 和 `current-input` 支持 `--layout worker-final`；默认仍为 `daily-archive`。
只读取完成的 final.json（is_processed 必须为 true），不读 selected/extracted 半成品；数字拍品目录必须与记录 ID 一致。拒绝越界符号链接与读取中改变的文件。逐文件稳定读取不是跨文件事务快照。

```powershell
venv/Scripts/python.exe -m src.analysis.six_month current-input --archive '<existing-readable-worker-root>' --layout worker-final --output artifacts/analysis/current-worker-preview-v1.json
```

路径由现有已授权共享提供，不自动新建共享、凭据、服务或同步任务。原始小区字段可能只是地段，输出标记 raw_community_or_locality_unverified；拍品 ID 不是已核房产 ID。首次观测以本次读取为准，不用目录日期或 mtime 冒充成交日/历史可得日。用途未知可保留但不是住宅认证，有限用途枚举也不保证覆盖地址文本中的商业提示。预览仍不生成普通市场价格。

PC2 已只读确认本地 output/nodes/pc2/detail_analysis_worker 及 _2/_3/_4 有 completed final；同一 reader 内存执行读取了两条北京成交日 2026-08-21、2026-08-22 的真实文件。该证明只是输入解码，不是足量近期窗口或真实预测。
Windows 既有 NAS UNC 可读且单例 CLI 已运行；样例不属八城，聚合/特征均为 0。PC2 当前 output 是本地 ext4，尚未证实向既有 NAS 自动同步，不能把 NAS 可访问等同新产物全量已接通。详见 VERIFICATION.md。
