# PC1 认证任务：用途、频率、无控制台启动和同步结果

核查时间：2026-09-27 18:45 UTC。代码基于 f891eaf70；本轮变更尚未提交。

## 1. 这个脚本做什么

FapaiFangNasAuthRecovery 定时运行 watch-pc1-nas-auth-recovery.ps1，向 NAS 查询认证恢复请求。没有需要本机处理的请求时退出；需要恢复时复用专用人工认证浏览器，检查会话并发布供 PC2 恢复采集使用的认证快照。它不负责商品 AI 分析，也不会每分钟重新登录或重启浏览器。

## 2. 为什么每分钟启动

注册脚本的默认 IntervalMinutes 为 1，用于及时发现 NAS 发来的恢复请求。它采用短任务轮询；每分钟启动不表示每分钟认证失败。IgnoreNew 防止同一任务重叠，单次执行上限仍为 10 分钟。退出码 0 只说明脚本执行正常；认证是否成功应检查 NAS 恢复结果、PC2 接收状态及采集计数。

## 3. 已添加并部署无控制台启动模式

register-pc1-nas-auth-recovery-task.ps1 新增 -LauncherMode NoConsole，且默认为 NoConsole；仅需要主动调试时显式使用 -LauncherMode Console。原有 API、CA、Python、浏览器及配置参数保持不变。

默认任务入口现为 pythonw.exe -I，调用 tools/background_task_launcher.py，再以 CREATE_NO_WINDOW 启动实际 PowerShell 子进程。启动器等待子进程并返回其退出码，保留计划任务的重叠控制及超时设置；不会记录命令行、Cookie 或原始输出。诊断状态存放在安装目录 FPFData/runtime/pc1-nas-auth-task.json。部署脚本也已纳入新启动器。

此前直接启动 powershell.exe，即使带 -WindowStyle Hidden，终端宿主仍可能在参数生效之前出现窗口。旧监控连续捕获了 11:11 至 11:14（UTC-07）每分钟一次的对应 PowerShell / WindowsTerminal 可见窗口；其父进程为 Task Scheduler 服务。未证实键盘焦点被抢占。

安装目录：C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop。
回滚备份：该目录 backups/no-console-task-20260927-114114，包含原任务 XML 和旧注册脚本。
已重新注册并启动任务；注册脚本和启动器的仓库/安装文件 SHA-256 一致，原运行配置保持不变。未重启人工认证浏览器。桌面 EXE 没有变化，沿用本轮此前已验证、重启及修复 Crow.lnk 的版本。

实际观察：2026-09-27 18:41:14.934 至 18:44:15.132 UTC，连续 180 秒窗口 show / foreground 钩子工作正常，控制台候选窗口事件为 0。全系统进程启动 WMI 订阅不可用；此结论基于窗口钩子，不依赖该订阅。期间立即执行及后续周期运行已观察到退出码 0，例如 18:41:21 至 18:41:29、18:43:24 至 18:43:54；后续 18:44:23 至 18:44:58 同样退出 0。有限观察期内未再出现该任务的控制台弹窗，不推断所有其他程序都不会弹窗。

监控证据：artifacts/no-console-task-watch-2026-09-27T18-41-11-762Z/events.jsonl。

验证：启动器及 PC1 transport 测试 15 passed；部署 bundle 测试 6 passed；有效行 checker 测试 19 passed；ratchet 扫描 1384 文件、无超过 500 有效行文件；Ruff 选定规则与格式检查通过；最终 git diff --check 通过。未重复无关全量测试。

## 4. 认证同步能否成功

可以，已经有成功证据，不能说每次都失败。17:31:43 UTC 的 PC2 receiver 记录 recovery_confirmed，接收 151 个 Cookie；对应 NAS 恢复结果为 succeeded / captured_count_advanced。

18:44:45 UTC 刷新的 NAS 状态中，最近一次已完成恢复 auth-recovery-33c50686eb0e4603bf0b6fd4fd4ee5cf 仍为 succeeded / captured_count_advanced，详情计数由 155333 增至 155358（增加 25），结束时间约 18:24:12 UTC。此时详情总数已达 155472，链接总数 330938，AI 完成数 121084。

同时，新一轮 auth-recovery-e055b996b8904f9ab2b42963f66c7113 为 pc1_claimed，尚无本轮快照及 PC2 接收时间，不能宣布这一轮也成功。另一个 cookie_snapshot_refresh 状态保留失败：cookie_snapshot_candidate_unhealthy，3/3 次尝试，53 个 Cookie，在两个抽样列表页均遇到 captcha。它属于不同状态记录，不能覆盖上述已经完成的恢复成功事实。

结论：认证同步链路有实际成功及恢复采集的证据，但站点会再次触发挑战，部分候选快照检查也会失败；没有完整历史台账，不能提供成功率或承诺每次成功。AI 数量未增长是另一条业务路径的问题，不能仅由认证任务退出码判断；此前已定位正式模型请求的 insufficient_user_quota，此次未重新验证 AI 上游恢复。
