# 挑战同步、分析重试与静默运行：2026-09-27

最终运行核查：2026-09-27 18:02 UTC。本轮代码基于 f891eaf70，修改尚未提交。

## 1. 挑战已同步，但详情进程恢复存在延迟

本次用户认证快照确实到达 PC2：

- 17:31:30 UTC：receiver 记录 restart_requested，151 个 Cookie。
- 17:31:43 UTC：receiver 记录 recovery_confirmed，恢复任务 auth-recovery-3dc678f706e54112bb1da3fbd1bcd710。
- 快照 SHA-256：354557931bb82a6417cf4f6410de65e17da60240071622d1c8d1362f7519fe26。
- 后续 NAS 标记 succeeded / captured_count_advanced，验证计数由 155151 增至 155156。
- 17:35:42 UTC：列表 worker 成功采集 20 页、80 个已有商品出现记录。新增唯一商品为 0，因此仅看商品链接总量会误以为没有工作。
- 17:49 UTC：详情总数 155198；18:02 UTC：链接 330938、详情 155281。

发现的恢复延迟在详情 worker 的批次等待：挑战失败后固定等待 900 秒，期间不重新查询 NAS 认证状态。即使 Cookie 已导入、挑战已解除，它仍可能等待剩余退避时间。

修复：新增 tools/detail_worker_wait.py，并由 tools/detail_worker_loop.py 在批次结束后调用。挑战相关长退避每 30 秒查询一次 NAS；只有全局明确未暂停、详情明确未暂停、无人工认证要求且无挑战 ID 时，才提前继续下一周期并刷新运行上下文。网络错误、未知状态、人工要求、新挑战、分析 worker 和非挑战退避均保留原等待。不会强制清除服务器挑战或伪造认证成功。

该修复已部署到 3 个详情 worker，保留原配置和旧容器。新进程已出现成功采集：detail-1 一批完成 6 项，detail-3 一批完成 1 项。随后仍可能遇到新的站点挑战；本次不承诺站点永不再次验证。新的提前唤醒逻辑通过确定性测试和候选镜像测试，未人为制造线上挑战来测试唤醒。

镜像：sha256:63f20f81a911d6e990d3a482f9997875c2e74cdc77b9037aec5f3b0213307530。
新容器：2ca2cdf57dbb、a18d6de3dee1、73d3b5f096a1。
PC2 私有回滚与回执目录：/srv/apps/fapaifang-worker/releases/20260927-auth-wakeup/。
旧容器以各自的 -before-auth-wakeup-20260927 名称保留。切换前核对了 Compose 标签及旧容器精确 ID，未执行服务级 Compose 重建。此轮没有主动重启 PC1 人工认证浏览器、PC2 浏览器或 NAS。

## 2. AI worker 没有被一次失败永久关闭

4 个 PC2 分析进程一直在运行，预检失败后返回当前批次，再按 60 秒周期重试。单模型业务请求失败会使其暂时阻止 900 秒；资格池还会对服务端限制退避。它们不是失败一次就退出。

本次从 PC2 发出的最小 deepseek-v4-flash 请求曾返回 HTTP 200。但正式分析请求随后仍失败，资格池再次进入暂时不可用状态。

这次已读取本机 CLIProxyAPI 的对应上游错误日志，找到比外层 503 更具体的原因：17:35 UTC，deepseek-v4-flash 的正式请求被上游返回 HTTP 403 / insufficient_user_quota，消息为“预扣费额度失败”。上游报告的剩余额度不足以覆盖该请求的预扣额度，随后其他候选路由返回 model_availability_filtered。小请求可调用不能证明较大商品文本的正式分析请求可支付并完成。

18:02 UTC 的 AI 完成数仍为 121084。本轮未修改 CPA、充值、替换凭据、降低模型资格要求或清空冷却。已询问用户具体恢复的模型或渠道；若恢复的是另一模型，需验证其资格与真实商品分析后再切换。当前未收到该信息，AI 恢复尚未验收。

## 3. 后台 PowerShell 静默运行

当前本机 FapaiFangNasAuthRecovery 顶层任务此前已有 -WindowStyle Hidden，桌面 Rust helper 也已有 CREATE_NO_WINDOW。无法仅凭源码断定此前某一次弹窗的具体进程。

本次补齐两个遗漏范围：

- 恢复 watcher 启动浏览器辅助脚本、认证检查子 PowerShell 时显式设置 -WindowStyle Hidden。
- 连续采集、数据同步、PostgreSQL 备份及健康检查、登录 watchdog、登录恢复 monitor 的任务注册入口均设置隐藏窗口，防止这些后台任务以后注册时创建可见控制台。

本机已安装的相关脚本已备份并覆盖核验，实际存在并更新的文件为恢复 watcher 和 watchdog 任务注册器；没有凭空注册其他未使用任务。当前恢复任务保持启用，更新后的实际运行退出码为 0。检查时未发现可见的 powershell/pwsh 主窗口；这是一份运行快照，不是对所有未来第三方脚本行为的保证。

本代理后续启动本地诊断进程使用 windowsHide=true，PowerShell 入口同时使用隐藏窗口参数。人工认证浏览器的可见性保留，未修改其登录配置。

本机脚本回滚目录：%LOCALAPPDATA%/FapaiFangCollectorDesktop/backups/silent-scripts-20260927-105700/。

## 验证与交付

- 挑战恢复等待、详情 worker、PC1 watcher 相关测试：87 passed，39.07 秒。
- 新 Python 文件 Ruff 检查及格式化通过。
- 7 个修改的 PowerShell 文件语法解析通过。
- 有效代码行测试：19 passed；ratchet：1382 文件，无超过 500 有效行的文件。
- PC2 候选镜像无网络预检、安装哈希、配置保留及三个 worker 健康检查通过；随后观察到成功业务采集。
- git diff --check 通过。未重复全量历史测试。
- 本机 Crow 使用原已验证 EXE 哈希 B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B，已正常重启并更新 Crow.lnk；新 PID 39736。此轮无需新桌面二进制。

已确认挑战同步成功，已修复详情恢复等待和后台控制台参数遗漏。AI 仍有上游额度阻塞，不能宣布三项全部完成。
