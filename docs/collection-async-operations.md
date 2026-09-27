# Collection API 后台操作契约

日期：2026-09-24。对应优化清单 #17。本文描述工作树中的实现；当前尚未部署到
Crow、PC2 或 NAS。AVM pipeline 仍属于分析引擎的迁移输入，本次改动不代表分析或
预测能力已经完成产品验收。

## 提交与查询

以下后台入口使用操作员凭据提交 JSON 对象。提交成功返回 HTTP 202，随后查询任务回执。
查询同样需要操作员凭据；采集 worker 凭据不能读取回执。

| 操作 | POST 路径 |
|---|---|
| 近期详情重放 | `/api/avm/recent_detail_replay` |
| 详情维护 | `/api/collection/details/maintenance`、`/api/avm/recent_enrich_maintenance` |
| 补抓缺失详情 | `/api/collection/details/fetch_missing`、`/api/avm/fetch_missing_detail_archives` |
| 归档详情重放 | `/api/collection/details/prepare_replay`、`/api/avm/archive_detail_replay` |
| Pipeline | `/api/analysis/pipeline/run`、`/api/avm/run` |
| Pipeline 旧入口 | `/api/avm/start_all_subtasks`、`/api/avm/run_all_subtasks_sync` |
| 种子批量提交，显式 `mode: async` | `/api/save`、`/api/collection/seeds/batch` |
| 单条估值，顶层显式 `execution_mode: async` | `/api/avm/evaluate`、`/api/analysis/evaluate` |
| AVM 批量筛选，顶层显式 `execution_mode: async` | `/api/avm/screen` |
| 位置推断，顶层显式 `execution_mode: async` | `/api/infer_location`、`/api/collection/details/infer_location` |
| 人工审核回执，省略 mode 或 `mode: sync` | `/api/avm/manual_review_receipts`、`/api/analysis/manual_review_receipts` |
| 漂移报告 | `/api/avm/drift_status`、`/api/analysis/drift_status` |
| 发布门禁报告 | `/api/avm/release_gate`、`/api/analysis/release_gate` |
| 近期缺口审计 | `/api/avm/recent_gap_audit` |

详情维护请求继续保留原参数、默认值和报告字段。只有 JSON 布尔值 `dry_run: false` 才允许
修改维护对象；字符串、数字等值不会打开写入。dry-run 仍保存任务回执和报告。
显式 `limit: 0` 保持有效。

提交响应示例：

```json
{
  "status": "accepted",
  "job_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "job_status": "queued",
  "status_url": "/api/collection/jobs?id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "cancel_url": "/api/collection/jobs/cancel"
}
```

使用同一 API origin 和操作员凭据 GET 响应中的 `status_url`。成功读取回执返回
HTTP 200；客户端需检查回执的 `status`。原先读取同步响应字段的调用方，现在从
`status: completed` 回执的 `result` 中读取这些字段。

Pipeline 的 `mode: sync` 和名称带 `sync` 的旧入口也采用这个 HTTP 契约。
Pipeline 在后台 worker 内同步执行，以便记录实际完成；引擎返回 `already_running`、
`started`、`failed` 或缺少完成状态时，该请求会得到失败回执。

种子批量提交的同步模式仍接受采集 worker 或操作员凭据。只有操作员显式提交
`mode: async` 时才切换到后台队列，确保提交者可以使用操作员凭据读取回执；提交成功
返回 HTTP 202 和通用
任务回执，完成结果位于回执的 `result`。控制字段 `mode` 不会写入种子业务 payload。
省略该字段或使用其他值仍走原有同步 HTTP 200 结果合同。异步处理失败时，回执错误码为
`AVM_SEED_BATCH_ASYNC_FAILED`；调用方不得因为 POST 超时或断线自动重复提交。

单条估值和位置推断默认仍同步返回原结果。两者都只在顶层显式设置
`execution_mode: "async"` 时入队；该执行控制字段与估值的
`options.valuation_mode` 无关，并且不会传给业务函数。位置推断异步回执会回显可选
`item_id`；完成结果保留原推断对象。相应任务失败错误码分别为
`AVM_EVALUATE_ASYNC_FAILED` 和 `AVM_DETAIL_INFER_LOCATION_ASYNC_FAILED`。

