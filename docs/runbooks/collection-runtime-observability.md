# 采集运行状态与统计观测

## 状态读取不等待全量统计

`/api/status` 的 lightweight 路径与 `/api/collection/overview` 共用一个 API 统计缓存，TTL 为 15 秒。统计到期或冷启动时由单个后台线程刷新；请求线程不等待数据库分组统计及 occurrence 全量计数。进程内最多一个刷新任务，其他请求复用快照，不排队创建新任务。

统计与控制状态分离：暂停、人工认证、collection scopes 等仍按每次状态请求实时读取。任务领取、租约、授权和暂停检查不使用统计缓存。worker 的展示/进度统计仍默认同步采样并复用 15 秒 TTL，不改变业务仓储读取接口。同步和后台统计都从刷新结束开始计算下一次尝试的 15 秒间隔，避免慢查询或慢失败刚结束就再次全量查询；失败仍保留原快照的生成时间和年龄，不把冷却间隔当作数据新鲜度。定向回归：`test_collection_statistics_slow_refresh.py`。

`statistics` 元数据：

- `valid=false`：尚无成功统计，数量未知。兼容数值字段中的零不能解释为真实零；桌面应沿用“统计不可用”和 `—` 的展示。
- `valid=true, stale=true`：保留的历史快照已过期或刷新失败，不能作为实时控制或重启依据。
- `refreshing=true`：当前 owner 的后台刷新正在执行，不代表业务采集或分析被暂停。
- `age_seconds`、`generated_at`：最后成功快照的年龄和生成时间；刷新开始或失败不会重置它们。
- `error_type`：仅异常类型，不记录数据库连接信息或异常正文。失败后至少等一个 TTL 再尝试。
- `minute_delta` / `window_seconds`：仅在快照有效且不陈旧时提供完整采样差值，否则为未知。

repository owner 更换或单调时钟回退会使原快照失效；旧后台任务晚到的结果不会写进新 owner。已有刷新结束之前不为新 owner 另外启动任务，避免异常切换导致线程扩散。冷启动一次统计不可用不等于数据库宕机，也不能据此放行任务或触发浏览器重启。

## 验证范围

优先执行 `tools/test/test_collection_statistics_background.py`、`test_collection_statistics.py`、`test_detail_worker_statistics.py`，并验证状态 API、桌面 unknown/stale 展示和 progress watchdog 的既有契约。可串行读取少量实际状态样本核对响应与元数据，不进行压测，不触发额外模型生成请求。

## 批次工作量与等待口径

`detail_worker_batch` 与批次 summary 保留原 `attempts`：它是调度尝试数，包含暂停和空队列，不能作为页面请求数或验证码尝试数。新增独立观测字段：

- `claimed_items`：成功领取到非空任务的次数。
- `process_item_calls` / `analysis_item_calls`：实际进入处理器或分析器的次数。目标配置或原始文件准备失败不计函数调用；函数内部失败仍计一次调用。
- `paused_results`：本批返回暂停结果的次数。
- `decision_counts` / `reason_counts`：允许列表内的结果与原因聚合。无 reason 不计原因；未知值统一归 `other`，不记录异常正文、URL、提示词或回答。
- `page_requests=null, page_requests_observed=false`：worker 层无法覆盖缓存、重定向和 browser fallback 的完整请求链，明确表示未知，不是零次请求。
- `item_observation_missing`：旧格式或不完整结果的计数，不能由 item_id 或成功 decision 反推领取和调用次数。当前生产路径应为零。
- `batch_elapsed_seconds`：从批次入口（包括 preflight）到 summary 组装完成的耗时，包含批内 pacing 和统计读取，不包含批次后等待。

`detail_worker_sleep.sleep_seconds` 仍是原有请求等待时长；有效的服务端退避下限可以将其延长。新增 `detail_worker_wait_finished` 记录 `requested_wait_seconds`、`actual_wait_seconds`、`status_poll_count` 与 `wait_exit`。实际等待从等待器入口至返回计时，包含状态 HTTP 轮询耗时，不是纯 sleep 时长。

`wait_exit` 使用 `detail_resumed`、`report_backoff_elapsed`、`deadline_elapsed`、`stopping`、`wait_returned`。普通 lifecycle wait 不提供终止原因，因此用 `wait_returned`，不猜测是自然到期还是取消。runtime context 刷新失败的普通等待同样记录完成事件，但不增加认证探测。

当 detail 报告被 `recent_auth_complete` 或 `recent_force_reset` 抑制，并带有有效的正数 `retry_after_seconds` 时，等待完成事件额外记录 `report_backoff_seconds`（向上取整，多条报告取最大值）。这是服务端要求的最短退避；即使 detail scope 从一开始就是 clear，也不能每隔 30 秒提前退出。下限内保留 lifecycle checkpoint 和取消响应，不进行无意义的状态轮询；到达下限后仍按原有轮询间隔检查 operator pause、aggregate 和 detail scope。

下限已满足且 detail 明确可继续时，`wait_exit=report_backoff_elapsed`，不表示发生了新的认证恢复。无该下限的正常恢复仍使用 `detail_resumed`，未知状态、读取失败、人工暂停或未解除的 challenge 仍等待到原期限。此修复不修改 solver、站点请求预算、冷却、重试预算或 seed/detail 隔离；不记录业务正文或凭据。

