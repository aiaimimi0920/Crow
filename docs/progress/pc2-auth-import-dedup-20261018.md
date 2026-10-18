# PC2 认证快照导入去重

## 行为

此前 `pc2_claimed` 和 `restarting` 重试均重新导入 Cookie；已有 marker 即使属于同一轮恢复也不阻止写入。当 NAS 确认响应丢失时，旧快照可能再次覆盖浏览器中的 Cookie。

新增 schema 2 导入凭据，绑定 recovery ID、快照 SHA-256、CDP endpoint 与浏览器 websocket 实例标识的 SHA-256。只有成功导入并检查 Cookie identity 后才写入凭据。相同浏览器、相同快照、相同恢复轮次重试时不再重复执行 Storage.setCookies，继续实际阶段探测和 NAS ACK 流程。

浏览器实例变化、快照或恢复轮次变化、旧 schema、缺少实例标识均重新导入。无法读取浏览器实例时不会伪报完成。新模块不保存 Cookie 值；原快照访问和验证边界不变。没有改变完整详情采集路径或 AI 证据采集。

## 验证

- 本地新增/原有导入测试 23 项通过。
- 同一最终源码的相关边界套件 44 项通过，包括阶段验证成功、失败、探测不可用和阶段 ACK 拒绝。
- 边界套件最初 4 项被旧夹具的短 token 和缺失 heartbeat stub 阻挡；更新夹具匹配既有生产协议，不放宽 token 校验、heartbeat 或断言。
- PC2 隔离候选镜像同一套件 44 项通过；网络关闭，无生产 Profile 或 Cookie 挂载。
- Ruff、格式、Git 差异检查通过；有效行数自测 19 项通过，ratchet 通过。
- 未运行全部历史测试，未在生产环境主动制造 ACK 丢失。

## 发布边界

发布证据目录：`/srv/apps/fapaifang-worker/releases/auth-import-dedup-20261018`。

PC2 browser-solver 由同一 supervisor 管理浏览器和 solver，退出任一子进程会使整个容器退出。因此本次需替换该容器，不声称无浏览器重启。保持配置、Profile、Cookie、挂载、设备、资源和安全配置；旧容器保留用于回滚。PC1 Edge、本机 Crow 和电脑不重启。采用 exact-ID 操作，更新两个已有 image authority，并保留原值用于回滚。

为避免镜像层数限制，基于既有固定 pre-diagnostic base 重建单层覆盖，继承并校验上一版全部 production overlay 后添加本次两个模块；不丢失之前 solver 修复。

激活和运行验收以发布目录中的 `activation.json` 和独立验证为准。原配置备份包含敏感信息，不应公开。

## 已完成激活与独立核验

- 新容器：`681e4bb4841e7a84a757f4e34bc57a249c08c7746d562ac54461e30343db6648`。
- 新镜像：`sha256:543909ea450509ff17326dbe914c8fff600d93fac17485a14e5336fe5e89f2dd`。
- 容器 healthy，稳定性观察后重启计数为 0；安装源码 SHA-256 与候选一致。
- 两个 image authority 均指向新镜像，engine controller 已恢复 active。
- 独立检查时 solver 心跳年龄约 40 秒，阶段为 `solver_attempt`；这不是网站认证成功或采集数量增长的证明。
- seed-1、detail-1 的 ID 与启动时间和更新前一致；detail-2、detail-3 启动时间也早于本次更新，均 healthy。
- 旧容器保留为 `fapaifang-pc2-browser-solver-before-auth-import-dedup-20261018`，未删除 Profile、Cookie、数据库或旧镜像。
