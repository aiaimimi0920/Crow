# 详情 worker 的暂停与认证等待

详情采集在领取下一项任务前读取采集状态。显式人工暂停是独立于验证码范围的控制指令：不能因 detail scope 已清除，也不能因目标详情页已经打开而继续领取任务。

## 状态优先级

- 顶层 `operator_paused=true`，或实际 `/status` 中 `captcha_solver.paused=true` 且 `pause_reason="operator"`，均优先于 scope 状态。
- 人工暂停返回 `detail_collection_paused`、`reason="operator_paused"`；已打开页面的认证恢复检查不能覆盖该决定。
- 没有人工暂停时，detail 使用自己的范围状态，不因 seed-only 暂停继承长退避。
- scope 兼容顺序为顶层 `collection_scopes`、`captcha_solver.collection_scopes`、`captcha_solver.scopes`。已存在的顶层字典是权威值，即使为空，也不能被嵌套的 clear 状态覆盖。
- 仅在 API 明确确认 detail 未暂停、不需要人工认证、且没有当前 challenge 时，认证等待才能提前结束。状态缺失、读取失败或仍有挑战时维持原有等待。

等待器最多每 30 秒读取一次状态。退避期满不等于授权恢复：下一轮仍须经过任务领取前的暂停检查。这些规则不承诺中断已经开始的任务，也不改变 analysis worker 的产品控制合同。

## 回归入口

- `tools/test/test_detail_worker_operator_pause.py`：真实执行函数及兼容 facade 的人工暂停、已打开页面和等待边界。
- `tools/test/test_detail_worker_scope_backoff.py`：seed-only 暂停下三种 scope 布局的详情唤醒。
- `tools/test/test_detail_worker_auth_wakeup.py`：未知/未恢复状态、顶层状态优先和合作停止。

测试使用合成状态及隔离文件，不访问实际站点，不清除生产暂停状态，不触发 solver。