对应定向回归为 `test_detail_worker_observation.py`、`test_detail_worker_auth_wakeup.py`、`test_detail_worker_report_backoff.py`、`test_detail_worker_operator_pause.py`，再扩展到 worker 生命周期、失败、归档完整性和历史保留边界。不要将以上计数拼成验证码通过率。

恢复等待的分段 sleep 不跨过有效的报告退避下限，例如 142 秒下限在第 142 秒检查，而不是睡到第 150 秒；不增加下限内的状态查询。状态 HTTP 查询和 CDP 元数据读取共用本次等待的单调时钟截止时间，只使用剩余预算，截止时不再发起末次查询。状态查询期间收到停止信号后返回 `stopping`，不将迟到状态或元数据记为恢复；自然到期仍由下一轮原有领取前门禁重新检查，不代表主动解除暂停。回归：`test_detail_worker_wait_deadline.py`。

### 暂停原因不等于正在求解

seed/detail worker 读取 scoped status 时，`paused=true` 只表示该阶段不可继续，不证明 solver 正在执行。仅当该 scope 的 `last_status=running` 时使用 `captcha_solver_running`；暂停但没有运行证据时使用既有 `collection_paused`。`manual_required=true` 仍优先使用 `captcha_solver_manual_required`，不能仅凭这些原因标签区分冷却、人工接管或其他等待，也不能据此清除状态或重试。

另一 scope 的 aggregate `running=true` 不得被误用于当前 scope。此次修复只纠正原因标签，不改变暂停布尔值、领取门禁、恢复轮询、退避或跨节点规则。对应离线回归为 `tools/test/test_collection_pause_reason.py`。

## Worker HTTP 会话生命周期

detail worker 的 CLI 和默认上下文构建路径拥有自己创建的 HTTP 会话。批次刷新完整成功后才关闭被替换的旧会话；刷新失败时，原会话继续用于既有回退路径。循环停止、单批完成或异常退出时关闭最后一个自有会话；同一会话被重复返回时不在批间提前关闭。

显式传入的 `http_session` 或 `runtime_context_factory` 保持借用语义，由调用者负责资源生命周期。分析专用 CLI 不创建采集 HTTP 会话。关闭失败只记录安全错误分类，不覆盖批次的原始结果或异常；不改变请求次数、刷新频率、退避、租约和暂停判断。

对应回归为 `tools/test/test_detail_worker_sessions.py`，同时覆盖兼容 facade 与实现模块。资源释放正确不等于已经证明吞吐或认证成功率提升，实际收益仍需自然运行样本验证。

## Detail 领取后的来源读取上限

领取事务提交后，detail 仅用最早的一条 occurrence 补齐来源默认字段；查询按 `seen_at ASC, id ASC` 排序并在 SQL 中使用 `LIMIT 1`。SQLAlchemy 结果的 `.first()` 本身不限制数据库返回行数，不能用它代替 SQL 上限。没有来源记录时保持原样，显式 seed 字段仍优先，历史 occurrence 不删除、不迁移；任务优先级、租约、失败计数、冷却和站点 pacing 不变。

回归：`tools/test/test_detail_claim_occurrence_budget.py`，用隔离 SQLite 核对实际 ORM 加载数量、历史保留、稳定排序及字段覆盖，并核对相同查询的 PostgreSQL SQL 编译结果。该上限减少重复来源多时的传输和对象加载，不消除数据库排序成本，也不代表已经证明线上批次提速或验证码通过率提高。

## Capture 失败诊断不丢失

detail worker 的失败结果可额外包含 `capture_failure`，不改变既有 `reason`、CDP health、任务状态、重试预算、租约或退避。

- `operation` 仅允许固定的 CDP 操作名、`detail_browser_capture_deadline`、`capture_helper` 或 `other`，未知内容不直接输出。
- `deadline_exceeded=true` 仅表示整个 capture helper 超过既有 180 秒截止时间，包含驱动启动、页面操作与清理；不能据此认定 TCP 端点不可达，也不能确定具体卡在哪一步。
- `cause.type` / `cause.message` 保留子进程异常的固定安全分类。Python 和 Playwright 的超时均归 `TimeoutError: timeout`，不复制原始异常正文、参数、业务 URL、提示词、回答或任意诊断后缀。
- 非超时的 Playwright 异常归为 `BrowserError: browser_error`，不根据异常文案猜测网络、页面关闭或站点拒绝原因。普通 helper 失败的原始异常栈经过已知采集模块时，`cause.frames` 最多保留 8 个固定仓库文件标签和整数行号；不输出绝对路径、函数名、源码、局部变量或异常链。跨进程读取时再次按同一白名单校验，已有 CDP/预算诊断不额外采栈。旧回复没有此字段时保持未知，不能反推失败阶段。
- 普通 helper 的 Playwright 导航失败可额外提供 `cause.browser_code`：仅从异常首行固定的 `Page.goto: net::` 前缀提取预定义 Chromium 错误码，接收端再次校验；不扫描 URL、调用日志或异常链，不输出原文。未知代码不提供此字段，其他错误类别、既有 CDP/预算诊断不变。错误码只说明浏览器报告的导航结果，不自动证明根因，更不能把 `ERR_ABORTED` 当作成功或授权重试。
- 旧格式子进程回复没有诊断时仍可读取，原因记为 `Exception: unexpected_error`，不猜测类型。非 capture 异常不添加此字段。

