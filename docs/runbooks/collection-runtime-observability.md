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

`detail_worker_sleep.sleep_seconds` 仍是原有请求等待上限。新增 `detail_worker_wait_finished` 记录 `requested_wait_seconds`、`actual_wait_seconds`、`status_poll_count` 与 `wait_exit`。实际等待从等待器入口至返回计时，包含状态 HTTP 轮询耗时，不是纯 sleep 时长。

`wait_exit` 仅使用 `detail_resumed`、`deadline_elapsed`、`stopping`、`wait_returned`。普通 lifecycle wait 不提供终止原因，因此用 `wait_returned`，不猜测是自然到期还是取消。新增观测不修改 30 秒轮询、operator pause、scope 隔离、checkpoint、冷却或重试预算，也不增加请求。runtime context 刷新失败的普通等待同样记录完成事件，但不增加认证探测。

对应定向回归为 `test_detail_worker_observation.py`、`test_detail_worker_auth_wakeup.py`、`test_detail_worker_operator_pause.py`，再扩展到 worker 生命周期、失败、归档完整性和历史保留边界。不要将以上计数拼成验证码通过率。
