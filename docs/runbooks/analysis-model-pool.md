# 商品分析动态模型池

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](crow-data-root-compatibility.md).

此功能只服务于采集引擎中的商品资料清洗/AI 归档，不代表 Crow 的独立数据分析、预测引擎已完成。

## 工作方式

1. 从当前配置的 OpenAI-compatible 服务的 `/models` 发现模型；目录仅用于核对精确 ID，不授权业务或生成测试，不使用其他服务的密钥。
2. 业务与后台资格测试只准入 `OPENAI_MODEL` 和 `OPENAI_MODEL_CANDIDATES` 中显式配置的精确 ID。GPT 默认禁止；`CROW_ANALYSIS_ALLOW_GPT=1` 时也只允许 `gpt-6.1-sol`、`gpt-6-luna`，不自动改名或加入其他 GPT。其他厂商同样必须显式配置；图像、语音、embedding/reranker 过滤不变。未知别名背后的实际模型仍由上游路由配置负责。
3. 每个候选执行固定的 5 个资料提取用例，覆盖成交价、万元换算、建筑面积、未成交和缺失信息。用例及标准答案在 `src/llm_qualification_cases.py`，版本为 `collection-exact-v1`。
4. 每例回答与标准答案精确比较：相同得 1 分，否则得 0 分。仅忽略首尾空白；不忽略 JSON 内部空格、键顺序、Markdown 包装，不使用模型裁判或模糊评分。
5. 总分至少 4/5 才合格；资格未过期且未冷却的显式路由按配置顺序使用，分数或测试耗时不能扩大允许范围或改变优先级。
6. `OPENAI_MODEL` 是常规首选，`OPENAI_MODEL_CANDIDATES` 去重后是有序故障回退，不轮换。首选未合格、过期、冷却或请求失败时才尝试明确允许且合格的回退；没有回退则返回不可用，绝不恢复任意历史模型。单模型失败仍冷却 15 分钟，401/403/429 共享退避不变。
7. 没有合格路由时，分析预检返回不可用，后台只核对并测试当前显式准入的模型。预检不等待整批测试，也不因此领取商品。处理中遇到整个池不可用，沿用现有释放领取、恢复原始详情并回退本次尝试次数的路径。

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
- 扫描只取目录与显式准入列表的交集，按首选、回退顺序分批；目录中未知模型及被排除的历史路由不会触发生成测试。
- 进度按模型 ID 记录，不依赖易变目录的位置；到期的显式候选按配置顺序重新测试，备用可用也不能阻止首选续期；不合格路由至少间隔 15 分钟才重新测试。
- 续期仍完整执行五例测试，不沿用过期分数；尚未到期或处于单模型冷却的记录不提前重测，账号冷却、请求间隔、候选数和扫描预算不变。
- 显式候选扫描完成且资格未过期时复用结果；资格有效期为 24 小时，到期后仅续测仍在允许范围的模型。
- 进程异常退出的扫描租约最多等待 600 秒再接管。
- 这些是请求量与频率限制，不是货币预算保证；上游的实际计费、模型别名映射及 token 限额执行情况仍需在 AI 服务侧管理。

## 配置

| 配置 | 含义 |
| --- | --- |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | 沿用设置界面的 AI 地址与凭据 |
| `OPENAI_MODEL` | 常规业务首选的精确 ID，同时构成资格测试准入范围 |
| `OPENAI_MODEL_CANDIDATES` | 逗号或分号分隔的有序显式故障回退，包含首选时去重；未配置则无其他回退 |
| `CROW_ANALYSIS_ALLOW_GPT` | 默认 `0`；开启仅允许两个精确 GPT ID，仍需显式配置和资格验证 |
| `FAPAI_ANALYSIS_MODEL_POOL_ENABLED` | `1` 启用；PC2 analysis Compose 模板默认启用，普通本地调用默认关闭 |
| `FAPAI_ANALYSIS_MODEL_POOL_PATH` | PC2 为 `/data/datas/model-pool/pool.sqlite3`；未指定时使用项目 `CrowData/model-pool/pool.sqlite3` |

修改服务地址、密钥、推理参数或超时配置会自动使用新的资格命名空间，旧请求条件的结果不能为新配置背书。密码不写入资格文件；命名空间使用上述条件及用例版本的摘要。旧资格记录保留，不迁移或删除业务 PostgreSQL 数据。

修改允许模型不更换命名空间：共享冷却、请求间隔、租约和历史资格记录全部保留。在每次候选读取、生成请求入口和请求槽等待之后重新检查当前准入；旧 `route_cursor` 不再用于业务轮换，不能绕过优先顺序。不要清空 `pool.sqlite3` 来应用策略。

例如仅配置 `OPENAI_MODEL=gpt-6.1-sol` 且 candidates 为空或同名时，只能使用该模型；需要 Luna 回退时，明确设置 `OPENAI_MODEL_CANDIDATES=gpt-6-luna`。其他厂商回退亦需逐个明确配置，不从目录补全。

当前动态池与 Module B 的固定三模型共识流程分离。不得把显式回退直接塞入要求恰好三个独立模型的共识接口。本次线上采用单路清洗与明确回退，关闭了原有“只有一个候选却开启 shadow”的无效 Module B 配置。

当前设置界面仍显示配置中的首选模型；没有新增“模型池管理”页面。实际资格结果可从 PC2 私有状态文件和 worker 预检摘要查看。

## 排障

- 容器 `healthy` 仅证明进程/基础依赖状态，不等于 AI 上游可用。
- `/models` HTTP 200 仅证明目录可访问，不等于聊天接口可调用。
- 资格记录中的 `matches`、`score`、`errors`、`checked_at`、`elapsed` 可区分答案不匹配、HTTP 失败和超时，不保存商品正文、模型完整回答或密钥。
- `cooldown_until` 和 `next_scan` 用于区分服务退避与模型能力不合格。不要把共享账号被限流/封禁后的一批 HTTP 失败，解释成每个模型都无法完成提取任务。
- 成功回退记录 `analysis_model_fallback_selected`，使用既有 SHA-256 模型标识（可离线匹配精确 ID），并保留 `last_successful_model` 元数据；不记录凭据、商品提示词或完整回答。
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