超时时若收到有效阶段标记，还会提供 `stage` 与 `stage_elapsed_seconds`，分别表示最后观测到的阶段及截至总截止时间在该阶段停留的秒数。阶段覆盖 helper 导入、驱动启动、CDP 连接、既有页面读取、新页创建、会话创建/配置、导航、详情就绪、会话分离、页面关闭、浏览器分离、驱动退出和回复写入。它是阻塞位置线索，不是对站点拒绝原因的判断。

阶段默认不启用，仅在私有 capture 子进程中通过固定枚举写入 stderr。父进程仅检查末尾 16 KiB，接受本次进程时间范围内的完整 LF/CRLF 标记；旧 helper、未知标记、不完整输出或日志噪声过多时可不提供阶段。Windows 超时异常不携带 stderr，因此在既有有界清理完成后读取缓冲区，但阶段计时仍截止于超时发生时。原始 stderr 不进入 worker summary。

`stage=cdp_connect` 覆盖连接前检查、端点解析和 Playwright 附着，不等于 TCP 连接失败。HTTP 元数据或浏览器级 CDP 命令成功，也不能证明 Playwright 附着已经成功：后者还会等待既有页面初始化。应分别核对传输通道和页面初始化；不要仅因浏览器健康就否定抓取超时，也不要仅因该阶段超时就关闭已有认证页、重复重启浏览器或缩短冷却。

私有 capture 的共享预算也约束连接后的新工作：读取既有页面和创建自有页面前检查剩余时间，导航的 90 秒上限取剩余预算与原上限的较小值，配置后和详情读取前后继续检查。预算耗尽不再开启新页或导航，也不接受超出预算才返回的成功结果；未设置私有 deadline 的调用保留原导航上限。清理不受该工作预算门禁阻止，仍尝试关闭自有页面、分离会话和 driver；第三方不支持协作超时的操作仍由既有 180 秒 hard deadline 兜底，并非保证所有页面创建或读取都能及时取消。

既有页面的认证分类不再调用没有 timeout 参数的 `page.content()`，而使用公开的 `locator("html").inner_html(timeout=...)` 读取文档子节点（含 title、script、表单和 body）。单页最多等待 5 秒，且不超过剩余工作预算；没有私有 deadline 时同样保留单页 5 秒上限。读取失败仍按既有规则进行 URL 分类，未耗尽预算时可继续新详情请求；整个预算耗尽则返回超时，不创建新页。不会聚焦、导航、关闭既有页面，也不会把 DOM 读取超时当成挑战已通过。此路径仍保留登录门禁、同目标旧挑战去重与跨 scope 隔离。

自有页面关闭失败时，如果已有主要失败或取消，保留原始失败，只记录清理异常的类型，不记录正文；如果原操作没有失败，则不能静默接受清理失败。此规则不授权关闭任何其他页面，不解决归属未知的旧空页，也不改变人工认证页保留规则。对应回归为 `tools/test/test_capture_operation_budget.py`。

对应回归为 `test_capture_progress.py`、`test_detail_capture_diagnostics.py`、`test_capture_error_frames.py`、`test_capture_browser_codes.py` 与既有 protocol、deadline、worker exception reporting 测试。该字段仅补充诊断，不新增探测请求、不调整超时或重试，不等于已经修复抓取超时或提高 solver 通过率。

## 浏览器代理故障保护

私有 detail capture 明确报告 `ERR_TUNNEL_CONNECTION_FAILED` 或 `ERR_PROXY_CONNECTION_FAILED` 时，worker 使用 `reason=detail_browser_proxy_unavailable`，恢复任务为 pending 并撤销本次领取产生的商品重试计数。其他导航错误（包括 `ERR_ABORTED`、普通连接重置、未知错误和旧格式回复）仍保持原商品失败策略，不因此获得无限重试。

代理故障结束当前批次，复用既有 `challenge_cooldown_seconds` 与 loop interval 的较大值等待；不改配置、不增加探测请求或重试预算上限。等待仍由可取消的 worker lifecycle 执行，不轮询认证状态，也不因认证 scope 为 clear 而提前退出。沿用现有 batch 字段 `challenge_break` 表示该提前结束路径，与已有 CDP 故障相同，不代表识别到验证码。

此错误不提交 captcha report、不触发 solver，不生成 CDP 不可达健康报告，更不会自动切换代理或直连。上游代理恢复后，任务仍可按原流程重新领取。历史已消耗的次数不自动回写，实际站点访问成功与持续吞吐改善仍需独立验证。回归：`test_detail_browser_proxy_failure.py`，并检查 worker 批次、共享任务状态与认证等待边界。

### 导航连接关闭时停止批内连续消耗