AVM 批量筛选也默认同步，只有顶层 `execution_mode: "async"` 才入队。`items` 类型仍在
入队前校验；完成回执的 `result` 使用原筛选响应结构，且在任务完成前写入符合条件的告警。
后台失败错误码为 `AVM_SCREEN_ASYNC_FAILED`。

人工审核回执的默认流程把审核记录写入、维护和操作历史收尾一起放入队列。队列拒绝或
queued 回执保存失败时，不写审核记录。入队前捕获数据根、审核内容、维护选项和写入依赖；
维护参数沿用原有人工审核接口的语义。完成结果和操作历史仍保留 `execution_mode: sync`，
HTTP 调用方使用上述 202 加轮询流程。显式 `mode: async` 也使用同一个
`CollectionJobManager` 和 durable receipt；为兼容旧客户端继续返回 HTTP 200、
`maintenance_job_id` 和 `maintenance_job_status`，同时提供通用 `job_id`/`status_url`。
旧的 receipt jobs 查询接口会把这类通用回执投影到原有响应形状，新的客户端应优先使用
`status_url`。

审核记录已经写入后，维护或历史收尾可能失败；已确认的审核记录不会被回滚或删除。
失败回执区分 UPSERT、MAINTENANCE 和 SYNC_FINALIZE 阶段，异常原文只进入日志。
报告任务完成表示报告生成结束；报告内容中的 `pass: false` 仍须由调用方按业务含义处理。

## 回执与失败处理

回执包含 `job_id`、`owner_id`、`operation`、`status`、`created_at`、`started_at`、
`finished_at`、`deadline_at`、`timeout_seconds`、`cancel_requested_at`、`stop_reason`、
`result` 和 `error`。时间使用带时区的 UTC 字符串。`owner_id` 标识接纳任务的 API
实例，便于核对执行归属；它不提供跨进程租约或锁。

`queued`、`running` 和 `cancelling` 需要继续轮询；`completed`、`failed`、`cancelled`、
`timed_out`、`interrupted` 为终态。失败回执保留操作错误码，公开消息为
`Collection operation failed`，`error.error_id` 对应任务 ID。异常原文保留在服务端日志。

队列已满或正在关闭时，提交返回 503 `COLLECTION_JOB_QUEUE_FULL`。回执无法持久化时，
返回 503 `COLLECTION_JOB_SUBMISSION_FAILED`，不会执行未确认入队的工作。
查询 ID 必须为 32 位小写十六进制字符串；非法 ID 返回 400
`COLLECTION_JOB_INVALID_ID`，不存在返回 404 `COLLECTION_JOB_NOT_FOUND`，回执损坏或
不可读取返回 503 `COLLECTION_JOB_STATE_UNAVAILABLE`。

POST 断线、查询超时或任务失败后，不要自动重发写请求。工作可能已经产生部分输出；
任务队列不提供业务事务回滚或跨请求去重。先核对回执、日志和已生成报告，再决定后续操作。

## 取消与执行时限

使用操作员凭据向 `cancel_url` POST JSON 对象：

