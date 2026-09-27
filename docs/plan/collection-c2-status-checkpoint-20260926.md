# C2 采集状态请求检查点

日期：2026-09-26。基线：`8b4529332fd888277ee71c69ddc41b30c06a34ef`。
状态：本记录仅覆盖 C2 的状态请求边界。C2 整包未完成；无部署、重启或业务数据修改。

## 已实现的路径

`/api/status` 普通请求不再调用 AVM 健康、operator evaluation 或混合分析阶段快照。
它从 repository 读取采集 seed/detail/search 计数，保留队列预览、AI 整理完成数、模型调用
指标、认证恢复和验证码状态。数据库阶段查询失败时仍保留原来的降级可用行为。

普通及 lightweight 状态移除 `avm` 字段；普通状态的 `collection_stage` 只包含
`seed_stage`、`detail_stage`、`search_tasks`，不包含估价 readiness、推荐动作和校准摘要。
状态生成失败的错误码为 `COLLECTION_STATUS_FAILED`。这些是明确的 HTTP 契约调整。
仓库内未找到业务客户端消费上述 AVM 字段；原有诊断断言迁到现存 `/api/avm/health`，
保留其诊断覆盖，不修改估值实现。桌面的 `modules.analysis` 仍表示网页 AI 整理，保留不变。

overview 的 challenge/auth-watcher 数据根使用采集 `DATA_DIR`，不再由 AVM 服务的目录决定。
历史采集诊断文件暂时仍在采集根下的 `avm/` 子目录；本次不移动文件或修改历史数据。

## 验证与范围

- 初始 handler 聚焦：12 passed，runner 2.20 秒；日志 `artifacts/c2-status-focused.log`。
- 初始隔离探针：2 passed，runner 4.05 秒；日志 `artifacts/c2-status-isolation.log`。
  generic/Taobao 两个新进程主动拒绝 `src.avm` 和 `tools` 导入；沿 C1 seed/detail 真实 SQLite
  存取与 reopen 后执行 native handler 的 HTTP 请求，验证非空记录、AI 完成数、无后处理字段，
  并关闭测试 HTTP server、join 线程。guard 断言无被吞掉的导入尝试。
- 集中边界检查：161 passed、1 failed、339 deselected，runner 11.66 秒；日志
  `artifacts/c2-status-boundary.log`。覆盖状态 handler、真实存储隔离、repository readers、
  状态快照、collection API、HTTP guards，以及本次迁移的 10 项 AVM 诊断断言和故障隔离。
- 唯一失败是 overview 旧测试只设置 AVM 根；改为显式采集根，并令 AVM 指向无关目录。
  修正后只重跑该测试：1 passed；日志 `artifacts/c2-status-root.log`。
  其余生产代码及测试输入未变化，复用上轮 161 项通过证据；不声称有一轮 162 项全通过。
- 3 个状态生产模块通过 mypy（`--explicit-package-bases --follow-imports=silent`）；
  日志 `artifacts/c2-status-types.log`。新/修改的格式化状态模块及新探针通过 Ruff。
  初次 Ruff 扫描暴露 C1 存储探针原有 RET501/PLR1711/C408/DTZ001，未扩大范围重写该旧 fixture。
  旧 facade 的 E9/F63/F7/F82 检查仍有动态导出导致的 F821：基线 117 条、当前 116 条，
  按诊断内容比较无新增；不把它报告成 lint 全通过。两个旧契约片段和 C1 探针的同组检查通过。
- 有效行数测试 19 passed；ratchet 通过，1354 个文件，无超过 500 有效行的文件。
  日志 `artifacts/c2-lines-tests.log`、`artifacts/c2-lines-ratchet.log`。

上述 HTTP 探针使用 fixture runtime/metrics 和实际 repository。它证明状态读取边界，
不证明生产 server 已独立启动、真实认证 runtime 已启动或 worker 能停止。
本次没有执行全量 fast/security、PostgreSQL、桌面构建、实际 AI 调用或发布验收。

## 继续 C2 的具体入口

`server_context.py` 仍 eager 创建 AVM 服务/pipeline，导入 analysis tools；`src.server`
仍使用旧 repository 工厂。`server_native_bindings.py` 同时组合 collection 和 analysis owner。
下一步复用原生 owner 建立采集组合，切换真实 CLI/桌面/PC2 入口，并在禁止后处理导入的新进程
中验证种子/详情接纳和真实 worker 停止。不要把本检查点当作 C2 完成，也不要创建空服务来
替代生命周期验证。C3 的归档/DB 失败恢复及 C4 dry-run 写入问题仍未在本轮处理。
