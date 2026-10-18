# PC2 solver 诊断与可重试挑战分类修复

## 范围与结论边界

2026-10-18，本轮针对 PC2 采集停在挑战验证的问题检查当前容器、自然运行日志与 CDP 响应。没有清空浏览器 Profile、Cookie、凭据或数据库，没有修改输入安全阈值、成功判定、重试预算，也没有提交或推送 Git。

基础设施健康与业务成功分开验收。现有采集停在认证暂停路径；正常运行的浏览器和 solver 不代表挑战已通过。本轮修复了确定的分类缺陷及诊断缺口，不宣称已解除来源网站的验证拒绝。

## 运行证据

- 初始 canonical browser 为 `b2ebcf48ebd34dd59c1b9a932005fecd98d70cbf351a7027172162ba7056a933`，healthy、RestartCount 0，CDP 可连接。
- 07:55:20–08:10:20 UTC 固定窗口：16 次完整配对 solver 调用均失败。13 次调用未完成拖动；其中 12 次系统光标已到达映射点，但未取得 DOM pointer-hit 成功证据。另 4 次调用共记录 11 次完成拖动，仍无验证成功；调用数、拖动数与验证轮询数不是同一分母。
- 后续自然网络观察：12 次 slide 请求 HTTP 200，固定字段投影为 `root.code=300`、`root.result.code=300`、`root.success=true`。外层 success 不等于业务挑战通过。结合页面 challenge 未消失且 has_error=true，可确认当前验证失败；不能由 300 推断 IP、Cookie、轨迹或特定风控原因。
- 现有 pointer probe 没有监听 mouseup，因此最后一次 mousemove.buttons=1 不能证明服务端响应发生于松手之前。
- 08:30:24 UTC，新增诊断捕获 `pointer_failure / target_changed / target`。这表示按下前目标位置已变化，拒绝拖动符合原有安全约束；不能用这一条反推此前 13 次失败全部同因。
- 用户反馈同一浏览器手动也无法通过，随后明确确认有自动操作干扰。需要独占窗口验证，不能视作隔离对照；也不能否认用户观察到的手动失败结果。

## 修改

1. `src/captcha_os_target.py` 在原有失败分支输出固定枚举原因，区分 native_focus、snapshot、event_buttons、event_serial、event_age；不改变失败返回值或输入许可条件。
2. `tools/pc2_solver_diagnostics.py` 加入白名单 pointer_failure 事件。未知值归 unknown，按阶段限流；不记录页面正文、URL、selector、Cookie、token 或异常原文。
3. `src/captcha_preflight.py` 统一错误 widget 可见性判断。旧逻辑使用首个 querySelector + offsetParent，而 explicitFailure 使用遍历全部节点的共享可见性规则，两者不一致。修复隐藏首节点、fixed 可见节点、透明节点三类错误分类，保留 loginRequired 否决，不放宽认证成功条件。

## 验证

- 三个可见性反例在旧代码下均失败；修复后 retryable suite 8 passed。
- 本地相关边界测试：147 passed、1 skipped；随后新增 producer→logger/filter→event 的 5 个分支测试，target suite 21 passed。它们是不同测试阶段，不合并称一次全套运行。
- 最终 PC2 候选在 network-none、无生产 Profile/凭据挂载的独立容器内：153 passed。测试依赖只安装到 tmpfs，不进入生产镜像。
- effective-line checker 自测 19 passed；最终 ratchet 扫描 1566 文件，无超过 500 effective lines 的文件；git diff --check 通过。
- 诊断相关四文件 Ruff 通过。preflight 原有 8 项、retryable 测试原有 1 项 Ruff findings 与 HEAD 对比完全相同，无新增；不能将这两文件报告为完整 Ruff 零告警。
- 独立只读审查未发现成功条件放宽、敏感日志泄漏或 scope 漂移；建议的真实日志接线测试已补齐。

## 发布与回滚

本轮发布采用固定原 browser image 加单层 scoped COPY。原基底已有 124 层，最初多 COPY 构建报 max depth exceeded；失败镜像未激活。没有为绕过限制删除镜像、清理运行数据或改用未经核验的旧版本。

- 诊断版 image：`sha256:2e2e2d01ef1dffcf4840908758ca8dfcd2a80ce27d9639490f3a5e03e4ac2b35`。
- 诊断版 container：`9f59e81813c8d37dfdae5857662af86ba79b2dce01093ac613bf4e717dfa1f3c`；安装 hash、CDP、80 秒稳定窗口通过。
- 最终修复候选 image：`sha256:abf0716b83f8b00bcf8b1569d78c650160664da3619db7bf2b62fa6cc7fda055`。
- 最终已激活 container：`d8b463835f2755041ff7d50b4635147571b0cc785656ddbdbb47b3b96ee41791`。独立复核安装源码 hash、两个 image authority、healthy、RestartCount 0 和 controller active 均通过。seed/detail 四个实例的 ID 与 StartedAt 未变化。
- 远端私有发布目录：`/srv/apps/fapaifang-worker/releases/solver-fix-20261018`，包含 before、authority 备份、manifest、tests.log、verified.json 及激活后 activation.json。
- 替换仅限 canonical browser 的 exact ID；旧容器停机保留。保留原 env、mounts、devices、安全配置与 Profile，验证旧 cgroup 无残留后才启动替代容器；同时更新 active 和 browser compose 的 immutable image authority。
- 不涉及 PC1 桌面或人工认证浏览器，不因此重建或重启桌面应用。08:33:44–08:35:24 UTC 的新容器日志仍出现完成拖动后 challenge_retry_exhausted，没有 verified 成功；部署成功不等于来源挑战恢复。