私有 capture 明确报告导航错误 `ERR_CONNECTION_CLOSED` 时，使用 `reason=detail_navigation_connection_closed` 并结束当前批次，复用上述既有冷却与可取消等待，不轮询认证状态。不继续领取本批其余商品，不额外发请求、探测代理或调用 solver；下一轮仍执行原有门禁。

这个错误不能确定由代理还是目标端关闭连接，因此不标记为代理不可用或 CDP 故障，也不撤销当前商品的尝试次数、不恢复为 pending、不回写历史次数。单商品原有上限、失败冷却和多 worker 租约规则保持不变，其他导航错误与旧格式回复不适用此批次保护。`challenge_break` 仅沿用既有提前结束字段，不是验证码证据。回归：`test_detail_navigation_connection_closed.py`。该保护减少依赖异常期间的批内无效工作，不代表上游恢复或真实 solver 通过率提高。

### 明确导航超时时停止批内连续消耗

私有 capture 的安全诊断明确为 `BrowserError` 且 `browser_code=ERR_TIMED_OUT` 时，worker 使用 `reason=detail_navigation_timed_out`，结束当前批次并复用既有冷却和可取消等待，不继续领取本批其余商品。该原因进入原有有界批次统计，不输出原始异常正文。普通 Python/Playwright `TimeoutError`、其他错误码、未知诊断和旧格式回复不适用此规则。

当前商品仍按原规则消耗尝试次数；不恢复 pending、不扩大预算、不提交 captcha report、不做 CDP 故障报告、不轮询认证状态。导航超时不能确定代理、目标站点或其他链路的根因；`challenge_break` 仍只是沿用提前结束字段。此保护不调整导航和 capture 超时，也不保证真实吞吐或求解通过率提高。回归：`test_detail_navigation_timeout.py`，包含私有 IPC、实际仓储、共享 worker 尝试上限、普通超时兼容性及取消等待。

## Detail HTTP 错误状态中的验证页

detail 的 HTTP 与附着浏览器路径先用现有识别器检查页面内容和最终 URL，再处理普通 HTTP 错误状态。只有已识别的验证页才进入原挑战流程；403、404、429、503 等状态码本身不构成验证码证据，普通错误仍失败，不增加浏览器重试。

HTTP 路径继续遵守原有 browser fallback 开关；浏览器路径保留新挑战页供既有 solver 使用，同一目标已有挑战页时仅关闭本次新建的重复页，不聚焦、关闭或导航原有页面。挑战类型通过私有 IPC 保留，worker 不消耗该次商品重试计数；原暂停、报告、冷却、租约、取消和总 capture 预算不变。回归：`test_detail_http_error_challenge.py`。离线复现此漏判不代表当前线上失败同因，也不能以错误状态识别修复代替代理恢复或实际求解成功率验收。

关闭本次新建的重复挑战页前，还须重新核对最初的同商品挑战页：该页仍在当前 context、读取前后目标身份一致、当前内容仍被识别为挑战且不是登录页。新请求期间旧页可能已恢复、被关闭或导航；不能继续用导航前的布尔判断授权关闭新页。读不到、目标改变或状态未知时保留新挑战页，不操作旧页；重读沿用单页最多 5 秒及原 capture 剩余预算，取消和预算耗尽向上传播。正常成功的详情抓取不额外重读，目录里后来出现的其他页也不因此获得关闭授权。回归：`test_detail_challenge_retention_race.py`。这是有界的关闭前核对，不是跨进程原子锁，也不证明历史站点拒绝均由此竞态造成。

### 导航异常后已加载的同商品挑战

附着浏览器的新建自有页面在 `goto` 抛出 Playwright 操作超时、`ERR_TIMED_OUT`、`ERR_CONNECTION_TIMED_OUT` 或 `ERR_CONNECTION_CLOSED` 后，仅补做一次当前文档读取，最多 2 秒且受原 capture 剩余预算约束。读取前后必须按既有规则绑定同一商品，内容与最终 URL 必须经现有识别器确认为挑战且非登录页，才保留 typed challenge 并沿用上述重复页复核。不重试导航，不聚焦或操作借用页面，不将半加载文档、普通详情 DOM、空白页或异商品升级为成功；没有有效证据时保留原导航异常。已证明的挑战在会话分离期间超时或取消时仍保留页面，但截止和取消优先，不伪报 challenge 结果。

代理、证书、未知错误及非 Playwright 异常不进入该读取分支。可选读取失败不覆盖原导航错误，不记录原始异常、页面正文或令牌；既有报告、冷却、租约及请求预算不变。回归为 `test_detail_navigation_challenge.py`、`test_detail_navigation_challenge_guards.py`，覆盖私有 IPC、worker 重试计数和页面所有权。离线可达路径不证明历史线上超时必然已加载挑战，也不能代替实际采集或求解通过率验收。

## Solver CDP 页面生命周期

`/json/new` 与 `/json/close/<id>` 只有 HTTP 成功响应才进入后续处理，错误响应正文不进入日志。业务新页还必须有有效字符串 ID、页面类型（若提供）和 WebSocket 地址；已返回有效 ID 但连接元数据不完整时，保留自有归属供清理，不重复创建页面。身份准备重试仍复用同一个已创建页面，原有次数、超时与取消门禁不变。

