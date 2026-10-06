# 24 小时自动求解只读观察

入口：`python -m tools.solver_observation --container <canonical-name> --output <private-directory> --source-revision <commit> --hours 24`。

在 PC2 Docker 主机运行；程序只读取 Docker inspect/logs 和容器内现有内部 `/status` GET。不要用 `live_slider_monitor.py` 代替：后者会导航、清理页面并主动求解。监测器不调用 solver、不写 Cookie、不点击/关闭页面、不修改冷却或轨迹。

## 统计口径

- `started/completed`：窗口内可观察的 solver 调用日志数，不等于唯一业务请求数。
- `automatic_local_success`：同一生命周期必须观察到 pyautogui 自动拖动、verified 阶段及 success=true；健康页面直接返回 true 不算自动解滑块。
- `automatic_auth_confirmations`：来源为 pc2_local_solver 的唯一 completion ID 确认数。
- `auth_confirmed`：还必须通过 target/challenge 与唯一成功调用关联。缺字段、错 scope 或有歧义时保留为 unlinked，不按时间接近猜配。
- `bound_health_verified`：已关联确认携带对应 scope 的健康证明。详情页证明不升级为全站授权。
- `collection_delta`：全窗口业务计数变化；不能直接归因于某一次验证。

这些日志不独立证明每一次上游 `/slide` code=0，也不能排除同时发生的人工输入。保留该限制，不将应用上报偷换成无条件的站点通过率。

## 产物与恢复

私有输出目录包含 `run.json`（固定开始/结束时间）、`events.jsonl`（白名单脱敏事件）、`business.jsonl`、`issues.jsonl`、`checkpoint.json` 与原子更新的 `report.json`。不保存原始日志、响应体、Cookie、完整 URL、令牌或异常消息；目标与 completion ID 仅保留可关联哈希。

建议由独立 systemd service 运行，使用唯一 unit 和输出目录，不依赖 SSH 会话。重启同一命令会复用原窗口和已持久化事件；文件锁拒绝重复实例。日志读取失败保留 cursor，后续补采；容器更换补采保留的旧 exact ID，重启边界使旧未完成调用不能跨生命周期完成。日志轮转或应用未发出的事件仍可能无法检测。

`window_finished` 表示时间窗口结束，不等于无缺口；同时查看 `logs_read_through_deadline` 与 `coverage_issues`。未到期只能报告阶段数据。若达到结束时间仍不能读取，记录缺口后停止，不无限延长采样或假装统计完整。

## 本轮验收与部署原则

先跑 `tools/test/test_solver_observation*.py`、Ruff 和仓库有效行门禁。生产求解算法不随本次观察器修改。发布使用已验证基底的离线源码层，原配置/挂载/浏览器资料/数据库保留，exact-ID 切换保留旧容器，不使用 service-wide Compose recreation。桌面构建输入未变时可复用已验证 EXE，仍需核对安装 SHA、运行路径及 Crow.lnk。

满 24 小时后先核对覆盖缺口，再提取成功调用和相邻失败的时序、scope、profile、确认链和业务变化。只有发现可复现的程序缺陷才修改；单次成功不证明稳定有效，也不支持直接提高重试频率。