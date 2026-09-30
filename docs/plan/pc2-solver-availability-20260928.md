# PC2 自动 solver 间歇性不可用修复

本次接续对话 `01a0e2e6-07ca-7242-b1bd-58f3ffb006fd`，检查实际安装配置、
PC2 日志、NAS 接口和恢复状态机。下文时间均为 UTC。

已修复并部署两处确定性故障：浏览器容器缺少验证码状态上报凭据，以及旧的
Cookie 恢复流程主动重启浏览器。部署后已经观察到一次真实的自动滑块解锁、
NAS 确认和后续详情采集增长。网站仍会拒绝部分拖动，单次失败和正常冷却仍然存在。

## 为什么会时好时坏

1. 浏览器容器保留了旧部署配置，只有 `FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE`，
   缺少 `FAPAI_COLLECTION_WORKER_TOKEN_FILE`。两者负责不同接口：Cookie 恢复、
   认证完成和冷却后恢复使用 recovery 凭据，`/api/report_captcha` 使用 worker
   凭据。因此，恢复心跳和 Cookie 同步能够正常工作，solver 失败、阻塞和冷却的
   上报却持续收到 HTTP 403 `COLLECTION_WORKER_FORBIDDEN`，PC2 与 NAS 的状态
   无法按预期同步。旧健康检查只检查浏览器、进程和心跳，未能发现这个配置缺口。

2. 无 scope 的旧 Cookie 恢复流程在导入后返回 `restart_requested`。
   `tools/pc2_solver_loop_control.py` 收到它后执行 `SystemExit(75)`，导致浏览器
   容器整体重启，共用 CDP 的 solver 和采集连接随之中断。日志中
   `00:38:24.540` 和 `01:47:50.000` 的恢复任务都触发了这条路径，约 12 秒后
   才出现后续确认。已有 scope 的流程不要求这个重启。

3. 另有正常的重试与冷却机制：当前配置连续失败 10 次后冷却 180 秒，再恢复尝试。
   部署前约 6 小时的样本中有约 209 次失败，多数为 `challenge_retry_exhausted`。
   日志能确认已找到滑块、聚焦正确窗口、校验 X11/CDP 坐标并执行鼠标拖动，随后
   网站返回验证码拒绝。不能把这些网站拒绝都归因于程序离线，也不能承诺修复后
   每个验证码都一次通过。本次没有修改拖动算法、浏览器身份、重试阈值或安全校验。

## 改动和部署

`tools/pc2_linux_healthcheck.py` 新增两种出站凭据的本地检查，复用实际请求的
`request_headers`，拒绝缺失、不可读以及两种角色共用同一凭据的配置。
健康检查不会提交验证码状态；实际 NAS 是否接受凭据另做在线验证。

`tools/pc2_auth_recovery.py` 的无 scope 恢复改为在现有浏览器中完成导入和验证。
保留 NAS 当前使用的 `restarting` 协议阶段，但不再主动请求进程退出；NAS 返回
`verifying` 时明确记录 `recovery_verifying`，继续等待真实采集进展。
快照摘要、关键会话 Cookie、scope 探测及 NAS 的采集进展确认要求均保留。

同时更新 PC2 环境示例和部署手册，明确浏览器也必须配置两种独立凭据。
worker 凭据直接使用 PC2 已有的 `/data/secrets/collection-worker-20260927.token`，
未生成或替换任何凭据。

PC2 于 `2026-09-28T03:16:52.077633431Z` 启动已验证的候选容器：

- 新容器：`72d56087024eff11dd7dfc26d7d94f05bbb92a81adcd448563570bf2c62fba14`。
- 镜像：`sha256:690e3e867d2d2455cea5f3fcbea9c2bebde469e9b743e941a1f5f70e6a5ea263`。
- 旧容器：`e74597aebc9b726cb8e2113d9cbbbf75bc4f74d96e96a35cac9237d0adfd2d39`，
  已停止并保留为 `fapaifang-pc2-browser-solver-before-solver-readiness-20260928`。
- 私有部署记录：`/srv/apps/fapaifang-worker/releases/20260928-solver-readiness-final/`。

