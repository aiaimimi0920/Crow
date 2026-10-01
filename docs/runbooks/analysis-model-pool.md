# 商品分析动态模型池

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](crow-data-root-compatibility.md).

此功能只服务于采集引擎中的商品资料清洗/AI 归档，不代表 Crow 的独立数据分析、预测引擎已完成。

## 工作方式

1. 从当前配置的 OpenAI-compatible 服务的 `/models` 发现模型；不使用其他服务的密钥。
2. 在发送测试请求之前排除名称含 GPT、Codex，以及 `o1`、`o3` 等 OpenAI 推理系列路由。明确的图像、语音、embedding/reranker 路由也按名称过滤。未知别名背后的实际模型仍由上游路由配置负责，不能仅凭目录证明其真实供应商。
3. 每个候选执行固定的 5 个资料提取用例，覆盖成交价、万元换算、建筑面积、未成交和缺失信息。用例及标准答案在 `src/llm_qualification_cases.py`，版本为 `collection-exact-v1`。
4. 每例回答与标准答案精确比较：相同得 1 分，否则得 0 分。仅忽略首尾空白；不忽略 JSON 内部空格、键顺序、Markdown 包装，不使用模型裁判或模糊评分。
5. 总分至少 4/5 才合格。按分数降序、测试耗时升序排序，最多保留前 5 个。没有合格模型时不强行补满。
6. 合格池内轮换使用；请求超时、HTTP 错误、空内容或响应结构错误会使路由进入 15 分钟冷却，并尝试其他合格路由。
7. 没有合格路由时，分析预检返回不可用，后台继续发现和测试。预检不等待整批测试，也不因此领取商品。处理中遇到整个池不可用，沿用现有释放领取、恢复原始详情并回退本次尝试次数的路径。

普通业务请求的单模型故障仍可切换其他合格模型；但 401/403/429 属于账号或服务级拒绝，会停止同池别名切换并共享退避。资格测试遇到第一个传输、HTTP 或响应格式错误即停止本批，不再把剩余案例和其他模型都请求一遍。已有未过期、未被停用的合格模型时，非 401/403/429 的探测失败只推迟共享扫描，业务继续使用合格路由；没有可用合格模型时仍进入全池退避。未完成测试的记录为 `score: null / status: probe_error`；429 或本机调度超时不覆盖模型已有分数。

资格测试是基础能力筛选，不保证实际商品资料永远分析正确。生产资料仍需通过已有提取、解析与落库检查。

## 并发和探测限制

- 四个分析 worker 共用一个私有 SQLite 文件，不新增业务 PostgreSQL 表。
- 资格扫描使用跨进程租约；每个进程也限制为一个后台刷新线程。
- 每批最多 8 个候选、40 个测试请求；正常批次结束后至少间隔 120 秒。失败时提前结束，而不是必须发满 40 次。
- 同池四个 worker 的资格测试和业务 chat 请求共用最短 4 秒启动间隔，约每分钟最多 15 次客户端请求。目录 GET、其他客户端及网关内部重试不在这个预算内，不能据此保证上游总请求数也只有 15 次。
- 测试请求沿用配置超时，上限 60 秒，最多 256 个输出 token；正确转发 `reasoning_effort`，不再忽略配置中的 `none`。目录查询仍最多 10 秒。
- 资格探测失败后，后台扫描通常至少等待 10 分钟；401/403 至少等待 1 小时并暂停业务，429 也保留全池退避。若上游提供更长的 `Retry-After`（秒或 HTTP 日期），保留更长的等待时间。目录请求同样遵守这些规则。扫描退避不会重置或取消所有 worker 共用的 4 秒请求间隔。
- 请求槽等待有时间上限；每例开始前也受本批 450 秒预算约束，避免排队无限等待或以耗尽租约为代价完成五例。
- 目录分批扫描，避免一个别名众多的模型家族独占首批；仍保留目录中的精确路由 ID。
- 进度按模型 ID 记录，不依赖易变目录的位置；到期候选先按显式配置顺序重新测试，再续期曾经合格的路由，避免它们被大量未测别名长期挤到队尾。其余候选仍优先测试未测路由；不合格路由至少间隔 15 分钟才重新测试。
- 续期仍完整执行五例测试，不沿用过期分数；尚未到期或处于单模型冷却的记录不提前重测，账号冷却、请求间隔、候选数和扫描预算不变。
- 全目录完成且仍有合格模型时复用结果；资格有效期为 24 小时。全部路由不可用/过期后重新探测。
- 进程异常退出的扫描租约最多等待 600 秒再接管。
- 这些是请求量与频率限制，不是货币预算保证；上游的实际计费、模型别名映射及 token 限额执行情况仍需在 AI 服务侧管理。

