# C2 独立启动与关闭检查点

日期：2026-09-26。基线：`389a56950`。本记录随 C2 启动实现提交。
状态：独立 API 的启动、状态、种子/详情接纳与必要 worker 关闭已验证。
真实客户端安装切换和维护入口分别继续在 C5、C4 完成；尚未部署。

## 实现与边界

`src.collection_server` 通过 `CollectionApplication` 组合采集 repository、adapter、
AI、RuntimeState、认证恢复和原生 handler。普通启动不导入混合 server/context，
也不创建 AVM 服务、pipeline 或分析工作目录。数据根支持显式参数和现有环境覆盖，
默认使用仓库下 `FPFData/datas`。现有 Docker API 启动工具已改用这一组合入口。

HTTP dispatch、鉴权和响应复用共享 handler；旧 `src.server` 仍供现有分析调用方使用，
未删除其协议或后处理实现。C5 必须核对所有实际入口、安装载荷和路径覆盖后再切换。
新 API 暂不发布混合维护及位置推断路由；C4/C5 只恢复其中的采集职责。

启动统一管理 solver retry、HTML scanner、auto tuner 和启用时的 NAS auth watchdog。
关闭设置同一停止事件，拒绝新的写请求和 cookie 快照调度，唤醒快照重试退避，
等待已开始的详情/solver executor 工作并取消尚未开始的任务。未确认停止的 worker
会导致关闭失败，不报告成功。原始 HTML 保留/提交故障恢复继续由 C3 验证。
维护 job 的活动取消和退出证明在 C4 完成，不将本包的 worker 检查替代它。

## 验证

两个全新子进程分别使用 generic 和 Taobao adapter，主动拒绝后处理导入，运行真实
HTTP、SQLite 存储和上述 worker。验证非空种子、状态/overview、HTML 接纳、fake AI、
记录与原始证据读回、输入清理，以及完整关闭。守卫记录所有禁止导入尝试，包含被捕获的
ImportError。另验证关闭等待仍在执行的详情、拒绝新写请求、打断 120 秒 cookie 退避，
且不误确认认证成功。该路径未调用真实 AI、外部浏览器或业务数据库。

- 最终 C2 边界组：209 passed，pytest 15.61 s，runner 16.48 s。
  范围为 `collection-runtime`、cookie retry/scheduler 和 server source contracts；
  使用质量 runner 的临时目录，业务 DB 禁用。
- 新关闭路径此前的定向复测：2 passed，runner 4.66 s。
  首次该测试失败于测试读取错误响应层级，修正为 `error.code` 后通过。
- 9 个组合/生命周期文件 mypy 通过；3 个 cookie 模块严格 mypy 通过。
- 新边界完整 Ruff、其余改动的选择性 Ruff、24 个文件格式检查通过。
  旧混合 server/context 的动态导出 lint 债务未在本包扩展清理。
- 有效行工具测试 19 passed；最终 ratchet 1362 个文件，无超过 500 有效行的文件。
  没有改动基线或排除规则。UTF-8 无 BOM 和差异检查通过。
- 集中测试后做了类型表达、等价 host 属性发布、格式及测试 `zip(strict=True)` 修正。
  C3 的新进程复测发现其中 `typing.Self` 的运行时导入不兼容 Python 3.10；已改为
  TYPE_CHECKING 内的 typing_extensions 导入，两个新进程再次通过。该修正随 C3 提交。
  因此 209 项证据对应类型调整前的状态，不将 `587cd1f46` 单独当作完整运行候选。

新增 API 探针加入 fast，`collection-runtime` 和组合入口静态检查接入 CI。
本包没有完整 fast/security、PostgreSQL、桌面构建、真实 AI 或安装验收结果。

## 后续

C3 处理详情依赖、来源提取器选择、敏感诊断及证据/JSON/DB 部分成功后的重试。
C4 完成无后处理维护、dry-run 零业务写入、任务取消与停止。
C5/C6 核对生产入口并在同一发布候选上进行集成、安装与运行验证。
