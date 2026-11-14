# Crow 采集修复独立复审

日期：2026-11-15。输入：用户桌面 `审查建议.md`。
源码基点：`89b985a60337b3b26b6085509b15f65281bdfbee`，加本次工作区修改。

## 结论和完成边界

原留言不是当前源码的准确说明，不能据其历史测试数字或部署描述验收。
已审查六项 finding，并继续完成种子合并、双写恢复、真实 executor 回执与失败捕获隔离。最新验证与部署结果见文末“继续执行回执”；下文早期测试数字保留为历史证据，不代表最终状态。
本次没有提交、推送、强制 resume，也没有删除历史备份。已授权的受影响应用部署按文末回执分别记录。
原有 PC2 browser/maintenance dirty edits 原样保留，未混入本次修复。

## 一、完整性

1. 队首窗口：当前仍存在先 LIMIT 再过滤冷却/已有文件的问题。已改为分页扫描，覆盖单条、批量和 visit；legacy visit 同时检查拒绝墓碑，显式 replay 才重新打开。
2. 重试：相同内容不清预算、模型最多五次等逻辑已经存在，但损坏回执仍被当成空预算。已严格校验持久化字段、拒绝 NaN/错误类型、保留损坏文件并记录错误，不再静默重置预算。
3. JSON/journal：文档宣称的生产追加写和全部读口统一不成立。当前生产 facade 仍全量发布，DataFixer 仍有旧读写口。已修 journal 重放覆盖、删除复活、压缩/追加竞争、坏行吞错和 DataFixer 原地截断/并发覆盖。但这不构成 DB 与 JSON 的分布式原子提交。
4. 旧 pause flag：当前源码已经取消无条件 TTL 解锁；未知/损坏 flag 保持门禁，不会仅因年龄而删除。
5. manual_only/delegation：当前源码保留人工门禁和节点输入所有权，不再凭 TTL 自动恢复，也不让 NAS 竞争接管 PC2。离线 owner 的恢复流程与最终 liveness 仍需真实运行验收。
6. auth completion：当前已按精确 challenge ID 选择 scope、拒绝无归属 completion，并保留 operator pause；不是原留言描述的“接管第一个 scope + set_pause(False)”。相关回归已执行。

## 二、正确性与本次改动

- `src/collection/pending_pages.py`、`detail_service.py`、`storage/repository_task_events.py`：数据库分页和冷却清理；窗口后可派发任务不再永久不可达。
- `src/collection/detail_failures.py`：坏预算 fail closed，错误可见；无法读取的历史回执不被新失败覆盖；指数运算有界。
- `src/solver_retry_monitor.py`：超时状态转换在锁内复核 execution/recovery/control 快照，不能用旧任务的超时取消新任务或覆盖新的人工暂停。
- `src/archive_transaction.py`：同协议本地写者的线程/进程锁；锁文件不属于 JSON glob，不能在运行中清理。
- `src/archive_json_io.py`：严格读取 journal；全量替换先安全排空旧 generation，不能让旧 journal 覆盖新记录；退休 journal 失败明确失败。原子写保留原证据。
- `src/collection_archive_records.py`：整段读改写使用归档事务。
- `src/collection/archive_records.py`：维护候选读取使用 journal-aware reader。
- `src/data_fixer_app_part_01/02/03/05.py`：旧编辑器读取兼容 journal；保存采用原子发布；检查读取后是否发生其他写者更新，冲突时提示重新加载，不悄悄覆盖。

没有重新启用 TTL 自动解锁，没有修改 Cookie、账号、浏览器 profile 或数据库 schema。

### 后续关闭与保留边界

- `seed_service.py` existing 分支已改为 DB-first，数据库在 SQLite 写事务 / PostgreSQL 行锁内读取最新记录，仅补空字段；JSON 在归档事务内 merge，并把实际发布记录返回缓存。真实 SQLite 与 PostgreSQL 回归覆盖晚到 seed 和并行补字段。
- seed DB 已提交但 JSON 失败时不 ACK，幂等重放修复发布；maintenance 保留 JSON-first 证据与既有补偿路径。新增 JSON 发布失败不提交 DB 的回归；原 DB 失败重放不重复抓取/付费调用的回归继续通过。这不是跨存储分布式原子事务。
- `submit_html` 保留兼容的 `status=queued`，另返回 `capture_saved`、`submission_state`、`processing_queued`，明确区分 accepted/duplicate/not_ready/error/unknown。failed_* HTML 保存到非扫描目录 `failed_capture`；旧 HTML 对应 failed 状态时禁止模型处理。
- 新锁协议只保护合作写者；旧二进制、直接文件写者以及跨主机共享文件系统锁语义不在本轮证明范围。

## 三、回退兼容性

`.bak` 只是代码备份，不是经过验证的发布回滚包。不能直接覆盖单个 reader/writer 后恢复服务。

安全回滚至少需要：停止受影响写者；备份基文件及 journal；使用匹配版本完整读取并 compact；核对记录及哈希；再整体恢复兼容 reader/writer。损坏 journal 不得通过丢弃坏行或删除文件来求成功。