## 配置

| 配置 | 含义 |
| --- | --- |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | 沿用设置界面的 AI 地址与凭据 |
| `OPENAI_MODEL` / `OPENAI_MODEL_CANDIDATES` | 发现时优先尝试的显式非 GPT 路由；启用动态池后不再是唯一可用路由 |
| `FAPAI_ANALYSIS_MODEL_POOL_ENABLED` | `1` 启用；PC2 analysis Compose 模板默认启用，普通本地调用默认关闭 |
| `FAPAI_ANALYSIS_MODEL_POOL_PATH` | PC2 为 `/data/datas/model-pool/pool.sqlite3`；未指定时使用项目 `CrowData/model-pool/pool.sqlite3` |

修改服务地址、密钥、推理参数或超时配置会自动使用新的资格命名空间，旧请求条件的结果不能为新配置背书。密码不写入资格文件；命名空间使用上述条件及用例版本的摘要。旧资格记录保留，不迁移或删除业务 PostgreSQL 数据。

当前动态池与 Module B 的固定三模型共识流程分离。不得把最多五个合格路由直接塞入要求恰好三个独立模型的共识接口。本次线上采用单路清洗与池内切换，关闭了原有“只有一个候选却开启 shadow”的无效 Module B 配置。

当前设置界面仍显示配置中的首选模型；没有新增“模型池管理”页面。实际资格结果可从 PC2 私有状态文件和 worker 预检摘要查看。

## 排障

- 容器 `healthy` 仅证明进程/基础依赖状态，不等于 AI 上游可用。
- `/models` HTTP 200 仅证明目录可访问，不等于聊天接口可调用。
- 资格记录中的 `matches`、`score`、`errors`、`checked_at`、`elapsed` 可区分答案不匹配、HTTP 失败和超时，不保存商品正文、模型完整回答或密钥。
- `cooldown_until` 和 `next_scan` 用于区分服务退避与模型能力不合格。不要把共享账号被限流/封禁后的一批 HTTP 失败，解释成每个模型都无法完成提取任务。
- 如果所有候选失败，应在设置中换成有可用非 GPT 额度的服务地址/凭据，或修复当前上游。不能为恢复增长而绕过 GPT 排除策略或资格门禁。

## 链接采集的人工挑战

PC2 收到终止性的 `manual_required` 时，现将原因从执行子进程传回控制循环，停止页面轮换并上报现有 NAS 人工认证接口。上报暂时失败会保留待上报状态，稍后重试，不重新开始自动处理。

在 PC1 使用“认证 → 打开挑战页面”，手动完成后点击“已完成挑战”。只有既有认证同步与服务端确认成功后才能恢复对应采集范围；不要仅清除暂停标志或删除浏览器资料来伪造恢复。

## 验证

```powershell
python -m pytest tools/test/test_llm_qualification_pool.py tools/test/test_llm_qualification_request_limits.py tools/test/test_pc2_terminal_manual_handoff.py tools/test/test_pc2_release_secret_mounts.py tools/test/test_llm_helper_openai_compatible.py tools/test/test_pc2_local_solver.py tools/test/test_detail_worker.py -q
node --test scripts/tests/effective-code-lines.test.mjs
node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json
```