keepalive 创建失败时，页面压缩保留一个实际存在的页面，不把错误响应里的 ID 当作保留页。关闭请求失败不增加关闭计数、不移除自有归属，也不清除该页的绑定信息；只有成功关闭才清理这些状态。关闭接口的正常纯文本回复无需解析 JSON，404 等失败也不伪装成已确认关闭。传输异常仅记录类型，不记录可能含私有 URL 或凭据的异常正文。

保活页创建和页面关闭在每次 HTTP 发送前复用 solver 的取消与截止时间检查，单次 timeout 不超过剩余预算；无 solve budget 的调用保留原 5 秒参数。已停止时不开始新的创建或关闭，不把停止异常吞成普通 HTTP 失败。批量自有页清理中途停止时，保留已经完成的关闭计数与其余页面归属；压缩及重复挑战页清理也在下一次 HTTP 前停止，不扩大任何页面关闭授权。清理返回后再检查停止状态，不能在最后一次关闭期间被取消或超时后仍发布成功。已发出的请求仍可能完成，Requests 的 timeout 不是严格的墙钟截止时间。

回归：`test_captcha_target_http_lifecycle.py`、`test_captcha_lifecycle_budget.py` 与 `test_captcha_target_open_recovery.py`，并检查页面选择、跨 scope 隔离、清理及截止时间边界。此修复防止页面管理误判和后续状态失配，不代表已经定位站点拒绝的原因或证明真实求解通过率提升。

未找到滑块时，复用已有页面摘要发布 `slider_missing` 安全诊断：只保留固定的文档就绪枚举和严格布尔状态，缺失值为未知，不记录页面正文、标题、URL、令牌或异常原文，不额外读取页面。沿用每阶段最多 64 条的日志限制，日志写入失败不改变求解与清理结果。页面状态本身不作为拖动成功或认证确认依据。回归：`test_captcha_missing_slider_diagnostics.py` 与 `test_pc2_solver_diagnostics.py`。

CDP 单命令使用单调时钟约束发送和等待回复的总窗口：普通命令 5 秒，截图命令沿用 12 秒上限；每次收取无关事件或旧 request ID 后只使用剩余时间，不重新获得完整等待窗口。原有更短的非 solve socket 超时和整个 solver 剩余预算仍优先，响应返回后再次检查停止和单命令截止时间，不接受晚到结果。临时 socket timeout 在命令结束后恢复，不让上次很短的剩余时间影响下一条命令；已经关闭或替换的 socket 不再恢复。不增加 CDP 命令或站点请求，不扩大重试、冷却、输入或页面操作授权。第三方发送/接收若不遵守 socket timeout，仍可能晚返回，但晚到结果不再作为有效响应。回归：`test_captcha_cdp_command_budget.py`，并检查既有 deadline、transport recovery、页面探测和执行归属边界。

CDP request ID 在尝试发送前占用，发送抛错也不复用。socket 发送失败不能证明上游没有收到请求；旧回复或旧错误只会作为不匹配消息跳过，不得冒充下一条命令的结果。尚未发送的序列化失败、预算到期不占用编号。best-effort 鼠标释放使用相同编号约束，仍只执行原有一次释放，不增加发送、重试或等待预算。回归：`test_captcha_cdp_request_identity.py`。

拖动后保留原有验证轮询，允许页面跳转期间的短暂摘要读取失败恢复为可确认的成功。轮询未能确认成功，且最终页面摘要仍明确返回 `probeFailed` 时，以既有 `cdp_unavailable` 分类结束本次求解，不把未知页面状态当作挑战失败，不刷新页面或再次输入。后续仍由原有重连、退避和请求预算处理；取消与总截止时间优先，明确成功、站点重试提示和本地 mock 的规则不变。缺少字段不被擅自解释为传输失败。回归：`test_captcha_verification_probe_failure.py`。这是离线可复现的失败保护，不证明历史端点残留或站点拒绝与它同因，也不代表真实通过率已经提高。

验证轮询结束后的文档若仍为 `loading` 且没有可见滑块，复用已有最多 8 秒、32 次的加载等待，不直接刷新正在跳转的文档。等待服从原 solve 截止时间与取消；新摘要仍需通过同目标业务载荷证明才算成功。一直加载返回 `challenge_loading`，读取失败返回 `cdp_unavailable`；加载后出现的其他目标滑块不授权额外输入，同目标滑块也只使用原重放预算。本地 mock 和原验证轮询不变。回归：`test_captcha_post_drag_loading.py`。该等待只避免已复现的过早刷新，不证明此前“1 px 无终态”样本同因，也不放宽滑块消失或空白页的成功判断。

NC 重试点击后的恢复探测不能用 `probeFailed` 摘要或 `loading` 文档累积稳定滑块样本。摘要读取失败立即交回原有恢复路径；加载可在原 3 秒探测内恢复，但到期仍加载时，不再遍历点击前保存的其他坐标，交回既有加载宽限、取消及总截止时间判断。安全日志 `NC retry document uncertain; deferring without further clicks.` 只表示停止旧坐标输入，不是认证成功。明确未恢复的非加载状态仍保留原候选点击规则，不增加预算。回归：`test_captcha_nc_retry_uncertain.py`、`test_captcha_nc_retry_readiness.py`。该边界已离线复现，不能据此认定真实 `code=300` 或此前 1 px 样本的根因。

