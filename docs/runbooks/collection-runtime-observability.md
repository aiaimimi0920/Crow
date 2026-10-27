# 采集运行状态与统计观测

## 状态读取不等待全量统计

`/api/status` 的 lightweight 路径与 `/api/collection/overview` 共用一个 API 统计缓存，TTL 为 15 秒。统计到期或冷启动时由单个后台线程刷新；请求线程不等待数据库分组统计及 occurrence 全量计数。进程内最多一个刷新任务，其他请求复用快照，不排队创建新任务。

统计与控制状态分离：暂停、人工认证、collection scopes 等仍按每次状态请求实时读取。任务领取、租约、授权和暂停检查不使用统计缓存。worker 的展示/进度统计仍默认同步采样并复用 15 秒 TTL，不改变业务仓储读取接口。

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

### 暂停原因不等于正在求解

seed/detail worker 读取 scoped status 时，`paused=true` 只表示该阶段不可继续，不证明 solver 正在执行。仅当该 scope 的 `last_status=running` 时使用 `captcha_solver_running`；暂停但没有运行证据时使用既有 `collection_paused`。`manual_required=true` 仍优先使用 `captcha_solver_manual_required`，不能仅凭这些原因标签区分冷却、人工接管或其他等待，也不能据此清除状态或重试。

另一 scope 的 aggregate `running=true` 不得被误用于当前 scope。此次修复只纠正原因标签，不改变暂停布尔值、领取门禁、恢复轮询、退避或跨节点规则。对应离线回归为 `tools/test/test_collection_pause_reason.py`。

## Worker HTTP 会话生命周期

detail worker 的 CLI 和默认上下文构建路径拥有自己创建的 HTTP 会话。批次刷新完整成功后才关闭被替换的旧会话；刷新失败时，原会话继续用于既有回退路径。循环停止、单批完成或异常退出时关闭最后一个自有会话；同一会话被重复返回时不在批间提前关闭。

显式传入的 `http_session` 或 `runtime_context_factory` 保持借用语义，由调用者负责资源生命周期。分析专用 CLI 不创建采集 HTTP 会话。关闭失败只记录安全错误分类，不覆盖批次的原始结果或异常；不改变请求次数、刷新频率、退避、租约和暂停判断。

对应回归为 `tools/test/test_detail_worker_sessions.py`，同时覆盖兼容 facade 与实现模块。资源释放正确不等于已经证明吞吐或认证成功率提升，实际收益仍需自然运行样本验证。

## Capture 失败诊断不丢失

detail worker 的失败结果可额外包含 `capture_failure`，不改变既有 `reason`、CDP health、任务状态、重试预算、租约或退避。

- `operation` 仅允许固定的 CDP 操作名、`detail_browser_capture_deadline`、`capture_helper` 或 `other`，未知内容不直接输出。
- `deadline_exceeded=true` 仅表示整个 capture helper 超过既有 180 秒截止时间，包含驱动启动、页面操作与清理；不能据此认定 TCP 端点不可达，也不能确定具体卡在哪一步。
- `cause.type` / `cause.message` 保留子进程异常的固定安全分类。Python 和 Playwright 的超时均归 `TimeoutError: timeout`，不复制原始异常正文、参数、业务 URL、提示词、回答或任意诊断后缀。
- 旧格式子进程回复没有诊断时仍可读取，原因记为 `Exception: unexpected_error`，不猜测类型。非 capture 异常不添加此字段。

超时时若收到有效阶段标记，还会提供 `stage` 与 `stage_elapsed_seconds`，分别表示最后观测到的阶段及截至总截止时间在该阶段停留的秒数。阶段覆盖 helper 导入、驱动启动、CDP 连接、既有页面读取、新页创建、会话创建/配置、导航、详情就绪、会话分离、页面关闭、浏览器分离、驱动退出和回复写入。它是阻塞位置线索，不是对站点拒绝原因的判断。

阶段默认不启用，仅在私有 capture 子进程中通过固定枚举写入 stderr。父进程仅检查末尾 16 KiB，接受本次进程时间范围内的完整 LF/CRLF 标记；旧 helper、未知标记、不完整输出或日志噪声过多时可不提供阶段。Windows 超时异常不携带 stderr，因此在既有有界清理完成后读取缓冲区，但阶段计时仍截止于超时发生时。原始 stderr 不进入 worker summary。

`stage=cdp_connect` 覆盖连接前检查、端点解析和 Playwright 附着，不等于 TCP 连接失败。HTTP 元数据或浏览器级 CDP 命令成功，也不能证明 Playwright 附着已经成功：后者还会等待既有页面初始化。应分别核对传输通道和页面初始化；不要仅因浏览器健康就否定抓取超时，也不要仅因该阶段超时就关闭已有认证页、重复重启浏览器或缩短冷却。

私有 capture 的共享预算也约束连接后的新工作：读取既有页面和创建自有页面前检查剩余时间，导航的 90 秒上限取剩余预算与原上限的较小值，配置后和详情读取前后继续检查。预算耗尽不再开启新页或导航，也不接受超出预算才返回的成功结果；未设置私有 deadline 的调用保留原导航上限。清理不受该工作预算门禁阻止，仍尝试关闭自有页面、分离会话和 driver；第三方不支持协作超时的操作仍由既有 180 秒 hard deadline 兜底，并非保证所有页面创建或读取都能及时取消。

既有页面的认证分类不再调用没有 timeout 参数的 `page.content()`，而使用公开的 `locator("html").inner_html(timeout=...)` 读取文档子节点（含 title、script、表单和 body）。单页最多等待 5 秒，且不超过剩余工作预算；没有私有 deadline 时同样保留单页 5 秒上限。读取失败仍按既有规则进行 URL 分类，未耗尽预算时可继续新详情请求；整个预算耗尽则返回超时，不创建新页。不会聚焦、导航、关闭既有页面，也不会把 DOM 读取超时当成挑战已通过。此路径仍保留登录门禁、同目标旧挑战去重与跨 scope 隔离。

自有页面关闭失败时，如果已有主要失败或取消，保留原始失败，只记录清理异常的类型，不记录正文；如果原操作没有失败，则不能静默接受清理失败。此规则不授权关闭任何其他页面，不解决归属未知的旧空页，也不改变人工认证页保留规则。对应回归为 `tools/test/test_capture_operation_budget.py`。

对应回归为 `test_capture_progress.py`、`test_detail_capture_diagnostics.py` 与既有 protocol、deadline、worker exception reporting 测试。该字段仅补充诊断，不新增探测请求、不调整超时或重试，不等于已经修复抓取超时或提高 solver 通过率。
