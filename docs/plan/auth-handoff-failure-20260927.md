# 本轮认证失败定位：Cookie 已导入，详情恢复验收超时

只读核查时间：2026-09-27 19:34 至 19:39 UTC（本机 12:34 至 12:39）。未修改生产代码、重启服务、刷新人工认证页或变更线上状态。

## 已确定的失败位置

本轮 recovery ID 为 auth-recovery-d7bbf64b4f875d40ad4003fd599dcb37，scope 为 detail。19:39:29 UTC 读取的 NAS 最终结果为 failed / verifying_timeout，实际结束约 19:38:10 UTC。恢复初始详情数 155693，失败记录中的详情数为 155719，最新详情数 155722。

Cookie 传递和 PC2 导入有完成证据。此次失败落在导入后的详情恢复验收阶段：NAS 要求计数增长，同时该阶段没有活动 challenge；这轮计数增长了，但新的 detail challenge 仍存在，因此被阻止完成，最终超时。

## 逐段证据

1. NAS 已登记本轮快照，含 152 个 Cookie，SHA-256 为 fc3c9e434575abf775581912b68a78e3652e9023bc6df658a26bd3114309a27a。PC2 下载路径按 recovery ID 和 SHA-256 校验内容。
2. 19:27:52 UTC：NAS 记录 PC2 claim 和导入后的回执阶段。19:27:53.489 UTC：PC2 输出 recovery_confirmed。当前只读 CDP 核查显示，7 个期望的关键 session Cookie 全部存在且值与快照匹配，缺失数为 0。未输出 Cookie 值。
3. NAS 此时将 detail 设为 verifying，期限约 19:37:53 UTC。PC2 的 recovery_confirmed 日志在此处只表示导入回执被接受，不能证明整个详情恢复已完成。此前把该日志当作最终恢复成功证据的表述需要修正。
4. 19:27:56.062 UTC：出现新 detail challenge captcha-1790537276062409985，目标仍为 sf-item.taobao.com/sf_item/610925725633.htm，距进入 verifying 约 2.6 秒。旧恢复绑定的是 captcha-1790537034722949513。
5. 同期 seed 也有新 challenge。列表 worker 后续返回 seed_collection_paused / captcha_solver_running，自动 solver 多次失败并替换挑战页。详情 worker 状态不一致：detail-1、detail-2 曾进入 900 秒等待；detail-3 在 19:33:51 和 19:35:41 各完成 10 个详情。部分采集能继续，并不等于全部挑战已经解除。
6. 19:39:29 UTC：NAS active 已清空，last_result 为上述 verifying_timeout。

同一快照此前用于 seed 恢复 auth-recovery-9a0f9d8841cf50df928c2fea0ddd65b7，NAS 于约 19:26:49 UTC 记为 succeeded / seed_payload_verified。该成功只证明当时 seed 探测通过，不保证后来不会再遇挑战。

## 代码中的具体缺口

- tools/pc2_auth_recovery.py:370-388：seed 会执行 probe_seed_access；detail 默认 authenticated=True、reason=cookie_import_verified，没有目标详情页复验。
- src/server_auth_recovery.py:207-221：validate_and_clear 校验 challenge ID/target 后清除 scope pause，没有检查浏览器 tab 或页面内容。
- src/nas_auth_recovery_stage.py:94-109：detail 收到导入回执后进入 verifying，等待后续采集证据。
- src/server_auth_recovery.py:145-156：仍有 challenge_id 的阶段被作为 blocked_scopes 传入。
- src/nas_auth_recovery.py:260-276：即使计数增长，只要当前 scope 被 blocked，就不会判为 succeeded。:213-231 在验收期限到达后记为失败。
- tools/pc2_auth_recovery.py:403-412：只有 seed 检查最终 succeeded；detail 对 verifying 也输出 recovery_confirmed，造成阶段含义不清。

因此，用户描述的 PC1 验证、NAS 传递、PC2 替换 Cookie 链路，这轮完成了传输与导入；PC2 替换后的页面复验和挑战交接仍有缺口。Cookie 导入不会自动刷新已打开的验证码页面，也不包含整个浏览器运行上下文。

## 尚未证明的更底层原因

当前证据不能区分：新 challenge 来自导入前保留的旧验证码页面再次报告，还是导入后新采集请求确实再次触发了站点挑战。相同 URL、不同 challenge ID，以及仅相隔 2.6 秒，不足以单独证明任何一种。也没有证据支持直接归因于 IP、指纹绑定或 Cookie 文件传输损坏。

需要在下一轮交接按 recovery ID 关联 PC2 的 target ID、导入前后页面状态和新业务请求，再确定再次挑战的来源。修复方向应是导入后在 PC2 实际消费会话的上下文验证同一目标页、按旧 challenge 身份处理交接、准确区分 imported / verifying / succeeded / challenge_recurred。不能仅去掉 blocked_scopes 检查来显示成功，也不能只重复复制 Cookie。

本次完成了失败边界诊断；未声称已经修复再次挑战。