连接主尝试的 5 秒间隔只在还有下一次主尝试时执行；最后一次连接失败后直接进入原有停止检查、认证恢复与清理，不为不存在的下一次重试空等。当前失败原因仍为 `cdp_unavailable` 时保留该诊断，不覆盖成普通 `max_attempts_exceeded`；取消、截止时间和真实认证恢复继续优先。观察产物同样保留固定的 `cdp_unavailable`、`deadline_exceeded` 类别，其他未知原因仍归 `other`。同一发现轮次用新 socket 重连相同 endpoint 的恢复机会保持不变，不增加尝试、导航、拖动、总预算或修改外层冷却。回归：`test_captcha_transport_retry_pass.py`、`test_solver_transport_failure_evidence.py`。这减少已确认的末次空等，不代表修复站点 `code=300` 的拒绝原因。

Linux 原生窗口聚焦和几何查询同样服从本次 solve 的取消与总截止时间。`xdotool`、`xwininfo`、`xprop` 每次启动前取原 3 秒上限与剩余预算的较小值；返回或抛错后再次检查停止，不接受迟到的聚焦或坐标证明，也不在到期后继续下一条聚焦回退命令。聚焦稳定等待复用可中断等待器。未设置 solve budget 时保留原命令上限，正常聚焦顺序、准确目标页激活、坐标解析、Windows 路径、请求预算及冷却均不变。运行中的命令仍依赖 subprocess 的超时回收，取消不保证立即中断底层命令，父进程 hard deadline 继续兜底。回归：`test_captcha_linux_window_budget.py`、`test_pc2_linux_window_focus.py` 与 `test_captcha_x11_window_geometry.py`；这是异常收尾可靠性修复，不等于已经定位站点拒绝原因或证明通过率提高。

## 已完成请求不被旧页面重新唤醒

控制面明确为 `manual_auth_completed` 或 `solved`，且 `paused/manual_required/running` 均为 false、没有当前或 scoped 活动挑战、也没有强制恢复标志时，`last_request` 仅用于历史诊断，不再授权周期 CDP 探测重跑旧页面。执行前再次读取控制面；探测期间刚完成的请求以 `request_already_resolved` 阻止启动，不清 Cookie、关闭页面或修改服务端状态。

新挑战 ID、活动 scope、暂停、未知字段、`manual_retry`、`resumed` 和 `resumed_after_cooldown` 不被这条完成规则抑制，仍遵循原人工窗口、节点归属、并发、预算和冷却约束。没有提高站点接受率的证据时，只能报告减少已完成请求的无效重跑，不能把它算作滑块通过。回归：`test_pc2_solver_resolved_request.py`。

### 不确定尝试不立即替换挑战页

本地尝试的 bool 返回接口保持不变；私有子进程回复另携带白名单失败原因，父循环不再把所有 `False` 当成挑战已拒绝。`cancelled`、`deadline_exceeded`、`cdp_unavailable`、`challenge_loading`、`slider_not_found` 与 `execution_unavailable` 只表示本次未确认结果：保留绑定页面，不立即关闭重开商品页、不补开或浏览参考页，也不因此向 PC1 自动升级。启动失败、子进程无结果及普通执行异常使用 `execution_unavailable`，不能误报成站点拒绝或 CDP 故障。

真实已失败拖动的参考计数仍保留，普通失败计数、重试间隔和共享浏览器冷却不返还、不重置；后续正常调度、人工控制及冷却恢复 ACK 后的既有清理规则不变，不保证页面永久保留。`challenge_retry_exhausted` 仍走原有拒绝后替换策略，`manual_required` 仍进入终止式人工接管。未知原因与旧格式无原因结果保持原有行为；本规则不扩展到所有 OS 输入失败类型。

既有 `local_solver_failure` 只新增安全枚举原因；`failed_challenge_target_rotation` 的 `reason=unconfirmed_attempt_target_preserved`、`attempted=false` 表示本次没有替换。不记录新的页面正文、URL、凭据或模型内容。回归：`test_pc2_solver_unconfirmed_result.py`、`test_pc2_solver_unconfirmed_loop.py` 及参考页、重试额度、人工接管、scope 隔离测试。此修复防止不确定状态触发额外导航，不证明此前真实 detail 拒绝已修复或通过率提升。

OS 输入返回未完成，且原有安全门禁已确认焦点失败、鼠标执行异常、`screen_mapping_*`、光标位置或按键状态无法核实时，本轮以既有 `execution_unavailable` 返回，不再刷新、等待或继续剩余主尝试，也不覆盖成 `max_attempts_exceeded`。外层沿用上述不确定状态策略保留目标，仍消耗失败次数并执行原冷却，不新增参考页、人工升级或输入；取消及总截止时间优先。输入前后原有松键清理仍执行，成功验证、明确拒绝、缺少后端时的原回退和本地 mock 行为不变。回归：`test_captcha_unconfirmed_os_execution.py`、`test_captcha_os_drag_fallback.py`。此项修正执行分类与额外刷新，不表示已定位底层鼠标状态异常原因或提高站点接受率。