部署前检查发现多个停止的备份容器共享 Compose 标签，因此只按精确容器 ID
替换 canonical browser，没有执行 service-wide Compose recreation。
挂载、端口、设备、用户组、网络和重启策略均与原容器比较；worker/recovery 凭据
与 CA 在切换前后按摘要核验，字节未变。共享 `runtime.env` 已备份并补齐 worker
凭据路径。其他 PC2 worker 和 NAS 容器没有被替换或重启。

候选镜像以实际安装版本为基础。已安装的 healthcheck 在 worker 模式上与仓库
存在既有差异，所以仅将新凭据检查插入该版本，保留其 worker 实现；未用整个本地
文件覆盖。安装后的两个文件 SHA-256 与候选记录一致：

```text
tools/pc2_linux_healthcheck.py
775351b75763ff9bf37517d1bfdd64f0b2d605b531fcdc162de9bb28d65854a5

tools/pc2_auth_recovery.py
c6ca050cfcf9b580cc29dbe9166d392494471c61e0e5d28811d45664bfc5a14b
```

切换前私下导出 156 个 Taobao Cookie，随后通过生产 importer 恢复。
即时读回有 154 个 Cookie identity，7 个关键会话 identity 全部保留；非会话
Cookie 会被页面正常更新。浏览器 profile 和数据挂载保留，未清空 Cookie、
数据库或用户数据。PC1 人工认证浏览器未重启。

## 在线验证

部署前后使用相同的无状态探测：发送故意不合法的 JSON `[`，让通过鉴权的请求
在解析阶段停止，避免提交虚假的验证码结果。`/api/report_captcha` 从部署前的
403 变为部署后的 400 `AVM_INVALID_JSON`，且真实安装环境自动附带 worker header。
`/api/collection/auth/complete` 也通过鉴权并在 JSON 解析阶段停止。

部署后的真实自动流程包含以下连续证据：

- `03:20:13.948` 找到滑块，`03:20:16.112` 完成窗口坐标校验并自动拖动 256 px。
- `03:20:20.433` 页面返回 `sliderGone=true`、`challengeGone=true`、
  `hasError=false`，solver 记录 `[OK] Verified: Captcha solved!`。
- `03:20:20.434` 记录 `local_solver_end`、`success=true`；之前同一轮有 3 次
  网站拒绝，随后第 4 次成功。
- `03:20:28.126` 的 `auth_complete_result` 为 `confirmed=true`、
  `auth_state_confirmed=true`、`scope=detail`、`scope_paused=false`。
- `03:22:47` NAS 两个 scope 均无待处理 challenge；链接数从部署前 `03:14:43`
  的 332,116 增至 332,169，详情数从 156,746 增至 156,777。该窗口的计数增长
  包含部署前后的正常业务，未将所有增量归因于本次自动解锁。

`03:22:43` 新浏览器为 healthy，重启计数为 0，solver 心跳回到 polling。
详情 worker 2、3 和链接 worker 均有真实批次完成记录。

本地 Crow 使用既有已验证的桌面构建，EXE SHA-256 为
`B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B`。
已正常关闭旧 PID 51360，启动安装目录下的 PID 39628，运行配置摘要未变；
官方脚本已更新 `Crow.lnk` 并验证目标、工作目录和图标。
第一次 UI 检查发生在页面仍初始化时；等待控件就绪后，实际调用刷新按钮成功，
状态、计数与列表均加载。`03:22:03` 的截图已目视检查，显示“运行中”。

本地证据：

- `artifacts/pc2-solver-contract-20260928.txt`：部署前接口契约探测。
- `artifacts/pc2-solver-audit-20260928.jsonl`：部署前日志审计。
- `artifacts/crow-solver-repair-20260928/verification.json`：安装版 UI 检查。
- `artifacts/crow-solver-repair-20260928/installed-crow-after-refresh.png`：实际窗口截图。

## 回归和检查范围

凭据、健康检查及冷却相关定向组：67 passed，12.63 秒。
覆盖 `test_pc2_solver_api_readiness.py`、`test_pc2_solver_watchdog.py`、
`test_pc2_linux_deployment.py`、`test_collection_api_credentials.py`、
`test_collection_node_credentials.py` 和 `test_pc2_solver_cooldown_recovery.py`。
新健康检查回归在修复前为 4 failed / 1 passed。

