# 认证完成快照的请求归属

认证完成分为两个阶段：浏览器侧报告完成，以及对应采集范围的健康快照通过后确认恢复。前者不能代替后者。

## 单任务刷新与缓存复用

- Cookie 快照刷新保持 single-flight，同一时刻只允许一个刷新 worker。
- 用于认证确认的完成快照必须同时匹配 `completion_id`、`scope` 和 `expected_challenge_id`。
- 相同 completion ID 但不同 scope 或 challenge generation，不能复用先前完成的快照。
- 显式 `scope=None` 表示旧版全局认证归属，不能被请求记录中的 `seed/detail` 提示替换；只有未提供 `scope` 字段时才使用该提示。
- 旧 worker 已发布 `completed` 但尚未退出时，另一请求返回 `cookie_snapshot.status=busy`、`retry_queued=false`；它没有被排队，不得报告 `auth_confirmation_pending=true`，更不能清除当前暂停状态。
- 忙碌不代表新的验证码失败，也不允许跳过健康检查。旧 worker 退出后，可重新提交原请求；新的 challenge generation 仍必须重新校验。
- 同一请求的幂等重放、已确认 receipt，以及人工暂停和 challenge 状态的原有保护不变。

## 回归入口

- `tools/test/test_auth_snapshot_request_ownership.py`：跨请求、跨 scope、跨 generation 的隔离，真实线程的完成发布/退出窗口，以及同请求缓存复用。
- `tools/test/test_auth_cookie_snapshot_scheduler.py`：single-flight、请求副本和启动边界。
- `tools/test/test_solver_scope_runtime.py`：状态发布、完成事务、幂等回执与新挑战并发。

这些检查使用合成状态和隔离文件，不执行第三方验证码，不读取真实 Cookie 或浏览器 profile。