```json
{"job_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

成功返回 HTTP 200 和当前回执。排队任务在取消回执持久化后进入 `cancelled`，释放容量，
不执行工作。运行中任务先进入 `cancelling`，继续占用容量；只有工作实际退出后才进入
`cancelled` 并设置 `finished_at`。重复取消返回当前回执；已完成的终态回执保持不变。
采集 worker、缺失凭据或错误凭据返回 403。

非法 ID 返回 400 `COLLECTION_JOB_INVALID_ID`；不存在的 ID 返回 404
`COLLECTION_JOB_NOT_FOUND`；当前 API 实例未持有的活动回执返回 409
`COLLECTION_JOB_NOT_OWNED`；回执损坏或取消状态无法持久化返回 503
`COLLECTION_JOB_STATE_UNAVAILABLE`。取消写入失败时不会确认取消或提前释放容量。

默认总时限为 1800 秒，从提交开始计时，包含排队时间。服务构造参数
`CollectionHTTPServer(job_timeout_seconds=...)` 和
`CollectionJobManager(timeout_seconds=...)` 可以调整默认值，直接调用
`CollectionJobManager.submit(timeout_seconds=...)` 可以覆盖单项时限。必须使用有限正数；
HTTP 提交对象目前没有对应的时限字段。`deadline_at` 用于展示，实际计时使用单调时钟。

排队到期的任务直接进入 `timed_out`。运行中任务到期先进入 `cancelling`，实际退出后
进入 `timed_out`。`stop_reason` 区分 `cancelled` 与 `timed_out`，错误码分别为
`COLLECTION_JOB_CANCELLED` 与 `COLLECTION_JOB_TIMED_OUT`；`cancel_requested_at`
记录取消或超时停止请求的时间。先确认的停止原因保持不变。

停止采用协作检查：维护阶段、重放逐项处理、补抓请求及后续写入、Pipeline 阶段边界会
检查停止信号，可中断等待会提前唤醒，补抓 HTTP 超时受剩余预算约束。部分旧业务函数和
原生阻塞调用仍须等待返回；它们停留在 `cancelling` 期间可能继续完成当前调用。
取消或到期后的返回值不会被发布为 `completed`，已经确认的文件、审核记录和采集证据
保持原样。取消请求不保证撤销业务输出，客户端应持续轮询并核对部分结果。

## 持久化与生命周期

每个 API 实例有一个 FIFO 后台 worker，最多接纳 8 个排队、运行或停止中的任务。
提交响应和任务执行都以已写入的 queued 回执为前提。回执路径为：

```text
<active-data-root>/runtime/collection-jobs/<job_id>.json
```

`active-data-root` 使用配置中的 AVM 数据目录；未设置独立目录时沿用项目运行数据根。
通用任务回执、详情维护报告和近期缺口审计报告通过同目录临时文件、flush、fsync、原子
替换发布。其余报告生成器沿用各自的输出流程。已完成回执从磁盘读取，
不长期占用活动任务内存。不会清理历史回执、采集证据或失败的待写快照；同一维护操作
的报告在成功发布后由新报告替换。

API 关闭后拒绝新任务，并取消尚未开始执行的任务，包括已经被 worker 取出但尚未
标记 running 的任务。已经运行的工作允许在进程存活期间完成；关闭 API 不会强制杀死它。
worker 异常退出时会尝试持久化 `interrupted` 并关闭队列；线程启动失败也会尝试记录
`interrupted`。任何退出回执保存失败都会保留最后确认的字节，并在失去执行归属后按
未确认完成处理。重新打开队列时，未被当前实例持有的 queued/running/cancelling 回执
在查询时显示为 `interrupted`，原文件及时间戳保持不变，不自动重放可能已经写过数据的操作。

该队列只协调一个 API 实例内的后台操作。多个 API 进程或直接调用维护 CLI 不共享队列。
同一实例创建队列后不允许切换数据根；修改根路径需要重启 API。

监听器将 TLS handshake 放到各请求线程，握手超时为 5 秒，HTTP handler 的 socket
超时为 30 秒。维护工作不会占用监听线程。地区保存接口的读、合并、写入也使用共享
文件锁，防止并发请求丢失彼此提交的数据。

## 验证入口与剩余范围

使用锁定的开发依赖环境，从仓库根运行：

```text
python scripts/run_quality_tests.py --suite fast
python scripts/run_quality_tests.py --suite security
node --test scripts/tests/effective-code-lines.test.mjs
node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json
```

运行器将数据根和状态文件放到新的临时目录并关闭默认业务数据库。
fast 包含队列状态、取消与到期竞争、真实维护停止边界及路由源码检查；security 包含真实
loopback HTTP/TLS、回执查询和取消权限、写入失败保留和并发地区保存测试。

人工审核回执的默认 maintenance 分支、显式 async 分支和上表中的报告入口已接入同一个
队列。旧的人工审核状态文件和数据库表只保留为兼容查询/历史备份；不再由显式 async
提交创建独立 worker。其他同步查询/计算入口和全局 RuntimeState 封装仍需继续审查。
这里列出的接口完成迁移，不代表完整优化清单已经关闭。多机器发布及安装后运行验证仍按
用户要求延后。