本次没有对生产 journal 执行 compact、迁移或删除，未验证实际备份的可启动性。

## 四、测试覆盖与实际结果

验证分批进行，不将不同工作树状态的通过数相加成一次全通过：

- 认证 scope/人工暂停/清理定向检查：65 passed，较早审查状态。
- 新增派发/回执/timeout 定向检查：19 passed，较早修复状态。
- 归档、DataFixer、失败持久化、采集兼容等相关检查：112 passed，扩大验证前状态。
- 扩大相关套件：1398 passed、2 failed、2 skipped，181.78 秒；含显式 PYTHONPATH 的子进程崩溃恢复。日志位于 `linshi/crow-review-20261115/affected.log`，JUnit 为同目录 `affected.xml`。
- 上述两个失败：DDL 历史摘要不匹配；日志测试仍在已拆出的旧文件查找 location logger。后者已修为检查真实 `detail_location.py`，未删除断言。
- 最后冷却辅助函数提取、日志测试修正后的定向验证：35 passed，8.19 秒，包括 journal 线程竞争/独立进程排他以及 DataFixer 并发冲突。
- 有效代码行检查器：19 tests passed；最终 ratchet 通过，无 501 行以上源码。
- `git diff --check` 通过。新增核心模块及定向测试 Ruff 检查通过；全部触及历史文件的 Ruff 检查仍存在旧 typing/datetime 告警，不报告为全绿。

早期曾失败、后续已修复的 DDL 摘要用例：

`tools/test/test_collection_model_names.py::test_postgres_and_sqlite_ddl_match_pre_rename_baseline`

期望：`e75691b5fafee1f7c09ef9fab18f8fa0b50700cb8b81b34453f0833f14cc26e8`

实际：`6fcc656c6b6bb1ab223a11b2520d842481eb894ef27c816b74b09772dcb869a8`

后续已核实差异仅为已提交迁移 `20261104_0014` 的两个索引。保留原 golden；单独精确断言新增索引 DDL，再从历史签名中剥离这两个已审核增量。没有改生产 schema 或直接替换 golden。

早期未验证项如下；真实 PostgreSQL、Linux 本地锁、受影响部署与桌面构建的后续证据见第七节。仍不声称覆盖完整历史套件、跨主机共享文件系统锁、断电级持久化或所有旧版本 writer 回退组合。

## 五、副作用评价

以 TTL 或全局 `set_pause(False)` 强行恢复存在越过人工意图、其他 scope 和输入 ownership 的风险，不接受“短暂恢复采集比死锁好”作为通用安全依据。

本次 fail-closed 会令损坏 journal/receipt 停留等待修复，这是明确错误，不再静默放开预算。锁文件为持久同步对象；纯读取旧归档不创建锁文件。DataFixer 并发冲突会返回失败，需要重新加载，而不是覆盖较新数据。

## 六、生产优先级与现场核验

先完成剩余正确性问题和发布门禁，准备受影响组件的可回滚候选，再按 exact container ID 激活；不要先强制 resume 来掩盖问题。只有已证明对应 challenge/人工意图允许恢复时，才使用匹配 scope 的恢复流程。

本轮只读现场事实：

- NAS SSH、sudo Docker 可用；CA 校验的 HTTPS `/api/status` 返回 200。原文“SSH 不可用”已过时。
- canonical `crow-api` running、RestartCount=0；没有 Docker Healthcheck，不称为 Docker healthy。control/PostgreSQL 容器 healthy。
- operator/agent token 文件存在，权限 600；没有读取 token 或执行认证控制调用，因此不声称 token 已验可用。
- NAS `/app/src` 对 HEAD 归一化哈希：312 文件相同、13 不同、10 缺失。线上不是完整 HEAD，但也不是所有修复都未部署。
- 多个停止/候选回滚容器共享 `fapaifang/crow-api` Compose 标签。现有部署脚本的 service-wide `compose up` 不可直接用于该现场；需要 exact-ID 方案并保留旧容器。

以上现场记录对应早期只读审查；后续激活情况见下面回执。只读健康检查不是部署、认证成功或业务采集成功。

## 七、继续执行回执

### 新增修复

- `src/storage/seed_merge.py`、`repository_collection.py`：数据库写边界锁定最新记录，粗采集只补空字段，避免 stale seed 覆盖详情或拒绝终态。
- `repository_core.py`：真实隔离 PostgreSQL 验证发现 `enable_postgis=False` 时仍更新不存在的 `geom` 列；已让写入与初始化遵循同一个配置开关。
- `capture_submission.py`、`detail_service.py`、`detail_processor.py`：持久捕获与 executor admission 分开报告，失败页面隔离且保留重试预算。
- 本地 DataFixer 为独立 Python/Tk 入口；其四个模块修复不声称被打进 Tauri EXE。

### 验证