Cookie 恢复相关定向组：56 passed，12.49 秒。
覆盖 `test_pc2_auth_recovery.py`、`test_pc2_detail_auth_probe.py`、
`test_nas_auth_recovery.py`、`test_stage_auth_recovery.py` 和
`test_pc2_pending_lifecycle.py`。无 scope 的两个入口回归在修复前均失败，
修复后验证只导入一次、不请求重启，并继续等待 NAS 确认业务进展。

两个测试组属于相继完成的改动批次，不合称全套测试通过。
官方 Ruff 格式和选定 CI lint 规则通过；最后的 import 排序调整未改变行为，
最终镜像在该调整后构建。候选镜像另通过 6 项离线凭据/恢复检查。
有效行检查测试 19 passed，ratchet 检查 1,389 个文件，无文件超过 500 有效行。
其测试 fixture 修复了 Windows CRLF/BOM 规范化摘要差异；未改阈值、baseline 或排除项。
`git diff --check` 通过。没有重复运行历史全套、security 或 PostgreSQL 套件。

## 接续验证与运行边界

接续对话 `01a0e5ca-4364-7be3-8bf1-00ddf47027d7` 后，于
`2026-09-28T03:59:48Z` 重新读取 PC2 实际容器及安装文件，确认容器 ID、
启动时间和两个安装文件 SHA-256 与上述部署记录一致，healthy，重启次数为 0。
`04:00:21Z` 心跳处于 polling，距最近更新时间约 1.9 秒，恢复状态中的
失败计数、冷却期限和待确认恢复请求均已清空。

已从同一容器的原始日志核实以下自然发生的事件：

- `03:33:02.466Z` 无 scope Cookie 恢复进入 `recovery_verifying`。
  NAS 保留的相同 recovery ID 结果为 succeeded，原因 `captured_count_advanced`，
  详情数由 156,792 增至 156,794。整个过程没有重启浏览器容器。
- `03:33:59.849Z` 连续失败 10 次，进入 180 秒冷却。
- `03:37:00.348Z` 冷却结束；`03:37:02.367Z` NAS 返回
  `resume_after_cooldown`、`auth_state_confirmed=true`、`scope_paused=false`。
  这证明本轮冷却已自动退出，并完成 NAS 恢复确认。

这轮没有 `node_solver_blocked_report` 事件，也没有在原观察窗口内发生恢复后的
新滑块尝试，因此不能宣称“阻塞上报确认 -> 冷却 -> 再次拖动”的全部线上分支均已
覆盖。原观察器只有先看到阻塞上报才会填充汇总中的恢复时间，所以其汇总中的 null
不能用于否认原始日志中实际存在的 `collection_resume_confirmed`。
阻塞上报分支仍以既有定向回归和实际接口鉴权探测为证据，不伪造线上挑战补齐结果。

`04:01:42Z` NAS 详情总数为 156,917，链接总数为 332,972；seed 未暂停。
detail 正在处理一轮新的验证码（`pause_reason=captcha_solver`、
`last_status=running`、`node_solver_blocked=false`），此刻没有活动 Cookie
恢复任务。该新挑战未在本报告中认定为成功；正常网站挑战仍会暂时暂停详情采集。

本轮只补运行核验和报告，没有更改产品代码、重新部署或再次重启应用。
先前的定向测试结果按原批次保留，没有合并成全套验收；当前 `git diff --check`
通过。最终容器和冷却日志证据见
`artifacts/crow-solver-repair-20260928/final-runtime-check.txt`。

## 回退与其他问题

另观察到部署前已存在的 detail-1 unhealthy，以及部分 AI worker 报
`detail_worker_llm_unavailable`；其他详情 worker 持续产出。这些独立问题没有
纳入此次 solver 修复，也没有据此宣称整套采集/AI 系统全部健康。

如需回退，使用上述私有 release 目录中的 `before.json`、`runtime-before.env`、
`preflight.json`、`activation.json` 和会话备份记录。只停止新浏览器的精确 ID，
恢复旧容器的 canonical 名称及对应 runtime 配置，然后恢复已保存会话。
保留新容器供排查，不恢复数据库，不按共享 Compose 标签批量重建。
回退会同时恢复这两处已确认的旧故障。

仓库基于 `master` / `79f45d4af561630abc414f6bab289952fb864069`；改动尚未提交或推送。