## CDP 端点中断恢复不再固定空等挑战冷却

只有重连前的端点健康探测明确失败时，私有捕获协议才携带固定布尔值 `endpoint_unhealthy=true`。detail 等待器在原等待总期限内，每 30 秒先检查控制面；仅在 detail 明确无挑战、无人工要求、未被操作员暂停时，以最长 5 秒只读请求 `/json/version`。HTTP 200 且返回有效的 browser WebSocket 元数据后，以 `wait_exit=cdp_resumed` 提前退出等待，下一轮仍执行原有领取前门禁。`cdp_poll_count` 只计本地端点探测，不代表站点访问或详情成功。

没有该明确证据的旧记录、页面/驱动超时、连接预算耗尽、代理故障及真正的挑战仍保持原退避；不以 HTTP 接口可达推断页面已恢复，不清冷却、不修改 Cookie/profile，也不提高业务请求预算。回归：`test_cdp_reconnect_health.py`、`test_detail_worker_cdp_recovery_wait.py`，以及原认证恢复、操作员暂停和请求截止时间用例。

## 私有 Capture 的 CDP HTTP 预算

通过 `tools/cdp_http_session.py` 发出的 CDP HTTP 请求也遵守私有 capture 的共享截止时间：每次发送前重新计算剩余秒数，取原请求超时与剩余时间的较小值；预算已耗尽时，不创建会话、不发送请求。缓冲响应返回后再次检查截止时间，不将迟到响应作为后续页面管理的依据。这包括该入口承载的目标列表、保活页、关闭页和连接元数据请求，不改变原有页面选择或清理授权。

没有私有 capture deadline 的其他调用保留原超时；原始请求失败、取消、单次会话关闭、代理禁用和安全诊断规则保持不变。Requests 的 timeout 不是完整响应的严格墙钟期限，因此仍保留父进程原有 180 秒 hard deadline 与 5 秒清理流程；此修复不宣称所有底层调用都能协作取消，也不增加站点请求、重试或模型预算。回归：`test_cdp_http_capture_budget.py`、`test_cdp_http_session_lifecycle.py` 与既有 capture 连接及工作预算测试。

## 可选异步描述补取的进程截止时间

详情主 HTML 已写入后，`build_description_audit` 对 `description-data` 的可选补取使用自有子进程，沿用原 20 秒请求参数，并将导入、请求、解码和结果返回约束在 20 秒执行窗口内。复用既有 capture 进程回收器及最多 5 秒清理上限；不通过后台线程假装超时，不遗留仍在访问站点的工作。没有有效链接时不启动子进程；没有新增请求、重试或模型调用，也不改变直连/代理规则。

成功时仍使用既有抓取器及 UTF-8/GBK 解码规则，保存描述文本和面积证据。超时或不可用时保留已经写入的主 HTML，并让描述及面积继续为未知，不伪造成功证据、不把它报告成验证码或 CDP 中断。取消和无法确认回收的停止信号继续向上传播。日志只输出固定原因类别，不输出描述链接、令牌、完整文本或子进程原始 stderr。其他分析调用直接使用 `src.llm_text_extraction.fetch_description_data_text` 的行为不变。

回归：`test_description_capture_deadline.py`、`test_detail_capture_deadline.py`、`test_live_batch_smoke.py` 及既有描述解码测试。主 HTML 与 selected 文件的时间差只用于定位补取阶段，不是浏览器导航耗时或验证码通过率；自然运行收益仍需单独回读。

## 控制面读取失败不授权继续采集

已配置 API 的 seed/detail worker 在 `/status` 超时、连接或 HTTP 错误、JSON 解码失败、非对象响应时，返回 `paused=true, reason=status_unavailable`。沿用三次读取、每次 5 秒超时及重试间隔；三次都失败后不领取任务、不处理商品、不进行人工认证探测，也不提交新的验证码报告。不将状态未知归因为验证码、CDP 或商品失败，不消耗商品重试预算。

此暂停仅为 worker 当前读取结果，不写服务端暂停状态。后续按既有可取消等待及状态轮询恢复，成功读到状态后仍由原作用域、人工暂停和认证规则判断。显式不配置 API 的独立运行继续使用 `status_probe_disabled`，分析专用领取路径不变。批次安全计数保留 `status_unavailable`，避免被归入 `other` 或误称正在求解。

回归：`test_collection_status_unavailable.py`。此门禁修复经离线故障注入可复现，但不能据此认定当前站点拒绝由控制面故障导致，也不能将少发无效请求等同于验证码通过率提高。

## Slider 探测的请求目标约束

显式指定 `target_url` 时，slider 探测在建立 WebSocket 和前台激活之前，对挑战页、普通页面及 iframe 使用一致的目标匹配规则；不能因另一个商品或 seed 页恰好有内嵌滑块，就把它当作当前请求的探测结果。detail 复用规范商品身份，忽略跟踪与挑战参数，但不跨商品或来源主机；seed 继续匹配列表身份参数，仅保留既有挑战重定向丢失查询参数的兼容路径。未指定目标的通用探测不变，没有可验证父页面绑定的异域 iframe 不作为显式目标的证据。