## 未完成验收

来源网站挑战恢复通过、seed/detail 持续产出尚未证明。历史按下前失败尚未全部归因；当前可见性缺陷并不能解释所有业务 code=300。需要保留该边界，不能用健康检查、测试通过或输入完成代替业务恢复。

## 后续切片：无自动输入干扰的限时人工窗口

用户确认手动验证期间有自动操作干扰。只读审查发现现有 manual_only 仅是 scoped 执行门禁：既不能取消已开始的 child，也不能阻止门禁之前的 pending control / tab compaction，因此不能充当独占窗口。

新增 `tools/pc2_solver_manual_window.py`，在 startup prepare 和每轮任何浏览器控制之前检查本机原子写入的限时请求。当前 iteration 和 child 自然结束后才 ACK，不在鼠标按下时强杀；持续健康心跳、不调用 NAS manual report、不操作 Cookie/Profile。到期恢复，最大 600 秒。配置默认值解析移回 `pc2_solver_config.py`，保留 None 与显式零值语义，使 loop 继续满足有效行数约束。

请求与 ACK 均在既有 bridge-control 内。操作者必须验证匹配的随机 request_id、同一 expires_at 且尚未过期；旧 ACK 文件不是永久有效的暂停凭证。请求必须原子写入；使请求过期是显式取消，损坏或不可读也会退出暂停，不能在人工期间原地修改请求。

此 helper 只暂停 solver，不会冻结 host watchdog。诊断运维脚本额外临时停止 controller、持有 operation.lock，等待 ACK 后才提示人工验证，并在到期/取消/finally 中恢复 controller。不停止浏览器、seed/detail 或 PC1。不能把 helper ACK 单独称为整个系统的全局锁。

验证：本地窗口及相关 loop 边界 67 passed；最终候选隔离容器 220 passed；新增 helper/config/loop/tests Ruff 通过，ratchet 1568 文件、无超过 500 effective lines。初次窗口候选测试因漏打包测试 helper 导致收集失败，未激活；补齐 helper、修复行数门禁后重新构建并通过。该结果不与此前 153 项候选混为一次运行。

窗口候选 image：`sha256:8fe6c01e3e0c548e44a9519600cec451f115bc5de8649fd1680de0267b7a0ea2`；发布与回滚目录 `/srv/apps/fapaifang-worker/releases/solver-window-r2-20261018`。实际激活和人工窗口结果以其中 activation.json、manual-window-receipt.json 及后续运行检查为准。

08:47 UTC 已完成窗口版激活：container `9d1130c4bfd92f4d08f5d302d3af96b62399b52f7479b6fcdb2a7ee0febff3ed`。源码 hash、CDP、healthy、RestartCount 0、80 秒稳定窗口通过，旧修复版容器保留。随后开始请求限时人工窗口，只有匹配 ACK 后才允许将其称为已取得。

08:49 UTC 独立检查已确认窗口生效：phase=manual_window、heartbeat_age=1.92 秒、ACK 与请求匹配、browser healthy/RestartCount 0、controller 临时停止。已提示用户在 08:57:17 UTC 前进行一次无自动 solver 干扰的手动验证；窗口结果和 controller 恢复仍需后续回执核验。

### 人工窗口实际结果与恢复

用户在确认 solver 静默后再次反馈“仍然认证失败”。随后再次独立检查仍为 manual_window、heartbeat_age=1.14 秒、ACK 有效、controller 停止、browser healthy/RestartCount 0，排除了自动 solver 继续输入这一干扰项。

在 08:49:10 ready 提示之后、08:51:45.639 关闭窗口之前，捕获到 10 次 slide 请求（08:50:40–08:50:57），均 HTTP 200、root.code=300、root.result.code=300、root.success=true，没有观察到内层通过。不能据此精确计为 10 次人工拖动，页面可能自行重试；但均属于已取得静默 ACK 的窗口。08:52:13 的额外 slide 发生于恢复自动化之后，排除在人工窗口证据之外。

已主动提前结束窗口，回执 controller_restored=true；随后独立核实：请求已过期失效、solver phase=solver_attempt、controller active、两个 image authority 与安装的 6 个源码 hash 匹配，browser healthy/RestartCount 0。seed/detail 四个实例的 ID 与 StartedAt 仍未变化。没有留下临时暂停，也未清空会话或更换网络。

最终状态：程序分类缺陷、诊断缺口及无干扰验证窗口已完成并部署；当前来源会话在无自动输入干扰的人工验证下仍失败。不能声称来源认证已修复，更不能仅凭 code=300 区分账号、会话、网络或平台策略原因。