- 最终扩大相关套件：**1409 passed，2 skipped，387.84 秒**。生产源码为本次候选 manifest 状态；之后仅做新增测试的 dict 字面量/未用变量格式修正，无生产源码变化。
- 两个 skip：Windows 上 Linux flock 协调测试；未配置隔离 PostgreSQL URL 的索引迁移测试。后者另行验证为 SQLite/PostgreSQL **2 passed**。
- 独立 PostgreSQL：种子合并、并行补字段、队列竞争与插入计数 **8 passed**，使用本地专用 `crow_quality`，未连接生产数据库。测试容器已停止，未删除其数据。
- ECL 检查器 **19 passed**；ratchet 通过，1836 文件，无 501 行以上源码。`git diff --check` 通过；24 个责任源码/测试的 UTF-8 无 BOM 与 AST 检查通过。
- 桌面 **68 tests passed**、TypeScript 检查和 Tauri release 构建通过。实际原生窗口显示 NAS 商品列表与实时计数，不把此读路径视为验证码解决证明。
- NAS 最终实际候选镜像隔离回归 **50 passed，109.09 秒**，包括 Linux 子进程归档锁；无生产数据挂载、`--network none`。测试依赖只读挂载，不安装进生产镜像。初次 pytest 依赖与测试目录布局问题已修复后复验，未激活失败候选。
- 日志：`C:/Users/Public/nas_home/AI/GameEditor/linshi/crow-review-20261115/affected-release.log`、`affected-release.xml`。

### 已部署与回滚

- PC2 仅更新 `detail-1`、`analysis-1` 的 3 个存储模块；未混入原有 browser/maintenance dirty edits，未替换 seed 或 browser-solver。
- PC2 候选基于各自已安装 image，仅窄范围 COPY；无生产挂载、无网络的候选测试验证真实 SQLite 并发合并。激活通过真实 solver 维护窗口 ACK/heartbeat/PID 准入，合作 SIGTERM 排空，按 exact ID 替换，更新持久 image plan，并释放自己拥有的维护请求。
- PC2 新 detail ID：`7ce548c080a04a491854da77309a96d4244656d5859a67b9514045bcb73d57b0`；新 analysis ID：`e5f2778a2ccaadcbb8e3e77f4b46d530134739d70fa4588f592c85f23e0289a7`。均 healthy/restarts 0，安装源码 3/3 哈希匹配，旧容器停止保留。
- 本地桌面：`C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/fapaifang_collector_desktop.exe`，SHA-256 `E428F78EB0641AA8339A0AB6F972F53EE4BD8BFC67CEEF842AE11D69B7ED2ABB`。EXE-only 原子更新，保留配置与辅助脚本，已启动实际安装路径并刷新/核验 `Crow.lnk`。
- 桌面回滚：安装目录 `backup/exe-only-20261115-031353-ddc2467f/fapaifang_collector_desktop.exe`。
- NAS 生产数据库预部署备份：`/volume1/docker/fapaifang/app/releases/review-20261115-r3/database-before.dump`，513018734 字节，SHA-256 `4e685dfde27a3ce5489cf50f6195c38ce85833c117d7d50ec3887982894cba34`，`pg_restore -l` 验证通过；未删除容器内副本。
- NAS 已实际切换：新 `crow-api` ID `95d4393e1a93ea22f4bf7ef325f7733cb9c50576d1ff9a41c5d052416a9021bf`；image `sha256:51d57679aeb3108dffd33635ea323cbef7230f1445a837f4a90c45a11101e018`。15/15 安装源码哈希匹配，running/restarts 0，无 Docker Healthcheck，因此不标为 Docker healthy。TLS CA 校验的 overview 与商品列表均 HTTP 200，列表返回真实记录。
- NAS 旧容器保留为 `crow-api-before-review-20261115-r3`；只更新 Compose 中 API image，未调用 service-wide recreation。Crow control/PostgreSQL 的 ID/PID/StartedAt 未变。
- 生产观察期间真实计数从桌面初次核验的链接 578895、详情 235003、归档/分析完成 232233，增长到最终 API 样本 578959、235020、232245。说明观察期间存在自然产出，不把净增量归因于某一个补丁，也不把当前分析模块宣称为完整产品能力。
- NAS 与 PC2 的部署、安装哈希与运行回执保存于各自主机 `releases/review-20261115-r3/`；本地安全输出与 API 样本保存于 `linshi/crow-review-20261115/`。

### 运行边界与额外观察

- 本次没有强制 resume，没有用 TTL 清除人工门禁，也没有尝试解决真实 CAPTCHA。新部署和 API 可用不能代替认证成功证明。
- PC2 solver 未替换、未由本次脚本发送 stop/restart；但后续只读巡检发现同一容器 RestartCount 从 28 变 29。Docker events 显示 exit 143 后按 `unless-stopped` 自动启动；没有对应外部 Docker kill/stop/restart/update 事件。当前 healthy，SIGTERM 来源未明，不把“solver 进程全程不变”作为最终结论。
- NAS 激活第一次准入尚未创建候选就停止：未相关的 AssetLibrary 四个容器在重启，导致过宽的 protected-process 检查失败。已核对 drift 仅属于这些同 ID 容器；准入范围收敛到 Crow control/PostgreSQL，未更改或重启 AssetLibrary。