此修复只收敛候选，不增加站点访问、滑块尝试、请求预算或并发，不修改拖动、成功验证、冷却和取消策略。探测串页与后续执行目标不同不能直接证明站点 `code=300` 的原因；后续执行层仍独立校验目标，实际接受率需要自然运行证据。回归：`test_pc2_slider_probe_target_binding.py`，并检查既有 CDP 探测、URL 身份安全、执行归属和 seed/detail 绑定。

认证恢复检查也以同一 detail 规范身份筛选既有页面，不因 `spm` 等跟踪参数漏掉健康的同商品页，亦不能漏掉仍在挑战、登录、硬拦截或状态未知的同商品页。原有“所有匹配页面均可确认且无挑战”约束保留；匹配身份本身不证明认证，不覆盖错误、探测失败或完整业务载荷校验。seed 健康证明仍要求完整列表身份，不沿用查找挑战时的查询参数丢失兼容；其他 scope 的旧会话回退不变。恢复门禁继续执行原有 completion/challenge 绑定及服务端确认，不以规范化为由直接清除暂停或重建页面。回归：`test_pc2_auth_target_isolation.py`。

失败后的页面轮换也必须按本次请求身份收敛，不能仅因同为 detail 或 seed 就关闭其他任务的挑战页。detail 使用同来源、同商品的规范身份；seed 保留列表路径、地区、页码和排序身份，查询参数丢失而无法确认归属的页面不作为可关闭的重复页。同目标的非登录挑战重复页仍可按既有流程轮换，并且只打开原有的一页；登录页、普通详情、其他商品、其他列表及其他 scope 保留。不修改暂停、退避、输入、重试或请求预算。回归：`test_pc2_rotation_target_isolation.py`。这是离线复现的页面隔离修复，不证明站点 `code=300` 的拒绝原因已定位，也不以减少误关页面代替真实通过率验收。

## NC 重置的有界安全时序

子进程诊断同样准入 `src.captcha_nc_retry`，仅输出固定的 `nc_retry_click`、`nc_retry_restored`、`nc_retry_authenticated`、`nc_retry_uncertain` 事件。点击只保留候选序号、数量及固定类型，不输出坐标、页面内容、URL、异常正文或参数原值；其他 INFO 继续被过滤，已有 WARNING 行为不变。沿用每阶段最多 64 条的限制，诊断输出故障不影响重试或清理，退出后还原 logger 状态，不改变 root logger。

离线观察投影将这些事件关联到同容器、未结束的当前调用，每次调用最多保留 64 条 `nc_retry_events`。旧日志没有事件时保持缺失，不解释为没有执行重试；`restored` 仅表示重现滑块，`authenticated` 也不替代完整调用的验证、自动输入、认证确认或 bound health 证据，不能直接增加成功计数。无效候选计数、未知类型及其他字段不作为可信证据。回归：`test_nc_retry_diagnostics.py`，并检查原诊断、NC 停止/恢复和观察归因用例。本项仅修复已复现的时序漏记，不改变输入、尝试次数、请求预算、冷却或截止时间，也不证明站点拒绝原因已修复。

## 轻量 CDP 命令不因通知续期

slider 轻量探测沿用每条命令 5 秒的窗口，但使用单调时钟统一约束发送、接收以及对无关响应和通知的等待。每次 I/O 只使用剩余时间；连续收到通知不会获得新的 5 秒，超过截止的匹配响应也不能作为有效探测结果。超时沿用现有按目标隔离和 socket 清理，然后才检查原有的下一候选，不创建页面、不增加命令重试或站点请求。

这是单条命令的截止保护，不是全部候选扫描共用 5 秒，也不更改挑战优先级、目标身份、前台激活、拖动、冷却或认证门禁。普通通知与匹配响应在窗口内继续正常处理，每条后续命令保留自己的原有窗口；取消类异常不被吞掉。回归：`test_pc2_slider_probe_deadline.py`，并检查 CDP 探测、目标绑定、循环节奏及本地 solver 契约。离线夹具可复现通知持续到来导致等待被续期的缺陷，但不能据此认定历史所有 CDP 超时的根因相同，也不能把截止保护等同于站点接受率提高。

## Detail Cookie 健康检查的重定向诊断

对原有一次 HTTP 请求返回的 301/302/303/307/308，仅将 `Location` 投影为 `sample_results[].redirect_kind`：`login_required`、`challenge_required`、`same_detail`、`other_detail`、`other_taobao`、`external_target`、`non_https_target`、`invalid_location` 或 `missing_location`。复用既有 URL 身份和登录识别；不输出原始 Location、查询参数、响应正文或 Cookie。缺少 headers 的旧 mock/响应保持兼容，过长、歧义及字段过多的地址只返回固定的无效分类。

这只是响应分类，不是根因或认证证明：`same_detail` 不表示可以跟随或已经认证，登录/挑战分类也不证明出口变化。仍为 `allow_redirects=False`，302 不写 Cookie 快照、不确认认证；不新增请求、不改变超时、重试预算、代理入口或 seed 健康规则。旧状态没有此字段时表示未采集，不能反推旧 Location。回归：`test_detail_auth_redirect_diagnostics.py`，并检查原 detail payload、scope/owner 绑定、Cookie 重试及 API 状态契约。
