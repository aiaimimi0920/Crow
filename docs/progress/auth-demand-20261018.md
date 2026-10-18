# 离线认证抑制与 PC2 浏览器运行时恢复

## 问题与边界

NAS 原自动认证只使用 pending、挑战和停滞状态，未要求在线采集证据。
旧 requested/pc1_claimed 在采集端非正常退出后仍可能被 PC1 领取和展示。
现有 solver 心跳只证明认证组件在线，不能替代采集 worker 的运行证据。

现在生产 coordinator 注入 inspected-worker lease 门禁：PC2 controller
只有在 EngineController.inspect 检查 canonical Running worker 成功之后
才向 RestartMailbox poll。NAS 只读该数据库，30 秒内且非未来时间的 lease
有效；没有文件、无法读取、过期或 operator pause 均禁止自动认证。
认证挑战导致的 pause 不作为 operator pause，以免阻断必要的认证恢复。

当前 inspect 要求 seed/detail/analysis 各组存在，所以此策略偏保守；它不是
任意多节点、任意单阶段拓扑的通用注册协议，也不是每个任务都有进展的证明。
关机或停止采集后最多存在当前 lease 的剩余有效期，不承诺瞬时识别物理断电。

## 修改路径

- 创建、snapshot 下发、claim 都检查门禁；失效的自动 recovery 保留失败记录，
  旧 ID 不会在重新上线后复活。显式 manual request 不由自动门禁撤销。
- 公开 status 仅增加 automatic_auth_allowed 布尔，不增加恢复 ID 或目标泄露。
- PC1 watcher 在初始读取、启页、已有页聚焦和 seed 补提示前检查资格与同一 ID。
- 旧 trigger 在启动计划任务前复核；新注册 legacy watchdog 使用 Automatic
  参数，在实际入口再次复核。显式人工调用不强制走自动门禁。
- 现场仅注册了 FapaiFangNasAuthRecovery；安装路径的 watcher 和相关脚本
  已备份、更新并核对哈希。等待运行中的旧脚本自然退出，没有终止 PC1 浏览器。

## PC2 故障恢复

浏览器最初 CDP 超时后，被 controller watchdog 尝试重启；随后 Docker 的
restarting/Pid=0 与 containerd 中仍 RUNNING 的任务不一致，形成退出 137 循环。
OOMKilled=false 且 cgroup oom/oom_kill=0，不能把 137 解释成已确认 OOM。
最初 CDP 卡死的应用级根因仍未证明。

恢复时仅暂挂 collection controller，停止 exact browser ID 的自动重启，
核清旧 task/cgroup 进程后，以原镜像、完整配置和原 profile 创建新容器。
未停止 Docker daemon、整台机器或 PC1 人工认证浏览器。旧容器保留。
修正 active.json 内落后的 browser image 指针，使其与实际原镜像一致。

新 browser ID 为 b2ebcf48ebd34dd59c1b9a932005fecd98d70cbf351a7027172162ba7056a933。
CDP、health 及 80 秒稳定窗口通过，后续复查仍 healthy、restart_count=0。
此前的收尾调度候选随后上线，seed ID 为
e1abe2cc6bceb4cdb8ff1d42e47d7cac5f99cfdcbd7d22dbca5e2db07e483a4f，
源码哈希、healthy、breadth_first、parallel_sorts 和 controller authority 均确认。

## 验证和部署

- 本地受影响认证、权限、HTTP、PowerShell 展示路径：120 passed。
- NAS 隔离候选环境：27 passed；不连接生产数据库执行测试。
- effective-lines checker：19 passed；ratchet 无超过 500 有效行的文件。
- Ruff 相关检查、PowerShell 解析、git diff --check 通过。
- NAS API exact-ID 替换完成，五个源文件哈希核验；保留旧容器。
  CROW_ENGINE_CONTROL_ROOT 显式指向已有共享控制目录，不迁移数据。
- 部署后从实际共享 lease 只读验证受控时间：30 秒有效，31 秒无效，未来时间拒绝。
  没有实际关机 PC2 来做破坏性演练；回归验证覆盖旧请求撤销和重新上线不复活。
- 现场 PC2 已在线，NAS automatic_auth_allowed=true 且存在待认证请求是允许的；
  不以本修复宣称账号已登录、挑战已通过或滨城已完成。

回执和备份索引位于本次临时证据目录 crow-closure-20261018。
未提交或推送 Git，未清空数据库、任务页码、cookies 或浏览器 profile。
