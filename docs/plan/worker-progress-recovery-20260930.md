# PC2 worker 停滞恢复：2026-09-30

## 本次闭环与边界

本次修复的是“worker 进程仍在，但采集心跳长时间不更新，现有浏览器
watchdog 不会恢复它”的运行时缺口。没有修改采集数据、认证状态、模型池
资格或限流策略，也没有把 worker 恢复等同于整个采集业务恢复。

开始检查时，`pc2-detail-1`、`pc2-detail-2`、`pc2-seed-1` 的心跳分别
过期约 60 小时、12 小时、85 分钟。Docker 健康检查持续报告：

```text
worker progress heartbeat is stale or stopped
```

两个详情进程处于内核 `epoll_wait`，链接进程处于 `poll`。没有取得 Python
调用栈，因此尚不能精确断言具体哪个浏览器或网络调用导致原始挂起。

## 实现

- `tools/pc2_worker_heartbeat.py`：在 worker 自身环境中只读心跳，核对
  worker ID、存活 PID、阶段与时间；使用容器时钟计算年龄。
- `tools/pc2_worker_watchdog.py`：仅处理 canonical、仍运行且 unhealthy
  的 worker；心跳超过配置阈值（至少 900 秒），并在 120 秒观察期内未
  改变，才允许进入恢复。
- 重启前再次检查 exact container ID、启动时间、健康状态与心跳；
  一轮只恢复一个 worker，不重启共享浏览器或停止中的 worker。
- 默认每 30 秒检查；每个容器滚动 24 小时最多重启 3 次，最短冷却
  600 秒并指数退避。controller 重启及短暂 healthy 不清空次数。
- 重启前先持久化回执；结果不明或失败时要求核对，不自动重放。
- 接入 controller 的现有 operation lock；存在 settings、restart 或
  release 未结算操作时不执行恢复。NAS 调用失败不会挡住前置 worker 检查。

## 验证

修改前，新增 controller 回归因缺少 `worker_watchdog` 参数失败；修改后：

- 新增 focused 回归：29 passed。
- worker、controller、browser/progress watchdog、状态保留和 engine controller
  相邻边界：77 passed，1 skipped。跳过项是 Windows 无法执行的 Linux flock。
- PC2 候选环境真实执行 Linux operation lock 互斥检查通过，并验证 controller
  接入与只读生产探测；准确识别上述三个挂起 worker。
- Ruff check、Ruff format、git diff check 通过。
- 有效行检查器：19 passed；ratchet 扫描 1397 文件，无超过 500 有效行的文件。

这些是本次 worker 恢复边界的验证，不代表全量 fast/security/PostgreSQL 或
桌面产品套件已重新执行。

## PC2 部署与现场结果

部署目录：`/srv/apps/fapaifang-worker/releases/20260930-worker-watchdog/`。
目录包含 candidate、`manifest.json`、`backup/`、`activation.json` 和
`verification.json`。恢复旧 controller 文件即可停用新增自动恢复；新增
模块可保留为未引用文件，无需删除数据或模块。

仅安装两个新模块并在已安装 controller 中加入调用；保留其原有回执处理，
未用 checkout 整文件覆盖旧安装中的其他行为。三个安装文件 SHA-256 核对通过。

首次激活因验收脚本直接比较 Docker mounts 数组顺序而误判，并已自动回滚。
只读复核证明 Docker 返回顺序不稳定、挂载集合不变；按 Destination 排序后
重新激活通过。没有省略配置、镜像或挂载校验。

2026-09-30 UTC 现场自动恢复记录：

| Worker | 新启动时间 | 结果 |
| --- | --- | --- |
| pc2-detail-1 | 11:57:03 | healthy，心跳持续更新 |
| pc2-detail-2 | 11:57:40 | healthy，心跳持续更新 |
| pc2-seed-1 | 11:58:18 | healthy，心跳持续更新 |

三者各由新 watchdog 恢复 1 次，保持原容器 ID、镜像、配置与挂载。
11:59:55 的观察窗口完成时三者已持续健康超过 60 秒。共享浏览器仍是原容器，
启动时间保持 09:49:16，未被本次恢复重启。12:03 的再次检查仍全部健康。

本机观察台未改动桌面二进制；已核对安装 EXE 与现有 release EXE 的 SHA-256
一致，重启 Crow 并刷新、验证 `Crow.lnk`，保留 runtime 配置。未重启人工认证浏览器。

## 尚未解决的业务阻塞

12:03 UTC 时 worker 已恢复，但详情仍报告 `captcha_solver_manual_required`，
认证恢复状态仍为 `pc1_claimed`。详情计数保持 163497；AI 完成数从早期
121721 到 121725，但归档仍受模型池冷却限制，不能声称持续吞吐已恢复。

只读网关日志补充确认了对应请求的 `403 / insufficient_user_quota`，以及
部分模型的 `503 / model_not_found`。12:03 的模型池全局冷却剩余约 42 分钟。
没有清空冷却、购买额度、修改网关或绕过模型资格。后续需要完成真实人工
认证，以及选择有可用额度和通道的非 GPT 归档后端，再以实际业务计数验证。

脱敏的本地诊断和部署脚本保存在工作临时区的
`crow-diagnostic-20260930/`，包括 `worker-hang-before.jsonl`、
`runtime-after-recovery.jsonl` 和 `gateway-quota-sanitized.log`。
