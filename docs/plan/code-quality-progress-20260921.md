# Crow 代码优化进度与验证记录

日期：2026-09-21。依据：`code-quality-review-20260920.md`。

状态：**部分完成，不能将原清单三批任务标记为全部完成。**
当前剩余代码任务与验收项见
[`code-quality-remaining-20260925.md`](code-quality-remaining-20260925.md)；
该清单已对照后续源码修复更新，文中较早的“尚未完成”段落保留为历史记录。
最新执行边界：用户已要求全部代码任务完成后再部署测试。本次续作没有部署、重启应用，
也没有迁移业务数据库。下文“本地桌面已更新”是该指令之前的历史记录。
2026-09-22 的 API 并发、后台任务和最新门禁结果见文末；接口用法见
[`collection-async-operations.md`](../collection-async-operations.md)。
本轮保留并验证其他 AI 的未提交成果，补充数据持久化、请求边界、watchdog
与测试门禁缺口。本地桌面已更新；NAS API 与 PC2 尚未激活这批源码。

## 数据保护边界

- 未执行业务数据删除、数据库重置、恢复覆盖、表清空、迁移降级、volume 删除、
  `prune`、release 清理或 Cookie 快照过期删除。
- 未运行清单 #33、#40、#46 中的自动删除建议。后续实现也必须遵守用户的
  “无论如何不删除已经整理好的数据”要求。
- Python 测试从新建的系统临时目录启动，显式关闭默认业务数据库，覆盖运行数据路径；
  仓库已有测试网络隔离保持启用。没有将测试指向 NAS 业务数据库。
- Postgres 并发测试使用已有专用容器 `crow-quality-pg-20260920`，已核实
  `crow.purpose=quality-regression`、仅 loopback 暴露端口、无业务目录挂载。
  每项测试创建独立随机 schema，测试结束保留 schema，没有清空原有测试数据。
- 本地应用更新只替换 EXE 和 3 个随包代码文件。运行配置、凭据、Cookie、浏览器
  profile 与数据库内容未被更新操作替换；运行配置 SHA-256 前后相同。
- 没有重启电脑、PC1 人工认证浏览器、NAS、PC2 或不相关服务。

以上是本轮操作边界，不等同于对全部历史业务数据做了全量完整性审计。

## 本轮新增修复

### #39：任务进度写入失败必须可见

`jobs/job_manager.py`：

- 保留已有的“损坏 JSON 读取失败即抛错”修复。
- 缓存读写采用深拷贝，调用方不能在保存成功前修改缓存中的已确认进度。
- 使用目标目录内唯一临时文件，写入后 `flush`、`fsync`，再原子替换。
- 保存失败使缓存失效并向上传播；公开的 `update_progress` 同样传播失败。
- 失败时保留原文件和待写临时快照，便于恢复，不清理既有文件。

回归测试：`tools/test/test_job_progress_durability.py`，覆盖缓存隔离、fsync 失败、
replace 失败、公开调用失败传播，核对原始文件 bytes 不变。

### #49：派发时间缓存不再永久增长

`src/collection/detail_service.py`：

- 三个派发入口在选取候选前移除达到冷却期限的内存时间戳。
- 未到期条目继续阻止重复派发；到期候选可重新派发。
- 不删除文件、记录或采集证据。

回归测试：`tools/test/test_detail_dispatch_retention.py`，覆盖三个入口、空候选、
冷却边界、重复派发防护与归档文件保留。

### #38：损坏 watchdog 状态不能重置重启上限

`tools/pc2_collection_watchdog.py`：

- 拒绝损坏 JSON、非对象状态、负数/布尔/字符串计数、非法或非有限时间戳。
- 状态不可读时保留原文件，返回 `state_unavailable`，暂停自动重启并输出错误日志。
- restart 命令失败时持久化 `restart_failed` 与告警，保留已消耗的重试次数。

回归测试：`tools/test/test_watchdog_state_preservation.py`，全部使用 FakeDocker，
不调用真实 Docker restart。

### #2、#25：补启动鉴权与路由边界

`src/server.py`：

- `/api/collection/control/start` 在业务操作前验证控制 token 和 JSON 请求体。
- GET 具体 API 使用解析后的 path 精确匹配，查询参数保留并继续传入 handler。
- `/api/avm/predict_extra` 等未知后缀不再匹配真实接口。
- upload 只匹配 `/api/upload`，未知后缀不进入文件写入路径。

回归测试：`tools/test/test_http_route_boundaries.py`。

此处不表示 #2 已全部完成：多个采集写入口仍需统一认证与配套客户端更新。
#25 的 POST/DELETE 全面路由表重构也尚未完成。

### #21：修复 Windows 上拒绝请求时的连接中止

合并测试真实捕获到 WinError 10053。错误 Content-Type 与未知 POST API 在未读取
请求体时关闭连接，可能使客户端收不到预期的 415/404。

`src/server_request_guard.py` 与 `src/server_handler_ingest.py` 复用已有
`_send_guard_error`：先发送并半关闭响应，再执行有字节上限及超时的请求体读取。
补充 2、4096、65536 字节请求体用例。最终合并测试通过。

### 测试门禁修复

`tools/test/test_server_source_contract.py`：

- 由测试文件位置推导仓库根，允许从隔离临时目录运行，防止扫描空目录造成假通过。
- 扫描所有路由 if 分支，避免首个独立 if 使后面的路由链被遗漏。
- JSON 路由清单识别统一 `_read_json_body`；HEAD 的明确 404 纳入契约。
- 没有删除原有用例或放宽行数策略。

`tools/test/test_control_plane_error_contracts.py` 与增强的
`tools/test/test_quality_http_guards.py` 验证设置、重启、认证恢复与上传的负向错误码。
这些测试调用真实 HTTP handler，使用替代的授权/存储对象，不操作真实控制邮箱。

## 对已有 AI 成果的本轮验证

已有 quality 测试覆盖的成果包括：上传路径约束与禁止覆盖、HEAD 404、AVM 数据目录
限制、控制 token 缺失拒绝、认证完成目标限制、公共恢复状态裁剪、JSON 大小/类型限制、
5xx 异常详情裁剪、种子重扫保留内部字段、租约不被短租期抢占、跨节点 artifact
认领不永久阻塞、fallback savepoint、DB 故障传播、409 回执归档、Cookie 原子写入、
禁止 HTTP 重定向、LLM 429 冷却和输出预算、worker 生命周期等。

这些成果仍在工作树中，未替其他 AI 提交、回滚或覆盖其实现。
“测试覆盖”只针对具体用例，不等同于原编号全部子要求及多机器发布均完成。

## 新鲜验证结果

| 检查 | 结果 |
|---|---|
| 本轮相关 Python 合并集，隔离目录执行 | **156 passed，20.67 秒** |
| 专用 Postgres，两 worker 同步竞争 search/page/page_parallel/detail | **4 passed，4.40 秒** |
| `node --test scripts/tests/effective-code-lines.test.mjs` | **19 passed** |
| `effective-code-lines --mode ratchet` | 通过；保留基线历史超大文件，没有新增豁免 |
| `git diff --check` | 通过；Git 有 LF/CRLF 提示，无空白错误 |
| `npm run typecheck` | 通过 |
| `npm run test` | **30 passed** |
| `npm run build` | 通过 |
| `cargo fmt -- --check` | 通过 |
| `cargo test --locked` | **9 passed，1 ignored**；忽略项为显式线上只读 probe |
| Playwright collection/authentication/settings smoke | **3 passed，24.1 秒** |
| `cargo build --release --locked` | 通过 |

默认 Playwright headless shell 未安装；使用现有 Chrome channel 的全新测试 profile
完成 smoke。没有附着或关闭人工认证浏览器。没有把失败的初次启动计为成功。

本轮编辑的源码/测试均核对为 UTF-8 无 BOM。没有运行全仓所有历史 pytest 用例，
没有宣称全量测试通过。

## 本地桌面激活证据

安装目录：`%LOCALAPPDATA%/FapaiFangCollectorDesktop`。

替换文件：

- `fapaifang_collector_desktop.exe`
- `tools/pc1_desktop_recovery.py`
- `tools/browserless_seed_probe_cookies.py`
- `tools/internal_api_http.py`

4 个文件均与对应验证源的 SHA-256 一致。

EXE SHA-256：
`4974266fa9694723c1680fd29964ff18c25eb61789c4e54c76a134ad27f7b5bc`。

原文件与原运行配置备份：
`%LOCALAPPDATA%/FapaiFangCollectorDesktop/backup/quality-20260921-3f0b268dfaf44997b262bb28d3314d82`。

首次替换遇到 Windows EXE 退出后的占用窗口，已恢复原版本；增加明确等待进程退出后，
第二次激活成功。新进程 PID `36296`，实际 executable path 指向上述安装目录。

运行配置 SHA-256 保持：
`7618a76d6fa1655af51f58e475e06dd0d103ef588484efe3034003553b349ddc`。

通过 `scripts/update-collector-desktop-shortcut.ps1` 更新桌面 `Crow.lnk`，并验证 target、
working directory、icon、EXE hash。未删除其他桌面文件。

使用安装配置中指定的 Python 运行已安装 helper：`config` 返回 `ok=true`、
`configured=true`；真实 HTTPS `get` 返回 `ok=true`、`available=true`，含 effective
设置。没有提交设置变更、重启请求或认证完成请求。

## NAS/PC2 发布阻塞与剩余工作

NAS 只读检查：`/api/status`、`/api/collection/overview` 均 HTTP 200；DB mode 为 true。
状态接口报告版本 `20260906-manual-auth-r2`。这只是当前线上观察，不能作为本轮部署证据。

**本轮没有部署或重启 NAS API、PC2 worker、PC2 browser。** 整包发布前仍需处理：

1. 鉴权与客户端不一致：`desktop_runtime_controls.ts` 的 `toggleRuntimePause` 调用
   `post(base, action, {})`，未传 token；服务端 pause/resume/start 已要求控制 token。
   现有 native HTTPS helper 仅支持 settings 与 restart，尚无这些运行控制操作。
   直接发布当前服务端会使相应桌面操作收到拒绝。应先完成受配置约束的凭据传递，
   不能退回无鉴权或把私密 token 暴露给任意 origin。
2. 全部写接口的统一认证仍未收口，例如采集上传与部分上报入口；GET resume 的
   loopback 兼容策略也尚未退役。需要同步验证现有 worker/userscript 协议。
3. `scripts/deploy-nas-central-api.sh` 的健康门仍从未鉴权 `/api/status` 读取
   `auth_recovery.enabled`；新的公共状态裁剪不会返回该字段。发布检查必须同步更新。
4. NAS 与 PC2 发布脚本仍包含服务级 Compose 重建；发布前必须检查相同项目/服务标签
   是否有保留备份容器，并在有备份时采用 exact-ID 替换与旧容器保留。

其余清单尚未完成的主要部分：

- #15 HTTPS 与角色 token 全链路迁移。
- #17 单线程 API、长任务异步化；#18 captcha deadline/可中断等待；#22 solver 状态封装。
- #20 页面输入与指令分离的完整契约；#27 aware UTC/schema 迁移与 clock 注入。
- #40 容量管理只能采用不删除整理数据的方案；#41 requirements lock 与基础镜像 digest。
- #42-45 验证码后端、异常、重复选择器与延迟配置加载等结构改造。
- #46 索引与批量锁；#47 剩余全量加载；#48 Alembic metadata 与生产 auto-create 策略。
- #50 热路径快照缓存；#56 非 root 浏览器；#57 多子进程监督。
- 第三批依赖注入、去运行时函数克隆、完整路由表、存储 policy 边界、测试组织与 CI。

行数政策沿用 AGENTS.md，没有修改基线、排除项或自行放宽测试目录。
后续先补齐全部剩余代码与验证任务；部署、应用重启、NAS/PC2 实际运行测试继续延期。

## 续作：AVM facade 显式依赖收口

`src/avm/service.py`、`src/avm/service_health.py`、`src/avm/service_data.py`、
`src/avm/service_prediction.py` 和 `src/avm/service_review.py` 已将
`service_context` 的通配符导入替换为显式导入。保留
AVM facade 的公共常量、类型依赖和五个可 monkeypatch 的函数，并继续由
`_ServiceFacadeModule` 将这些 patch 同步到各 mixin 模块。这样减少隐式名称泄漏，
同时不改变 `AVMService` 的公共导入路径和现有测试替身语义。

`src/avm/engine.py` 同步改为显式重导出 `predict_price`、`predict_fair_price`、
`AVM_CONFIG_MANAGER` 和 `get_active_risk_factor_overrides`，避免通过预测引擎的
通配符链泄漏整个内部模块命名空间，同时保留现有配置 monkeypatch 入口。

`src/avm/engine_temporal.py`、`src/avm/engine_statistics.py`、`src/avm/engine_guards.py`
和 `src/avm/engine_predict.py` 也已改为显式声明核心
时间、筛选、权重和风险依赖；
保留供下游统计、护栏和预测模块使用的内部符号，避免在底层引擎迁移过程中改变
预测行为。AVM engine 聚焦回归 **48 passed**。

验证：AVM engine、HTTP contract 与 weighting 聚焦集合 **53 passed**；本项不包含
FunctionType 动态克隆、其他 facade 或生产数据库迁移，剩余 facade 收口仍未完成。

`src/server.py` 的 facade 重绑定循环已抽取为 `_publish_rebound_function()`，统一维护
`FunctionType`、`src.server` globals、`_CONTEXT` 同步和函数元数据行为。没有改变动态
路由绑定或历史 RuntimeState patch point。`test_server_source_contract.py` **14 passed**。

`src/captcha_target.py` 已移除对 `captcha_context` 的通配符导入，改为显式声明 CDP
目标管理实际使用的标准库、`requests`、URL 解析函数和页面目标上限常量。保留
`CaptchaTargetMixin` 的模块级 monkeypatch 入口。验证码 deadline 和日志回归 **17 passed**，
并通过模块导入 smoke；其他 captcha facade 仍需继续迁移。

`src/captcha_cdp.py` 同样已改为显式声明 JSON、CDP 网络、WebSocket、URL 编码和浏览器
身份注入依赖，保留共享模块对象的 monkeypatch 行为。针对 captcha deadline、日志和
相关 solver 分片的聚焦回归通过；扩展 captcha 合并集本次为 **300 passed, 1 failed**，
唯一失败是既有 `test_live_drag_distance_uses_remaining_track_geometry` 的源码断言，
与本次 import 收口无关，未将其报告为全套通过。

## 续作：安全运行控制、快照缓存和存储查询

以下为用户明确延期部署之后新增的源码工作。全部测试使用临时目录、合成凭据或独立
`crow_quality` 数据库的新 UUID schema，没有对整理数据进行删除、覆盖恢复或清理。

### 桌面开始、暂停与恢复的安全传输

- `desktop_runtime_controls.ts` 使用 native 配置地址与 helper 发起 start/pause/resume，
  不把 operator token 交给浏览器 fetch。浏览器回退要求显式 token，并复用已有 HTTPS/
  loopback origin 检查。未知 action 在发出请求前拒绝。
- Rust action 白名单和 `desktop_settings_client.py` 同步支持三个固定 action；helper
  强制配置 origin、空 JSON body、固定目标路径、私有 CA 和禁止重定向。
- 独立 TLS 网关先验证 operator 角色，再经 `collection_runtime_proxy.py` 转交同机 API。
  agent token、任意 URL、非 loopback 主机、query、path、GET 变更请求均不被允许。
- TLS 网关部署时需显式提供 `FAPAI_CONTROL_LOCAL_API_BASE`，值为与网关处于同一网络
  命名空间的 API loopback HTTP origin，包含实际端口。没有隐式远程地址回退；未配置
  返回 503。主 API 与网关必须使用同一 operator token 文件；如果主 API 配有优先级更高的
  `FAPAI_CONTROL_PLANE_TOKEN`，也须与之匹配。此项配置尚未写入任何运行环境。
- NAS 的网关发布包需要包含 `tools/collection_runtime_proxy.py`；桌面 helper 没有导入
  此网关模块，因此桌面包无需携带它。

验证：合成私有 CA 的真实 loopback TLS、固定路由、角色拒绝及重定向拒绝测试组
**20 passed**；桌面 `npm run typecheck` 通过、`npm run test` **31 passed**；Rust
`cargo fmt --check` 通过，`cargo test --locked` **9 passed, 1 ignored**。忽略项为明确要求
手动启用的安装包在线探测，没有在本次执行。没有构建或激活新的桌面发布包。

此处补齐了上文第 1 项“native helper 不支持运行控制”的代码缺口；统一所有写接口的
鉴权和其他客户端迁移仍未完成，不能据此将 #2 或 #15 整体标记完成。

### 快照缓存与 OS 鼠标默认策略

- `runtime_snapshot_cache.py` 提供按 resolved path、JSON/JSONL 类型及文件 signature
  区分的 LRU 缓存。signature 包含 mtime_ns、大小、ctime_ns 和 inode；缓存条目最多
  128 个，缓存源文件字节预算 8 MiB，超预算文件仍可读取但不驻留。此预算不是 Python
  解析后对象的精确内存上限。
- 每次返回深拷贝；文件变化、损坏、读取失败或过深 JSON 不返回旧成功值；读取过程中
  文件变化也不发布该结果。只移除内存缓存条目，完全不删除文件。
- `server_hybrid_runtime.py` 的两个公共 JSON/JSONL 读取助手已接入。manual review
  其他独立读取函数尚未全部接入，#50 仍是部分完成。
- #42：`captcha_os_windows.py` 默认禁用 OS 鼠标，只有显式
  `FAPAI_SOLVER_OS_MOUSE` 真值才启用；移除生产代码对 `PYTEST_CURRENT_TEST` 的判断。
  测试只注入 policy/mock target，不接触鼠标或真实浏览器。

验证：首次快照/鼠标/HTTP 组合 **53 passed**；之后补充过深 JSON 保留源文件的用例，
随最后一次存储组合测试验证通过。

### 存储查询和非破坏性索引迁移

- `repository_detail_claim.py` 的 detail 和 analysis 两条认领路径均由逐候选 SELECT
  改为批量 `IN (...) FOR UPDATE SKIP LOCKED`。仍按现有优先级获取候选、加锁后重新
  校验状态和租约，再按业务优先级排序；没有降低现有租约保护。
- `repository_seed_scan_jobs.py` 只查询 `DISTINCT status` 集合，保留空任务、completed、
  blocked、in_progress、pending 的原有判断，避免加载全部 progress ORM 对象。
  #47 的分页认领仍有其他全量 job 查询，需要继续处理。
- 新增迁移 `20260921_0012` 和一致的模型索引：
  `fapai_seed_item(status, first_seen_at)`、`property_ingest_event(event_type, created_at)`。
  upgrade 只建索引，downgrade 只撤销这两个索引；不删除事件或条目。
- 保留期删除没有实现，也不允许按原建议加入。后续容量管理应保留历史事件和整理数据。

验证：初次 SQLite 索引迁移、种子队列和数据保留测试 **67 passed**；独立 PostgreSQL
并发与 SQLite/PostgreSQL 索引双向迁移组 **6 passed**。之后补充 analysis 两 worker
竞争用例；最终 PostgreSQL 五类认领、种子队列和快照缓存组合 **64 passed**。
所有 PG 测试 schema 保留，没有清理数据库。索引迁移尚未在业务库执行；未来激活时需
安排实际表的建索引窗口，这些测试不构成线上迁移或完整 Alembic 历史链验证。

### 尚未完成的范围

续作门禁：有效行数 checker 自测 **19 passed**；最终 ratchet **1016 files** 通过，
`git diff --check` 通过。本轮检查的源码/测试/文档均无 UTF-8 BOM；Git 状态没有删除项，
其他 AI 的未提交成果仍保留。两轮独立只读核验覆盖运行控制通道及存储/缓存改动。

原清单仍有全量写接口授权、客户端 HTTPS/角色迁移、RuntimeState/线程化/长任务异步、
captcha deadline、aware UTC/clock/schema、完整 LLM 证据与指令分离、依赖 lock/digest、
完整快照缓存、非 root 浏览器、进程监督，以及第三批结构改造和 CI 等任务。
第三批要求把约 97k 行测试合为不超过 30 个模块，与现行有效行数门禁有直接冲突，尚未
获得修改门禁的明确授权；没有通过删除测试、修改 baseline 或增加排除项规避该冲突。
本次不会将这些剩余项标记已完成，也不进入部署阶段。

## 最新续作：deadline、依赖、CI、LLM 与迁移门禁

本节覆盖上文尚未更新的状态。原清单仍未全部完成；没有部署、重启本地 Crow、NAS、PC2
或人工认证浏览器，没有迁移业务数据库，没有删除整理数据、Cookie、历史事件或发布包。
其他 AI 的工作树改动保留，未执行暂存、提交、回滚、镜像清理或容器卷删除。

### 已实现并验证的新增范围

- #18：`captcha_budget.py` 为 solve 提供 monotonic deadline、取消 Event、有限锁等待。
  retry、preflight、slider、fallback、OS 输入等待改为可中断等待；CDP HTTP/WebSocket
  超时受剩余预算限制；服务器重试与 CDP readiness 共用 deadline。停止后释放已按下的
  CDP 鼠标，保留需要人工恢复的页面，不为清理再发超时网络请求。OCR/native 调用仍采用
  合作式取消，不宣称能强行终止所有底层调用。测试修复了旧模拟时钟与全局状态泄漏。
- #41：增加完整 hash 的 `requirements.lock` / `requirements-dev.lock`，声明 numpy，
  删除已核对无使用的 selenium-wire、requests-toolbelt；Python 3.10 限定有 wheel 的
  onnxruntime 版本。Python、Node 基础镜像及 CI PostGIS 镜像固定到实际查询的 digest。
  Linux 使用 opencv-python-headless，Windows/macOS 保留 opencv-python，避免两个包
  同时拥有 cv2，以及纯 Python slim 环境下图形库缺失造成 OCR 导入失败。
- CI：新增 `.github/workflows/ci.yml`、隔离测试运行器与显式快路径、security、postgres
  分组；快路径超过 60 秒会失败，普通组有 180 秒上限。Python 增量 Ruff/mypy、桌面
  typecheck/test/build、Rust fmt/test 和定时 Playwright smoke 已接入。没有运行 hosted
  workflow，也不将本地结果表述为 GitHub CI 已通过。
- #57 的进程监督部分：新增 `process-supervisor.sh`，等待任一关键子进程退出，使用
  共同 grace deadline 停止并 wait/reap 同组子进程；watchdog 使用实际父 PID。
  两个 browser Dockerfile 和发布包预检均包含 helper。真实 Linux 假子进程以状态 0、7
  退出时，均验证其兄弟进程被收尾回收。没有运行发布脚本。
- #45：删除 import 阶段 secrets.json 读取及全局凭据别名，模型池/selector 首次使用时
  加锁加载，迁移了 data_fixer、auto-tuner 和根目录诊断入口。QualificationStore 按进程、
  绝对路径、凭据与请求策略摘要复用，最多缓存 16 个；共享 store 的 scan_lock 与 SQLite
  lease 共同阻止重叠扫描。取消 slot 等待不会惩罚模型评分；selector 的满容量等待也有
  deadline/取消检查，未知、禁用、空模型池统一报 backend unavailable。
- #20：商品、拍卖、AVM 和资格评估通过共同 EvidencePrompt 保留原字符串调用契约，
  HTTP、资格池及 WebSocket 传输均把固定指令放在 system、来源证据放在 JSON user
  数据字段；转义角色/标签文本，集中输入与输出预算。抓取文本不会拼入 system。
  捕获 wire payload 的测试验证三条传输路径；这不等同于证明模型绝不会受提示注入影响。
  资格版本改为 `collection-exact-v2-evidence`，旧资格记录保留，不复用旧提示的评分。
- #48：生产 auto_create 默认关闭，显式 `FAPAI_DB_AUTO_CREATE=1` 仍可用于空测试库。
  Alembic 接入 Base.metadata；PostgreSQL 元数据补全初始迁移原有的 geom/GiST，过滤
  真正属于 extension 的表。删除 alembic.ini 中隐式数据库凭据默认值，迁移需明确 URL。
  没有改写历史 migration 或创建业务表。SQLite/PostGIS 完整升级链、保留证据以及
  `alembic check` 通过；新增测试列能确实触发 drift 错误，过滤器没有将检查变成空操作。
- #50：除了已有 hybrid JSON/JSONL 缓存，gap audit、optimization progress、action
  effectiveness、manual review 文件快照和校准 JSON 对象检测也接入统一缓存。
  DB receipt 仍实时查询，写入流程不使用缓存。补充了 facade 调用测试并修复克隆函数
  globals 无 snapshots 的真实回归；损坏文件不返回旧成功值，也不改写源文件。
- #43 的裸 except 部分：`src/` 裸 except 已清零，Ruff E722 全目录检查加入 CI。
  全量 print/logging 迁移和其他 broad exception 的分层处理仍未完成。

### 额外数据保护修复

核对异常处理时发现 `update_item_in_json` 和地区列表保存会把损坏 JSON 当空数据继续
写回。新增 `archive_json_io.py`：读取失败或形状非法即报错；序列化、flush、fsync 成功
后才原子替换目标。失败保留确认文件和 `.tmp` 待恢复快照，临时快照不会被 `*.json`
归档扫描误认。测试验证损坏 JSON、非法形状、fsync/replace 失败时原 bytes 不变，以及
成功追加保留其他记录。所有这些测试只写临时测试目录。

### 验证记录与发现的测试环境问题

- LLM/legacy caller 第一轮 **202 passed**；新增证据边界后的综合组修复假响应结构。
- 最近一次包含 LLM、planner、dual-write、entrypoint、server status、归档保护与
  data_fixer 的组合：**483 passed，3 failed**。3 个失败为历史正向 HTTP 测试未携带
  已要求的 operator token；补充合成凭据后针对这 3 项重跑：**3 passed，186 deselected**。
  没有关闭生产鉴权来让测试通过，也没有把分次结果伪称为一次全仓通过。
- Windows 隔离快路径：**100 passed，10.17 秒总耗时**；security：
  **78 passed，2 skipped，13.70 秒总耗时**。跳过的是 POSIX 子进程监督测试，已在 Linux
  实际执行相同责任的测试。
- 真实独立 Postgres/PostGIS 分组：**10 passed，8.84 秒总耗时**。包括五种双 worker
  认领、两种数据库索引保留测试、显式 auto-create，以及 SQLite/PostGIS 完整迁移链、
  数据保留与负向 drift 检测。专用容器 `crow-quality-postgis-bf3b00e4`，仅 loopback
  暴露且没有业务 bind mount；保留随机 schema，没有执行数据库清理。
- Linux 首次测试缺少 jobs 源码挂载，未收集成功；第二次源码直接经 NAS bind mount
  读取，全部快路径测试通过但 **71.20 秒**，正确触发时限失败。将只读挂载的测试源码
  复制到测试容器本地文件系统后，快路径 **100 passed，3.83 秒总耗时**；security
  **79 passed，1 skipped，10.05 秒总耗时**。Linux 跳过的是 Windows launcher 用例。
  容器仅用于测试，未替换任何应用容器。
- cv2 导入实测发现 Linux 安装 full OpenCV 缺少 libxcb；随后调整平台依赖标记并重建
  hash lock。最终全新 Linux 锁依赖安装与 OCR 导入验证结果另见下方追加记录。
- 全 `src` Ruff E722 通过；本轮责任模块 E9/E722/F63/F7/F82/B 通过；
  captcha_budget、llm_evidence_prompt、quality_suites 的 mypy strict 通过。

### 仍未完成的任务

上述结果不代表三批清单全部完成。还包括：全部写接口与 worker/userscript 的统一鉴权；
全链路 HTTPS 与角色凭据迁移；RuntimeState、线程化及长任务异步；aware UTC/clock
和兼容迁移；#47 剩余分页队列全量查询；非删除式容量管理；非 root 浏览器；验证码
指针/选择器抽象；去 FunctionType/import-star、路由表、storage policy 边界、认证码
单一来源、控制器/拓扑合并、桌面剩余 TypeScript 迁移、测试组织及全量 logging。

测试模块不超过 30 个的要求与现行 700 有效行上限冲突，已经提出澄清，尚未获得变更
行数政策的答复。继续保留全部测试、原 baseline 和排除规则，不通过删测试满足指标。
未进入部署阶段；已整理的数据及线上配置仍按用户要求保留。

### 最后一次锁依赖与本地门禁结果

全新 Python slim 测试容器按更新后的 hash lock 安装成功；第一次 OCR 探针因宿主到
bash 的嵌套引号错误未执行，修正测试命令后复用该隔离依赖层，没有改动包来绕过错误。
`crow-quality-headless-final-67d6240c` 在 network=none 下：cv2、ddddocr、numpy、
onnxruntime 全部导入成功，`pip check` 通过；fast **100 passed，3.83 秒总耗时**；
security **79 passed，1 skipped，8.39 秒总耗时**。Windows 验证虚拟环境按同一更新锁
检查 **72 packages compatible**，四个 CV/OCR 模块导入成功。

最终有效行数门禁：checker 自测 **19 passed**；ratchet **1032 files** 通过，
`>1500=1` 为未改变源码的历史基线项，`701-1500=0`、`501-700=0`，无新增豁免。
`git diff --check` 通过；Git 状态 182 个未提交/未跟踪路径，没有删除项，也没有
FPFData/datas/output/secrets/release 路径的版本化变更。已检查变更源码、配置和文档无
UTF-8 BOM。此 Git 检查不等于遍历未版本化业务数据做全量审计。

剩余任务继续以上一节清单为准，尚不能报告“全部优化完成”或开始部署。

## 续作：种子查询、HTTP 路由和存储显式依赖

本节更新前述剩余项的状态。仍未部署、替换容器、重启应用或操作业务数据库。

### 本次已实现

- #47：`seed_scan_candidates.py` 用 SQL 排序和每批 128 条的 keyset 分页读取候选。
  删除认领前全量加载 job/progress 的步骤；只加载类别名称来计算 policy 排序。
  前面的候选被租约、失败冷却、页数上限或其他 policy 阻挡时，继续读取后面的窗口。
  顺序模式仍按区域、类别、job、sort、page 分发；并行模式保留 retry/page 优先级。
- claim 前继续先锁 job，再锁定并刷新当前 progress。独立复核指出初版仍会在锁 job
  后加载全部 sort，已改成只刷新当前候选、分批读取需要检查的前序 sort。
  测试覆盖超过 512 个不可用候选、其他 policy 占满窗口、单 job 超过 512 个 sort，
  并检查实际实例化的 ORM 行数。真实 PostgreSQL 验证 keyset 后续窗口和双 worker 排他。
  全程未删除 job、progress 或业务证据。
- #25 与第三批路由改造：GET/POST 静态路由统一为 `(method, path)` 表，包含 engine、
  settings 和 manual-review 注册项；注册重复路由即报错。仅静态资源和 item ID 保留
  必要的前缀匹配。全部 `_server_*_branch_NN` 改为业务名称，不保留旧名字别名。
- POST/DELETE 使用 `urlparse(self.path).path`，query 仍供 handler 读取；修复
  pause 带 query 被误认为 resume、recovery claim 被误认为 result、manual captcha
  带 query 失去人工处理类型的问题。pause/resume 也读取有大小限制的 JSON body。
  DELETE 先鉴权再解析 body，缺失配置使用统一 fail-closed 错误。
- 测试的路由枚举改读实际路由表；新增对每个 POST 路由携带 query 和非法 suffix 的
  HTTP 检查，以及 pause/recovery 的真实分派检查。旧测试的手工 handler 补充正确的
  Content-Type；只验证错误脱敏的 stub 改发空 body，避免 Windows 未读 body 的连接重置。
- 第三批显式依赖：16 个 repository Mixin 全部移除 `repository_context import *`。
  stdlib、SQLAlchemy、models 和业务 helper 分别从实际来源导入。现有 repository
  门面和 context 的动态导出仍保留，尚未完成整个门面重构。
  readiness 的字段名与聚合结果使用 `zip(strict=True)`，避免今后列数漂移时静默截断。
- CI 新增这 16 个 Mixin 的 import/F401/F403/F405/F821 等检查，以及新路由和候选模块
  的 lint、格式和 mypy strict。实际 `--show-files` 返回 16 个文件，未使用空扫描充当通过。

### 本次验证

- 最后一次存储与 HTTP 综合回归：**298 passed，131.23 秒**。包含 DB dual-write、
  种子队列、generic collection、observer query budget、manual-review store/jobs、
  路由边界、source contract 和 auth stage isolation。
- 最后一次独立 Postgres/PostGIS suite：**24 passed，40.31 秒总耗时**，包含新候选
  窗口测试、原有认领并发、索引、完整迁移及负向 drift 检查。仅使用已核验的
  `crow-quality-postgis-bf3b00e4` 测试容器和新增随机测试 schema，保留测试数据。
- 本轮 security：**83 passed，2 skipped，21.49 秒总耗时**，跳过的是 Windows
  无法执行的 POSIX 监督用例。此结果发生在最后的 Mixin import 调整之前；之后使用
  上述 298 项和 24 项回归验证 import 调整，没有将分次结果拼成全仓一次通过。
- 新模块 Ruff 格式检查及 mypy strict 通过；16 个 Mixin 的增量 lint 通过。
  对旧 server 动态命名空间尝试 F821 会报告既有动态导入符号，本次没有添加忽略规则
  将其伪装为通过；server 本身的 E9/E722/B 检查通过。
- checker 自测 **19 passed**；最新 ratchet **1035 files** 通过，无新增例外；
  `>1500=1` 仍为未改动源码的历史基线，`701-1500=0`、`501-700=0`。
- Git 状态检查为 198 个未提交/未跟踪路径，无删除项，无 FPFData/datas/output/secrets/
  release 的版本化变更；检查到的变更源码、配置、文档均无 UTF-8 BOM。
  此检查未遍历或改写未版本化业务数据。

### 尚未完成，不能部署验收

#47 和 #25 本次已处理。第三批路由的统一资源 404/error envelope、GET 副作用迁移、
全部写接口鉴权及客户端凭据迁移仍未完成。其他剩余项包括 RuntimeState/线程化/异步任务、
aware UTC 与兼容迁移、全链路 HTTPS 和角色 token、非删除式容量管理、非 root 浏览器、
验证码 backend/selector 抽象、其余 FunctionType/import-star 门面、storage policy 解耦、
认证码单一来源、控制器/拓扑收敛、桌面剩余 TypeScript、测试组织及 logging。
仍保留原有效行数政策、全部既有测试和数据；尚未满足“清单全部完成”。

## 续作：认证契约、验证码后端及桌面基础依赖

本次继续修改和隔离验证，未执行部署脚本，未重启 Crow、PC2、NAS 或人工认证浏览器。
未读取或改写业务数据库，未删除 Cookie、资料、备份、release 或历史测试产物。

### 本次已实现

- 第三批认证码单一来源：新增纯模块 `src/auth_recovery_codes.py`，集中活动状态、
  超时原因、失败码、快照可用状态与原有中文桌面提示。NAS、PC1 与 snapshot endpoint
  使用同一份定义；生成器输出 `auth_recovery_codes.generated.ts`，CI 运行 `--check`
  阻止漂移。未知状态/原因及对象、列表等异常 wire 值安全回退，不回显内部诊断。
- TS 消息查询检查自有属性，`toString`、`constructor`、`__proto__` 等输入不能命中
  原型链。保留各阶段及 legacy 的既有语义；本次未退役 legacy 状态机。
- 桌面部署文件列表补入 Python registry；standalone helper 测试在临时目录中使用
  `python -I`，验证不依赖仓库导入回退。只检查部署脚本语法，没有执行部署。
- #44：新增 `captcha_dom.py`，集中 slider/track、验证、预检、重试和 Playwright/OCR
  fallback 的选择器；共享主文档及一层同源 iframe 遍历。保留各调用者原有的选择器
  范围、隐藏 iframe 策略及坐标语义，不扩大 fallback 的匹配范围或递归深度。
  修复 x 偏移为 0 的 iframe 被误标为 main 的问题。
- #44：新增 `OSPointerBackend` 协议及 PyAutoGUI、Win32、uinput 三个实现。
  实际代码中只有三个可选拖拽后端；X11 是坐标映射和残留按键恢复能力，继续独立。
  默认仍为 PyAutoGUI，native/uinput 显式启用；uinput 设备生命周期及可中断反馈
  收敛循环由 solver 持有。构造函数支持注入后端，测试不打开真实输入设备。
- 独立复核发现 OS 拖拽会吞掉 `SolveStopped`，已让停止信号穿过输入初始化、焦点、
  映射和拖拽异常边界。真实 budget 的 deadline/cancel 测试验证：先释放已按下的
  按钮，再由外层关闭 solver 资源并释放锁，不把停止原因改写为一般拖拽异常。
- 第三批桌面依赖：新增 `desktop_value.ts`、`desktop_dom.ts`、`desktop_native.ts`。
  object 不再放在 overview 中，移除 overview/auth_scope 的运行时循环；三个 element
  helper 和 HTML escaping 共用定义；Tauri 检测与调用共用入口并保留方法 receiver。
  native settings/restart 的串行队列和超时策略保持不变。其余 JS 迁移仍未完成。
- desktop smoke 实际运行暴露旧脚本未填凭据就等待暂停成功的问题。现在先验证无
  凭据时不发送控制写请求，再填隔离 fixture 凭据验证暂停/开始；preview 服务同时
  对 pause/start/restart 校验 fixture token。没有放宽产品鉴权以迁就测试。

### 本次验证

- 最后一次认证、stage isolation、standalone bundle、captcha DOM/solver/pointer/
  deadline/X11 聚合回归：**241 passed，97.84 秒**。使用锁定依赖的 Python 3.10，
  临时工作目录、禁用业务 DB、独立数据根和 solver state，关闭真实 OS 输入。
- 快路径：**123 passed，12.78 秒总耗时**，包含新增契约、DOM、pointer 和 bundle
  用例。DOM 测试在 Node VM 中执行实际发给 CDP 的 JavaScript。
- desktop `typecheck` 通过；Node 测试 **34 passed**；Vite build 通过（38 modules）。
  此 build 只生成本地构建产物，未激活 desktop EXE，也未执行 Tauri 发布。
- 浏览器 smoke 首次因缺少 Playwright 对应 headless-shell 版本而不能启动。
  使用已安装 Edge 的独立临时浏览器上下文后，authentication/settings 通过；collection
  暴露上述凭据问题，修正后单独重跑通过（8.3 秒总耗时）。这些是分次验证结果，
  不是宣称修改后的三个 smoke 曾在同一轮全部通过。新建的 UUID 测试目录均保留。
- 新增 Python 模块的 mypy strict、增量 Ruff lint/format、部署脚本 PowerShell
  解析通过；生成 TS 契约与 Python registry 一致。
- checker 自测 **19 passed**；ratchet **1047 files** 通过，无新增例外；
  `>1500=1` 为未改变的历史基线，`701-1500=0`、`501-700=0`。
- Git 检查为 **222** 个未提交/未跟踪路径，无删除项，无受保护数据目录的版本化
  变更；检查到的变更源码/配置/文档无 UTF-8 BOM，`git diff --check` 通过。
  未遍历未版本化业务数据，未用上述 Git 结果声称已做全量数据审计。

### 剩余范围

本次完成认证码单一来源及 #44 的代码改造，并推进桌面共享依赖。仍不能报告清单全完：
全部写接口鉴权与客户端迁移、GET 副作用/统一资源错误、RuntimeState/线程化/异步任务、
aware UTC 兼容迁移、全链路 HTTPS/角色 token、非删除式容量管理、非 root 浏览器、
其余 FunctionType/import-star 门面、storage policy 边界、legacy 协议退役、控制器/
拓扑收敛、剩余 JS/TS 与 lint 门禁、测试组织、logging 等仍需继续处理。
保留数据和现行有效行数门禁的约束不变，部署仍按用户要求推迟。

## 续作：采集客户端凭据绑定与提交确认

本轮已完成的独立部分：

- 新增 `src/collection_api_credentials.py`。配置
  `FAPAI_COLLECTION_WORKER_TOKEN_FILE` 后，HTTP helper 按需读取该 token，使用
  `X-FAPAI-Collection-Token`，只自动附加到 `FAPAI_API_BASE_URL` 指定的同一
  scheme/host/port 和 `/api/` 路径。默认端口规范化、路径边界及异常配置均有测试。
- 自动 worker 凭据不发送给外部供应商、其他端口、CDP 路径或其他 API 前缀。
  对配置目标的远程 HTTP、路径点段及 percent 编码歧义先拒绝，再读取 token。
  支持 HTTPS 或 loopback 隧道；不关闭 TLS 校验。显式传入的既有角色 header 不被替换。
- 这是可选的客户端准备工作：未配置新 token 时维持现有调用；服务端尚未启用
  worker 总鉴权，不能将本项报告为“全部写接口已鉴权”或“全链路 HTTPS 已完成”。
  尚未向任何现有安装写入新凭据，也未修改生产环境变量或 Compose 运行配置。
- `internal_api_http` 的 GET/POST 接入凭据绑定；POST 可复用调用方提供的 session，
  默认仍由 helper 管理无环境代理的 session；全部请求禁止自动跟随重定向。
- `hybrid_seed_collector` 和 `area_followup_persistence` 的直接 POST 改用共享传输。
  修复种子 batch 失败后仍提交进度的问题：3xx/4xx/5xx、错误 envelope、空或无效
  回执均阻止 progress 请求，避免未保存种子时将扫描页标为完成。
- 桌面 helper 打包列表补入新依赖；质量测试运行器清空新 token-file 环境变量，
  防止本机测试意外读取安装凭据；CI 增加新模块的 lint、format、mypy 和负向测试。

本轮验证：fast **153 passed，27.02 秒总耗时**；security **100 passed、2 skipped，
23.50 秒总耗时**（Windows 跳过 POSIX 监督用例）；面积补全回归 **11 passed**。
首次面积回归发现两个旧 FakeSession 未接收 `allow_redirects`，已让 fake 检查禁止
重定向，并补齐真实 response 的 status_code 契约，然后重跑通过。
新增模块 mypy strict、增量 Ruff lint/format 通过；checker 自测 **19 passed**，
ratchet **1049 files** 通过，未修改既有行数规则或 baseline。

### 用户脚本生成产物需要确认

现有安装文件有 **1909** 行有效代码，由 12 个受门禁检查的源文件拼接而成。
源文件均为 58 到 275 行，生成输出必须保持单文件安装。修改鉴权 helper 后重新生成
会违反当前“历史超限文件内容不得改变”的规则。没有擅自放宽规则、排除产品源码、
更新 hash 检查或把未经客户端迁移的服务端鉴权开关提前打开。

具体事实、baseline commit、policy/source hash 和源文件行数已记录到
`docs/plan/userscript-generated-artifact-review-20260921.md`。已请求用户确认是否仅对
这一份可重复生成的安装文件采用生成产物规则，并继续检查全部源文件与生成一致性。
此确认点来自项目 AGENTS.md 的行数政策与现有单文件安装约定，未引用 Skill 来添加审批。

业务数据、资料、Cookie、profile、备份和 release 均未删除，部署仍未执行。
全部写接口的服务端收口和其他未完成结构任务继续保留，清单尚未完成。

## 恢复会话 01a0c1e9：写接口鉴权、客户端与验证续作

本节更新上文过期状态。未部署、替换容器、重启应用或修改业务数据库；没有删除整理
数据、Cookie、profile、备份或 release。已有工作树改动继续保留，没有暂存或提交。

### 已恢复并验证的实现

- 服务端每个已注册 POST 在分派前进入统一鉴权，新增路由默认要求 operator。
  worker、node recovery、operator、engine/settings agent 使用明确角色边界。
  任务认领、resume、replay 和生成报告的旧 GET 返回 405，并提供 POST 替代路径。
  新 HTTP 安全测试遍历全部 POST 路由，验证无凭据和错误凭据不能产生业务副作用。
- 用户脚本使用独立 worker/operator 凭据，绑定配置的 loopback 端口；认领使用 POST，
  session_id 放 JSON body。单文件生成例外已经得到用户确认并实现，详情和完整性 hash
  见 `userscript-generated-artifact-review-20260921.md`。没有扩大手写源码或测试例外。
- 桌面 manual_update/reanalyze/reset_links 经固定 native helper 和 HTTPS operator
  通道发送；浏览器回退须显式凭据，不能向远程 HTTP 发送秘密。Rust action 白名单、
  Python helper、同机代理、打包依赖和前端测试已同步。
- hybrid seed claim 改为共享 POST helper，session_id 不再放 URL；旧 fake session
  同步检查 POST body 和禁止重定向。相关 547 项回归通过，见下文时间边界。

### 本次新增：Python 节点凭据与私有 CA

- `collection_api_credentials.py` 在明确配置的 API origin 下，仅给三个 node-auth
  POST（complete、force_reset、resume_after_cooldown）附加现有 recovery 凭据。
  普通 worker 请求不读取 recovery 文件；其他 origin、端口、CDP 路径不自动获得它。
  缺失、无效或与 worker 相同的 recovery 凭据被拒绝；每次读取支持轮换。
- 显式 supplied 角色凭据继续由调用者负责，不自动升级成其他权限。只有 recovery
  配置时，独立 PC1/helper 的显式传输和普通 CDP 请求不被强制绑定到 collection origin。
  此兼容步骤不等于完成 PC1/PC2/desktop 三角色全部凭据退役和迁移。
- `FAPAI_API_CA_FILE` 为共享 GET/POST 提供私有 CA，仅用于绑定 API；未设置时使用
  正常证书验证，配置文件不存在即失败。真实合成 TLS 测试验证 GET/POST 成功及移除 CA
  后拒绝不可信证书，没有连接线上 API。
- 独立复核发现 requests.Session 会合并旧默认角色 header，已用单请求 None 覆盖
  清除默认 worker/recovery/operator header，再加入本次角色，不修改共享 session。
  supplied session 的 verify=False 不能关闭本次证书验证。测试检查真实 requests
  PreparedRequest 和 adapter options，未用假的字典合并模拟替代 requests 行为。
- `check_server.py`、`unpause_check.py` 改为配置驱动的安全 API 地址和共享传输；
  恢复与认领使用 POST，恢复缺少 operator 文件不发送写请求。测试只使用替代传输，
  本次未实际运行这两个脚本访问应用。
- 隔离测试运行器清空新增 CA 环境变量；CI 增加新角色策略、操作合同和诊断客户端
  的增量 lint/format/mypy 检查。没有运行 hosted CI。

### 新鲜验证与失败边界

- Rust 官方 formatter 已修复中断点的格式错误；`cargo test --locked`：9 passed、
  1 ignored。忽略项为显式安装包在线 probe，本轮未执行。
- 最新 fast：172 passed，23.31 秒总耗时；security：125 passed、2 skipped，
  22.59 秒总耗时。跳过的是 Windows 上的 POSIX 进程监督用例。
- hybrid seed、PC2 solver、standalone desktop bundle：547 passed，50.89 秒。
  此结果在后续 supplied-session 默认 header 清理之前；该清理由上述最新安全组验证，
  不能把不同时点结果拼成一次全仓通过。
- desktop typecheck 通过，Node 36 passed，Vite build 通过；Edge 独立临时 profile
  下 collection/authentication/settings 三条 smoke 同轮全部通过，23.6 秒。
  没有附着、重启或关闭人工认证浏览器，没有生成或激活新的桌面发布 EXE。
- userscript/checker 四个 Node 测试文件：51 passed；ratchet 通过。新 Python 模块
  strict mypy 与增量 Ruff 通过。新增 CI 检查暴露的旧 server_routes 格式问题已用
  官方 formatter 修复，没有关闭检查。
- 扩大到 `test_avm_http_contract.py` 和 `test_server_source_contract.py`：
  **251 passed、110 failed，65.28 秒**。这组未通过，不能报告 HTTP 全量回归通过。
  失败包含仍调用 GET 写路由、未携带新凭据的旧请求、GET-only 数值路由 inventory、
  新错误码契约和依赖 CWD 的源码编译/测试清单检查。需要逐项迁移请求和断言，
  不能用全局替换 urllib 请求或关闭服务器鉴权来隐藏差异。
- 已针对 CWD 问题修正测试根目录解析与 Git cwd；源码编译输出放在测试临时目录，
  避免在工作树产生 pyc。其单独验证结果在下方补充。

### 后续仍需完成

优先收尾上述旧 HTTP 契约和 source inventory；继续检查所有角色客户端及完整 HTTPS
入口/Compose 配置，尚未给任何运行环境写入新凭据或 CA 配置。统一 404/error envelope、
RuntimeState、线程化/异步任务、aware UTC 兼容迁移、非删除式容量管理、非 root
浏览器、其余 FunctionType/import-star、storage policy 边界、legacy 协议退役、
控制器/拓扑、剩余 JS/TS 和测试/logging 改造仍未全部完成。

约 97k 测试行合为不超过 30 个模块仍与现行 700 有效行上限冲突；已批准的单生成文件
例外不授权放宽测试政策。没有删测试或重新生成历史 baseline 来消除该冲突。
清单仍为部分完成，继续遵守全部代码任务完成后再部署测试的要求。

### 本次最后检查

隔离 CWD 下源码编译与测试 inventory 两项定向重跑：2 passed、348 deselected，
35.82 秒。没有重跑或宣称前述 361 项整组已转绿，其余失败仍需处理。
最终 9 个责任模块 Ruff lint/format 通过；ratchet 扫描 1055 个文件通过，
`>1500=0`、`701-1500=0`、`501-700=0`（生成输出按已批准规则单独验证）。
`git diff --check` 通过；255 个未提交/未跟踪路径，删除项 0，受保护数据目录版本化
变更 0，检查到的变更文本无 UTF-8 BOM。这些 Git 检查不等于审计未版本化业务数据。

## 最新续作：旧 HTTP 契约迁移与资源错误状态

本节替代上文“110 failed 仍待修复”和“优先收尾旧 HTTP 契约”的当前状态。
整份三批开发清单仍未完成。未部署、重启应用、访问线上 API 或迁移业务数据库；
没有删除整理数据、凭据、Cookie、profile、备份或 release，没有暂存、提交或回滚。

### 已完成的契约迁移

- 85 处旧 GET 写请求逐项迁移到带明确合成角色凭据的 POST，参数放 JSON body；
  另补齐 12 处原有正向 POST 的凭据。没有猴子补丁改写 urllib 或放宽服务端鉴权。
- 旧 HTTP fixture 把 solver 状态目录绑定到各自临时数据目录，并在结束时恢复环境。
  force-unlock 用例读取正确目录，历史 challenge 状态不再跨测试污染。
- 更新 resume envelope、save-locations 的实际写入失败注入点，以及退役 GET 的
  source inventory；13 个迁移 POST 纳入 JSON 对象请求体检查，28 个旧测试名同步。
- prepare_replay 的 POST alias 使用现有 archive 合同：默认 30 天 / 500 条，
  负数 limit 归零；不增加旧 GET 的 7 天 / 100 条兼容分支。

### 维护操作的写入边界

- 新增 `collection_maintenance_options.py`，统一维护参数的整数与负数处理，
  显式 limit=0 保持为零；超时非正值回到默认值。
- replay/fetch handler 仅在 JSON `dry_run: false` 时允许真实写入与 reload。
  null、0、空字符串及字符串 "false" 均保持 dry-run，避免非法假值意外激活写入。
- `test_maintenance_write_boundary.py` 的 15 个真实 HTTP 用例覆盖三个路由及上述值。

### 资源接口错误状态

- get_item、两个 update_item alias、两个 HTML alias、两个 observer item 入口：
  缺少或空白 ID 返回 400，明确不存在的条目统一返回
  `404 / AVM_DETAIL_ITEM_NOT_FOUND`。
- get_item 数据库查询失败且无缓存时返回 503；已有缓存仍可返回 200。
  observer 存储未启用或缺少详情能力返回 503。服务异常继续返回 500，意外的
  update service 状态不伪装为资源不存在。
- 空任务队列保留 200 与空对象。正常结果 payload 保留原合同。
- 新增 `test_item_resource_errors.py`，覆盖路由 alias、缺参、无存储、资源不存在、
  正常详情、数据库异常缓存回退及非预期 service 结果；已加入 security 和 CI lint。
  独立只读复核确认 detail service 的 id_not_found 与 repository 的 found=false 合同。

### 本次新鲜验证

| 检查 | 结果 |
|---|---|
| 旧 HTTP、source inventory、write access、维护边界、资源错误五文件合并 | 412 passed，27.76 秒 |
| fast 隔离组 | 172 passed；测试 22.95 秒，总耗时 27.39 秒 |
| security 隔离组 | 168 passed、2 skipped；测试 38.46 秒，总耗时 43.91 秒 |
| 有效行数 checker 自测 | 19 passed |
| ratchet | 1058 files；三个超过 500 行的档位均为 0 |
| 维护参数模块和两个新增测试 Ruff lint/format | 通过 |
| 维护参数模块 strict mypy | 通过 |
| git diff --check | 通过 |

security 跳过项仍为 Windows 上的 POSIX 进程监督用例。Python 测试使用新临时目录、
关闭业务数据库并隔离 solver/模型池状态。合并测试最初暴露的 observer 故障注入前置
条件和错误码 inventory 已修复；表中为之后完整重跑结果。新测试的官方 formatter
调整后又通过 security 组，不把第一次失败计为成功。没有运行 hosted CI 或部署验证。

仍需继续完成完整 HTTPS/角色客户端迁移、RuntimeState 与线程/异步任务、aware UTC
兼容迁移、非删除式容量管理、非 root 浏览器、其余 FunctionType/import-star、storage
policy、legacy 认证协议退役、控制器/拓扑、剩余前端 TypeScript 和测试/logging 改造。
测试不超过 30 模块与现行行数上限的冲突仍保留，未扩大用户批准的单生成文件例外。

### 资源查询防御性补充

observer item handler 现在要求详情属性可调用；启用的 repository 若暴露同名非函数
属性，会按存储能力不可用返回 503，而不会落入误导性的 500。新增边界用例后，资源
错误测试为 **30 passed**。未对已有超大 legacy handler 运行全文件 formatter，避免
无关格式化扩散；`git diff --check` 仍通过。

### 凭据目标边界补充

`collection_api_credentials._bound_target` 不再把缺少路径的 API 配置静默补成 `/api`。
现在必须显式配置 `/api` 前缀；根路径和其他路径均在读取凭据前失败。新增两个配置
负向用例后，collection credential 与 node credential 合并测试 **35 passed**。
客户端已有的 session stale-role 清理和私有 CA 验证保持不变；HTTPS 服务端 listener
与 Compose/部署接线仍未完成，不能将 #15 标记完成。

安全隔离组在该约束变更后重新执行：**172 passed、2 skipped，25.56 秒测试耗时**。
跳过项仍为 Windows 上的 POSIX 进程监督用例；没有运行 hosted CI 或线上验证。

## 最新续作：可选 HTTPS API listener

新增 `src/collection_http_server.py`，为 collection API 提供显式可选 TLS listener：

- 证书和私钥必须同时提供，TLS 最低版本为 TLS 1.2；缺少任一文件或证书材料无效时，
  在 runtime 初始化前失败。
- 每个连接在有限握手超时内完成 TLS handshake；明文请求、错误证书和 stalled
  handshake 不会占住 listener。默认未配置证书时仍保持原有 HTTP listener，避免把
  Compose 的 HTTP URL 单独切换成无法连接的 HTTPS。
- `run_isolated_collection_api.py` 增加 `--tls-cert-file` / `--tls-key-file`，
  `docker_entrypoint.build_api_command()` 通过 `FAPAI_API_TLS_CERT_FILE` 与
  `FAPAI_API_TLS_KEY_FILE` 传递；不完整 TLS 配置直接拒绝。
- 新增真实 loopback TLS 测试，验证证书信任、角色鉴权仍在 TLS 下生效、明文被拒绝、
  listener 在异常握手后可恢复以及启动参数传递。测试已加入 security suite 与 CI 增量
  lint/format。此改动没有修改 Compose 默认 URL，也没有部署证书或私钥。

验证：TLS/entrypoint/docker 组合 **47 passed**；新增模块 Ruff lint/format 通过，
`git diff --check` 通过。完整 HTTPS 默认化、Compose secret mount、反向代理和部署
证书供应仍未完成，#15 继续保持未完成状态。

### HTTPS Compose 配置接线补充

collection 与 NAS central API compose 的 API 服务现在显式传递可选的
`FAPAI_API_TLS_CERT_FILE` / `FAPAI_API_TLS_KEY_FILE`。默认值为空，因此不会在没有证书
时改变现有 HTTP 行为；两个服务原有 `/data/secrets` 挂载继续作为证书文件的受控来源，
没有新增公开 bind mount、复制证书或读取运行时 secrets。新增 Compose 文本契约与 TLS
启动组合测试后，相关组 **44 passed**。反向代理、默认 HTTPS URL、证书供应脚本和
worker CA/token mount 仍需后续完成。

### collection worker TLS/角色凭据环境接线

collection compose 中的 12 个 seed/detail/analysis worker 现在都显式接收：

- `FAPAI_API_CA_FILE`，用于已配置 HTTPS API 的私有 CA；
- `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，默认指向共享 secret volume 中的
  `/data/secrets/collection-worker.token`。

默认 API URL 仍保持 HTTP，CA 和 token 环境变量默认为空或受控路径；这不会改变现有
部署行为，也没有生成或写入任何 secret。新增 Compose 计数契约后，`test_docker_entrypoint.py`
全文件 **37 passed**。worker 的默认 URL 切换、token 文件实际供应/权限校验及 NAS/PC2
部署脚本接线仍待完成。

### 异常边界清理补充

扫描 `tools/` 后发现的 3 个旧裸 `except:` 已改为显式异常边界：价格分析日期转换
仅捕获类型/数值转换异常；两个 solver 辅助脚本捕获 `Exception`，不再吞掉
`KeyboardInterrupt` 等进程控制异常。三文件 `py_compile` 通过，当前 `src/` 与
`tools/` 均无裸 `except:`。未扩大改动到无关异常处理或改变 solver 业务流程。

### PC2 worker CA/token 环境接线

`ops/pc2-linux/compose.yaml` 的 `x-common-env` 现在同步传递
`FAPAI_API_CA_FILE` 与 `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，所有 PC2 seed/detail/
analysis worker 通过公共环境块继承同一配置；secret volume 继续只读挂载到
`/data/secrets`。新增的 PC2 Compose 契约用例通过。该文件其余历史部署断言仍有两项
与此前进程监督/浏览器 hotfix 改动不一致，未将失败归因于本次环境接线，也未借机修改
无关部署逻辑。

### 公共状态健康门修复

部署脚本的健康门继续使用无需凭据的 `GET /api/status`，因此公共 recovery 快照现在
保留非敏感的 `enabled` 标志，同时继续剥离 recovery ID、目标和快照摘要。这样健康门
可以验证 recovery 功能已启用，而不会要求部署脚本读取或传递 recovery token。更新了
HTTP guard 回归断言；当前环境没有安装 pytest，本轮只完成 `py_compile` 语法验证，需在
锁定的测试容器中重跑 `test_quality_http_guards.py` 与 `test_nas_centralization_config.py`。

### 搜索任务认领的有界读取

`RepositorySearchMixin.claim_search_task` 已移除对全部活动任务的无界
`scalars().all()`，改为数据库按既有 pending/priority/sort/更新时间顺序排序并以
`yield_per=128` 流式读取，查询本身使用 `FOR UPDATE SKIP LOCKED`，保持双 worker
排他认领语义。当前仅完成 `py_compile` 和 diff 检查；PostgreSQL 并发及大任务集回归
仍需在锁定测试容器中执行。

### collection/worker-node 凭据环境接线补全

默认 collection 的 seed/detail 主服务以及 `docker-compose.worker-node.yml` 的共享环境
现在显式传递 `FAPAI_API_CA_FILE` 和 `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，与已有的
副本 worker、PC2 compose 和只读 `/data/secrets` 挂载保持一致。清除了 collection compose
中两组重复的 CA/token 键，避免 YAML 重复键导致 Compose 解析失败。使用 `FAPAI_NODE_ID`
和临时 `FAPAI_SHARED_DATA_ROOT_HOST` 进行 `docker compose ... config --quiet` 已通过；
尚未切换默认 HTTP URL，也没有供应或复制任何真实 secret。

## 恢复会话 01a0c339：搜索认领与桌面安全配置

此前最后一批搜索认领代码未通过运行验证。本次在锁定的 Python 3.10 环境复现了
5 个失败：空地区优先级生成了非法的 `CASE ELSE ... END`。现已改用 SQL literal，
并将流式查询限制为候选主键；只有实际选中的行才加载 ORM 对象并执行
`FOR UPDATE SKIP LOCKED`，加锁后重新确认状态和租约。有效租约在 SQL 中排除，
迭代结果通过 context manager 关闭。新增 513 行候选队列、跨 policy 窗口、过期租约、
单行物化和真实 PostgreSQL 并发测试，证明一个 worker 持有事务时另一个仍能领取不同任务。

PC1 `RecoveryClient` 现在要求显式安全 API 配置，支持 `FAPAI_API_CA_FILE`，并在每次
请求时重读 token；保留禁用代理和拒绝重定向。公共 Python HTTP helper 对显式传入的
worker/recovery/operator 头同样检查 HTTPS 或 loopback HTTP，关闭无自动凭据配置时
提前返回造成的明文传输绕过。新增真实 TLS、私有 CA、重定向、token 轮换和畸形 origin
测试。没有读取、生成或轮换任何运行中的真实凭据。

桌面配置写入和本地部署准备现在共用 `collection-api-origin.ps1`。省略 API/CA 参数
时保留既有配置；远程明文 HTTP、畸形 origin、不可读或无效安装配置在构建、停止应用和
替换文件之前拒绝。新增 `ApiCaFile` 参数和 Python runtime path 识别，备份范围补入随包
`src/` 文件。`resolve-pc1-auth-python.ps1` 选择一个 Python 应用，修复多个 PATH 命中
被拼成无效命令的问题。测试显式使用具备锁定依赖的解释器，没有放宽产品依赖检查。

### 本批验证

| 检查 | 结果 |
|---|---|
| search policy、新搜索回归、既有 PG 并发组 | 18 passed |
| 完整 postgres 隔离组 | 30 passed，16.08 秒测试耗时 |
| fast 隔离组 | 174 passed，11.57 秒测试耗时，13.25 秒总耗时 |
| security 隔离组 | 208 passed、2 skipped，43.82 秒测试耗时 |
| 安装配置、Python resolver、launcher 定向组 | 23 passed |
| fixture/lint 修正后搜索、TLS、安装配置、runtime config 复验 | 43 passed，29.16 秒 |
| 有效行数工具测试 | 19 passed |
| ratchet | 1065 个文件；501-700、701-1500、超过 1500 均为 0 |
| 本批 8 个 Python 文件 Ruff lint/format、UTF-8 无 BOM | 通过 |
| `collection_api_credentials.py` strict mypy | 通过 |
| `git diff --check` | 通过 |

security 的两个跳过项是 Windows 上的 POSIX 进程监督测试。PG 使用已核验的无业务挂载、
仅 loopback 端口、`crow.purpose=quality-regression` 专用测试容器；每次创建独立 UUID
schema 并保留，没有接入业务库。测试套件运行器的定向列表需要文件名，初次误传
`tools/test/` 前缀导致路径重复，纠正后得到上述 43 passed。

完整 lint 初次发现新测试的 fixture 导入、UTC 调用和 subprocess check 参数问题，
以及 runtime config 的格式差异，均已修正。没有修改行数 baseline、排除项或批准例外。
四个只读子代理均因默认模型渠道返回 HTTP 503 失败，本批没有独立代理复核证据。

## 恢复会话 01a0c3a2：共享认证维护入口安全收口

继续保留未部署、未注册计划任务和未修改业务数据的边界。只修复共享认证维护脚本中
仍遗留的远程明文默认地址：`register-pc1-shared-auth-maintenance.ps1` 现在要求显式
API origin 或环境变量，复用 `collection-api-origin.ps1` 的 HTTPS/loopback 校验，并将
可选私有 CA 文件传递到 NAS 恢复任务注册器。脚本在 CA 文件不存在时提前失败，不会
创建计划任务。测试补充默认值、来源校验、旧远程地址不存在及 CA 参数传递断言。

PowerShell AST 解析通过；本机 Python 环境未安装 pytest，定向 pytest 尚未执行，需在
锁定测试环境中运行 `tools/test/continuous_collection_scripts_test_part_01.py`。没有运行
部署脚本或写入任何真实凭据。

## 继续收口：数据修复器浏览器启动边界

`src/data_fixer_app_part_03.py` 原先将记录中的 URL 拼接进 `start "" "..."` 并以
`shell=True` 执行。现在仅接受带 host 的 HTTP/HTTPS URL，拒绝控制字符、引号和其他
协议，并通过 `webbrowser.open` 打开，避免记录内容进入命令解释器。新增静态回归测试
锁定无 shell 命令拼接和 URL 校验。未改变整理数据、浏览器 profile 或运行配置。

同时修复 detail 调度器的线程竞态：`next_task`、`next_visit_task` 和 `batch_tasks` 在
冷却检查与写入 `dispatched_tasks` 之间使用共享锁，避免多个 HTTP worker 同时派发同一
条目。新增双线程回归测试；没有改变持久化数据或冷却策略。

另外收紧 `watch-pc1-auth-auto-resume.ps1`：删除远程 HTTP 默认地址，改为显式 API
配置并复用统一 origin 校验。未配置或配置为非 HTTPS/非 loopback HTTP 时，在发出请求
前失败；新增脚本契约断言。

同样收紧 `trigger-taobao-login-recovery-if-needed.ps1` 的状态检查路径：删除其远程
HTTP 默认地址，复用 HTTPS/loopback origin 校验，避免计划任务在缺少配置时把凭据和
状态请求发送到固定远程地址。

同时修复 legacy Flask facade 中的 `/api/next_task` GET 副作用：任务认领路由现在仅保留
POST，与主 server 路由和已退役 GET 合同一致，避免浏览器预取或跨站 GET 推进共享任务状态。
新增路由方法回归断言。

桌面端 API 默认地址也完成第一步收敛：浏览器无法推导 origin、Tauri 配置缺失时只回退
到 loopback `127.0.0.1:8001`，不再回退到硬编码 NAS 远程 HTTP 地址。Rust、前端和
CSP 同步更新，并新增默认值测试；远程 NAS 使用显式运行配置提供地址。

detail service 的两个运行时 `print` 也已迁移到模块 logger：HTML 持久化使用结构化
`info`，LLM 推断失败使用 `logger.exception` 保留堆栈，同时维持原有失败事件和返回
契约。新增源码回归断言，未改变业务数据。

solver stale-auth 预检异常也改为 logging exception，保留原有“故障隔离后继续释放提交
令牌”的状态机行为，避免异常文本直接写 stdout。新增源码回归断言。

AVM 配置加载器的启动、热重载和 watcher 日志也已从 `print` 迁移到模块 logger；失败
路径使用 `logger.exception` 保留堆栈，配置 fallback 行为不变。新增结构化日志回归断言。

detail dispatch 时间戳改用 aware UTC clock；为兼容历史/测试传入的 naive timestamp，过期
计算会按 UTC 解释后再比较。新增时钟回归测试，尚未扩展到整个 storage schema 的 UTC
迁移。

storage canonical record 和 seed collision repair 的生成时间也改用 `timezone.utc`；修复
receipt 继续输出兼容的 `Z` 格式，避免改变现有外部契约。新增 storage UTC 源码契约测试，
数据库列类型和其余时间调用仍需后续迁移。

collection stage state 和 generic product adapter 的默认时间也改用 UTC-aware clock，
并新增默认时间源码契约测试。调用方显式传入的时间保持原有优先级。

repository context 的内部 clock 现在优先调用 aware `clock.now(timezone.utc)`，仅在兼容
旧 facade/test clock 时回退到 `utcnow()`；租约和 cooldown 仍按统一 UTC 归一化比较。新增
clock 契约测试，尚未改变历史数据库列的 naive 存储格式。

PC2 browser image 现在创建固定 UID/GID 的 `fapaifang` 非 root 用户并以该用户运行
启动器；部署脚本的 host-display 授权改为可配置用户，删除对 root 的硬编码。挂载的
profile、output 和 bridge-control 目录在镜像内预先授权。这样 Chrome 不再以 root 和
`--no-sandbox` 组合运行；实际 Docker 构建和 host-display 运行仍需在 PC2 发布窗口验证。

同时清除 `tools/pc2_solver_context.py` 中的远程 NAS API 默认拓扑，运行环境未提供地址
时仅回退到 loopback，生产远程地址必须由 Compose/runtime env 显式注入。新增源代码契约
测试，未改变现有显式 API 参数行为。

collection API listener 现在基于 `ThreadingMixIn` 提供 daemon request threads，并设置
`block_on_close=False`，避免慢客户端或同步 handler 阻塞其他请求和进程关闭。TLS handshake
的既有限时仍保留；新增 server 契约测试。真实长任务异步化和 PC2 发布验证仍需后续完成。

本批没有部署或重启 Crow、PC1 人工认证浏览器、PC2、NAS；继续遵守全部代码任务完成
后再部署测试的明确要求。#15 的剩余 PowerShell 客户端、角色隔离和证书供应，以及
RuntimeState、异步长任务、aware UTC 迁移、非删除式容量管理、非 root 浏览器和第三批
其他结构任务仍需继续。测试不超过 30 个模块与行数上限的冲突尚未获得新的政策决定。

## 2026-09-22：API 并发与后台任务回执

本批继续推进 #17，保留现有未提交成果。未部署或重启 Crow、PC2、NAS、人工认证
浏览器；未连接业务数据库，未修改运行配置、凭据、浏览器 profile 或已整理数据。
没有提交代码、删除文件、重新生成行数 baseline 或新增策略豁免。

### 已实现与复现证据

`collection_http_server.py` 原先即使启用了 ThreadingMixIn，TLS handshake 仍在
`get_request()` 中占用监听线程。真实 socket 回归先复现一个不完成握手的连接阻塞
另一个可信客户端，再将握手移入请求线程。握手 5 秒超时、HTTP handler 30 秒超时和
失败连接清理均保留；阻塞 handler 与半截请求头也改用真实并发测试验证。

新增 `collection_jobs.py`：每个 API 实例一个 FIFO worker，活动任务上限为 8。
queued 回执先通过原子 JSON 写入，再确认提交和执行。支持完成、失败、取消和查询时
识别 interrupted；重启后不自动重放可能已经产生写入的任务。失败时保留已确认的
回执、报告及待写快照，错误原文只进入日志。额外复现了“worker 已取出任务，关闭 API
后仍开始执行”的竞态，并补上启动前的关闭检查；对应测试由失败转为通过。

`collection_maintenance_jobs.py` 在入队前捕获服务、数据目录和规范化参数，承接近期
重放、归档重放、补抓详情及维护工作。维护报告先原子发布，需要时再重载数据。
只有明确的 JSON `dry_run: false` 才允许修改维护对象，`limit: 0` 不会被默认值覆盖。

11 个维护/pipeline 入口及别名现已返回 HTTP 202 与 `job_id`、`status_url`；新增
`GET /api/collection/jobs?id=...`，读取结果同样要求操作员鉴权。任务在后台完成后，
原响应内容位于回执的 `result`。Pipeline 在队列 worker 内同步执行，只有实际返回
`completed` 才记为成功；`already_running`、`started`、失败或缺少状态都不会误报完成。
默认 pipeline 数据目录也与配置的 AVM 服务目录保持一致。完整契约和恢复规则见
[`collection-async-operations.md`](../collection-async-operations.md)。

`_post_save_locations` 另有一个被线程化暴露的读改写竞态：测试强制第二个请求先写入，
第一个持有旧快照的请求随后覆盖它，丢失第二个地区。为整个读、合并、写入段加入
共享 FILE_LOCK 后，两个请求和原记录均保留；9 项归档保留测试通过。

旧 AVM HTTP 测试现在显式检查 202，并在 mock 和临时目录有效期内完成带鉴权的轮询。
保留空请求体、参数边界、错误码和报告内容检查。路由源码门禁跟踪真实委派方法及维护
参数准备函数，并带递归访问保护；没有删除路由覆盖或添加检查排除项。
队列及源码门禁已加入 fast，真实 HTTP 任务测试加入 security，新模块加入 CI
Ruff/formatter/strict mypy 检查。

全组门禁还捕获了两处此前未闭环的问题：LLM 提取函数被克隆到 `llm_helper` 后缺少
logger，触发 NameError；桌面配置成功测试没有创建传入的 CA 文件。补齐 logger、创建
明确的测试 CA 路径 fixture，并新增“CA 缺失时原配置字节不变”的负向测试，保留生产
配置写入器原有的拒绝行为。相关 LLM、风险提取、配置组 51 项通过。

### 最终验证

| 检查 | 结果 |
|---|---|
| fast 隔离组，含队列与路由源码门禁 | 198 passed；20.46 秒测试耗时，22.74 秒总耗时 |
| security 隔离组 | 255 passed、2 skipped；69.14 秒测试耗时 |
| 新队列、HTTP 任务、维护写入边界、完整 AVM HTTP 契约和源码门禁合并组 | 418 passed；29.66 秒测试耗时 |
| 关闭竞态修复后的队列与 HTTP 定向组 | 41 passed |
| LLM 与配置修复定向组 | 51 passed |
| 有效行数工具测试 | 19 passed |
| ratchet | 1088 个文件；501-700、701-1500、超过 1500 均为 0 |
| 13 个新模块/定向测试的严格 Ruff 规则集、14 个文件 formatter 检查 | 通过 |
| 本批 Python 文件 E9、E722、F63、F7、B 检查 | 通过 |
| 队列、维护准备、HTTP listener 三个模块 strict mypy | 通过 |
| 本批 30 个源码、测试、配置与文档 UTF-8 无 BOM 检查 | 通过 |
| `git diff --check` 与工作树范围复核 | 通过；无删除、无暂存、无受保护数据目录的 tracked 变更 |

security 的两个跳过项仍为 Windows 上的 POSIX 进程监督测试。表内各组有交集，不能
相加为独立用例总数。API 合并组使用 `scripts/run_quality_tests.py` 的隔离入口，在
进程内临时注册 `test_collection_jobs.py`、`test_collection_job_http.py`、
`test_maintenance_write_boundary.py`、`test_avm_http_contract.py` 和
`test_server_source_contract.py`；没有直接从业务运行目录启动 pytest。
最终工作树共有 329 条未提交/未跟踪路径记录，其中包含开始时的 322 条既有记录。
Git 的 LF/CRLF 提示不影响空白检查结果；没有为消除提示修改仓库换行配置。

本轮 4 个只读子代理均因默认模型渠道 HTTP 503 在启动时失败，没有取得独立代理
复核证据。没有运行新的 PostgreSQL、桌面构建或安装后验收；本批未改这些运行产物。

### 仍待推进

#17 的人工审核回执 sync/async 提交路径已统一进入通用 CollectionJobManager；旧
ManualReviewMaintenanceManager 仍仅作为历史查询兼容层保留，其他同步报告入口尚未
迁移，不能把所有长操作标记为完成。下一步仍需处理 solver/pause/队列的锁定状态对象
与 RuntimeState、aware UTC 数据库迁移、其余 HTTPS/角色凭据部署及证书供应、非删除式
容量管理、非 root 浏览器运行验证和第三批结构任务。测试模块数量与现行行数策略的冲突
继续保留为待决定事项。完整优化清单维持“部分完成”，全部代码任务完成后再部署测试。

### 2026-09-22：显式 async 回执队列与 Alembic metadata parity

显式 `mode: async` 的人工审核回执已改为提交到通用 `CollectionJobManager`，不再在
请求线程直接执行维护，也不再创建独立的 `ManualReviewMaintenanceManager` worker。
提交使用固定的 32 位十六进制任务 ID，仍返回旧客户端需要的 HTTP 200、
`maintenance_job_id` 和 `maintenance_job_status`，并额外提供通用 `job_id`/`status_url`。
旧的 receipt jobs 查询接口会合并读取这类通用回执；通用队列增加了持久化 receipt 列表、
显式任务 ID 防重和 `interrupted` 终态校验。异步队列拒绝时不会先写审核记录。

Alembic offline 配置现在按 URL backend 选择与 online 相同的 dialect-specific metadata；
schema gate 继续从 `20260905_0011` 升级到当前 `head`，并验证新增 `0012` 查询索引和
证据字段保留。定向验证：collection job tests `11 passed`，schema/index gate
`3 passed, 2 skipped`。AVM HTTP 契约已将显式 async 的拒绝路径改为模拟通用
`CollectionJobManager` 容量错误，当前 `350 passed、1034 subtests passed`。

storage 的 UTC 时钟另外增加了 `use_repository_clock()` context injection。它在请求或
测试上下文内优先使用显式 callable，并继续把 aware UTC 值规范化为现有 schema 使用的
UTC-naive 值；未注入时才走旧 facade clock 兼容路径。行为测试覆盖 aware 值规范化和
上下文退出后的恢复，尚未把全部 collection/AVM 直接 `datetime.now()` 调用迁移到该
接口。

### 2026-09-22：种子数据库异常传播与 savepoint 回归

`SeedCollectionService.submit_batch()` 现在不会把 `get_flat_item()` 的数据库异常当作
“没有已有记录”。查询失败会先记录结构化异常日志，再原样向上传播，避免数据库不可用
时继续走新项目写入路径。新增隔离回归测试确认异常会阻止持久化回调。

种子队列的通用方言 `begin_nested()` 分支新增了实际回归覆盖：测试将 SQLite fixture
的 dialect 名称临时切换为通用分支，模拟并发重复插入并验证 savepoint 回滚后外层事务
仍可继续写入 occurrence。生产代码未改变，也没有触碰业务数据库。

PC1 recovery 状态码映射已有 `requested_timeout`、`pc1_claimed_timeout`、
`desktop_manual_takeover` 和 `recovery_unknown` 的统一回归覆盖；#52 因而具备当前
代码证据。#28 的跨平台 FPFData 路径解析和 #36 的桌面编辑值类型边界也已由现有
Linux/UNC/TypeScript 测试覆盖。完整清单仍保持“部分完成”，RuntimeState、HTTPS
部署与真实 PC2/NAS 运行验证继续未完成。

同时收口了 solver 状态读取的一处并发窗口：`_captcha_solver_runtime_status()` 在同一
把 `SOLVER_LOCK` 下复制运行标志、队列标志、开始/结束时间、状态、失败原因、暂停原因、
最后请求和 challenge ID，再在锁外组装持久化 scope 信息。这样一次 status 响应不会把
一轮 solver 的字段拼成跨执行快照；完整 `RuntimeState` 写入 API 以及所有旧全局写点
仍待继续迁移。现有 collection status 与 solver ownership 回归共 `81 passed`。

### 2026-09-22：collection runtime snapshot 与 UTC fallback

新增 `_collection_runtime_snapshot()`，统一在一次读取中采集 solver 状态、有效暂停状态、
认证恢复快照和 collection scope。轻量 status 与完整 collection status 现在复用该快照，
避免分别读取这些跨线程状态后拼出不一致响应。新增回归验证 solver 与 recovery snapshot
各读取一次，相关 status/source-contract 组共 `91 passed`。

`GenericProductAdapter.partition_key()` 的无日期 fallback 也改为使用 aware UTC 日期，
不再依赖本地时区的 `date.today()`。collection UTC 默认值测试已补充该边界。数据库历史
列仍保持 UTC-naive 兼容格式，完整 schema timezone 迁移尚未执行。

### 2026-09-22：solver execution snapshot 与 recovery malformed-state guard

`SolverExecutionState` 新增只读 `snapshot()`，在同一把状态锁下复制当前 execution 的
身份、epoch 和取消/替换标志，同时保留 `owns()` 所需的真实 execution 对象。该 API
为后续 RuntimeState 收口提供兼容边界，没有迁移现有全局写入点，也没有改变 replacement
run 的所有权语义。新增空状态、激活、取消和清理回归覆盖。

PC1 desktop recovery 对 NAS 返回的 malformed 顶层或阶段字段改为 fail-closed，统一返回
`recovery_unknown`，不会因 `None`、数组或字符串状态触发属性错误，也不会把未知 recovery
ID 误报为 `challenge_changed`。现有 timeout/manual takeover 映射继续由统一状态码模块
提供。定向 recovery 与 solver ownership 测试共 29 项通过；完整清单仍保持“部分完成”，
RuntimeState 写入迁移、HTTPS 部署和真实 PC2/NAS 运行验证仍未完成。

本轮重新运行 collection UTC、seed service/savepoint、collection status snapshot 和 solver
ownership 合并回归组，共 `103 passed`；结果未改变上述剩余范围。

桌面设置轮询另外收口：只有请求传输阶段的失败会消耗连续轮询失败预算；成功取得状态
后若 `effective` 配置不符合响应契约，错误仍会显示给操作员，但不会把轮询重试计数误判
为网络故障。`collector-desktop` 的 TypeScript 类型检查和 37 项测试全部通过。

请求体边界继续收口：collection settings、engine restart 和 desktop auth 三类仍直接
读取 `Content-Length` 的入口现在统一使用 `_read_limited_body()`。非法、缺失、超限或
不完整 body 都会进入现有 400 错误路径，不再让 `KeyError` / `ValueError` 逃出 handler。
HTTP guard、写入权限和路由边界定向组共 `57 passed`。

第三批结构任务开始收口认证恢复状态码来源：PC1 desktop recovery、desktop auth 和
shared auth 现在复用 `auth_recovery_codes.py` 中的 challenge/unknown 常量，减少跨端
硬编码字符串漂移。相关恢复、阶段、NAS 和代码生成测试共 `80 passed`；server facade
仍保留兼容重绑定，尚未完成全量 FunctionType/import-star 重构。

## 2026-09-22：solver 执行状态集中管理

本批推进第二批的带锁状态对象与第三批的显式状态依赖，保留已有未提交成果。
继续遵守“全部代码任务完成后再部署测试”的要求；没有部署、重启 Crow、PC2、NAS
或人工认证浏览器，没有迁移业务数据库、修改运行凭据或删除整理数据。

### 已完成的状态迁移

`SolverExecutionState` 现在同时持有执行身份、运行标志、提交令牌、起止时间和结果状态。
已移除 `server_context` 中以下六个独立全局变量，未增加旧字段转发或镜像状态：

- `SOLVER_RUNNING`、`SOLVER_PENDING_TOKEN`、`SOLVER_START_TIME`。
- `SOLVER_LAST_STATUS`、`SOLVER_LAST_FAILURE_REASON`、`SOLVER_LAST_FINISHED_TIME`。

生产写入统一使用 `reserve`、`release`、`activate`、`record_outcome`、`finish`、`clear`
及人工状态方法；这些方法在对象自己的 RLock 下完成成组更新。提交令牌只允许持有者
释放或激活，过期令牌不能消费新的提交；带执行身份的结果与完成操作拒绝旧执行，两个
执行具有相同时间戳时也不会混淆。清理会通知旧执行取消和被替换，并保留已确认的结束
时间。状态接口、重试、报告和恢复入口改为读取同一对象的快照。

服务器执行、派发、人工认证、Cookie 恢复与控制入口已迁移到这些方法。源码核对确认
`src/server*.py` 中不再引用上述六个旧全局，也没有直接给对应对象字段赋值。现有
HTTP 响应合同和阶段隔离继续由行为回归验证。

HTTP fixture 每次注入独立的执行对象及其锁；旧测试直接配置对象字段，不再依赖被
删除的全局变量。新增八线程竞争提交、旧令牌释放/激活、同时间戳执行替换、清理后
迟到结果与结束时间保留的回归。原有假替换执行改用真实 `begin()`，同时覆盖身份取消。

扩大回归时发现一条历史 force-reset 正向测试没有传入已经要求的 recovery 凭据，
因此实际先返回 403。现在分别检查无凭据时的 403，以及携带合成测试凭据后业务拒绝的
409；没有降低服务端鉴权要求。

### 新鲜验证

测试复用经 `uv pip sync --dry-run --require-hashes` 核实的 Python 3.10.11 专用环境，
72 个锁定依赖无需改变。Python 用例全部经 `scripts/run_quality_tests.py` 从新临时目录
运行，关闭业务 DB，隔离数据根、solver 状态、模型池及凭据环境，并保留默认网络隔离。

| 检查 | 结果 |
|---|---|
| 改动前 solver 所有权、采集状态、阶段隔离基线 | 108 passed |
| 状态迁移后同一基线 | 108 passed |
| 最终 solver、完整 AVM HTTP、源码合同、认证恢复/阶段及控制链路合并组 | 517 passed，35.66 秒测试耗时，37.59 秒总耗时 |
| fast 隔离组 | 212 passed，21.75 秒测试耗时，23.66 秒总耗时 |
| security 隔离组 | 272 passed、2 skipped，73.59 秒测试耗时，75.45 秒总耗时 |
| 有效行数 checker 自测 | 19 passed |
| ratchet | 1092 files；501-700、701-1500、超过 1500 三档均为 0 |
| 状态对象及所有权测试的严格 Ruff lint/format | 通过 |
| `solver_execution_state.py` strict mypy | 通过 |
| 其余责任文件的增量 lint | 28 个文件 E9/E722/F63/F7/F82/B 通过；context 见下方说明 |
| 本批 29 个 Python 文件 UTF-8 无 BOM 检查 | 通过 |
| `git diff --check` 与工作树范围复核 | 通过；无删除、无暂存、无受保护数据目录的版本化变更 |

合并组先出现的 `516 passed, 1 failed` 已由上表的完整重跑替代。各组存在交集，不能将
用例数相加。security 的两个跳过项仍为 Windows 上的 POSIX 进程监督测试；没有运行
新的 PostgreSQL、桌面构建、hosted CI 或安装后运行验证。

额外对全部责任文件尝试 F82 检查时，`server_context.py` 的两个既有动态依赖
`_real_taobao_auto_solver_enabled`、`_normalize_challenge_scope` 仍报告 F821；本批仅从
该文件删除六个状态声明，没有改写这两处函数。其 E9/E722/F63/F7/B 检查通过。没有添加
忽略标记或修改 CI 规则把动态门面问题隐藏为全量 lint 通过。

两个只读子代理均因默认模型渠道 HTTP 503 未能启动，本批没有独立代理复核证据。
最终源码、调用点、测试、行数和 Git 范围由主线程核对；历史代码图没有作为当前实现证据。

### 仍待推进

本批完成了执行状态这一项归属迁移，完整 RuntimeState 仍未完成。暂停原因、阶段
challenge、人工恢复 epoch 与重试计数、SEEN_IDS/PENDING_TASKS 等仍需继续迁移；
`FunctionType` 门面和其余结构任务仍在。HTTPS/角色凭据供应、aware UTC schema、
非删除式容量管理、PC2 浏览器实际验证及测试组织政策冲突也未由本批解决。
完整优化清单继续标记“部分完成”，部署继续延期。

### 2026-09-22：文件处理占用状态收口

新增 `CollectionProcessingState`，把后台 detail 文件的去重占用从裸集合移入
`RuntimeState.processing`。`claim()` 在一次锁内完成检查与登记，`release()` 在
提交完成、提交失败和 detail 处理收尾路径统一释放；扫描器和服务层继续接收
`MutableSet` 兼容接口，因此不改变现有回调合同。旧的 `CURRENT_PROCESSING` 只保留
为兼容别名，生产读写已经改走 `RUNTIME.processing`，避免扫描线程与 HTTP/后台线程
在检查和登记之间重复提交同一文件。

认证完成回执的内存确认集合也已并入 `SolverRecoveryState`。持久化 JSON 仍是回执的
跨进程来源，运行时状态只保存受锁保护的副本并按既有 256/192 条上限裁剪；旧发布
字典在测试或兼容调用被替换时会在下一次操作同步到 `RUNTIME.recovery`，不会形成
第二个生产真相源。

Cookie 快照刷新状态和后台线程句柄也已由 `RuntimeState.cookie_snapshot` 持有；调度、
轮询状态与写入更新共用同一把运行时锁。历史 `AUTH_COOKIE_SNAPSHOT_STATE` 发布名在
被替换时只执行一次兼容同步，并重置旧线程句柄，防止测试或热重载复用失效 worker。

`CollectionRuntimeIndex` 现在持有 `SEEN_IDS`、`PENDING_TASKS` 和
`DISPATCHED_TASKS` 的默认容器，`DATA_LOCK` 与索引锁绑定；旧发布名仍作为兼容别名，
后续调用点可以逐步改为 `RUNTIME.collection` 的原子方法。当前仍保留旧 handler 的
可变 dict/list 合同，尚未宣称所有调用点都完成显式依赖注入。

Runtime 生命周期的 `started_at` 与 `initialized` 也归入 `RuntimeState`；初始化只在
状态对象未启动时执行，健康接口通过兼容读取器读取旧发布时间，既支持历史测试注入，
也避免再增加一组独立可变全局。

新增并发回归验证八个 worker 只有一个成功 claim，重复 add/release 不会残留占用；
定向 collection/runtime/solver 回归 **20 passed**，随后 collection state 与 runtime
回归 **9 passed**。新增源码和测试完成 `py_compile`；有效行数 checker 自测 **19
passed**，ratchet **1101 files** 通过，`git diff --check` 通过。Ruff/mypy 命令在
当前 `venv` 中不可用，未把缺少工具报告成通过。

续作门禁补充：在当前隔离质量入口重新运行 fast 套件为 **220 passed**（21.93 秒测试
耗时，24.86 秒总耗时）；security 套件为 **272 passed、2 skipped**（67.39 秒测试
耗时，68.67 秒总耗时）。security 的两个跳过项仍为 Windows 上的 POSIX 进程监督
测试；末尾的 HTTP 测试线程异常只来自测试服务器关闭阶段，没有失败用例。两组均由
`scripts/run_quality_tests.py` 创建临时数据根运行，未连接业务数据库。

该批只收口文件处理占用状态，不表示 `SEEN_IDS/PENDING_TASKS`、完整 RuntimeState、
HTTPS 证书供应、数据库 UTC schema 或部署验收已经完成。

### 2026-09-22：collection index 兼容别名同步与共享鉴权锁

`CollectionRuntimeIndex.bind_legacy_aliases()` 现在在索引自己的 RLock 内吸收
`SEEN_IDS`、`PENDING_TASKS`、`DISPATCHED_TASKS` 被 facade 或旧测试重新绑定的容器，
保留原对象身份，不复制或丢弃调用方注入的数据。`server_context._collection_runtime_index()`
会在运行时入口重新发布 state-owned 容器和 `DATA_LOCK`；`load_data()`、detail 文件处理、
运行时条目驱逐以及 seed batch 提交已改用该索引的容器。这让新路径依赖 `RuntimeState.collection`
，同时保留既有 handler/service 的 dict/list 参数合同和旧测试的可替换 seam。

`AUTH_COMPLETION_LOCK` 与 `AUTH_COOKIE_SNAPSHOT_LOCK` 的兼容发布名现在分别指向
`RuntimeState.recovery`、`RuntimeState.cookie_snapshot` 的共享 RLock。确认回执和 Cookie
快照的状态读写不会再因独立模块锁与状态锁分离而产生竞态；现有线程句柄和旧状态字典的
替换兼容逻辑保持不变。认证完成 finalize 使用的串行锁也已归入
`SolverRecoveryState.finalize_lock`，保留原有独立锁的串行语义。HTTP 测试 fixture 同步
注入新 RuntimeState 的对应锁和 `DATA_LOCK`。

验证：RuntimeState 与 collection runtime 定向组 **13 passed**；旧 collection status
兼容组 **24 passed**；fast 隔离组 **220 passed**
（20.94 秒测试耗时，21.86 秒总耗时）；security 隔离组 **272 passed、2 skipped**
（66.34 秒测试耗时，67.33 秒总耗时）。本轮修改的 Python 文件 `py_compile` 通过，
有效行数工具测试 **19 passed**，ratchet **1101 files**（501-700、701-1500、超过 1500
均为 0），`git diff --check` 通过。当前 `venv` 仍未安装 Ruff/mypy；使用临时 `uv run`
环境对新增 RuntimeState 文件和测试执行 Ruff lint/format、对 `collection_runtime_index.py`
与 `runtime_state.py` 执行 strict mypy，均通过。责任范围的完整旧文件 lint 仍保留
`server_context.py` 中既有的两个动态依赖 F821，以及历史 formatter 差异，未通过放宽规则
隐藏。未部署、重启本地 Crow、连接业务数据库或修改已整理数据。


### 2026-09-22：seed scan 维护分页与 PC2 recovery token 校验

archive_seed_scan_jobs_except() 现在按稳定的 job_key keyset 游标和 128 行窗口读取 stale jobs；每个窗口先按既有 policy ownership 过滤，再按 progress_key 以同样窗口归档 progress。job 与 progress 仍在一个事务内更新，保留已归档行不重复计数、lease 清除、跨 policy 不归档和三字段返回合同；窗口结束后释放 ORM 引用，避免长生命周期 worker session 保留整个旧队列。

新增回归测试覆盖 257 个 stale jobs/progress 的窗口边界、identity map 峰值不超过两个窗口、lease 清除和第二次调用计数为零。此前完成的 release_seed_scan_worker_leases() 也继续使用 128 行窗口，并保留 job 状态刷新；observer-region reset_seed_link_region() 现在同样按 job_key/progress_key 窗口重置，仍保留单事务和 collected item/occurrence 不变。

tools/pc2_auth_recovery.load_recovery_token() 现在与 PC1 recovery client 使用相同的 fail-closed 格式合同：去除文件首尾换行后，token 必须是 16 至 4096 个 ASCII 非空白字符；空文件与非法格式分别保留明确的 ValueError。测试覆盖 16/4096 边界、首尾换行、中间空白、非 ASCII 和超长/过短 token。

本批验证：seed_queue_repository_test_part_02.py 8 passed，加上 test_seed_maintenance_windows.py 2 passed；seed candidate/release 组合 23 passed、2 skipped；PC2 recovery 14 passed；effective-code-lines 19 passed、ratchet 1102 files；相关 Python py_compile 与 Ruff 规则检查通过，git diff --check 通过。责任文件仍存在历史 Ruff formatter 差异，未做全文件无关格式化；未部署、重启本地 Crow 或接触业务数据。

### 2026-09-22?legacy detail dispatch ? UTC ????

legacy detail task/status ???????? aware UTC ??????? cooldown ???
???? naive dispatch timestamp ? UTC ????? DB/detail service ???? aware
????????????? naive ??????? aware/naive ????????????
? aware UTC??????? naive/aware ????legacy ???????????? aware
?????????

???legacy dispatch ? detail service ??? **5 passed**????? `py_compile`
? Ruff ?????????`server_context.py` ???????? facade F821??????
??? formatter ???`git diff --check` ???????????? timezone schema ???
????????? Crow/PC2/NAS ???

### 2026-09-22?LLM prediction metrics ? UTC ????

`src/llm_metrics.py` ????????????????????? aware UTC clock
??????????????????????????? JSONL ???? UTC offset?
?????? UTC ?????????????????????

???LLM metrics/helper/lazy-config ??? **31 passed**????? formatter?
???? `py_compile` ??? Ruff ???????`llm_metrics.py` ???? formatter
??????????????????????????

### 2026-09-22?AVM pipeline ?????? UTC

AVM pipeline ? run/task `started_at`?`finished_at` ? run completion timestamps ??
? aware UTC ??????? JSON ??????????????? pipeline ?????
??? UTC offset??? pipeline ????????????

???AVM pipeline ??? **31 passed**????? `py_compile` ??? Ruff ?????
???? formatter ???pipeline ?????? formatter ???????????????
??? schema ????????????????????

### 2026-09-22: AVM alert timestamp UTC boundary

The `/api/avm/screen` alert writer now obtains `created_at` from the shared
aware UTC clock. The existing `YYYY-MM-DD HH:MM:SS` string contract, second
precision, and one timestamp shared by a screen batch remain unchanged.

Added a focused behavior test that injects an aware UTC clock and verifies the
persisted alert timestamp is rendered from UTC rather than the host local
timezone. The focused test passed; no AVM alert schema or offline generator
was changed.

### 2026-09-22: snapshot cache nesting guard

The bounded runtime snapshot cache now scans JSON text for excessive structural
nesting before calling `json.loads`. JSONL records use the same guard. This
prevents malformed or adversarial snapshots from exhausting the Python C stack
on Windows while preserving the existing empty-result and source-file
preservation contract.

The focused cache tests pass, including the 2,000-level nesting regression,
and the isolated fast quality suite passes 221 tests.

### 2026-09-22: real `/api/status` recovery projection

The authenticated status response keeps the full recovery snapshot for operator or
node callers, while the anonymous `/api/status` response uses the existing public
projection. The projection removes recovery IDs, manual request IDs, target URLs,
challenge IDs, and snapshot digests/fingerprints.

Added a real TCP regression test that runs the actual `_get_status` handler with an
active synthetic recovery snapshot, checks the anonymous response for the public
shape and absence of sensitive values, and checks the control-token response still
returns the full snapshot. The focused security file passes **33 tests**.

No runtime credentials, database contents, or deployed applications were touched.


### 2026-09-22: hybrid event timestamp parser boundary

Hybrid escalation and recovery summaries now parse both legacy
`YYYY-MM-DD HH:MM:SS` values and ISO `Z`/offset values into aware UTC before
calculating unresolved-window duration or recovery latency. Canonical mixed-format
ordering also compares UTC instants; malformed or historically non-canonical text
keeps the previous lexical fallback so existing negative-latency fixtures remain
stable. Writers and historical JSONL values were not rewritten.

The focused hybrid timestamp tests pass **3**, and the existing escalation/recovery
regression files pass **16** together. No runtime data or deployed service was
touched.

### 2026-09-22: bounded runtime JSON readers and iterative location traversal

Added `src/runtime_json.py` as the shared runtime JSON boundary. It scans structural
nesting before decoding, catches decoder recursion failures, and exposes bounded text
and file readers with a 256-level limit. Collection job receipts, search job snapshots,
archive records, collection data, and AVM raw-record loading now use the shared reader
and fail closed or skip invalid files according to their existing contracts. The
search location loader now walks `children` with an explicit stack, so a deep in-memory
location tree does not consume Python recursion.

The deep-tree regression injects an in-memory tree so it tests iterative traversal
without bypassing the JSON parser guard. Diagnostic HTTPS fixtures now provide an
explicit test CA path, matching the remote-HTTPS fail-closed credential contract.
Focused runtime, collection, server, and safety regressions pass **51 tests**.
The isolated fast quality suite passes **234 tests**; the security suite passes **275
with 2 skipped**. Effective-code-lines tests pass **19**, ratchet reports **1109
files** with all oversized tiers at zero, and `git diff --check` exits successfully
with only the repository's existing LF-to-CRLF warnings. No deployment or runtime
restart was performed.
### 2026-09-22: seed scan worker lease release regression

Added a bounded-window regression for `release_seed_scan_worker_leases()` in
`tools/test/test_seed_maintenance_windows.py`. It exercises more than two
maintenance windows, verifies that only the exact worker owner is released,
checks job status refresh and identity-map bounds, and confirms a second release
is idempotent. The production lease release implementation was not rewritten.
The focused maintenance-window file passes **3 tests**.
The seed maintenance regression is now included in `scripts/quality_suites.py`'s
unit/fast selection rather than relying only on an ad-hoc focused command. The
registered fast suite rerun passes **237 tests** in **18.44 seconds**.
### 2026-09-22: source-aware detail claim URL policy

Detail and raw-analysis claims now resolve the seed URL policy from an explicit
`SeedScanPolicy`, the stored `source_platform`, or the explicit source URL. Generic
rows therefore use `GenericSeedScanPolicy` and fail with a controlled missing-source-URL
error instead of fabricating a Taobao detail URL. Unlabelled legacy rows without a URL
retain the Taobao compatibility fallback; Taobao platform aliases keep their existing
normalization. The optional keyword-only policy argument preserves existing worker
callers and lets a future adapter pass its complete policy without a storage-to-adapter
reverse dependency.

The seed identity regressions now cover both detail and raw-analysis claims for generic
rows without a URL, including transaction rollback of the lease/status mutation. The
focused identity, seed queue, and generic runtime tests pass **55 tests**. This change
only touched isolated test databases; no runtime data, credentials, deployed service,
or application restart was used.
### 2026-09-22: collection handlers read RuntimeState-owned containers

The legacy detail dispatch, status preview, item lookup, analysis-screen lookup,
manual item update, next-visit, and HTML submission handlers now obtain the shared
`CollectionRuntimeIndex` at the request boundary and use its lock, seen IDs, pending
queue, and dispatch cooldown map. The server facade still publishes the old names for
older callbacks and tests, while these production paths no longer read a stale copied
container after an alias rebind.

The focused dispatch, ingest, RuntimeState, write-access, and item-resource regressions
pass **56 tests**. This is a scoped RuntimeState write/read migration; solver/control
state and the remaining facade exports still require separate work. No deployment,
restart, runtime-data access, or business database connection was performed.
### 2026-09-22：人工审核异步回执与 maintenance reconcile_limit 合同

新增 HTTP 回归验证，显式 `mode: async` 的两条人工审核入口都返回旧客户端需要的 HTTP 200、32 位 `maintenance_job_id`、`maintenance_job_status=queued`，同时使用通用 CollectionJobManager 的 `job_id/status_url`。测试将 legacy `ManualReviewMaintenanceManager` 设为禁止调用，并等待通用回执完成，确认完成结果会更新 `maintenance_job_status=completed`。

通用 `recent_enrich_maintenance` 适配层和 `DetailCollectionService.run_maintenance()` 现在保留并转发 `reconcile_limit`，避免后台维护入口与人工审核回执入口的参数合同分裂。新增隔离测试验证适配层和 service 都把自定义 limit 传给 runner；人工审核 HTTP、collection job HTTP 与 detail service 聚焦组共 **50 passed**。
### 2026-09-22：日期路径解析异常边界

`server_data_runtime` 的两个日期路径 helper 现在只把无效日期文本的 `ValueError` 作为兼容 fallback；意外的解析器 `RuntimeError` 会继续传播，避免再次吞掉内部逻辑错误。新增回归测试用隔离 fake datetime 验证该边界；`tests/test_server_data_runtime.py` **2 passed**。
### 2026-09-22：detail service UTC fallback

DetailCollectionService._utc_now() now prefers an aware UTC clock and, when a
zero-argument test/facade clock raises TypeError, prefers utcnow() before the
legacy zero-argument now() compatibility fallback. This prevents local wall
clock values from being relabeled as UTC while preserving older deterministic
clock fakes. The regression test covers that fallback ordering, and the source
avoids dynamic attribute access that triggered the targeted Ruff B009 rule.

The focused detail, maintenance, collection-job, manual-review, and data-runtime
regressions pass **61 tests**. The touched Python files compile successfully and
the targeted Ruff B009 check passes. No runtime data, credentials, deployed
service, or application restart was used.
### 2026-09-22：UTC metadata boundary gate

Added an isolated SQLAlchemy metadata gate for the transitional UTC timestamp
contract. Every datetime column in Base.metadata must use UtcNaiveDateTime except
the three explicitly documented civil/business datetime fields:
property_listing.auction_date, property_listing.auction_start_time, and
property_legal_context.appraisal_benchmark_date. The exceptions are also
checked to remain legacy naive physical DateTime columns, so a future instant
column cannot silently regress to an ordinary naive type or be changed by this
gate without an explicit semantic decision. No production database schema was
modified.

The focused UTC type, schema migration, and storage timestamp tests pass
**8 passed, 1 skipped**, and the new metadata test file passes the targeted Ruff
check. This gate records the current transition boundary; it does not claim the
PostgreSQL timezone-aware schema migration is complete.
### 2026-09-22：Compose role credential wiring

The collection and NAS API Compose services now declare separate worker,
engine-operator, and engine-agent token file paths under the shared secrets
mount. Worker services continue to receive only the worker token path; the
recovery token remains isolated to the NAS API. The worker environment example
now uses an HTTPS central API URL and explicitly documents the private CA and
worker token paths, while noting that HTTP is limited to loopback development.

Added a text-level Compose regression that scopes worker counts before the API
service and verifies all three API role paths in both Compose files. The
credential/TLS/entrypoint focused group passes **88 tests**. This change only
updates configuration contracts and isolated tests; no secrets were created,
no runtime data was accessed, and no service was deployed or restarted.
### 2026-09-22：load_data 异常边界

server_data_runtime.load_data() now separates file read/JSON decode failures
from per-record processing. File-level fallback catches only OSError,
UnicodeError, and ValueError; non-object JSON list entries are skipped with a
warning. Expected malformed-record errors remain isolated to the individual
record, while unexpected RuntimeError-style processing bugs propagate instead
of being mislabeled as a file-load failure. This preserves the corrupt-file
continuation contract and makes the failure boundary observable.

Added a regression proving an unexpected record parser error is not swallowed.
The focused runtime JSON, collection runtime, and server data runtime group
passes **18 tests**. No runtime data or database was accessed.
### 2026-09-22：seed_batch 显式异步入口

/api/save and /api/collection/seeds/batch now accept an explicit
mode: async that queues the existing seed submission handler through the
durable CollectionJobManager. The response uses the standard 202 receipt and
/api/collection/jobs status URL. The control-only mode field is removed
before the business handler sees the payload. Default and non-async requests
retain the existing synchronous result and error contract.

HTTP regressions cover both aliases, receipt shape, payload forwarding,
completed result persistence, and the async failure code. The focused job HTTP
and legacy seed batch contract group passes **35 tests**. No seed data, runtime
database, or live service was modified.
### 2026-09-22：本轮续作回归

在 UTC fallback、metadata gate、load_data 异常边界、Compose role credential 路径及
seed_batch async 入口合入后重新运行：fast **244 passed**；security **281 passed、
2 skipped**；effective-code-lines tests **19 passed**；ratchet **1111 files**，
所有超限分级为 0。collection API Compose config --quiet、git diff --check 与本轮
责任 Python 文件 py_compile 均通过。最后一次定向运行覆盖 UTC、schema gate、job HTTP、
Compose 文本合同及 server data runtime，共 **86 passed**；涉及测试文件的 Ruff 检查通过。

security 两个 skip 仍为 Windows 环境不适用的 POSIX 进程监督用例。没有连接业务
PostgreSQL、读取 FPFData/凭据、部署或重启 Crow、PC2、NAS。本批不关闭完整代码质量清单；
证书供应和真实 HTTPS 部署、物理 UTC schema revision、其他长任务调用方迁移、完整
RuntimeState 和剩余结构任务仍需继续验收。
### 2026-09-22：seed_batch async operator receipt access

Async seed submissions now require the control-plane operator credential in
addition to the route-level worker authorization. This ensures the submitter is
authorized to read the returned generic job status URL; worker-authenticated
synchronous seed submissions keep their existing route and response contract.
The regression confirms worker credentials cannot enqueue async work.

After this authorization boundary change, the security suite passes **282
tests, 2 skipped**, and the job HTTP/legacy seed/worker-access focused group
passes **44 tests**. Effective-code-lines tests pass **19**, ratchet reports
**1111 files** with all oversized tiers at zero, py_compile succeeds, and
git diff --check exits 0. No deployment or application restart was performed.

### 2026-09-22: opt-in asynchronous AVM evaluation

`POST /api/avm/evaluate` and its `/api/analysis/evaluate` alias now accept a
top-level `execution_mode` of `sync` or `async`. Missing mode remains synchronous;
`options.valuation_mode` continues to control only the valuation time semantics.
Subject and area validation happen before queue submission, and the execution
control field is removed before calling `AVMService`. Async requests return the
shared durable job receipt, preserve an optional `request_id`, and store the
normal evaluation response in the job result. Existing synchronous response
and failure contracts remain unchanged.

The five new isolated HTTP regressions pass, including non-blocking completion,
the alias, async failure receipts, valuation-mode preservation, and rejection
before enqueue. Existing evaluate HTTP contracts pass **12 tests**; the isolated
security suite passes **287 tests, 2 skipped**. The skipped cases remain the
Windows-inapplicable POSIX process-supervision tests. No deployment or
application restart was performed.

### 2026-09-22: opt-in asynchronous location inference

`/api/infer_location` and `/api/collection/details/infer_location` now share
the same optional top-level `execution_mode` contract as online evaluation.
Requests without the field remain synchronous. Async work captures the request
values and detail service/LLM callbacks before queueing; the returned receipt
includes the optional item ID, and the original inference object is stored as
the completed result. The old synchronous HTTP result and failure code remain
unchanged.

Two new isolated HTTP tests cover async result and failure receipts. The new AVM
and detail-inference job tests pass **7 tests**, the existing evaluate/inference
HTTP contracts pass **18 tests**, and the security suite passes **289 tests, 2
skipped**. Ruff focused lint/format checks and Python compilation pass. The two
skips remain Windows-inapplicable POSIX process-supervision tests. No deployment
or application restart was performed. Effective-code-lines tests pass **19**;
the ratchet reports **1113 files** with all oversized tiers at zero, and
`git diff --check` exits 0.

### 2026-09-22: NAS API loopback binding and TLS guard

NAS Compose now publishes the API to `127.0.0.1` by default. The controlled
deployment helper validates the configured host address as IPv4 and rejects a
non-loopback binding unless both TLS certificate and key paths are configured.
TLS health checks resolve the certificate host to the configured listener
address; wildcard binding resolves through loopback. The deployment guide now
uses the configured HTTP/HTTPS mode when reading `/api/status` and documents the
external-binding requirement.

The focused deployment and loopback contract tests pass **4 tests**. The full
security suite passes **306 tests, 2 skipped**; effective-code-line tests pass
**19**, and the ratchet reports **1113 files** with all oversized tiers at zero.
Compose config validation and `bash -n` pass. Ruff is unavailable in the active
Python environment. No certificate, secret, runtime data, deployment, or service
restart was used. External certificate supply and real HTTPS runtime validation
remain open.

### 2026-09-22: async AVM screening and PostgreSQL UTC schema

`POST /api/avm/screen` now supports an explicit top-level
`execution_mode: "async"` and uses the durable collection-job receipt. The
default synchronous response remains unchanged; input validation precedes
enqueue, and the background result preserves alert writes and the original
summary payload.

Revision `20260922_0013` converts UTC instant columns to PostgreSQL
`timestamp with time zone` using `AT TIME ZONE 'UTC'` in both directions.
Civil/business date fields remain naive, and `UtcNaiveDateTime` binds aware
UTC values while retaining naive UTC Python results for current caller
compatibility. Offline migration and SQLite schema checks passed. The revision
has not been run against PostgreSQL, and no business database was accessed.

### 2026-09-22: restored NAS health invariant and continued RuntimeState writes

The NAS API candidate health gate again requires
`auth_recovery.enabled`; its contract test now asserts that requirement. The
area-result and area-approval handlers obtain the pending queue from the
current `CollectionRuntimeIndex`, so a legacy queue rebind is adopted before
the detail service receives it. A regression test covers both handlers.

Fresh verification: security **313 passed, 2 skipped**; unit **214 passed**;
effective-code-line tests **19 passed**; ratchet **1116 files**, with every
oversized tier at zero; targeted Python compilation, `bash -n`, and
`git diff --check` passed. Ruff is unavailable in the active environment. No
PostgreSQL migration, deployment, application restart, runtime-data access, or
credential access was performed.

### 2026-09-23: shared detail-dispatch lock

`DetailCollectionService` now accepts a dispatch lock. Production service
instances use `RuntimeState.collection.lock`, the same lock used by legacy
detail-task handlers that read or update `dispatched_tasks`; standalone service
instances retain the local fallback lock. The DB-backed status preview also
reads dispatch timestamps under the runtime-index lock. This removes the split
lock protection around the shared dispatch map without holding a lock during
repository iteration.

Added a concurrency regression proving service dispatch waits on the injected
runtime-state lock and registered it in the fast suite. Fresh validation: fast
**258 passed** (34.95 seconds total); security **313 passed, 2 skipped**
(100.47 seconds total); focused Ruff lint, Python syntax compilation, effective
code-line tests **19 passed**, ratchet **1118 files** with all oversized tiers
at zero, and `git diff --check` passed. The two security skips remain the
Windows-inapplicable POSIX process-supervision tests.

The changed-file formatter check still reports legacy formatting differences
in the touched modules; no whole-file formatting pass was applied. Strict mypy
for `detail_service.py` still reports six pre-existing errors in its callback
contract and untyped helper return values; it reported no error for the new
dispatch-lock type. No deployment, application restart, database migration, or
runtime-data access was performed; the optimization plan remains incomplete.

### 2026-09-23: consistent RuntimeState pause snapshots

Control-flow decisions that previously read `paused` and `reason` from separate
`RuntimeState.control.snapshot()` calls now use one snapshot. Solver transient
pause checks take the control and execution snapshots under their shared runtime
lock, and successful solver cleanup derives its challenge scope and completion
request from one recovery snapshot. This prevents concurrent transitions from
combining fields from different states.

A regression test supplies successive, conflicting control snapshots to model a
transition between reads; the scoped collector now remains paused according to
the single `manual_required` snapshot. The test is part of the existing fast
suite. The first run reproduced the bug (**1 failed, 262 passed**); after the
fix, fast passes **259 tests in 39.23 seconds**, and security passes **313 tests,
2 skipped in 115.31 seconds**. The skips remain the Windows-inapplicable POSIX
process-supervision tests.

The effective-code-lines tests pass **19**; ratchet passes for **1118 files**
with every oversized tier at zero. Focused Ruff lint, Python syntax compilation,
and `git diff --check` pass. Ruff format check still reports legacy formatting
differences in five touched server modules; no broad formatting rewrite was
applied. No deployment, application restart, database migration, runtime-data
access, or credential access was performed.

### 2026-09-23: lock-safe item lookup

`_get_item` checked `item_id in seen_ids` and then indexed the dictionary
separately, while runtime eviction removes entries under the collection index
lock. A concurrent eviction could therefore raise `KeyError`. The handler now
reads the entry once with `.get()` under that shared lock, then sends the
response after releasing it. A regression test verifies the index read holds
the lock. The initial fast-suite run reproduced the bug (**1 failed, 259
passed**); after the fix, fast passes **260 tests in 36.12 seconds**, security
passes **313 tests with 2 skipped in 98.92 seconds**, and the focused
RuntimeState module passes **12 tests in 2.33 seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for the test module; the existing task-control module still reports
broad legacy formatting differences, so no whole-file rewrite was applied.
Ruff lint reports module-wide legacy findings; the `_get_item` block and test
module are clean. The full plan remains incomplete; no deployment or
application restart was performed.

### 2026-09-23: lock-protected next-visit snapshot

`_post_detail_next_visit` copied `seen_ids.items()` without the collection
index lock. A concurrent insertion or eviction could raise during dictionary
iteration or produce an inconsistent candidate snapshot. The handler now
copies the entries under the shared index lock, then calls the detail service
after releasing it. A guard-lock regression test reproduced the unsafe read
before the fix. The final fast suite, including both index-read regressions,
passes **261 tests in 34.65 seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for the test module; full-file checks of `server_handler_task_control.py`
and `server_handler_ingest.py` still show legacy formatting differences. The
scoped lint run found no test-module diagnostics; the handler retains existing
`F405` findings for symbols supplied through `server_context` star imports.
No deployment or application restart was performed.

### 2026-09-24: NAS API container naming and post-rename verification

The NAS Compose service and current deployment references now use the consistent
container name `crow-api`; current worker and documentation contracts were
updated from the former `fapaifang-api` name. The active container was created
from the already verified image without rebuilding application code and is Up
with `127.0.0.1:19520->8001/tcp`. The previous container was stopped, renamed,
and retained for rollback rather than deleted.

After the rename, the host nginx TLS edge remained registered at
`/usr/local/etc/rc.d/S99crow-api-tls.sh`, and PC1 rechecked
`https://192.168.15.200:9520/api/status` with the local CA successfully. The
response still reports the pre-existing `auth_recovery.enabled=false` invariant;
this remains an open runtime health issue independent of TLS and naming.
CPA was not changed or redeployed.

### 2026-09-24: NAS API TLS activation and desktop HTTPS switch

A local private CA and NAS API certificate were provisioned under the
operator-controlled `aikey` directory and copied to the NAS secrets share.
The NAS API now uses external HTTPS port **9520**. Its existing HTTP API image
is held on protected loopback port **19520**, and the NAS host nginx TLS edge
proxies `https://192.168.15.200:9520` to that loopback endpoint. The previous
NAS environment and Compose files were retained as backups; the old API
containers were renamed rather than deleted for rollback.

The HTTPS endpoint was verified from PC1 with the local CA and returned a
valid `/api/status` JSON response. The active image reports the existing
runtime `auth_recovery.enabled=false` state; that independent health invariant
remains open and was not hidden by the TLS change. The Crow desktop runtime was
updated to the HTTPS origin and CA path, the verified EXE was installed after
backing up the prior installation, and `Crow.lnk` was refreshed. The running
desktop process resolves to the installed EXE and uses the new HTTPS runtime.

The NAS nginx edge was also registered as `/usr/local/etc/rc.d/S99crow-api-tls.sh`
with start/stop/restart handling. CPA was not changed.

The desktop Playwright smoke gate initially lacked the local Chromium
artifact. After installing the pinned Playwright Chromium/headless-shell
artifact, `npm run test:smoke` passed all **3 tests** (collection,
authentication, settings) in 12.6 seconds. This remains a frontend/browser
smoke result; native Tauri packaging and installed EXE runtime validation are
still open.

### 2026-09-23: desktop frontend and PostgreSQL UTC gate follow-up

The pending desktop frontend gates now pass in `collector-desktop`: `npm run
typecheck`, `npm run lint`, `npm test` (**42 passed**), and `npm run build`
(Vite converted 41 modules and produced `dist/index.html` plus the JS/CSS
assets). Native Tauri packaging and Playwright/runtime smoke remain separate
unverified gates.

The native Tauri build subsequently passed and produced the release EXE plus
MSI and NSIS bundles under `collector-desktop/src-tauri/target/release`.
Attempted local activation was correctly stopped by the deployment guard:
the existing desktop runtime points at an authenticated non-loopback HTTP
collection API (`http://192.168.15.200:8001`) without a collection CA/TLS
configuration. No insecure activation was forced; the installed desktop was
not replaced or restarted.

The dedicated loopback PostGIS test container also completed the real UTC
migration regression. With the explicit psycopg 3 URL
`postgresql+psycopg://...`, `test_utc_datetime_type.py` and
`test_utc_datetime_migration.py` pass (**12 passed**), including both
`America/Los_Angeles` and `Asia/Shanghai` session zones, upgrade/downgrade,
instant preservation, and civil-date preservation. The generic
`postgresql://` URL selects unavailable psycopg2 in the current environment;
the project lock specifies psycopg 3, so the explicit driver URL is required
for this gate. No business database was accessed and no deployment or restart
was performed.

### 2026-09-23: lock pending-task removals

`DetailCollectionService.submit_html()` and `apply_working_item_patch()` removed
cached IDs from the shared `pending_tasks` list without taking the injected
runtime lock. The detail-task handler filters and iterates the same list under
that lock. Both removals now hold the service's shared lock only for the list
membership check and removal, leaving file and database work outside the lock.
A parametrized guard-lock test reproduced both unsafe paths before the fix
(**2 failed**) and passes for both operations after it. The focused detail
dispatch tests pass (**4 tests**), RuntimeState tests pass (**13 tests**), and
the final fast suite passes **263 tests in 33.29 seconds**.
The final security suite also passes **313 tests with 2 skipped in 86.82
seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for both regression test modules; the existing source modules still have
whole-file formatting differences. Ruff reports no regression-test diagnostics;
the handlers retain existing `F405` findings from `server_context` star imports.
No deployment or application restart was performed.

### 2026-09-24: restore NAS auth-recovery health invariant

The NAS runtime environment now explicitly sets
`FAPAI_NAS_AUTH_RECOVERY_ENABLED=1`, with the existing recovery token file
present and non-empty. The `crow-api` container was recreated from the retained
`fapaifang-collector:tls-existing` image without rebuilding application code;
the previous container was renamed and retained for rollback. The container is
Up on `127.0.0.1:19520->8001/tcp`, and the HTTPS edge remains on port 9520.

Fresh PC1 verification through the local CA now reports
`auth_recovery.enabled=true` and build `20260924-auth-recovery-enabled`.
The API remains paused on the existing captcha challenge state; this is an
independent operational pause, not a TLS or container-health failure. CPA was
not changed or redeployed.

### 2026-09-24: enforce Chromium sandbox for PC2 browser

The PC2 browser startup script now refuses root execution and refuses to start
when the Linux unprivileged user-namespace sandbox is unavailable. The browser
continues to run as the dedicated non-root `fapaifang` user, and the unsafe
`--no-sandbox` launch flag was removed. The deployment contract test now locks
these requirements. Focused PC2 deployment tests pass **15 tests** and the
startup script passes `bash -n`; a real PC2 image rebuild and runtime smoke
remain required before marking the browser release gate complete.

### 2026-09-24: detail dispatch lock ownership follow-up

数据库详情任务的 `dispatched_tasks` 之前由 `server_handler_get_collection.py` 和
`server_handler_ingest.py` 直接传入 `DetailCollectionService`，服务内部默认使用
自己的 dispatch lock；状态读取路径却使用 `CollectionRuntimeIndex.lock`，导致同一
共享字典存在两把锁。`next_task()` 与 `next_visit_task()` 现在接受可选的调用方锁，
两个 RuntimeState handler 显式传入 `runtime_index.lock`，冷却清理和检查/写入操作
因此与状态快照共享同一所有权边界。既有独立服务调用仍保持默认锁兼容。

`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。使用临时 `uv run` 补齐 pytest、BeautifulSoup、SQLAlchemy、
Requests 和 websocket-client 后，详情并发回归 **6 passed**。PC2 真实镜像运行、
Tauri 安装后验证、业务 PostgreSQL migration 与其余 RuntimeState 写入迁移仍保持开放。

### 2026-09-24: RuntimeState pending removal callback

详情 HTML 提交、条目更新、面积识别结果和人工确认路径现在可以把
`CollectionRuntimeIndex.remove_pending` 作为显式回调传入 `DetailCollectionService`。
这些 RuntimeState handler 不再要求服务直接从裸 `pending_tasks` 列表执行移除；服务仍
保留旧列表参数作为兼容回退，旧测试和非 RuntimeState 调用不改变。新增回归测试验证
回调路径确实移除当前条目，同时保留原有锁保护列表路径。

本批 `compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过；详情并发回归使用临时依赖环境运行 **6 passed**。没有部署或
重启。`detail_processor.py`、`seed_service.py` 中的 `seen_ids`/`pending_tasks` 批量
写入仍需后续按 RuntimeState API 继续迁移。

### 2026-09-24: detail processor RuntimeState callbacks

`CollectionRuntimeIndex` 新增受锁的 `set_seen()`。详情处理器现在支持显式注入
`queue_pending`、`set_seen` 和 `remove_pending` 回调：重试任务通过 RuntimeState
队列去重，成功归档通过受锁 API 更新 seen entry 并移除 pending。`DetailCollectionService`
和 `process_single_file()` 已把这些回调接入当前 collection runtime；旧的裸容器参数
仍保留为兼容回退。两项过时测试改为重置 `RUNTIME.collection.pending_tasks`，不再依赖
已删除的 `server.PENDING_TASKS` 别名。

聚焦详情服务、并发分发和 runtime data 回归共 **15 passed**。`compileall`、有效行数
ratchet（1125 files，三档 oversized 均为 0）和 `git diff --check` 通过。seed service
仍需下一批处理其 check-then-append 的完整锁边界；没有部署或重启。

### 2026-09-24: seed service RuntimeState callbacks

`CollectionRuntimeIndex` 新增受锁的 `get_seen()`，seed batch handler 现在把
`get_seen`、`set_seen` 和 `queue_pending` 回调传给 `SeedCollectionService.submit_batch()`。
service 保留 `seen_ids` / `pending_tasks` 参数作为旧调用兼容面，但 RuntimeState 调用
路径不再直接写入新条目或追加 pending；已有条目合并在外层 collection lock 内完成，
新条目写入和 pending 去重使用受锁 callback。测试替身缺少新方法时由 handler 安全回退，
不改变旧测试契约。

详情处理、并发分发、runtime data、seed service 和 seed lock 边界组合回归 **19 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-24: server settings and auto-tuning imports made explicit

`server_collection_settings.py` 与 `server_auto_tuning.py` 已移除
`server_context` 通配符，分别直接声明 URL/JSON 和定时器依赖。collection settings
回归 **12 passed**，两个模块 import smoke 通过；control-plane 错误码合同问题已在
后续 recovery write-route 切片中修复。没有部署或重启。

### 2026-09-24: server facade contract coverage

在不改变动态 facade 实现的前提下，补充两项低风险契约回归：所有被重绑定到
`src.server` 的函数必须使用 `server` facade 的 globals，所有静态 `ROUTES` 注册项
必须对应 `DataHandler` 上可调用的方法。这样可以锁定 `FunctionType` 重绑定和路由
动态挂载的当前不变量，避免后续 RuntimeState 或路由重构静默破坏跨模块全局解析。

`tools/test/test_server_source_contract.py` 全部 **14 passed**。`compileall`、有效行数
ratchet（1125 files，三档 oversized 均为 0）和 `git diff --check` 通过。没有部署或
重启；FunctionType/import-star 的运行逻辑重构仍需单独处理。

### 2026-09-24: task-control RuntimeState dispatch methods

非 DB 详情任务控制路径不再直接重写 `pending_tasks` 或直接赋值
`dispatched_tasks`。`CollectionRuntimeIndex` 新增受锁的
`prune_processed_pending()` 和 `mark_dispatched()`，`server_handler_task_control.py`
在既有外层 collection lock 内使用这两个方法，保留冷却、已处理过滤、任务计数和
批量返回行为。该切片没有扩大到其他同型 handler。

RuntimeState、详情处理、seed service、并发分发和 runtime data 组合回归 **29 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-24: seed batch RuntimeState lock boundary

`handle_seed_batch_submission()` 现在在调用 `SeedCollectionService.submit_batch()` 的
整个生命周期内持有 `CollectionRuntimeIndex.lock`，覆盖 seen entry 查找、数据库回退
查询、已有记录合并、新记录写入和 pending 入队。这样 check-then-append 不会被并发的
seed batch 请求拆开；service 的既有参数和持久化契约保持不变。新增回归测试验证调用
确实发生在 collection lock 内。

详情处理、并发分发、runtime data 和 seed lock 边界组合回归 **16 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。seed service 的裸容器参数仍作为兼容面保留，后续可继续做
更细粒度的 RuntimeState callback 迁移；没有部署或重启。

### 2026-09-24: collection next-task RuntimeState methods

`server_handler_get_collection.py` 的非 DB 详情任务入口现在使用
`CollectionRuntimeIndex.prune_unavailable_pending()` 清理孤儿或已处理 pending 项，
并使用 `mark_dispatched()` 写入冷却时间。原有 URL 选择、冷却跳过和单任务响应行为
保持不变；该路径与 task-control 入口使用统一的 RuntimeState 方法。

RuntimeState、详情服务、详情并发和 runtime data 组合回归 **28 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-23: runtime data loader 使用 RuntimeState collection API

`server_data_runtime.load_data()` 不再直接写入 `seen_ids` 和 `pending_tasks`。
文件扫描和数据库 hydration 现在通过 `CollectionRuntimeIndex.set_seen()` 与
`queue_pending()` 完成，保留重复入队抑制和既有 done/processed 判定。这样
启动加载路径与在线 handler 使用同一套受锁 RuntimeState API，减少裸容器写入面。

`test_runtime_json.py`、`test_runtime_state.py` 和
`test_collection_processing_state.py` 组合回归 **23 passed**。没有部署或重启；
其他 service 的兼容参数和剩余裸容器写入仍需继续迁移。

### 2026-09-23: runtime eviction 使用 RuntimeState collection API

`_evict_runtime_item()` 不再直接操作 `seen_ids.pop()`；
`CollectionRuntimeIndex` 新增受锁的 `remove_seen()`，并与既有
`remove_pending()` 一起用于运行时条目驱逐。该切片保持删除内存索引的原有语义，
不删除磁盘归档或业务数据库记录。

RuntimeState、collection processing 和 server data runtime 回归 **18 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。其他 service 的裸容器参数和写入
仍需继续迁移；没有部署或重启。

### 2026-09-23: detail dispatch 写入通过 RuntimeState callback

详情服务的 `next_task()`、`next_visit_task()` 和 `batch_tasks()` 现在支持显式的
`mark_dispatched()` callback。在线 server handler 将 dispatch 时间写入
`CollectionRuntimeIndex`，兼容测试和旧调用仍可使用原始字典参数。这样新的详情
分发写入不再直接修改 RuntimeState 拥有的 `dispatched_tasks` 容器。

详情 dispatch、RuntimeState 和 collection restart 组合回归 **37 passed**，有效代码
行 ratchet 与 `git diff --check` 通过。过期清理和旧 service 参数仍保留兼容面，
没有部署或重启。

### 2026-09-23: seed batch 使用 RuntimeState lookup/update API

`SeedCollectionService.submit_batch()` 在 RuntimeState 调用路径中不再直接用
`seen_ids` 做存在性判断，也不直接修改已缓存 entry 的 `data`。已有条目通过
`get_seen_entry()` 查询，并优先使用 `set_seen()` 写回合并结果；旧参数仍保留给
独立 legacy 调用。seed batch 的整体 collection lock 和 pending callback 保持不变。

seed service、seed identity、collection processing 和 RuntimeState 回归 **26 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: collection read snapshots and atomic legacy next-task claim

`CollectionRuntimeIndex` 新增 `state_snapshot()` 和
`claim_next_pending()`。状态概览现在使用一致的 seen/pending/dispatch 快照，
legacy 详情任务入口则在 RuntimeState 内部一次锁操作中完成 pending 清理、冷却检查、
条目读取和 dispatch 标记，避免 handler 直接访问内部容器或把 check-then-mark 拆开。

RuntimeState、详情 dispatch、collection restart 和 server facade 契约回归 **45 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: handler collection reads and legacy batch claim use state APIs

`_get_working_item()`、analysis screen lookup 和 detail next-visit 入口不再直接读取
`seen_ids`；legacy visit entries 使用 RuntimeState snapshot。详情批量任务入口新增
`claim_pending_batch()`，在共享锁内完成 pending 清理、计数、冷却检查和 dispatch 标记，
避免 handler 自己遍历内部容器。历史 `PENDING_TASKS` 与 `DATA_LOCK` facade 接入仍保留，
用于不破坏既有维护回调和测试边界。

RuntimeState、detail dispatch、collection restart 和 server contract 回归 **53 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: task-control item lookup uses RuntimeState read API

`server_handler_task_control._get_item()` 现在优先使用 `CollectionRuntimeIndex.get_seen()`，
将在线 RuntimeState 读取与其他 handler 统一；针对旧的轻量测试替身保留受锁 fallback。
该改动不改变数据库优先级、404/503 错误合同或返回数据。

collection runtime、RuntimeState、detail dispatch 和 server facade 回归 **41 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail processor requires RuntimeState callbacks

`DetailProcessor` 和 `DetailCollectionService.process_html_file()` 已移除
`seen_ids` / `pending_tasks` 原始容器参数。重试、完成保存和 pending 清理现在必须
通过 `queue_pending()`、`set_seen()` 和 `remove_pending()` callback 完成；内部不再保留
直接 append/remove/index 写入 fallback。生产调用方已全部传入 RuntimeState callbacks，
相关单元测试改为验证 callback 合同。

collection adapter、detail service、detail dispatch 和 RuntimeState 回归 **40 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail update handlers remove raw pending container contract

`submit_html()` 和 `apply_working_item_patch()` 不再接收原始 `pending_tasks` 列表，
只接受必需的 `remove_pending()` callback。详情 ingest、area result 和 manual approve
handler 已全部改为传入 RuntimeState callback；detail service 内不再保留直接
`pending_tasks.remove()` fallback。相关 RuntimeState 测试改为验证 callback 身份。

detail service、detail dispatch、collection adapter、RuntimeState 和 quality collection
回归 **48 passed**，有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: seed service requires RuntimeState callbacks

`SeedCollectionService.submit_batch()` 已移除原始 `seen_ids` 和 `pending_tasks` 参数。
已有条目写回和新条目入队现在必须通过 `set_seen()` 与 `queue_pending()` callback，
生产入口由 `CollectionRuntimeIndex` 提供；seed service 内不再保留直接字典/列表写入
fallback。相关 seed 和 source-neutral adapter 测试已改为验证 callback 合同。

seed service、collection adapters、quality collection 和 seed identity 回归 **34 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail dispatch reads and expiry use RuntimeState callbacks

`CollectionRuntimeIndex` 新增 `get_dispatched()` 与 `prune_dispatched()`。detail
service 的在线 `next_task()`、`next_visit_task()` 和 `batch_tasks()` 现在通过
RuntimeState callback 读取和清理 dispatch cooldown；只有旧的字典调用才使用兼容
路径。handler 保持共享锁、时间语义和历史 facade alias 行为。

detail dispatch、RuntimeState、legacy UTC dispatch、quality collection 和 server facade
回归 **44 passed**，有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: runtime count and dispatch snapshots for read-only paths

`CollectionRuntimeIndex` 新增 `counts_snapshot()`。runtime loader 的 DB-first 和最终
加载日志不再直接读取内部 seen/pending 容器；状态概览的 DB dispatch preview 也统一
使用 `state_snapshot()`。这些只读路径保持原有日志、计数和 cooldown 行为，同时继续
由 RuntimeState 提供一致性边界。

RuntimeState、runtime JSON、quality collection 和 server facade 回归 **43 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: captcha OS mapping imports made explicit

`captcha_os_mapping.py` 不再通过 `captcha_context` 通配符导入。该模块实际使用的
`math` 与 `os` 改为直接声明的标准库依赖；其余图像、指针和临时文件依赖继续在
对应方法内局部导入，避免把无关的 context 命名空间和副作用泄漏到 mapping facade。

captcha solver 分片、pointer backend 与 logging 回归 **72 passed**，有效代码行
ratchet 与 `git diff --check` 通过。此前更大 captcha 扩展集合仍有一个与本切片无关
的 drag geometry 源码断言失败，未将其报告为全通过；没有部署或重启。

### 2026-09-24: captcha orchestration, slider, and NC retry imports made explicit

`captcha_orchestration.py`、`captcha_slider.py` 与 `captcha_nc_retry.py` 已移除
`captcha_context` 通配符导入，分别声明实际使用的 `random`、`json`、`math`、`os`
和 `time` 标准库依赖。验证码 mixin 的共享模块对象、随机数 monkeypatch、CDP DOM
评估和 NC 重试行为保持不变，未扩大 facade 的公开导出面。

验证码 solver、deadline、DOM evaluation、retryable challenge 和 logging 回归
**95 passed**，有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: captcha preflight, fallback, and OS input imports made explicit

`captcha_preflight.py`、`captcha_fallbacks.py` 与 `captcha_os_input.py` 已移除
`captcha_context` 通配符导入。Preflight 直接声明 URL 解析、路径、正则和 mock 模式
依赖；OS input 直接声明 `math`、`os` 与 `random`；fallbacks 删除了无实际使用的
context 导入。OS pointer backend、DOM preflight、fallback 和 PC2 retry 回归保持
原有行为。

相关验证码、pointer backend、DOM evaluation 与 PC2 回归 **133 passed**，有效代码行
ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: captcha Windows facade imports made explicit

`captcha_os_windows.py` 不再依赖 `captcha_context` 通配符，直接声明窗口聚焦和
平台分支实际使用的 `os`、`re`、`subprocess` 与 `time`。Windows/Linux 窗口定位、
CDP preflight 和 pointer backend import smoke 回归 **26 passed**，有效代码行 ratchet
与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: captcha solver facade imports made explicit

`captcha_solver.py` 已移除 `captcha_context` 通配符，显式保留 facade 兼容所需的
`requests`、`websocket`、`time`、`os`、`random` 共享模块及 CDP/mock 常量。既有
`captcha_solver.*` monkeypatch 入口与 mixin propagation 继续可用；solver context、
CDP request、target limit 和 OS drag 回归 **30 passed**，有效代码行 ratchet 与
`git diff --check` 通过。没有部署或重启。

### 2026-09-24: data fixer part modules remove context wildcards

`data_fixer_app_part_01.py` 至 `_05.py` 与 `data_fixer_runtime.py` 已移除
`data_fixer_context` 通配符，改为按模块责任声明 UI、文件、AI、HTTP 和运行时依赖。
可选 AI 依赖缺失时保留原有 disabled 行为，并将 runtime 的 `DataFixerApp` 解析
延迟到 `main()`，避免 facade 构建期间循环导入。data fixer facade import、路线源
码合同、浏览器 URL 和社区提示回归 **8 passed**；有效代码行 ratchet 与
`git diff --check` 仍需在提交前运行。

### 2026-09-24: collection operation compatibility seams retained

在移除 `server_collection_operations.py` 的通配符后，补回显式的
`_collection_runtime_index` 与 `_prefer_db_task_reads` compatibility seams，保留旧测试
和维护回调的 monkeypatch 入口。quality collection runtime 回归 **8 passed**。

### 2026-09-24: data runtime imports made explicit

`server_data_runtime.py` 已移除最后一个 `server_context` 通配符，直接声明 runtime
archive、detail artifact、collection sync、数据库、认证恢复、JSON、文件扫描、线程
和时间依赖。data runtime import smoke、server source contract、RuntimeState、runtime
JSON 与 collection processing 回归 **37 passed**，没有部署或重启。

### 2026-09-24: auth recovery imports made explicit

`server_auth_recovery.py` 已移除 `server_context` 通配符，直接声明 recovery
coordinator、challenge scope、solver grace、token 文件、HMAC、JSON、路径和时间
依赖。server source contract 与 RuntimeState 回归 **27 passed**，import smoke 通过。
control-plane 组合在后续 recovery write-route 切片中完成了错误码合同修复。

### 2026-09-24: recovery write-route error contract corrected

`POST /api/collection/auth/recovery/request` 的 recovery authorization rejection
现在返回该路由约定的 `AUTH_RECOVERY_FORBIDDEN`；其他 recovery-protected collection
routes 继续使用 `COLLECTION_AUTH_RECOVERY_FORBIDDEN`。control-plane error contract
回归 **12 passed**，没有部署或重启。

### 2026-09-24: auth cookie imports made explicit

`server_auth_cookie.py` 已移除 `server_context` 通配符，直接声明 cookie snapshot、
solver retry、RuntimeState、共享数据根目录、正则、文件系统、时间和类型依赖。PC1
desktop auth、NAS auth recovery 与 server source contract 回归 **53 passed**，没有
部署或重启。

### 2026-09-24: hybrid context/runtime imports made explicit

`server_hybrid_context.py` 与 `server_hybrid_runtime.py` 已移除 `server_context`
通配符，直接声明 AVM calibration、analysis-stage、manual-review control-plane、
DB repository、JSON、临时目录和路径依赖。server source contract 与 hybrid seed
collection 回归 **48 passed**，没有部署或重启。

### 2026-09-24: collection status imports made explicit

`server_collection_status.py` 已移除 `server_context` 通配符，直接声明 AVM、数据库、
认证恢复、RuntimeState、文件系统、线程、时间和可选 llm helper 依赖。collection
status import smoke、server source contract、controller coordination 和 RuntimeState
回归 **30 passed, 1 skipped**，没有部署或重启。

### 2026-09-24: manual-review facade imports made explicit

`server_manual_review.py` 已移除 `server_context` 通配符，直接声明 control-plane
backup、receipt、analysis-stage、数据库和路径依赖。manual-review facade import、
server source contract、control-plane backfill 与 analysis-stage planner 回归
**69 passed**，没有部署或重启。

### 2026-09-24: collection operations imports made explicit

`server_collection_operations.py` 已移除 `server_context` 通配符，直接声明 collection
adapter、detail/seed service、数据库、风险标签、RuntimeState、executor、JSON 和
时间依赖。collection jobs、controller coordination 与 server source contract 回归
**28 passed, 1 skipped**，没有部署或重启。

### 2026-09-24: analysis handler imports made explicit

`server_handler_analysis.py` 已移除 `server_context` 通配符，直接声明 AVM pipeline、
AVM service、数据库、manual-review receipt、maintenance、可选 llm helper、路径和
RuntimeState 依赖。analysis handler import smoke、server source contract 与 AVM HTTP
contract 回归 **14 passed**，没有部署或重启。

### 2026-09-24: collection handler and solver dispatch imports made explicit

`server_handler_get_collection.py` 与 `server_solver_dispatch.py` 已移除
`server_context` 通配符，直接声明 collection archive/manual-review、数据库、认证
恢复、JSON、网络请求、线程和 executor 依赖。collection handler、solver dispatch、
server source contract、PC2 retry 和 RuntimeState 回归 **32 passed**，没有部署或重启。

### 2026-09-24: server request-guard imports made explicit

`server_request_guard.py` 已移除 `server_context` 通配符，直接声明 HMAC、JSON、环境
变量、类型和 URL 解析依赖，并保留认证恢复 token 文件常量。request guard import
smoke 与 server facade/source contract 回归 **14 passed**，没有改变 token、CORS、
request-size 或 CDP endpoint 合同；没有部署或重启。

### 2026-09-24: server handler/control imports made explicit

`server_handler_task_control.py`、`server_handler_core.py`、`server_collection_control.py`
与 `server_collection_console.py` 已移除 `server_context` 通配符，直接声明各自的
时间、URL、JSON、文件系统、RuntimeState、challenge 和 collection control 依赖。
server source contract、collection controller coordination 与 HTTPS control 回归
**19 passed, 1 skipped**，没有部署或重启。

### 2026-09-24: server ingest handler imports made explicit

`server_handler_ingest.py` 已移除 `server_context` 通配符，直接声明 analysis ingest
所需的 math、文件系统、URL、RuntimeState、AVM service、数据库和 alert threshold
依赖。ingest UTC handler、server source contract 和 import smoke 回归 **15 passed**，
没有部署或重启。

### 2026-09-24: hybrid summary imports made explicit

`server_hybrid_escalation.py`、`server_hybrid_events.py`、`server_hybrid_history.py`、
`server_hybrid_lifecycle.py`、`server_hybrid_operator_summary.py` 与
`server_hybrid_policy.py` 已移除 `server_context` 通配符，仅保留实际使用的
`typing.Any` 与 `pathlib.Path` 类型依赖。Hybrid facade import smoke、server source
contract 和 hybrid seed collection 回归 **39 passed**，没有部署或重启。

### 2026-09-24: server solver state imports made explicit

`server_solver_scope.py`、`server_solver_state.py` 与 `server_desktop_auth.py` 已移除
`server_context` 通配符，直接声明 solver scope/state 所需的 JSON、文件系统、时间、
RuntimeState、challenge 常量和 recovery facade 依赖。server source contract、
RuntimeState 与 legacy dispatch UTC 回归 **30 passed**，没有部署或重启。

### 2026-09-24: server engine-control imports made explicit

`server_engine_control.py` 已移除 `server_context` 通配符，直接声明 JSON、URL
解析、挑战 scope 和 RuntimeState facade 依赖。collection engine restart、parallel
restart 和 runtime control transport 回归 **28 passed**；提交前仍需运行有效代码行
ratchet 与 diff 检查。没有部署或重启。

### 2026-09-24: collection job cancellation, deadlines and durable exit receipts

本轮接续对话 `01a0d203-dd82-7623-918f-2ca35a8a59b2`，保留原工作树中的 compatibility
seam 和进度记录。沿用全部代码任务完成后再部署测试的边界；没有部署、重启应用、修改
运行凭据、访问业务数据库或触碰 CPA。

先恢复基线：fast **275 passed**，security **4 failed, 316 passed, 4 skipped**。
修复 `src.avm.engine` 缺少 `get_effective_risk_factor_map` 导出造成的实际导入回归；
同时把 HTTP 写入边界和归档并发测试中的过期全局变量注入改为 RuntimeState-owned
容器及文件锁。相关报告、权限、归档和校准回归 **40 passed**。

通用 CollectionJobManager 增加操作员取消接口 `POST /api/collection/jobs/cancel`、
默认 1800 秒总时限和 API 实例 owner ID。排队时间计入时限，实际计时使用单调时钟；
HTTP 请求尚不提供单项时限字段，可通过服务/管理器构造参数及 Python submit 参数配置。
活动状态新增 `cancelling`，终态新增 `timed_out`，回执记录 deadline、停止原因、停止
请求时间和实际退出时间。排队取消先持久化再释放容量；运行中取消继续占用容量直到
工作退出。超时或取消后返回的工作结果不能被发布为 completed。

线程启动失败和 worker 异常退出会尝试记录 interrupted。取消、完成或退出回执无法
写入时保留已确认字节；查询无法确认执行归属的活动回执时只做 interrupted 投影。
重启不重放、不删除历史回执，不回滚已经确认的业务输出。owner ID 不提供跨进程租约。

维护编排、人工审核、Pipeline、详情重放和补抓加入协作停止检查。补抓 HTTP timeout
使用剩余预算，可中断等待响应停止信号。原生阻塞调用和未改造的内部循环仍须等待返回，
不能将 cancelling 解释为已退出。完整接口合同见 `docs/collection-async-operations.md`。
新增真实队列竞争、取消写入失败保留、线程启动失败、HTTP 权限、超时和证据保存测试。

### 2026-09-24: remove collection aliases and migrate HTTP test state ownership

新增 RuntimeState 替换回归先得到 **3 failed, 8 passed**：facade 的 load_data 和详情
分发会用旧 pending/dispatched 别名覆盖新实例的容器，原始 data-runtime 模块还依赖
未声明的 `_collection_runtime_index`。现改为读取 `RUNTIME.collection`，由 index
方法持有自身锁；删除 server 的 PENDING_TASKS、DISPATCHED_TASKS、DATA_LOCK 和两处
回填逻辑。加载仍原地更新容器，分发仍等待并发完成操作释放同一把锁。

同步迁移所有已定位的测试注入点。根 conftest 曾重新创建已删除的全局字段，并从旧
线程字段检测泄漏；现只注入新的 RuntimeState 和临时 DATA_DIR，检查实际 cookie
snapshot worker，并由 monkeypatch 正确恢复状态。认证幂等测试现在清空真实的
confirmation store，Cookie 重试测试也直接注入真实状态对象。

相关状态、JSON、UTC、锁竞争和 HTTP guard 回归 **69 passed**；扩展 collection
status 与 AVM HTTP 合同回归 **441 passed, 1065 subtests passed**，总耗时 **43.03 秒**，
包括仓库 Python 源码编译检查。新增状态回归及既有 UTC 分发用例已纳入 fast/unit。

### 2026-09-24: current batch verification and remaining boundaries

- 最终隔离 fast：**305 passed**，运行器总耗时 **33.30 秒**，满足小于 60 秒的门禁。
- 最终隔离 security：**333 passed, 4 skipped**，总耗时 **73.58 秒**。跳过项为两个
  POSIX 子进程信号用例和两个未配置专用 PostgreSQL 的用例，不计为运行验收通过。
- CI 中 **39 项 Ruff / format / strict mypy 检查全部通过**。修复了四个 formatter
  阻塞文件及三个 import-block 问题；Windows 本地重放 storage 命令时只调整 TOML
  参数的 shell 引号，没有修改 Linux CI 的检查语义。生命周期四个源文件的 strict
  mypy 也独立通过。
- 有效代码行 checker **19 passed**；ratchet 扫描 **1130 个文件**，501 行以上各档均为
  **0**。没有修改 baseline、排除项或放宽测试策略。
- `git diff --check` 通过，已检查变更范围；42 个新增/修改文件均为有效 UTF-8，无 BOM。

完整优化清单仍为部分完成。对 server.py、server_collection_operations.py、
server_data_runtime.py、server_handler_analysis.py 和 server_handler_task_control.py
额外运行 F821 扫描，仍有 **194 条**动态命名空间依赖诊断。这些文件未因此获得全仓
lint 通过结论；FunctionType、其余 facade、完整依赖注入、日志脱敏和测试组织仍需继续。
默认子代理通道返回 HTTP 503，本轮没有取得独立子代理复核，复核由主线程完成。

后续代码工作应从剩余 facade 的显式依赖和调用点逐项收敛，并保留当前负向测试与状态
隔离证明。PC2 非 root 浏览器实际运行、本地安装包激活、业务 PostgreSQL 迁移和多机
部署仍未执行。原清单“不超过 30 个测试模块”的建议与现行有效代码行及保留测试的
要求冲突，不能通过删测试或放宽门禁满足该建议。

### 2026-09-24: native guard and snapshot ownership, monotonic wait correction

`server_request_guard`、`server_collection_settings`、`server_auto_tuning`、
`server_hybrid_history`、`server_hybrid_lifecycle` 已转为原模块函数，server 仍导出
既有名称，但不再对这五个模块使用 FunctionType 克隆。请求凭据、body 限额和 settings
store 的测试注入改到实际所有者；认证恢复复用同一 token 读取逻辑。抽出
`status_snapshot_values`，让历史与生命周期汇总显式依赖快照读取和字段转换。

直接调用的回归在改动前得到 guard **8 failed, 54 passed**、hybrid **3 failed,
11 passed**；改动后分别 **62 passed**、**14 passed**。settings/control/restart
回归 **37 passed**；双写、guard、hybrid 与 NAS auth 扩展组 **216 passed**。
这些证明没有覆盖剩余 facade、server_context 导入副作用或安装应用运行。

快路径暴露了两个时限问题。运行态用例原先可能在排队期间到期，现以进入事件同步后
调用真实到期回调；排队到期和 HTTP 用例继续覆盖实际 timer。另一个是真实生产缺陷：
Windows Event.wait 可能在单调时钟截止点前返回，使维护操作进入下一阶段。
JobControl.wait 现循环核对工作时限与请求等待时长。确定性时钟回归改动前 **2 failed**，
HTTP 50 ms 时限压力组改动前 **10 failed / 20**；修复后生命周期、停止边界及包含
20 次 HTTP 时限检查的扩展组 **50 passed**。临时重复参数随后移除。

本检查点新鲜验证：隔离 fast **337 passed**（运行器 **35.55 秒**），security
**369 passed, 4 skipped**（**98.86 秒**）；新增三组的 **9 项 Ruff / format / strict
mypy 全部通过**。有效行 checker 通过，ratchet 扫描 **1133 个文件**，501 行以上各档
均为 **0**；`git diff --check` 通过。CI 的新模块 mypy 组使用 explicit-package-bases，
避免 src namespace package 在 follow-imports skip 下被解析为 Any。

后续继续迁移 hybrid events/escalation/operator summary/policy 的显式依赖。完整代码
任务仍未完成，沿用完成全部代码任务后再部署的安排。

### 2026-09-24: hybrid native dependencies, overview ownership and UTC ordering

继续迁移 `server_hybrid_events`、`server_hybrid_escalation`、
`server_hybrid_operator_summary`、`server_hybrid_policy`。四个模块的依赖已显式导入，
server 直接发布原模块函数；累计九个模块从克隆集合中移出。直调回归在改动前为
**4 failed, 7 passed**，失败均为缺少隐式全局依赖；迁移后相关组 **13 passed**。

按职责把 27 个概览字段投影分入 `server_hybrid_overview` 和
`server_hybrid_escalation_overview`，只读输入使用 Mapping，保留既有导出名称。
`collection_status_snapshots` 独立持有当前采集状态、挑战命中率、共享数据根和 PC1
认证等待摘要四个函数。它直接依赖快照读取及历史汇总，不依赖数据库或人工审核编排。
新增直调回归先得到 **2 failed, 10 passed**，抽取后与既有快照读取用例合跑
**17 passed**。原模块继续导出已有入口；人工审核持久化函数暂留原有运行方式。

本轮还复现并修复了 UTC 迁移遗漏：未解除升级窗口及 hybrid retrial budget 按文本
比较时间，导致 `02:00+02:00` 和 `00:01Z` 的先后顺序被误判。三个窗口场景、历史
预算及当前快照预算同时覆盖原模块和 facade，新增 **10 个失败用例**全部复现；改用
既有 `_utc_timestamp_leq` 后 **23 passed**，保留非标准旧时间文本的回退比较语义。

对八个原 hybrid 模块的 74 个函数与 HEAD 做 AST 复核，**66 个函数体完全相同**，
**0 个函数丢失**。其余八处差异为已有快照 helper 类型边界、计数类型转换、可空优先级
声明和上面的 UTC 修复。formatter 导致两个文件超过 500 有效行时，通过字段投影
职责拆分解决，没有申请例外、修改 baseline 或放宽策略。

最终新鲜验证：

- 隔离 fast：**363 passed**，运行器 **38.59 秒**。
- 隔离 security：**369 passed, 4 skipped**，运行器 **95.08 秒**。带 handler 异常
  采集的诊断复跑同样通过，**84.05 秒**；仅记录两个拒绝不可信 CA 用例触发的
  `TLSV1_ALERT_UNKNOWN_CA`，没有其他 handler 异常。四个 skip 仍是 POSIX 信号和
  专用 PostgreSQL 条件用例，不作为相应运行验收通过。
- 最终 hybrid / UTC / 双写 HTTP 合同扩展组：**224 passed**，运行器 **70.03 秒**。
- CI 的 **48 项 Ruff / format / strict mypy 全部通过**；新增所有者与回归已纳入 CI，
  policy ownership 用例也加入 unit/fast。
- 有效行 checker **19 passed**；ratchet 扫描 **1137 个文件**，501 行以上各档均为
  **0**；正常仓库换行配置下 `git diff --check` 通过，65 个变更文件均为 UTF-8 无 BOM。

剩余结构工作包括 `server_hybrid_runtime` 的人工审核持久化依赖、
`server_hybrid_context` 的 AVM / 人工审核编排，以及其他 server facade、完整
RuntimeState 依赖注入、导入副作用、日志脱敏和行为化测试组织。UTC helper 仍来自
server_context，本轮没有宣称消除其导入副作用。完整开发计划仍为部分完成；本轮未
部署、重启安装应用或操作业务数据，继续遵守全部代码任务完成后统一部署的安排。

### 2026-09-24: native AVM previews and explicit manual-review persistence

把 AVM 操作预览迁入 `src/avm/operator_evaluation.py`，显式依赖快照读取与校准工具，
保留 `server._avm_operator_eval_summary` 和旧模块导出。原生调用的缺失文件、损坏
JSON 回归在修改前为 **2 failed, 2 passed**，失败都是缺少 `_load_json_snapshot`；
迁移后四个场景全部通过。预览继续使用 `write_back=False`，临时校准与配置文件只在
临时目录内生成，不修改损坏输入，也不为缺失输入创建业务 AVM 目录。

新增 `manual_review_status`、`manual_review_context`、`manual_review_validation`，
分别持有人工复核持久化状态、收据上下文编排和纯校验。原生状态函数接受显式
`repository`；server 的既有入口通过普通委托函数传入当前 `DB_REPOSITORY`，保持
调用签名和仓库切换语义。两个原 hybrid 模块只保留重新导出，并移出 FunctionType
克隆集合；累计 **11 个模块**使用原生导出。四个新增所有者的独立导入测试确认不会
加载 `src.server` 或 `src.server_context`。

修复收据加载器捕获所有 `TypeError` 后改读 JSON 的问题。新增回归先得到 **1 failed**，
证明数据库内部类型错误被吞掉；现在错误原样传播且只读取一次。两个旧的单参数 mock
改为接收真实 `repository` 参数，并迁移到实际所有者。完整性记录 spy 同步迁移；
原生、facade 和两个 HTTP 别名继续验证一次状态请求只记录一次，且先记录再读取历史。
任务摘要仍合并持久化 collection job 收据，校验错误码与中文消息保持原样。

对三个原模块的相关函数与 HEAD 做 AST 复核，归一化仓库参数注入和类型 cast 后，
**19 个函数体一致，0 个函数丢失**。两处差异为上述加载错误修复，以及 AVM 对可空
evaluation 的局部收窄和移除单次使用的命令摘要转发函数。`_db_collection_stage_snapshot`
函数体保持一致，仍是后续需要消除隐式依赖和重复组装的入口。

本检查点新鲜验证：

- 原生所有者 / source contract / 人工复核 job 相关组：**44 passed**。
- AVM HTTP / 数据库双写 / 校准预览 / 新增所有者扩展组：**614 passed，1078 subtests
  passed**，运行器 **94.62 秒**。
- 隔离 fast：**375 passed**，运行器 **34.62 秒**。
- 隔离 security：**369 passed, 4 skipped**，运行器 **99.03 秒**。四个 skip 仍是
  POSIX 信号和专用 PostgreSQL 条件用例，不视作这些环境的运行验收。
- 新增 CI 的 **3 项 Ruff / format / strict mypy 全部通过**；mypy 覆盖六个源模块，
  12 个新增回归已纳入 unit/fast。
- 有效行 checker：**19 passed**；ratchet 扫描 **1143 个文件**，501 行以上各档为
  **0**；没有修改 baseline、排除项或例外政策。`git diff --check` 通过。

后续结构工作仍包括采集阶段汇总组装、其他 server facade、完整 RuntimeState 依赖
注入、剩余导入副作用、日志脱敏和行为化测试组织。完整开发计划仍为部分完成；本轮
没有部署、重启安装应用或操作业务数据，继续按全部代码任务完成后统一部署执行。

### 2026-09-24: native collection stage status and shared hybrid assembly

把 `_db_collection_stage_snapshot` 迁入 `collection_stage_status`，数据根目录和
repository 改为显式参数。`server._db_collection_stage_snapshot()` 保留无参签名，
每次调用传入当前 `DATA_DIR` 和 `DB_REPOSITORY`。`server_manual_review` 只保留
端点常量及重新导出，并移出 FunctionType 克隆集合；累计 **12 个模块**使用原生导出。

新增 `hybrid_collection_status`，集中计算 27 组 hybrid 摘要与对应概览投影。数据库
启用和停用分支复用同一份摘要与投影，消除两份字段清单和重复投影调用。原有数据库
计数异常回退、人工复核摘要合并和一次状态请求一次完整性记录的顺序保持不变。

新增原生与 facade 回归：数据库停用时保留 hybrid 字段、真实 SQLite 仓库的计数
映射，以及 stage/search/readiness 三种计数查询失败时清空部分结果。修改前为
**5 failed, 5 passed**，原生调用均缺少 `_load_manual_review_receipt_snapshot_for_runtime`；
迁移后 **10 passed**。三个既有双写测试文件的 22 处快照 mock 改到实际所有者。

另以迁移前函数对照新实现，在数据库停用、启用和计数查询失败三种固定输入下，全部
响应字段和值一致，**3 passed**。对照暂时固定完整性历史写入边界；真实写入次数由
保留的状态回归验证。仓库外临时测试路径启动超时，同一脚本在仓库标准测试入口下
**5.30 秒**完成；临时脚本、目录和相关测试进程随后清理，未保留旧实现副本。

本检查点最终验证：

- 状态 HTTP / 数据库双写 / UTC / 人工复核与新增所有者扩展组：**313 passed**，
  运行器 **107.75 秒**。
- 隔离 fast：**385 passed**，运行器 **50.76 秒**，通过 60 秒门槛。
- 隔离 security：**369 passed, 4 skipped**，运行器 **92.52 秒**。四个 skip 仍为
  POSIX 信号和专用 PostgreSQL 条件用例。stderr 出现一条后台 HTTP 异常头；对既有
  两个不可信 CA 拒绝用例定向诊断得到 **2 passed**，仅记录两个预期的
  `TLSV1_ALERT_UNKNOWN_CA`。
- 新增 CI 的 **3 项 Ruff / format / strict mypy 全部通过**；mypy 覆盖三个源模块，
  10 个新回归已加入 unit/fast。
- 有效行 checker：**19 passed**；ratchet 扫描 **1146 个文件**，501 行以上各档均为
  **0**；baseline、排除项和例外政策未修改。`git diff --check` 通过，79 个变更文件
  均为 UTF-8 无 BOM。

本轮完成了采集阶段汇总的显式参数与 hybrid 组装迁移。hybrid 的 UTC helper 仍从
`server_context` 导入，所以尚未消除这条间接初始化依赖；其余 server facade、完整
RuntimeState 注入、剩余导入副作用、日志脱敏和行为化测试组织继续保留为后续范围。
完整计划仍为部分完成，本轮未部署、重启安装应用或操作业务数据。

### 2026-09-24: standalone UTC timestamps and hybrid import isolation

把 `_utc_now`、`_as_utc_timestamp`、`_parse_utc_timestamp` 和
`_utc_timestamp_leq` 从 `server_context` 迁入只依赖标准库的 `utc_timestamps`。
保留 naive 时间按 UTC 解释、ISO 时区归一化、旧格式解析回退，以及非标准时间文本的
字典序比较规则。`server_context` 和 `server` 继续重新导出同一个原生函数，不增加
兼容包装；现有通过 `server.datetime.datetime` 替换时钟的用法仍然有效。

三个 hybrid 模块改为直接导入 UTC 所有者，切断 escalation、operator summary、policy
及其上层 hybrid / collection stage 汇总对 `server_context` 的间接初始化依赖。修改前
五个独立进程导入回归全部失败；迁移后，加上 UTC 所有者共 **6 个独立导入回归通过**，
均未加载 `src.server_context` 或 `src.server`。这不代表其他服务端导入副作用已经消除。

新增 **64 个原生 / facade 时间回归**，覆盖缺失和非法输入、旧格式、大小写 Z、正负
时区偏移、跨时区先后与相等、非标准文本排序、零参数时钟和返回 naive 值的时钟。
连同六个导入回归共 70 项纳入 unit/fast，并为新所有者加入 Ruff、format 和 strict
mypy CI 门禁。`quality_suites.py` 经项目格式器统一换行，套件阈值保持不变。

本检查点最终验证：

- UTC / 导入隔离 / legacy dispatch / ingest 定向组：**89 passed**，运行器
  **12.84 秒**。
- 状态 HTTP / 数据库双写 / UTC / 人工复核扩展组：**313 passed**，运行器
  **114.89 秒**，包括既有共享时钟注入下的 300 秒未解决窗口断言。
- 完整隔离 fast：**455 passed**，运行器 **55.20 秒**，通过 60 秒门槛。
- 隔离 security：**369 passed, 4 skipped**，运行器 **116.05 秒**；四个条件 skip
  不计作相应平台或 PostgreSQL 的运行验收。
- 新所有者、三个 hybrid 调用模块及两个新测试的 Ruff 检查通过；七个相关文件的
  format 检查通过；strict mypy 覆盖四个源模块，全部通过。
- 对 `server_context` 额外执行 F821 检查仍得到两处旧动态注入名称：
  `_real_taobao_auto_solver_enabled`、`_normalize_challenge_scope`。对照修改前 HEAD
  得到相同两处告警；没有将其记为已完成静态迁移的模块。
- 有效行 checker：**19 passed**；ratchet 扫描 **1149 个文件**，501 行以上各档为
  **0**；baseline、排除项和例外政策未修改。`git diff --check` 通过，83 个变更文件
  均为 UTF-8 无 BOM。

fast 的首次运行被外层 100 秒限制中断，没有最终结果；开启逐用例和线程诊断的重跑
得到 **455 passed / 98.86 秒**，因耗时未通过门槛。随后仅在诊断进程内对照原有
385 项，耗时 **44.38 秒**；恢复完整 455 项并仅增加耗时报告后取得上述最终通过
结果。新增 70 项的 setup/call/teardown 合计约 **2.46 秒**；未定位到单个长期等待，
也未据此修改产品逻辑、减少门禁用例或放宽阈值。保留这次耗时波动记录。

UTC 依赖拆分已完成；其他 server facade、完整 RuntimeState 注入、其余导入副作用、
日志脱敏和行为化测试组织仍在后续范围。完整开发计划仍为部分完成，继续按全部代码
任务完成后统一部署与安装应用验收的约定执行。

### 2026-09-24: native solver request payload and bounded pytest collection

把 solver 请求组装、CDP 地址规范化、scope 别名与自动解题开关迁入
`solver_request_payload`；淘宝挑战 URL 的路径和查询字段规则归入
`collection/adapters/taobao_solver_target`。累计七个 helper 使用原生函数，保留
`server_context`、`server_solver_scope` 和 `server` 的原有导出入口；请求鉴权直接
引用新的 CDP 规范化函数。未更改请求字段、自动解题默认值或配置的按次读取行为。

新增 25 项回归，覆盖原生 / facade 请求规范化、列表身份参数保留、详情挑战凭据清理、
非目标 URL 原样保留、CDP 地址映射、scope 别名、自动解题开关、RuntimeState 替换后的
请求合并，以及 solver 默认实例和 challenge target 的优先级。两个新模块均通过
独立进程导入检查，未加载 `server_context` 或 `server`。上一检查点记录的
`server_context` 两处 F821 告警已随依赖迁移消除。

验证期间，完整 fast 为 **480 passed / 64.92 秒**，未通过 60 秒门槛。函数级诊断
显示 pytest 在显式文件列表之外仍构造同目录候选模块，再逐项匹配路径；该次带
cProfile 的运行包含 **119110 次 `nt.stat` 调用**，收集阶段累计 **53.74 秒**。
这些诊断耗时包含 profiler 开销，不作为正常运行性能的对照值。

质量运行器增加公开 pytest 参数 `-o python_files=`，保留原来的显式文件参数，避免
为清单外的兄弟文件构造测试模块。普通 pytest 入口及仓库配置保持原样。新增两项
运行器行为回归先复现了未选文件被构造 collector 的问题；修复后通过，验证清单中的
非标准文件名仍执行、conftest 夹具和隔离配置生效，以及真实断言失败仍返回非零值。
未删除门禁用例，未提高 60 秒或 180 秒阈值。

对修改前后两种收集方式逐项比较，均得到 **482 个用例，顺序完全一致**；完整节点
清单的 SHA-256 均为
`71c3bc85994ef1c5387fa674344a6f24a04ef91a8e1e8e5a4f099f8b7ff8dd8c`。
本次收集对照的运行器耗时分别为 **25.94 秒 / 14.84 秒**。

本检查点验证：

- 重构前状态 / RuntimeState / solver ownership 基线：**115 passed**；加入新回归后
  定向组 **140 passed**，运行器 **14.62 秒**。
- 运行器行为回归：**2 passed**，运行器 **3.12 秒**；两项均已纳入 unit/fast。
- 完整隔离 fast：**482 passed**，运行器 **45.19 秒**，通过原有 60 秒门槛。
- AVM HTTP / NAS auth recovery / request guard 扩展组：**371 passed，1088 subtests
  passed**，运行器 **38.78 秒**；这些是接口回归，不代表分析或预测引擎完成验收。
- 隔离 security：**369 passed, 4 skipped**，运行器 **103.25 秒**；条件 skip 不计作
  相应平台或 PostgreSQL 的运行验收。
- 相关 Ruff、七个文件的 format、三个源模块的 strict mypy 均通过；
  `server_context` 的 E9/E722/F63/F7/F82/B 检查通过。
- 有效行 checker：**19 passed**；ratchet 扫描 **1153 个文件**，501 行以上各档为
  **0**。baseline、排除项和例外政策未修改；`git diff --check` 通过，89 个变更文件
  均为 UTF-8 无 BOM。

`_refresh_solver_last_request` 和 `_build_solver_for_request` 仍依赖 context 中的
运行时与工厂，可作为下一段显式依赖迁移的入口。其他 server facade、完整 RuntimeState
注入、剩余导入副作用、日志脱敏和行为化测试组织继续保留在计划中。完整计划仍为
部分完成；本轮未部署、重启安装应用或操作业务数据，继续等待全部代码任务完成后
统一部署与验收。

### 2026-09-24: explicit solver runtime requests and native data-fixer composition

`solver_request_runtime` 接管请求合并和求解器实例选择，通过参数接收 RuntimeState、
默认实例与构造工厂。请求的原子合并、输入和返回值隔离、challenge target 优先级以及
调用时读取 CDP 配置的行为保持不变。`server` 使用普通委托提供原入口；context 中
剩余的四个本地函数已全部移出，context 不再属于 FunctionType 克隆来源。其他 server
core/handler 模块的克隆仍待迁移。

`DataFixerApp` 改为普通 mixin 继承，保持既有后段方法覆盖顺序以及 `save_area`、
`open_url` 入口；`main` 直接使用原生实现。删除动态函数克隆、运行时造类和 context
全量导出。测试改为注入 AI 方法实际所属模块，保留原来的提示词和数据保存断言。

基线还复现了四个既有失败：裸 `llm_helper` / `avm.community_resolver` 导入受
`sys.path` 和测试顺序影响，导致 AI 帮助函数缺失或小区名称规范化被静默禁用。已改为
明确的 `src` 包导入，并删除错误的 `src/src` 搜索路径注入。独立进程验证可选 AI
依赖不可用时仍可加载应用及位置规范化逻辑，且不会初始化 server。

删除唯一无调用点、依赖不存在 Flask `server.app` / `request` / `jsonify` 的旧
`setup_routes` 方法；实际入口继续使用 `AreaFixerHandler`。相应的九处 F821 消除。

本检查点证据：

- solver 定向基线 **63 passed**；加入运行时并发合并、快照隔离、显式工厂及独立导入
  回归后 **76 passed**，运行器 **10.23 秒**；新 owner 的 strict mypy 通过。
- data-fixer 基线 **18 passed, 4 failed**；修复后定向组 **23 passed**，运行器
  **2.94 秒**，包括临时 JSON 的指定记录更新、其他记录和内部字段保留、未匹配记录
  字节不变、选择/暂停/批量批准、浏览器 URL 限制和 Windows batch 入口。
- 新 owner、入口及回归文件的 Ruff 通过；所有 data-fixer 模块的 F821 / E722 等
  检查通过。新回归已纳入 unit/fast 和 CI 静态检查。
- ratchet 扫描 **1156 个文件**，501 行以上各档仍为 **0**。

这两个边界已完成实现与定向验证；更大范围的最终门禁仍需在当前工作树上执行。
完整开发计划继续为部分完成，尚未部署或重启安装应用；旧数据库、运行数据和现有
发布均未操作。

### 2026-09-24: native captcha imports, platform isolation and current gates

`captcha_solver` 删除 `_CaptchaFacadeModule` 和跨模块 `__setattr__` 转发，只保留
普通 `CaptchaSolver` 类及原有公开常量。`captcha_context` 收敛为常量和明确的浏览器
identity helpers 导出，删除导入时两次重配宿主 stdout/stderr 的副作用。

验证码测试的 11 个分片改为显式 import，97 个依赖引用移到实际的标准库/HTTP/
WebSocket 模块。平台模拟只替换三个验证码模块的 `os` 依赖；不再修改全局
`os.name`。原基线在 **99 passed** 后触发 pytest INTERNALERROR，错误是 Windows
失败报告无法构造 `PosixPath`，因此该基线不能视为通过。

恢复可诊断的回归后，确认 Linux X11 坐标映射缺少 `math` 导入，已在实现所属模块
补齐；现有两条 X11/CDP 几何回归通过。旧测试对不存在 `captcha_os_input.time`
的注入改为实例等待接口。过时的 `solve()` 源码字符串断言替换为三条真实求解调用，
验证半途滑块、DOM offset 和缺少矩形时的剩余距离。

测试等待 fixture 现在同时推进虚拟单调时钟，避免只模拟 sleep 而仍忙等真实时间；
真实 deadline / cancel 测试继续使用真实预算对象。此前未由主测试入口导入的
part 11 两条 preflight/连接保留用例已接入。新增独立 `captcha` 质量套件并加入 CI，
加入平台隔离和独立进程的宿主流配置回归。

当前工作树的新验证结果：

- 完整隔离 fast：**510 passed**，运行器 **49.49 秒**，仍通过原有 60 秒门槛。
- 注册后的 captcha 套件：**184 passed**，运行器 **8.05 秒**；其中所有指针和
  浏览器交互均使用模拟依赖，不代表真实站点或 PC2 运行验收。
- AVM HTTP / NAS auth recovery / guard 扩展回归：**371 passed, 1092 subtests
  passed**，运行器 **34.98 秒**。
- 完整隔离 security：**369 passed, 4 skipped**，运行器 **92.31 秒**；未把条件
  skip 计作相应平台或 PostgreSQL 的运行验收。
- 新 owner/入口及相关测试 Ruff 通过；16 个 captcha 源模块的 F821/E722 等检查
  通过；13 个本轮格式化门禁文件通过；四个源/套件模块 strict mypy 通过。
- 有效行 checker **19 passed**；ratchet **1157 个文件**，501 行以上各档为 **0**。
  行数政策、baseline 和排除项保持原样。

以上完成求解请求依赖、data-fixer 组装和 captcha 门面三个边界。完整计划仍有其他
FunctionType 门面、context 通配导入、完整 RuntimeState 注入、日志脱敏与行为测试
组织等未完成项；安装应用、NAS、PC2 的部署和数据库保留验收继续按全部代码任务
完成后执行。

### 2026-09-24: native LLM validation and control import isolation

承接 `quality-review-fixes` / `f2d735ab20` 之后的未提交工作树，确认 `llm_helper`
已使用普通显式导出，测试注入实际实现所属模块。补完该批次验证：原生 LLM / engine /
control 基线 **28 passed**，运行器 **4.09 秒**；注册后的 `llm` 套件 **221 passed**，
运行器 **15.59 秒**。覆盖提取、证据隔离、资格池、重试、选择器、坐标、现有集成调用
和 data-fixer；模型与网络依赖均为隔离测试替身，不代表真实模型验收。

定位到 control 导入仍经 `server_request_guard` 的路径常量加载 `server_context`，
提前构造 repository、solver 和 runtime。新增 `server_runtime_paths` 承接原有路径
计算，保留环境变量优先级和相对 `datas` bootstrap 值，不读取凭据或构造运行时。
engine control 直接导入 scope 常量，runtime 类型仅供静态检查；desktop auth 要求
显式传入当前 coordinator 和 RuntimeState，既有 server 委托在调用时提供这些对象。

独立进程回归验证 request guard、collection settings、engine control、desktop auth
四个模块不会加载 server/context、captcha solver 或 storage；另覆盖默认路径、状态根
目录与显式恢复路径的四种组合及无状态文件写入。修改前与 guard ownership 合跑为
**4 failed, 16 passed**，修复后 **20 passed**，运行器 **9.94 秒**。最终复核将相对
路径的文件断言绑定到子进程工作目录；此后单独重跑这八项为 **8 passed**，运行器
**9.11 秒**，对应 Ruff 和 format 通过。

扩展认证回归时复现两项 PC2 seed receipt 失败：旧测试 token 仅 13 字符，未达到
生产代码现有的 16-4096 个 ASCII 非空白字符要求，执行在回执断言之前中断。仅更新
合成凭据并运行官方 import sorter / formatter，生产 token 校验保持原样。修复后
认证扩展组连同负向 token 测试 **74 passed**，运行器 **6.73 秒**。将已有的
`test_stage_auth_recovery.py` 和 `test_seed_auth_target_binding.py` 纳入 security；
格式化后两文件独立验证 **21 passed**，运行器 **3.97 秒**。

本检查点门禁按实际运行状态记录：

- 完整隔离 fast：**535 passed**，运行器 **45.75 秒**，通过原有 60 秒门槛。
  此结果在新增 security 清单及最终路径断言修正之前取得；生产代码此后未改动。
  最终路径断言已按上文单独验证，未为刷新数字重复运行完整 fast。
- security 首次为 **370 passed, 4 skipped**，运行器 **74.14 秒**。纳入上述 21 项
  并修复 fixture 后重新运行，最终 **391 passed, 4 skipped**，运行器 **83.92 秒**。
  后一次使用相同隔离和超时运行器，在 pytest 子进程捕获 HTTP handler 异常；仅有
  两次负向 TLS 用例预期的 `SSLError / TLSV1_ALERT_UNKNOWN_CA`，无其他异常。
  四项 skip 为两项 Windows 不适用的 POSIX supervision 用例及两项缺少专用 URL 的
  PostgreSQL 用例，不计作对应平台或数据库验收。
- LLM 相关 CI Ruff、三个文件的 format、一个源文件的 strict mypy 通过；control /
  路径 / fixture / suite 七个文件的 Ruff 和 format、五个源/套件文件的 strict mypy
  通过；`server_context` 的 E9/E722/F63/F7/F82/B 检查通过。
- 有效行 checker **19 passed**；ratchet 扫描 **1160 个文件**，501 行以上各档为
  **0**。baseline、排除项、门槛和例外政策未修改。`git diff --check` 通过，当前
  **136 个变更文件**通过 UTF-8 无 BOM 检查；原有未提交修改保留。

完整计划继续为部分完成：`server` 仍克隆 **10 个 core 模块和 5 个 handler 模块**，
其余依赖注入、显式导入 context 时的运行时构造、日志脱敏和行为化测试组织仍待收口。
现有 14 个 native 模块包含此前批次，不能全部计作本轮迁移。本轮未提交或推送，未
部署、重启安装应用或操作业务数据；PC2/NAS、真实浏览器和数据库保留验收继续在
全部代码任务完成后统一执行。以上本地结果不代表托管 CI 或完整发布验收通过。

### 2026-09-24: native HTTP responses, scoped solver transactions, and import cost

继续在 `quality-review-fixes` / `f2d735ab20` 的既有未提交工作树推进。
`server_http_responses` 现在直接负责 JSON 序列化、公开恢复状态投影和错误详情处理；
`server_collection_jobs` 接收显式数据目录并使用 HTTP host 的任务管理器，保留提交、
查询、取消和 admission-before-execution 行为。handler 装配只克隆模块自身定义的
函数，原生 response 导出不会再次绑定到 server globals。路由源码契约补齐对限定名
委托调用的追踪；保留原有路由清单，HTTP 相关组最终 **133 passed**，运行器
**26.38 秒**，HTTP 三个源文件的 strict mypy、Ruff 与 format 通过。

新增 `SolverScopeRuntime`，显式接收 RuntimeState、数据目录、legacy receipt 路径
回调及重置时限。`server_solver_scope` 已移出 core 克隆清单，source URL 的 scope
识别归入 Taobao adapter。scope receipt、暂停、manual flag 和 force reset 由原生
模块负责；对 `src/`、`tools/` 的 AST 核对未发现仍从 `server_context` 导入已移除
scope 函数的调用方。

并发回归先复现了三个问题，再完成修复：

- 两个发布操作共用 PID 临时文件，造成 `FileNotFoundError`，文件和缓存也可能错配。
- 读取旧 inactive receipt 的线程可能在新 challenge 发布后清掉新缓存。
- force reset 校验旧 ID 后，可能清掉并发发布的新 challenge。

read / persist 的文件与缓存事务，以及 force reset 的身份校验与修改，现在共用
RuntimeState 的 RLock。重置完成后的 aggregate status 在释放锁后计算。新行为模块
`test_solver_scope_runtime.py` **9 passed**，运行器 **5.55 秒**；作用域扩展组
**172 passed**，运行器 **24.47 秒**。原有 force-reset grace 和 manual-only 重启
测试迁入该模块，使用临时 receipt 和显式 runtime，保留其行为断言。六个相关源文件
strict mypy、Ruff 与 format 通过。

首次 milestone fast 的 **549 项断言通过**，但运行器 **68.59 秒**，未通过 60 秒
门槛。计时诊断再次超时（**133.16 秒**），独立导入检查是主要耗时组之一。导入链
证实 HTTP guard 为加载 URL 规则而经 collection 包初始化加载 AVM、LLM 和校准
工具。两个 collection 包改为按需解析既有公开导出，类型检查保留显式定义，不克隆
函数。新增禁止上述业务模块提前加载的断言先 **8 failed**，修复后 **8 passed**；
适配器、seed / detail 服务、repository 和导入扩展组 **103 passed**，运行器
**24.73 秒**。两个 package 源文件 strict mypy、三文件 Ruff 与 format 通过，并
加入现有 CI 检查。

本检查点最终生产代码状态的门禁结果：

- 隔离 fast：**549 passed**，运行器 **55.45 秒**，通过原有 60 秒门槛；未减少
  suite 清单、跳过测试或放宽阈值。
- 隔离 security：**400 passed, 4 skipped**，运行器 **79.50 秒**。skip 仍是
  两项 Windows 不适用的 POSIX 用例与两项未提供专用 URL 的 PostgreSQL 用例。
- security 退出时的一条后台 HTTP 提示经定向诊断定位到 PC1 不受信任 TLS 负向
  测试。最初临时诊断器误用了 Python 3.10 不支持的 `sys.exception()`，该次带
  warning 的诊断不计作通过证据。改用 `sys.exc_info()` 后 PC1 transport
  **11 passed**，运行器 **10.25 秒**，捕获到的唯一异常为预期
  `SSLError / TLSV1_ALERT_UNKNOWN_CA`；API TLS 定向组另为 **9 passed**。
- 有效行 checker **19 passed**；最终 ratchet **1164 个文件**，501 行以上各档
  均为 **0**。`server.py` 为 **466** 有效行；策略、baseline、排除项均未改动。
- `git diff --check` 通过；当前 **146 个变更文本文件**通过 UTF-8 无 BOM 检查。
  原有未提交修改保留。

完整计划仍未结束：server 还克隆 **9 个 core 模块和 5 个 handler 模块**，另有
PC2 local solver 等工具侧克隆门面、剩余 RuntimeState 注入、context 初始化、日志
脱敏及行为化测试组织待收口。此次导入改进不能计作这些任务全部完成。尚未提交、
推送、部署或重启应用；业务数据库、凭据、Cookie、profile 和既有 release 未操作。

### 2026-09-24: RuntimeState dispatch consumers use coherent snapshots

详情单任务、详情访问任务和数据库批量详情任务入口在把 `dispatched_tasks` 传给 service 前，统一从 `CollectionRuntimeIndex.state_snapshot()` 获取受锁快照，不再把共享可变字典直接暴露给 service。调度写入仍通过 `mark_dispatched`、`get_dispatched` 和 `prune_dispatched` 回调完成，保留现有冷却与返回行为。

RuntimeState、HTTP 写保护、详情并发和 UTC handler 回归 **23 passed**；三个 handler `compileall` 通过，有效行 checker **19 passed**、ratchet（1166 files，三档 oversized 均为 0）和 `git diff --check` 通过。尚未部署或重启；完整 RuntimeState/facade 收口、PC2/NAS 真实运行和发布验收仍保持开放。

### 2026-09-25: collection operations direct-import boundary repair

`server_collection_operations.py` 之前把 `_collection_runtime_index` 和 `_prefer_db_task_reads` 从 `server_context` 导入，但这两个符号只由 `server` facade 动态提供，直接导入 collection operations 时会在测试收集阶段失败。现改为在模块内基于 `RUNTIME.collection` 提供 runtime index helper，并用本模块的 `DB_REPOSITORY` 与 `_runtime_env_flag` 实现数据库读取偏好判断；保留 `server.py` facade 的动态重绑定兼容面。

`test_quality_collection_runtime.py` 与 `test_http_write_access.py` **19 passed**，相关模块 `compileall` 通过。`test_runtime_state.py` 当前仍有 3 个既有 facade/fixture 失败（control snapshot、get_item fallback、next_visit fake），未将其与本次 import 修复混报为通过；没有部署或重启。

### 2026-09-25: RuntimeState handler compatibility boundary tightened

详情任务控制的条目读取恢复使用 facade 注入的 `_collection_runtime_index()`，避免 handler 固定抓取旧的 `RUNTIME.collection`，从而让 RuntimeState 替换和测试替身保持同一入口。详情访问任务现在在请求体校验后只做一次 `state_snapshot()`；轻量兼容替身没有该 API 时，在共享锁内复制 `seen_ids` 与 `dispatched_tasks`，避免重复快照或无锁读取。

`test_quality_collection_runtime.py`、`test_http_write_access.py`、`test_legacy_dispatch_utc.py` 组合回归 **22 passed**，相关模块 `compileall` 通过。`test_runtime_state.py` 仍受工作区 `datas/force_unlock.flag` 与旧测试对 facade seam 的假设影响，单独留下 1 项 pause snapshot 失败，未将其计入通过。没有部署或重启。

### 2026-09-25: force-unlock seam aligned with RuntimeState pause decisions

`_collection_scope_effectively_paused()` 现在先通过 facade 的 `_solver_force_unlock_flag_exists()` 判断全局 force-unlock 标记，再调用 `SolverScopeRuntime.scope_effectively_paused(check_manual_flag=False)`。这样生产路径仍保留强制暂停安全门，测试和运行时替换可以通过 facade seam 控制该标记，不会被工作区残留 flag 绕过注入。`SolverScopeRuntime` 的直接调用默认仍检查 manual flag。

RuntimeState 回归 **13 passed**；collection runtime、HTTP 写保护和 legacy dispatch 组合回归 **22 passed**。没有部署或重启。

### 2026-09-25: auth recovery stable solver dependencies made explicit

`server_auth_recovery.py` 补齐了直接模块导入所需的 `Any` 类型和稳定 solver 依赖：请求构造、挑战 scope 规范化、目标 URL 规范化、Taobao 自动 solver 能力判断、manual-only 判断以及 challenge scope 推导现在由其实际 owner module 显式导入。仍依赖 server facade 注入的 RuntimeState、cookie、solver retry 和 recovery orchestration helpers，暂不从 `_CORE_MODULES` 移除，避免跳过剩余依赖收口。

auth recovery/control-plane/HTTP route 组合回归 **48 passed**；RuntimeState、collection runtime、HTTP 写保护和 legacy dispatch 组合回归 **35 passed**。没有部署或重启。


### Auth recovery progress repository ownership

Moved capture and pending-detail counters into auth_recovery_progress with an
explicit repository protocol. Recovery wrappers pass their current repository;
server facade re-exports remain compatible. Transition regression proves that
moving a captured detail through analysis states does not invent new progress.
Disabled, unavailable and invalid repositories retain the unknown/zero contract.

Focused progress, scoped-stall, recovery API and source-contract tests: 41 passed.
New module and tests: Ruff lint and format passed. Checker: 19 passed; ratchet:
1168 files, all tiers above 500 zero. Full git diff --check passed. Registered
the regression in UNIT_FILES. Core facade removal remains open; no deployment.


### Processing claims remain owned by the submitting runtime

submit_task captures its processing registry before claiming a file. Completion,
worker failure, cancellation and executor rejection now release that same registry,
even if the facade runtime is replaced while work is outstanding. The replacement
runtime retains its independent claim for the same path. Four regression cases
failed before the fix; processing/runtime/data-runtime tests then passed 33 tests.
The test module is already registered in UNIT_FILES. Ruff lint/format passed for
the changed test. Effective-line tests: 19 passed; ratchet: 1168 files, no files
above 500. No deployment or runtime-data changes. Full optimization remains open.


### Single owner for processing claim release

Removed the second processing-registry release from DetailProcessor and its
service parameter chain. The submission Future now owns the entire claim
lifetime, including worker failure, cancellation and executor rejection. A real
detail-service regression (missing temporary HTML file) failed before this fix:
the worker released the claim before Future completion, allowing duplicate work.
After the fix, the claim blocks resubmission until the Future is terminal.

Processing, detail service/adapters, collection runtime and data-runtime tests:
42 passed. Focused Ruff checks passed; new regression format check passed.
Effective-line self-tests: 19 passed; ratchet: 1168 files, all above-500 tiers zero.
No deployment or runtime-data changes; full optimization remains open.


### Quality runner collection-root isolation

Milestone fast hit its unchanged 180-second limit. Targeted traceback showed
pytest collecting unrelated directories while the runner executed from an
isolated temporary working directory. The runner now explicitly passes its
project root as --rootdir. Real subprocess regressions verify that root while
retaining selected-file collection, project fixtures and failure exit codes.
Focused runner tests: 2 passed; Ruff lint/format passed.

The subsequent isolated fast run completed 572 tests in 58.36 seconds, but the
runner elapsed time was 60.12 seconds, exceeding the unchanged 60-second limit.
The fast gate remains FAILED on timing; assertion success is not gate success.
Stopped only the identified diagnostic process tree after collecting its stack.
Effective-line self-tests: 19 passed; ratchet: 1168 files, all above-500 tiers zero.
No deployment. Import/subprocess cost remains the next performance investigation.


### Defer HTML parser initialization until parsing

Import profiling attributed about 141 ms of a 1.36 s server_context import to
BeautifulSoup. Auction extraction, text extraction and detail artifacts now
load BeautifulSoup at parsing entrypoints. A fresh-process regression verifies
bootstrap omits bs4 and first filter_content use loads it and returns expected text.
Focused bootstrap/detail/adapter/native ownership tests: 38 passed. The initial
ad-hoc invocation lacked PYTHONPATH for subprocess imports; corrected invocation
used the repository root. Offline LLM suite: 221 passed, runner 17.67 seconds.

Latest isolated fast: 573 assertions passed, runner 67.98 seconds; unchanged
60-second performance gate FAILED. No overall speedup claim is supported.
E9/F821 source checks and test Ruff/format passed; effective-line tests 19 passed,
ratchet 1168 files, above-500 tiers zero. Scoped diff check passed. No deployment.


### Avoid unused temporary-directory fixtures in fast tests

The autouse HTTP poll fixture requested tmp_path before checking the test module,
forcing filesystem setup/cleanup on unrelated tests. It now requests tmp_path
only after matching AVM HTTP or collection-status tests. Before/after setup-plan
for the atomic-claim test proves the unused tmp_path dependency is removed;
network isolation fixtures still run. Ruff and format checks passed.

Fresh isolated fast: 573 passed, runner 59.06 seconds, exit 0 under the unchanged
60-second limit. The margin remains small. Isolated security: 405 passed, 4 skipped,
runner 96.06 seconds, exit 0. A background loopback HTTP exception notice was
emitted; its cause was not classified in this run and no clean-log claim is made.
Skipped cases remain unverified. Effective-line tests 19 passed; ratchet 1168
files, all above-500 tiers zero. Scoped diff check passed. No deployment.

### Recover orphan pending IDs during legacy batch dispatch

A real HTTP regression reproduced a disconnected response with KeyError for a
pending ID absent from seen_ids. Batch claims now filter missing IDs under the
existing lock before counting and dispatch, preserving pending-list identity.
The regression checks valid-task delivery, completed counts, processed/orphan
removal, and cooldown through the compatibility POST route.

Focused and affected RuntimeState/dispatch/retention tests: 40 passed. Ruff lint
and format checks passed. Effective-line self-tests: 19 passed; ratchet: 1168
files, all above-500 tiers zero. Independent read-only review found no concrete
regression. This covers in-memory legacy dispatch; DB dispatch is unchanged.
Broad suites were not rerun for this narrow fix. No deployment.

### Isolate collection index loading from facade globals

Moved the complete JSON scan and DB hydration implementation into
collection_index_loader.load_collection_index. Runtime index, repository,
configuration lookup, counts, record synchronization, archive path and clock
are explicit inputs. The facade retains its existing load_data entrypoint and
current dependency injection seams. The new module imports without server,
storage, solver or LLM initialization. server_data_runtime remains a rebound
module for its other responsibilities; full facade retirement is incomplete.

Baseline runtime/data tests: 16 passed. Affected post-extraction tests: 45 passed,
including DB-first, empty/failed-count fallback, disk/DB merge, direct runtime
entrypoint and fresh-process import isolation. An intermediate eager DB-count
callback lookup broke disabled-DB direct loading; restoring deferred lookup
fixed that regression. New tests are registered in the unit suite.

New loader/test Ruff checks passed; touched suite/import-test and new-file format
checks passed. Python compilation and scoped diff checks passed. Effective-line
self-tests: 19 passed; ratchet: 1170 files, all above-500 tiers zero. No broad
suite rerun or deployment; these results do not establish release acceptance.

### Preserve confirmed bytes in remaining legacy archive writers

update_file_global and remove_item_from_json now use archive_json_io.write_records
instead of truncating the confirmed archive. Existing file-lock, missing-ID no-op
and log-and-return failure contracts remain unchanged. Serialization happens
before opening a temporary file; publication follows flush/fsync and atomic
replace. Failed publication retains the pending snapshot for recovery.

Five new regressions failed before the fix, including a serialization failure
that left truncated JSON. After the fix, affected archive/detail/adapter/runtime
JSON tests: 50 passed. Direct and facade success paths preserve unrelated evidence;
missing IDs leave confirmed bytes unchanged. A pre-existing test handler mutable
class list was made instance-owned for Ruff; the final archive suite then passed
18 tests. Test Ruff/format, source compilation and scoped diff checks passed.
Effective-line self-tests: 19 passed. No business data writes, broad suite rerun
or deployment occurred; failure propagation to higher-level callers is unchanged.

### Propagate archive update failure before publishing collection state

update_file_global now logs and re-raises actual archive failures. Missing-file
and missing-ID no-ops are unchanged. Detail patch/status and existing-seed merge
prepare detached records and write the archive before modifying cached data or
pending state. This supersedes the preceding log-and-return update contract;
remove_item_from_json still retains its previous exception behavior.

Real fsync/replace faults exercise all three service paths. They preserve archive
bytes and nested cached values and prevent DB callbacks, queue mutation and
eviction after failed archive publication. An authorized HTTP update returns
500 / AVM_DETAIL_UPDATE_ITEM_FAILED and retains its pending task.

Review found HTML was already scanner-visible before the archive status write.
HTML now stages to a uniquely named .pending-*.tmp file and publishes only after
the status path succeeds; failed input remains recoverable outside item-*.html
scanner matches. Successful status behavior remains covered by service tests.

Affected archive/detail/seed/adapter/runtime JSON tests: 68 passed. Test lint and
format checks, production syntax compilation and scoped diff checks passed;
changed service regions were formatted with Ruff. Effective-line self-tests:
19 passed; ratchet 1171 files, all above-500 tiers zero. No deployment.

Remaining persistence scope includes DB/archive cross-store partial commits,
new-seed publication ordering, missing-archive policy and rejected-detail cleanup.
This batch does not claim an atomic transaction across storage and runtime state.

### Publish new seed archives before indexing and DB callbacks

New seeds are staged by target archive path. Each archive is validated with
read_records and atomically published with write_records before its records
enter seen/pending, DB persistence callbacks or DB-first cache eviction. Duplicate
IDs within the same batch merge missing fields in staging and publish once;
the first non-empty value wins. Removed the direct truncating archive write.

Seven initial regressions failed against the previous implementation, covering
publication faults, unreadable archives and lost duplicate-record fields.
Final affected seed/archive/adapter tests: 60 passed. Coverage includes memory
and DB-first modes, original-byte preservation, publication before DB callback,
one-time duplicate delivery and a later partition failure retaining only the
already-published partition's state. New tests are registered in the unit suite.

Test lint/format, changed production-region format, E9/F821, compilation and
scoped diff checks passed. Effective-line self-tests: 19 passed. This is per-file
publication, not all-or-nothing batch or DB/archive transactional consistency.
No deployment or business-data mutation; rejected-detail cleanup remains open.

### Retain detail input across publication failures

remove_item_from_json now logs and propagates failed archive publication. Detail
processing distinguishes the publication phase from extraction failures: neither
accepted-record save failures nor rejected-record removal failures trigger input
deletion on repeated attempts. The failure marker is retained or written on a
best-effort basis. DB callbacks and runtime completion remain after JSON success.

Initial real-disk fault regressions: 6 failed, 2 passed, exposing rejected-input
cleanup and second-failure deletion. Final affected detail/archive/adapter/claim
tests: 54 passed. Each publication scenario now fails twice, checks unchanged
input/archive bytes and no completion callbacks, then restores the disk operation
and verifies successful completion and marker cleanup. Both fsync and replace,
accepted and rejected records, and pre-existing failure markers are covered.

Test lint/format, changed processor-region formatting, compilation and scoped
diff checks passed. Effective-line self-tests: 19 passed; ratchet 1173 files,
all above-500 tiers zero. Source-archive error propagation and swallowed DB errors
remain separate open boundaries. No deployment or business-data mutation.

Milestone isolated fast: 602 passed in 64.28 seconds; runner elapsed 65.72 seconds,
exit 1 because the unchanged 60-second performance gate was exceeded. This is a
FAILED gate despite passing assertions. Slowest reported cases were subprocess
bootstrap/import-isolation checks (about 1.4-1.9 seconds each). Performance remains
open; no threshold, test exclusion or release-acceptance claim was changed.

### Reduce unused SQL dialect imports and projection fixture I/O

Import-time profiling measured server_context at 1.76 seconds, including 0.89
seconds in storage imports. Removed unused insert-dialect exports from repository
context and load the matching PostgreSQL/SQLite insert only inside active seed
upsert. The bootstrap regression failed before this change and now confirms both
dialects remain unloaded until needed. A subsequent single import measured 1.27
seconds (not a stable benchmark claim). Repository/import tests: 82 passed,
1 PostgreSQL case skipped because no dedicated URL was configured.

Intermediate isolated fast still failed timing: 602 passed, runner 62.30 seconds.
Its slowest setup cases created disk SQLite schemas for stage-status projections.
Those tests do not reopen the DB or assert disk persistence. Their fixture now
creates an independent in-memory SQLite repository per test, retaining real
schema creation, SQL operations, filesystem audit outputs and all assertions.
Focused stage-status tests: 10 passed in 1.57 seconds; Ruff/format passed.

Final isolated fast: 602 passed in 38.43 seconds, runner 39.49 seconds, exit 0,
under the unchanged 60-second gate. E9/F821, source compilation, scoped diff checks
and import-test format checks passed. Effective-line tests: 19 passed; ratchet
1173 files, all above-500 tiers zero. PostgreSQL live acceptance remains unverified
for this import change. No deployment, threshold change or test exclusion.

### Make source HTML archival a required publication boundary

archive_json_io now exposes atomic UTF-8 write_text; write_json serializes before
delegating to the same temporary-file/flush/fsync/replace implementation. The
detail processor uses it for the primary source archive and propagates failures.
The retained-input publication phase begins before source archival, preventing
completion, rejection cleanup or repeated-failure deletion after that write fails.
Optional derived-artifact extraction keeps its existing best-effort behavior.

Eight source-archive fault regressions failed before the change. Tests explicitly
separate source and record publication faults so the new earlier boundary cannot
mask JSON failure coverage. Repeated fsync/replace failures retain the prior source
archive, input and record bytes; recovery verifies exact UTF-8 Chinese text and
normal completion. Initial affected detail/archive/adapter/raw-capture group:
64 passed. After import/format cleanup, focused source/seed/HTTP/claim group:
39 passed. Capture-stage optional archival tolerance remains covered and unchanged.

Helper/test lint and format, changed processor formatting, syntax compilation and
scoped diff checks passed. Effective-line tests: 19 passed; ratchet 1173 files,
all above-500 tiers zero. No broad-suite rerun or deployment for this batch.

### Require DB confirmation before publishing runtime completion

persist_item_to_db and mark_item_deleted_in_db now log and propagate repository
write errors. Detail patch/status and existing/new seed flows publish cache and
pending changes only after DB confirmation. Disabled repositories retain their
intentional no-op behavior, verified through both facade and native entrypoints.
Detail processing retains captured input through repeated DB failures and can
complete after recovery for both accepted and rejected records.

Four regressions initially exposed HTTP 200 and premature state publication on DB
failure. After propagating errors, two retry tests exposed duplicate seed archive
rows after JSON success/DB failure. New-seed archive publication now reuses rows
by ID, fills missing fields and preserves prior enrichment before retrying DB.
Both memory and DB-first retries are covered. JSON may already be committed when
DB fails; this change does not claim a cross-store transaction or roll back data.

Final affected detail/seed/archive/adapter/processing tests: 79 passed. Independent
read-only review found no concrete regression. Test lint/format, changed service
formatting, syntax compilation and scoped diff checks passed. Effective-line tests:
19 passed; ratchet 1173 files, all above-500 tiers zero. No deployment or broad
suite rerun; live PostgreSQL validation remains a separate release gate.

### Close the PostgreSQL milestone and include seed insert counts

The postgres suite now includes test_seed_postgres_insert_counts.py. It reuses
the claims fixture with a loopback-only crow_quality database and a fresh random
schema, replacing the separate fixed crow_seed_count_test database. Assertions
still compare reported inserts/duplicates/occurrences with committed SQL rows.

Initial validation against postgres:16-alpine produced 35 passed and 3 failed:
the full-history and UTC migrations require the unavailable PostGIS extension.
No migration or test was weakened. Reused crow-quality-postgis-bf3b00e4 after
checking its quality-regression label, zero mounts and loopback-only binding.
Its pinned image is postgis/postgis:16-3.5 at digest
sha256:94146ac37bc61e2322f88016056c5920729cb8c64c8542ed590af8fc2abdac07.
The PostgreSQL gate requires PostGIS even though the claims fixture itself
disables spatial initialization. Use the dedicated PostGIS fixture for the
whole suite; inspect its current port after starting it, since the port is dynamic.

Targeted schema/UTC PostgreSQL tests: 5 passed, 4 deselected. Then the isolated
official postgres suite passed all 38 tests in 24.31 seconds, runner 25.33 seconds.
This validates the current seed dialect path, claims, candidate windows, streaming,
indexes, full migrations and UTC semantics. It does not replace the separate
fault-injection evidence for JSON/DB publication or full application acceptance.
Both previously stopped quality containers were stopped again after validation;
their schemas and data were retained. No business database or application changed.

Ruff check and format passed for the changed test/suite scope. Effective-line
tests: 19 passed; ratchet: 1173 files, all above-500 tiers zero. Scoped diff checks
passed. No fast/security rerun, deployment, commit or push in this batch.

### Extract native console assets and manual-review HTTP ownership

Moved console asset/path/page readers out of the rebound auth-completion module
into collection_console_assets with an explicit build-directory argument. Server
facade wrappers retain late lookup of COLLECTOR_DESKTOP_DIST. The fallback HTML
was compared byte-for-byte before/after extraction and is unchanged. Native and
facade tests cover built/fallback pages, MIME/bytes, encoded traversal, missing
files and directories; isolated import proves no server-runtime initialization.
The static regression is now included in the fast/unit suite.

Formatting exposed 651 effective lines in server.py. Instead of adding an
exception, extracted manual-review repository/root readers into late-bound
ManualReviewReaders, DELETE transport into server_manual_review_delete, and GET
route groups into their existing manual-review owner. DELETE still authorizes
before parsing and preserves deletion, audit append, context read and response
ordering. All runtime callbacks and receipt paths are supplied by the facade.
Removed an unused source-contract marker and duplicate threading import.

The source-contract scanner follows native DELETE delegation and checks AST
calls rather than receiver names/quote style for 404 boundaries. Its initial
two failures were stale structural assumptions; affected HTTP behavior passed.
Initial console baseline: 2 passed. Console/native-import slice: 39 passed.
Expanded console, native import, source contract, route boundary, AVM HTTP,
collection status and HTTP guard group: 544 passed, 1111 subtests in 47.22 seconds.
After final test-lint/export-order cleanup, the affected source/native/route
group passed 49 tests in 12.66 seconds. These are sequential scoped results,
not a full fast/security or deployment acceptance claim.

Independent read-only reviews found no concrete regression. Scoped Ruff checks
and formatting passed; modified files remain UTF-8 without BOM. Effective-line
tests: 19 passed; final ratchet: 1176 files, all above-500 tiers zero, with no
baseline or exception changes. Server core/handler rebinding remains unfinished.
No deployment, application restart, business-data mutation, commit or push.

### Preserve failed challenge receipt snapshots and require fsync

Legacy and scoped challenge persistence now use archive_json_io.write_json,
replacing PID-named temporary files and failure cleanup. Both paths use unique
same-directory snapshots, flush/fsync before replace, and retain failed snapshots
without changing the confirmed receipt. Scoped cache publication remains under
the runtime lock and follows successful file publication. Legacy refresh keeps
the original challenge creation time and both paths preserve str-or-None errors.
The legacy helper imports the writer locally to remain valid under rebinding.

Four new fault cases failed before the patch: fsync faults were never reached,
and replace faults left no retained snapshot. After the patch, repeated fsync
and replace failures preserve confirmed bytes/cache and each failed snapshot;
recovery writes a new confirmed receipt without deleting old snapshots. Focused
durability/scope tests: 14 passed. Affected durability/scope/collection API/archive
tests: 121 passed in 11.27 seconds. Read-only review found no concrete regression.
The new regression is registered in the fast/unit suite.

New-test Ruff, scoped E9/F821, full formatting of the native scope module/test/suite
and range formatting of the modified legacy writer passed. A broader optional
lint probe still reports four existing BLE001 catches and one SIM103 in the
native scope module; this batch does not claim full lint closure there. Effective
line tests: 19 passed; ratchet: 1177 files, all above-500 tiers zero.

Milestone fast run: 657 passed in 83.46 seconds; runner 85.23 seconds, exit 1
because the unchanged 60-second threshold was exceeded. This supersedes the
older passing fast result for the current worktree. Fast performance acceptance
is open and requires profiling; no threshold relaxation or test removal.
No deployment, application restart, business-data mutation, commit or push.

### Remove N+1 job refresh from worker lease release

The diagnostic fast run kept the same suite/isolation/60-second threshold and
only expanded duration reporting: 657 passed in 88.79 seconds, runner 90.95 seconds,
exit 1. Release-worker bounded-window regression was the slowest call at 6.23
seconds. An added SQL-count assertion established the mechanism: releasing 257
progress rows issued 518 SELECTs because each job was refreshed separately.

seed_scan_job_status now shares the existing status policy between individual
refresh and batch refresh. Worker release flushes progress changes, fetches one
bounded job window and its distinct progress-status projection, then updates jobs
in the same transaction. The regression passes a ceiling of 10 SELECTs for the
same 257-row fixture, with the original 256-object identity-map ceiling, worker-b
lease assertions and all persisted-row assertions retained. No fixture was changed
to an in-memory DB and no workload/assertion was removed.

New SQLite/PostgreSQL contract tests compare individual and batch refresh across
empty, exhausted, blocked, active, archived and mixed progress; they check retained
completion timestamps and missing/duplicate keys. SQLite seed queue/maintenance/
status group: 60 passed, 2 dedicated-PostgreSQL cases skipped in 47.38 seconds.
Dedicated loopback PostgreSQL status/claims/insert-count group: 10 passed in 8.74
seconds; the previously stopped no-mount quality container was stopped afterwards,
with test schemas retained. This targeted group needs no PostGIS migration.

Independent review found no introduced regression. Helper/test lint, scoped
E9/F821, formatting and scoped diff checks passed. Effective-line tests: 19 passed;
ratchet: 1179 files, all above-500 tiers zero. The last full fast result remains
failed on time; it was not rerun or represented as passing after this slice.
Import profiling also measured server_context at 2.13 seconds, including storage
at 1.04 seconds; remaining fast cost needs separate investigation.
No deployment, application restart, business-data mutation, commit or push.

### Defer storage imports in read-only control-plane status paths

Import profiling traced collection_stage_status through manual_review_status,
analysis_stage_snapshots, manual_review_receipt_store and the backfill facade to
the shared control-plane context, which eagerly imported the full repository.
Moving storage imports to _build_repo after its injected-repository early return
removes SQLAlchemy/AVM loading from these read-only imports. Implementation type
annotations use TYPE_CHECKING. The public backfill facade retains its three
repository exports through lazy attributes, including dir and star-import support.
Repository construction, environment/explicit URL behavior and initialization
remain unchanged when a caller actually requests a repository.

Two strengthened fresh-process import tests failed before this patch and passed
afterwards, including reuse of an injected repository without importing storage.
The isolated collection_stage_status import measured 1.04 seconds before and
0.20 seconds after; these are diagnostic samples, not a stable benchmark claim.
Factory/import/runtime ownership/backfill regression group: 33 passed in 9.00
seconds. After the final test-only lint cleanup, factory/export tests: 5 passed.
Independent review raised the facade-export compatibility risk; lazy exports and
identity/star-import regressions address it without eager storage loading.

The intermediate full fast run, before the export-compatibility follow-up, had
663 passed and 2 dedicated PostgreSQL cases skipped, pytest 76.10 seconds and
runner 77.70 seconds, exit 1. The unchanged 60-second gate remains open; this is
not a full fast pass for the final worktree. The dedicated PostgreSQL cases had
already passed in the previous storage slice and their inputs were unchanged.

Scoped test lint, changed-range/native formatting and diff checks passed.
Effective-line tests: 19 passed; ratchet: 1180 files, all above-500 tiers zero.
No deployment, application restart, business-data mutation, commit or push.


### Observe real lock contention in scoped challenge regressions

The completed JUnit fast profile had 664 passed, 2 dedicated PostgreSQL skips,
pytest 63.59 seconds and runner 66.52 seconds (exit 1). Testcase durations summed
to 43.186 seconds against the XML suite time of 63.482 seconds; the remainder
includes collection and runner overhead and is not attributed to imports alone.
Independent measurement found source-contract function extraction about 0.315
seconds per run; its proposed optimization saved only about 0.196 seconds, so
that code was left unchanged.

The three scoped publication/read/reset concurrency regressions now observe a
failed nonblocking acquisition of the original shared RLock, then let the worker
block on that same lock. Their one-second negative waits are replaced by an
asserted contention event and a completion-state check before releasing the
controlled I/O boundary. Five-second failure bounds and all durable/cache/order
assertions remain. The original lock remains shared with runtime control state;
no production lock, persistence or network isolation behavior changed.

Focused scope/durability tests: 14 passed in 3.24 seconds. Independent review
found no blocker. Ruff fixed two existing trivial empty-dict lambda findings;
file lint and format checks passed. Effective-line tests: 19 passed; ratchet:
1180 files, all above-500 tiers zero. Scoped diff checks passed.

Final full fast on this code state: 664 passed, 2 dedicated PostgreSQL skips,
pytest 74.40 seconds, runner 75.81 seconds, exit 1. The 60-second gate remains
FAILED. Bootstrap subprocess tests varied from roughly 1.1-1.3 seconds in the
previous profile to 1.9-3.0 seconds here, so no aggregate speedup is claimed.
Next investigation remains collection/startup cost and its observed variability;
no unchanged broad suite was rerun merely to obtain a passing timing sample.
No deployment, application restart, business-data mutation, commit or push.


### Bound explicit quality-suite sibling collection

Collection-only cProfile identified directory enumeration, not server imports,
as the largest remaining fast overhead: 31,363 ignore checks and 111,714 stat
calls; Dir.collect cumulative time was 18.027 seconds under instrumentation.
A path-count probe localized 31,027 ignore checks to tools/test. The initial
confcutdir hypothesis was rejected: pytest already discovered the repository
pytest.ini, and the outside-project regression did not fail. No confcutdir
change was retained.

The runner now supplies an absolute repository-root ignore glob. Pytest bypasses
ignore rules for explicit files and their parent paths, while skipping unselected
siblings before constructing their collectors. The relative glob was ineffective
from the isolated temporary CWD and was corrected to a root-derived absolute
pattern. Suite membership, temporary storage, network fixtures, rootdir, failure
propagation and the 60-second threshold remain unchanged. All six suite manifests
were checked: every entry is an existing explicit file, with no directory entries.

The strengthened real subprocess regression rejects construction of an unselected
sibling directory collector. Both parameter cases failed before the runner fix
and passed afterwards; selected standard/nonstandard filenames, project fixtures
and successful/failing child exit codes remain covered. Scoped Ruff lint/format
and diff checks passed. Effective-line tests: 19 passed; ratchet: 1180 files,
all above-500 tiers zero. A scout could not start because its configured model
provider was unavailable; investigation and final verification were completed
locally, without claiming independent review of this slice.

Final official fast: 664 passed, 2 dedicated PostgreSQL skips in 48.18 seconds;
runner elapsed 49.61 seconds, exit 0. This is a fresh PASS of the unchanged
60-second gate on the current code state, with the same 666 collected cases.
It does not establish PostgreSQL, security, desktop or deployment acceptance for
the complete optimization plan. No unchanged broad suite was rerun afterwards.
No deployment, application restart, business-data mutation, commit or push.


### Security milestone and durable auth-completion confirmations

Before this persistence slice, the official isolated security suite passed:
414 passed, 4 skipped in 75.79 seconds; runner 76.91 seconds, exit 0. This
validates the explicit-suite collection runner against the security manifest,
not the later persistence change or full release/runtime acceptance.

The remaining auth-completion confirmation writer used a PID temporary file,
no fsync, and deleted failed write snapshots. It now uses archive_json_io.write_json
with a function-local import safe under existing server function rebinding.
Unique retained pending snapshots, flush/fsync and atomic replacement precede
the existing cache update under the recovery lock. Confirmation merging and
retention policy, public return/error behavior and locking remain unchanged.

The shared durability fixture now includes completion receipts. Both new fsync
and replace fault cases failed before the patch. Consecutive failures now retain
confirmed bytes and cache plus distinct failed snapshots; recovery verifies disk
and completion-cache agreement and preserves failed snapshots. A trial generic
cache assertion was corrected because the legacy challenge writer intentionally
only publishes to disk; its existing exact recovered-ID assertion is retained.

Initial focused group: 25 passed. Final affected scope (durability, collection API
status, control concurrency, seed-probe confirmation): 114 passed in 5.80 seconds.
An earlier AVM HTTP name filter selected zero tests and is not counted as evidence.
Test lint/format, changed-function range formatting, diff check and source syntax
via import passed. Whole legacy control-module F821 check reports 71 unresolved
facade names; this slice does not claim that module lint-clean or remove rebinding.
Effective-line self-tests: 19 passed; final ratchet: 1180 files, no above-500 tiers.
The prior 49.61-second fast PASS predates this slice; no fresh whole-fast result
is claimed for the added two cases. No deployment, restart, business-data mutation,
commit or push.


### Explicit authentication confirmation storage ownership

Extracted normalization, tolerant reading, confirmation lookup and durable
publication into src/auth_completion_store.py. The native module receives the
receipt path, SolverRecoveryState and clock explicitly and has no server-context
or repository import. Timestamp acquisition remains inside the existing shared
lock. Disk/cache merge precedence, trimming policy, tolerant read behavior and
publication error returns are unchanged. Existing server entrypoints delegate
with the current path and recovery state on each call; server.py did not grow.

Durability fault cases now run against both facade and native completion writers.
A fresh-process import assertion checks that the native module does not load
server/context/storage/AVM/solver initialization. A runtime replacement regression
verifies distinct receipt paths and caches, including rejection of the prior
runtime confirmation in the replacement runtime. Remaining facade wrappers and
other FunctionType rebinding are explicitly not closed by this extraction.

An initial direct pytest invocation omitted the PYTHONPATH required by the
fresh-process tests and failed 17 subprocess import cases; that run is not a
passing gate. The final affected group used the official isolated quality runner
with an explicit temporary focused manifest: 136 passed in 17.94 seconds, runner
19.12 seconds, exit 0. Native/test full Ruff lint and format checks passed; scoped
diff checks passed. Effective-line self-tests: 19 passed; ratchet: 1181 files,
all above-500 tiers zero. No full-fast or full-security result is claimed for
this later worktree. No deployment, restart, business-data mutation, commit or push.


### Preserve unreadable authentication confirmation receipts

The extracted reader exposed a pre-existing loss path: malformed JSON, wrong
receipt shape or invalid timestamps became an empty/partial map, allowing the
next completion to overwrite the original evidence. Four initial negative cases
failed against that behavior before the fix. The reader now treats only a missing
file as empty; malformed content, invalid/ambiguous normalized IDs, non-finite,
negative or boolean timestamps fail validation. Normal numeric timestamps remain
accepted. Publication catches read/validation errors and returns the existing
error-string result before writing or changing the cache. Confirmation lookup
propagates unreadable-state errors rather than confirming from stale cached data.

Ten malformed-receipt cases verify original bytes and cache remain unchanged,
no temporary write is started, and a cached confirmation cannot mask corruption.
Focused durability file: 19 passed. Final isolated affected group (durability,
collection API status, control concurrency, seed-probe and native imports):
146 passed in 13.74 seconds, runner 14.73 seconds, exit 0. Native/test Ruff lint,
format and scoped diff checks passed. Effective-line self-tests: 19 passed;
ratchet: 1181 files, all above-500 tiers zero. No full-fast/security or live
acceptance is claimed for this state. No deployment, restart, business-data
mutation, commit or push.


### Native read-only collection observer queries

Moved collection item-list, region-list and item-detail query construction into
collection_observer_queries with an explicit repository parameter. The shared
integer query parser now lives there and is re-exported by the legacy status
module without FunctionType cloning. Existing public query entrypoints retain
late-bound DB_REPOSITORY delegation; validation, defaults/clamps, unavailable
repository payloads and result fields are unchanged. Storage annotations are
TYPE_CHECKING-only, so this read-only module imports without server/storage setup.

Added direct/native and facade tests for repository replacement, stage
normalization, upper/lower numeric bounds, invalid numeric fallback, missing IDs
and disabled/missing repository methods. Final isolated affected group (collection
API status, native imports, source contracts and HTTP guards): 162 passed in
16.23 seconds, runner 17.14 seconds. After changed-range formatting, the five new
query behavior cases passed again. An earlier direct invocation selected a fresh
process import test without PYTHONPATH and failed that import; only the corrected
isolated runner result establishes import acceptance.

Native/test lint and format checks passed, plus scoped diff check. Effective-line
self-tests: 19 passed; ratchet: 1182 files, no above-500 tiers. Remaining collection
write/control/auth orchestration and broader facade rebinding remain open. No
full-fast/security, deployment or live acceptance is claimed for this state.
No deployment, restart, business-data mutation, commit or push.


### Native collection observer command boundary

Moved reanalysis, manual-update and region-link-reset request validation and
repository calls into collection_observer_commands. Each function receives its
repository explicitly; the original facade delegates with the current repository.
HTTP authorization, body parsing, response codes and exception handling remain
in their existing handlers. No actual repository mutation or business service
operation was performed during this refactor.

New native/facade parameterized command tests cover repository replacement,
argument normalization, empty/invalid input before any repository access,
disabled/missing-method repositories, and publication exceptions reaching the
HTTP boundary. The file is registered in UNIT_FILES and therefore the fast suite.
Direct command regressions: 34 passed. Final isolated affected group (commands,
collection API status, native imports, source contracts and HTTP guards):
197 passed in 17.59 seconds, runner 18.67 seconds. Correctly selected live-loopback
GET/POST observer error-contract tests: 2 passed, 348 deselected, including the
three command routes. An initial misspelled filter selected zero tests and is
not counted as acceptance.

Native/test/suite Ruff lint and formatting passed; scoped diff checks passed.
Effective-line self-tests: 19 passed; ratchet: 1184 files, no above-500 tiers.
The new command module imports without server/context/storage initialization.
Remaining runtime-control/auth orchestration and full server rebinding removal
are open; no full-fast/security or deployment acceptance is claimed for this
state. No deployment, restart, business-data mutation, commit or push.


### Resume commits runtime release after durable cleanup

Reproduced a control-boundary bug: resume cleared collection pause, advanced the
resume epoch and reset solver state before deleting manual flags/challenge files.
All four new flag/challenge permission-failure cases failed before the patch,
including requests with only a scoped pause and those with an operator pause.

Resume now holds the shared RuntimeState lock, keeps collection paused, and
performs durable cleanup before committing the resume epoch, solver/manual state
reset and final unpause. Failure retains the pause and prior solver outcome/epoch;
a later retry after the fault succeeds. Existing cleanup can still be partial
across multiple files; this is fail-closed runtime coordination, not a claimed
cross-file atomic transaction or restart-recovery acceptance.

The new regression uses real temporary flags/receipts and narrowly injected
remove/unlink failures, verifies the failed receipt bytes remain unchanged, and
checks successful recovery. A separate cross-thread nonblocking acquisition
probe proves the shared runtime lock spans cleanup while pause/epoch remain
uncommitted. Tests are registered in the fast/unit manifest.

Affected isolated group before the final test-only lock probe: 134 passed in
15.80 seconds, runner 17.33 seconds. Final resume regression file: 5 passed in
2.37 seconds. Test/suite lint and format checks, source changed-range formatting
and scoped diff checks passed. Effective-line self-tests: 19 passed; ratchet:
1185 files, no above-500 tiers. No full-fast/security or live deployment result
is claimed for this state. No deployment, restart, business-data mutation,
commit or push.


### Combined fast/security milestone and native typing gates

Fresh official fast after the confirmation/observer/resume slices passed:
726 passed, 2 dedicated PostgreSQL skips in 57.34 seconds; runner 59.12 seconds,
exit 0 against the unchanged 60-second threshold. The timing margin is small;
this is a measured run, not a guarantee of stable host performance.

Subsequent strict checking found eight typing issues in the three new native
modules: legacy dependency return types and an integer default inside a string
list expression. Explicit casts document the trusted legacy return boundary;
the integer parser now branches on missing values before conversion, preserving
its fallback/clamp behavior. No runtime validation or security guard was relaxed.
Strict mypy (--explicit-package-bases --follow-imports skip) now passes these
three files; this does not claim the entire legacy repository is type-safe.

Added CI lint, format and strict-mypy steps for the native confirmation/observer
modules and their relevant tests. All added commands passed locally; CI YAML
parsed successfully and contains the three intended steps. The project venv
lacks mypy/PyYAML, so checks used uv tool/ephemeral environments without changing
project dependencies. Post-typing focused behavior regressions: 63 passed in
3.20 seconds. Final official security: 414 passed, 4 skipped in 82.84 seconds;
runner 84.38 seconds, exit 0. Fast predates the typing edits and is not relabeled
as a fresh full run of the final source state.

Effective-line self-tests: 19 passed; ratchet: 1185 files, no above-500 tiers.
Scoped diff/status and seven-file lint/format checks passed. Remaining full-plan
structural, PostgreSQL/desktop and live release acceptance work remains open.
No deployment, restart, business-data mutation, commit or push.


### Authentication finalization cannot erase a newer challenge

A deterministic interleaving reproduced loss of a newly published scoped
challenge: finalization validated the old ID while holding only finalize_lock;
an incoming writer used RuntimeState.lock and published a new ID before the old
cleanup ran. The regression failed with the final challenge ID None instead of
new. Finalization now holds both the existing finalize_lock and RuntimeState.lock
across current-ID validation, durable cleanup, confirmation and outcome update.
The incoming writer waits, then publishes after finalization releases the shared
lock, preserving the new durable challenge. The only finalize_lock acquisition
site was checked; no reverse acquisition site was found in current source.

The regression uses an actual temporary receipt, an event signaling the writer
attempt, and a nonblocking shared-lock probe; it does not rely on timed negative
waits. Scope tests: 10 passed. Final isolated affected group (scope, resume commit,
durability, collection status, control concurrency and seed confirmation):
141 passed in 7.02 seconds, runner 8.30 seconds, exit 0. Test lint/format and
scoped diff checks passed. Effective-line self-tests: 19 passed; ratchet: 1185
files, all above-500 tiers zero. Earlier fast/security results predate this fix;
no fresh full-suite or live acceptance is claimed. Other auth entrypoint and
structural boundaries remain open. No deployment, restart, business-data mutation,
commit or push.


### Cooldown resume preserves concurrent challenge publication

Extended the deterministic new-challenge interleaving regression to cooldown
resume. The prior finalization case passed while cooldown failed with its newly
written challenge erased (None instead of new). Cooldown now holds RuntimeState
lock across scope/ID matching, receipt lookup, cleanup, durable confirmation and
state/grace commit. Response formatting remains outside the critical section.
No extra facade helper, function clone or new lock was introduced. This provides
in-process serialization; cross-file atomicity and restart acceptance remain
separate open requirements.

Scope tests: 11 passed after the fix. Final isolated affected group covering
scope, resume failures, durability, collection API status, control concurrency,
seed confirmation and source contracts: 156 passed in 11.74 seconds, runner
12.89 seconds, exit 0. Test lint/format, changed-range source formatting and
scoped diff review passed. Effective-line self-tests: 19 passed; ratchet: 1185
files, all above-500 tiers zero. No fresh full-fast/security or live result is
claimed for this state. Other authentication entrypoints and the larger
structural migration remain open. No deployment, restart, business-data mutation,
commit or push.

### Direct auth completion preserves concurrent challenge publication

Extended the deterministic challenge-publication regression to the direct
auth-complete branch. Before the fix, the new challenge was erased (None
instead of new); the existing finalize/cooldown cases passed. The direct path
now holds RuntimeState.lock across challenge revalidation, cleanup, receipt
publication and solver outcome/grace update. Cookie snapshot scheduling remains
outside that lock; a second regression publishes a new challenge during scheduling
and proves its solver outcome is not overwritten afterward. No reverse acquisition
of finalize_lock was introduced. Focused independent review found no blocker.

Final isolated affected group: 158 passed in 10.90 seconds, runner 11.95 seconds,
covering scope runtime, resume commit, durability, collection API status, control
concurrency, seed confirmation and source contracts. An earlier command selected
two nonexistent test filenames and ran no tests; the corrected run above is the
acceptance evidence. Test Ruff lint/format, source compilation, changed-range
formatting and scoped diff checks passed. Effective-line self-tests: 19 passed;
ratchet: 1185 files, all above-500 tiers zero. Existing dirty changes were retained.

This closes the direct cleanup interleaving only. Preparation/async/idempotent
entrypoint boundaries, cross-file durability and the larger structural migration
remain open. No fresh full-fast/security, PostgreSQL, desktop or live acceptance
is claimed. No deployment, application restart, business-data mutation, commit
or push was performed.

### Async auth completion preserves the finalizer's committed outcome

Two deterministic regressions reproduced redundant caller-side outcome writes:
a background finalizer could finish before the caller consumed the pending
snapshot response and then be reverted to manual_required; a new challenge
published after synchronous finalization could have its outcome overwritten by
the old completion. The caller now leaves async outcomes to phase-one pause and
the finalizer. Direct cleanup retains its locked commit; the temporary
direct_state_committed flag is no longer needed. Previously confirmed receipt
replay behavior is unchanged and remains a separate boundary to examine.

Both new cases failed before the fix. The isolated affected group now passes
160 tests in 14.75 seconds (runner 16.70 seconds): scope runtime, resume commit,
durability, collection status, runtime-control concurrency, seed confirmation
and source contracts. Test Ruff lint/format, source compilation and scoped diff
checks passed. Effective-line self-tests: 19 passed; ratchet: 1185 files, all
above-500 tiers zero. No broad suite was rerun for this change. No deployment,
restart, business-data mutation, commit or push. Overall optimization and full
release acceptance remain incomplete.

### Confirmed receipt replay no longer renews authentication grace

Added receipt replay cases with and without a newly published scoped challenge.
Both failed before the fix: replay replaced completed_at=123 with the current
time and replaced the original completion request. Removed the remaining caller
outcome/grace write; direct completion and finalization still own initial commits.
Replay preserves completed_at, completed_request, completed_detail_count and
the solver outcome observed after concurrent challenge publication. Existing
idempotent response semantics are retained.

Current isolated affected group: 162 passed in 11.24 seconds, runner 12.55
seconds. Test Ruff lint/format, source compilation and scoped diff checks passed.
Effective-line self-tests: 19 passed; ratchet: 1185 files, all above-500 tiers zero.
At this authentication milestone, the official isolated security suite was run:
422 passed, 4 skipped in 73.39 seconds, runner 74.70 seconds, exit 0. Skips remain
unverified gates; the result does not establish PostgreSQL, desktop or live
acceptance. A loopback request exception notice appeared during the suite but
did not fail a test. No threshold, suite selection or isolation was weakened.

Preparation/scope-selection races and the broader original structural backlog
remain open. No deployment, restart, business-data mutation, commit or push.

### Native lightweight collection status assembly

Moved lightweight status arithmetic and response assembly out of the cloned
server_collection_status implementation into collection_status_payload. The
native module imports only typing/collections and receives explicit statistics,
metrics, runtime, build and label dependencies. Deferred callbacks preserve
existing read order and failure behavior. The public server wrapper resolves
current dependencies on each call. It remains a compatibility wrapper in the
core binding list; this does not eliminate the remaining FunctionType mechanism.

Before extraction, status/native-import tests: 116 passed. After extraction:
118 passed in 14.78 seconds, runner 16.19 seconds. Added fresh-process native
import isolation and current-dependency delegation proof. After binding a test
loop variable for Ruff, the changed native-import suite passed 29 tests in
8.35 seconds. A temporary deterministic old/native comparison passed 102 cases
for full response equality, callback order, valid/invalid statistics and malformed
count failure behavior. No legacy implementation was retained in product code.

New module strict mypy, Ruff lint/format, Python compilation and scoped diff
checks passed. CI includes the native module in lint/format/strict typing checks;
workflow YAML parsed. Effective-line self-tests: 19 passed; ratchet: 1186 files,
all above-500 tiers zero. Earlier security evidence predates this extraction;
no new full-suite or runtime acceptance is claimed. No deployment, restart,
business-data mutation, commit or push. Remaining status orchestration, core
bindings and the full original optimization checklist are not complete.

### Native seed queue count loading

Moved default counts and repository fallback into collection_queue_counts with
an explicit repository protocol. The server re-exports the native default factory
and delegates loading with its current repository/default factory. Disabled or
missing methods return fresh defaults; native seed counts take priority and
retain extra keys; legacy search counts retain integer/null conversion. Query
failures propagate without silently falling back to legacy counts. The unrelated
collection-stage error policy was not changed.

Added five repository-contract cases before extraction: the native-import suite
passed 34 tests. After extraction, both facade/native variants plus import
isolation and collection API status passed 129 tests in 15.48 seconds, runner
16.55 seconds. Native strict mypy, Ruff lint/format, source compilation and scoped
diff checks passed. CI now covers this native module in its existing typing and
format/lint gates. Effective-line self-tests: 19 passed; ratchet: 1187 files,
all above-500 tiers zero. No full-suite rerun, deployment, restart, business-data
mutation, commit or push. Remaining server bindings and full-plan acceptance
are still open.

### Native repository status read boundaries

Moved pending-task, aggregate-count and recent-event reads into
collection_repository_status with an explicit repository. Server wrappers keep
the public entrypoints and resolve current repository/preference dependencies.
Preserved three distinct failure policies: pending reads log and return empty;
aggregate reads fall back to four counters and propagate fallback failures;
event reads propagate failures. The aggregate catch retains a documented BLE001
exception for compatibility. Type-only storage imports avoid runtime bootstrap.

Four new behavior tests passed before extraction. Facade/native variants,
fresh-process imports, API status and solver logging then passed 144 tests in
11.37 seconds, runner 12.19 seconds. Logging is now additionally checked at
runtime with exception-info assertions. Tests are registered in UNIT_FILES;
native lint/format/strict mypy checks are registered in CI. Local checks passed,
including compilation and YAML parsing. Ruff corrected mixed line endings in
the edited suite-manifest lines; the subsequent format check passed.

Effective-line self-tests: 19 passed; ratchet: 1189 files, all above-500 tiers
zero. Broad suite and live acceptance were not rerun. The status facade still
has remaining runtime orchestration and core rebinding; overall plan completion
is not claimed. No deployment, restart, business-data mutation, commit or push.

### Native cookie snapshot retry policy

Extracted the retry loop into auth_cookie_snapshot_retry with explicit state
writer, refresh, finalizer, clock and sleep dependencies. The server wrapper
retains late resolution of the three runtime effects; attempt/backoff settings
are read once at entry as before. The native module imports no server/storage
runtime. Snapshot scheduling and shared state ownership remain in their current
owners; this slice does not eliminate the status facade's core binding.

Pre-extraction API/scope proof: 106 passed. Post-extraction retry, API, scope and
native-import proof: 153 passed in 13.02 seconds, runner 14.00 seconds. New tests
cover refresh exceptions, invalid results, 300-second capped backoff, injected
timestamps, disabled/success/failed terminal states and finalizer invocation.
After a lint-only test mapping correction, the five retry tests passed again.
The existing finalizer-exception propagation is explicitly covered and remains
an open runtime failure-handling issue; this behavior-preserving extraction did
not silently change it.

Ruff lint/format, strict native mypy, compilation, YAML parse and scoped diff
checks passed. New tests and CI native gates are registered. Effective-line
self-tests: 19 passed; ratchet: 1191 files, all above-500 tiers zero. No broad
suite/live acceptance, deployment, restart, business-data mutation, commit or
push. Full optimization-plan completion remains unproven.

### Cookie finalization exceptions publish a terminal snapshot state

Reproduced the dead-worker/running-status mismatch with OSError, ValueError and
RuntimeError: all three cases left only the running update before the fix.
The retry owner now records failed, auth_state_confirmed=false, retry_queued=false,
the completion timestamp and a generic auth_finalization_failed reason before
re-raising the original exception. refreshed remains true because cookie refresh
succeeded; inspected success consumers also require completed status. No automatic
repeat of potentially partial finalization is introduced, and exception details
are not copied into the new client-visible failure reason.

Affected retry/API/scope group: 113 passed in 15.36 seconds, runner 17.86 seconds.
Then an added runtime-state/scheduler test verified visible failure and successful
explicit rescheduling of the same receipt using a real worker thread; the final
retry file passed 8 tests in 4.06 seconds, runner 6.38 seconds. Test doubles cover
refresh/finalization; this is not browser or durable cross-file acceptance.
The catch does not roll back partial finalizer mutations or mask an error from
the state writer itself; those boundaries remain outside this fix.

Ruff lint/format, native strict mypy, compilation and scoped review passed.
Effective-line self-tests: 19 passed; ratchet: 1191 files, all above-500 tiers zero.
No broad-suite rerun, deployment, restart, business-data mutation, commit or push.
The earlier extraction's open finalizer-status issue is now addressed; remaining
runtime and structural plan requirements are still incomplete.

### Snapshot worker launch failures leave no pending task

Thread construction and Thread.start failure both reproduced an orphan pending
snapshot. The scheduler now clears the unstarted worker reference and records
failed with retry_queued=false, auth_state_confirmed=false and a generic
snapshot_worker_start_failed reason before re-raising the original exception.
Cleanup remains inside the shared state lock. Runtime pause state is preserved;
the exception text is not added to the client-visible snapshot state.

Both new regression cases failed before the fix, then proved that the same
receipt can be rescheduled with a real worker after the injected failure is
removed. Affected retry/API/scope tests: 116 passed in 4.65 seconds, runner
5.56 seconds. Test lint/format, changed-range source formatting, compilation and
scoped diff checks passed. Effective-line self-tests: 19 passed; ratchet: 1191
files, all above-500 tiers zero. No broad-suite or live acceptance was rerun.
No deployment, restart, business-data mutation, commit or push. Remaining
snapshot scheduling ownership and the overall structural plan stay open.

### Restore fast-gate margin with atomic SQLite schema creation

The full accumulated fast gate ran 767 passed/2 skipped but failed its unchanged
60-second limit: pytest 77.52 seconds, runner 79.30 seconds. Investigation of
slow repository factory/setup tests found schema DDL executing outside SQLite
transactions. An isolated temporary-file probe observed 88 CREATE statements
outside a transaction (0.306 seconds), versus none outside an explicit transaction
(0.021 seconds). These are local observations, not guaranteed host timings.

SQLite auto_create now runs metadata creation on one engine.begin connection,
issuing BEGIN only when the DBAPI connection is not already in a transaction.
Non-SQLite and PostGIS initialization paths remain unchanged. A new regression
interrupts after the second CREATE TABLE: before the fix two partial tables
remained; afterward only the pre-existing table and its row remain, and retry
creates the complete schema. The existing per-repository initialization lock
and success-only initialized marker are retained. Independent focused review
found no blocker; alternate SQLite drivers were not tested.

Focused initialization/factory/status checks: 12 passed, 2 skipped, 1.31 seconds.
Fresh full fast gate after the fix: 768 passed, 2 skipped in 38.90 seconds;
runner 40.81 seconds, exit 0. No tests were removed, no selection narrowed, and
neither the 60-second threshold nor data/network isolation was weakened. The
two skips remain excluded acceptance, not passing database integration evidence.
Test Ruff lint/format, changed-range source formatting, compilation and scoped
diff checks passed. Effective-line self-tests: 19 passed; ratchet: 1191 files,
all above-500 tiers zero. No deployment, restart, business-data mutation, commit
or push. Full security/PG/desktop and original-plan completion remain separate.

### Native cookie snapshot single-flight scheduler

Moved enabled-refresh scheduling into auth_cookie_snapshot_scheduler. Runtime
state, attempt settings, worker callable, clock and thread factory are explicit
dependencies. The shared lock still spans active-worker/reused-completion checks,
state publication, worker registration and startup. Launch-failure cleanup and
exception propagation are preserved. The facade retains the disabled-request
branch and resolves dependencies when invoked; complete core rebinding removal
is not claimed.

New native/facade real-thread tests verify a second request reuses the active
worker without overwriting stored state, payload/completion-request dictionaries
are copied, and completed-receipt reuse does not start another worker or re-read
attempt settings. Together with existing launch-failure, retry, API, scope and
fresh-import tests: 161 passed in 16.82 seconds, runner 18.33 seconds. Focused
independent review found no introduced blocker.

Native strict mypy, Ruff lint/format, compilation, workflow YAML parse and scoped
diff checks passed; new tests/CI checks are registered. Effective-line self-tests:
19 passed; ratchet: 1193 files, all above-500 tiers zero. The previous 40.81-second
fast result predates this extraction; no new full-fast/live acceptance is claimed.
No deployment, restart, business-data mutation, commit or push. Remaining status
facade ownership and the full optimization checklist remain open.

### Native overview stage summaries

Moved overview links/detail/analysis field serialization into the existing
collection_status_payload module. The server facade retains status/runtime reads,
operator pause classification and diagnostic I/O. The native projection runs at
the same point after restart/challenge/watcher diagnostics; field labels, integer
coercion, null defaults and legacy finalized-count fallback are unchanged.

Three new facade tests verify operator/manual pause classification and exact
diagnostic-to-projection order. Status/native-import tests: 135 passed in 14.39
seconds, runner 15.36 seconds. A temporary deterministic comparison against the
pre-extraction expression passed 62 complete response/error cases including null,
numeric string, fractional value, absent finalized key and malformed count inputs.
No old projection implementation was retained in product code.

Native strict mypy, Ruff lint/format, compilation and scoped diff checks passed.
Effective-line self-tests: 19 passed; ratchet: 1193 files, all above-500 tiers zero.
Existing CI gates already cover both modified native module and test file. No
broad-suite rerun or live acceptance; remaining facade/runtime ownership and full
plan requirements stay open. No deployment, restart, business-data mutation,
commit or push.

### Disabled refresh preserves an active snapshot worker

The native scheduler now checks for an active worker under the shared lock before
handling refresh_cookie_snapshot=false. A disabled second request returns the
active receipt without replacing its pending state. The facade delegates this
decision to the scheduler. Idle disabled requests retain skipped semantics and
do not read retry settings, sample the clock, create a thread or invoke a worker.

The active-worker regression previously reproduced one failure and three passes;
the fix passed the 120-test retry/status/scope affected group (5.01 seconds,
runner 6.28 seconds). After adding idle no-effects coverage, the scheduler-only
suite passed 5 tests in 1.38 seconds (runner 2.23 seconds). These are separate
runs, not a combined full-suite result. Ruff lint/format and native strict mypy
passed. Effective-line self-tests passed 19 tests; ratchet passed across 1193
files with all above-500 tiers zero. Scoped diff checks passed.

The optimization plan remains open, including remaining facade ownership and
release/runtime acceptance. Deployment remains deferred until code tasks are
complete; no application restart or business-data mutation was performed.

### Native collection runtime snapshot assembly

Moved runtime snapshot assembly into collection_status_payload with explicit
solver and recovery readers. The facade resolves current runtime dependencies
on each invocation. Solver status is read once before recovery; invalid scope
containers still become an empty dictionary, valid dictionaries retain identity,
and reader exceptions propagate unchanged without invoking later readers.

Before extraction, native-import tests including the new facade contract passed
58 tests in 12.84 seconds (runner 14.25 seconds). After extraction, native/facade
contract cases and status API tests passed 159 tests in 15.92 seconds (runner
16.95 seconds) using isolated temporary storage. Native strict mypy, Ruff
lint/format, compilation and scoped diff checks passed. Effective-line self-tests
passed 19 tests; ratchet passed 1193 files with all above-500 tiers zero. Existing
CI checks already include the native module and contract test file.

Read-only binding review confirmed server_collection_status is still cloned by
server.py; this slice does not complete FunctionType removal. Overview I/O and
facade dependency ownership remain open. No broad-suite rerun, deployment,
restart, business-data mutation, commit or push occurred.

### Native observer overview orchestration

Moved overview response assembly into collection_status_payload with explicit
status, control, data-root and diagnostic readers. The facade keeps dependency
resolution; reads still occur in status/control/root/restart/challenge/watcher
order before module projection. Pause classification and response fields remain
unchanged. Diagnostic failure tests assert exception identity and that subsequent
diagnostics and module projection do not run.

Pre-extraction native-import baseline passed 79 tests (14.48 seconds; runner
16.51 seconds). An initial type-only annotation caused a NameError during import;
quoting the forward reference fixed it. The corrected status/native-import suite
passed 168 tests in 18.03 seconds (runner 19.41 seconds), using isolated storage.
Ruff lint/format, native strict mypy, compilation and scoped diff checks passed.
Effective-line self-tests passed 19 tests; ratchet passed 1193 files with all
above-500 tiers zero. No full-fast or release/runtime acceptance is claimed.
The status facade still requires explicit binding work before FunctionType
removal. Deployment remains deferred; no restart or business-data mutation.

### Native collection status bindings (2026-09-25 continuation)

Resumed conversation 01a0d6c0-d589-7d41-9b05-1597d4bc2207 at its final milestone
check. Work remains based on HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus
the existing dirty worktree. The previous conversation's 810-test fast result
and 422-test security result were recovered as historical evidence, not reused
as proof for the new bindings.

server_collection_status is now outside the legacy cloning list. Its nine
stateful readers are native CollectionStatusReaders methods with explicit
repository, runtime and diagnostic providers. The two cookie refresh entrypoints
are native AuthCookieSnapshotJobs methods. Public server entrypoints remain
available, and retained callables observe replaced runtime/repository objects.
Existing read order, failure propagation, scheduling locks and retry behavior
are preserved. These native modules can import without initializing the server,
storage, captcha, AVM or LLM runtime.

ModuleExports now owns startup publication and the remaining legacy rebinding.
It preserves function defaults, keyword defaults, annotations, closures, metadata
and target globals. ManualReviewReaders declares its own exported method names.
This keeps server.py at 493 effective lines without an exception. Moving the
remaining rebinding mechanism into this owner does not remove it: eight core
modules and five handler modules still require migration.

Verification proceeded from the behavior boundary to the shared bootstrap:

- Pre-edit status/cookie/repository baseline: 191 passed, pytest 17.25 seconds,
  runner 18.70 seconds. The added native status import regression failed before
  the fix because it loaded server_context and the heavy runtime dependencies.
- Native publication, status HTTP, repository reads, cookie retry/scheduling,
  source contracts and auth concurrency: 229 passed, pytest 24.56 seconds,
  runner 25.59 seconds. New tests include a real status projection after replacing
  the repository/runtime and preservation of legacy callable contracts.
- Ruff lint/format checks passed for the affected native modules and tests;
  server.py binding ranges used the official formatter. Strict mypy passed for
  eight native source files, Python compilation passed, and CI YAML parsed.
- Required effective-line checker tests: 19 passed. Ratchet: 1196 files, with
  all handwritten above-500 tiers zero. No baseline or exception was changed.
- First normal fast run: 817 passed, 2 skipped, pytest 70.85 seconds, runner
  72.95 seconds. This failed the unchanged 60-second gate, so security did not
  start in that attempt. A separate cProfile diagnostic used the same test
  selection and completed in 50.41 seconds; it is not a fast-gate acceptance run.
- Final official fast run: 817 passed, 2 skipped, pytest 40.29 seconds, runner
  41.73 seconds, exit 0. Final security run: 422 passed, 4 skipped, pytest
  77.18 seconds, runner 78.56 seconds, exit 0. Only skipped-case reporting was
  enabled for these runs; code, selection, thresholds and isolation were unchanged
  after the first timing failure. The precise cause of that timing variation
  remains unproven; the successful rerun does not establish a latency guarantee.

The two fast skips are PostgreSQL seed-job status refresh cases. Security skips
two POSIX child-signaling cases and two PostgreSQL timestamp-migration cases.
No PostgreSQL, Linux/PC2, desktop release or live runtime acceptance is inferred
from those skips. All Python test runs used isolated temporary storage with the
business database disabled. Existing organized data and runtime configuration
were not modified.

New tests are registered in UNIT_FILES and native static checks are registered
in CI. Changed files were checked as valid UTF-8 without BOM; diff checks passed.
The original optimization plan remains incomplete. The next structural boundary
is the remaining core/handler ownership, including server_collection_control;
its auth preparation and durable finalization requirements must retain their
own behavioral/concurrency proof. Deployment and application restarts remain
deferred until the code tasks are complete. No commit or push was performed.


### Bind authentication completion preparation to one challenge generation

Reconciled the original 58 findings and structural batches against current source,
call sites, test manifests, and the later progress entries. The current inventory is
code-quality-remaining-20260925.md. It distinguishes remaining code, implemented
capabilities, conditional-platform skips, historical evidence, and deferred rollout.

The audit exposed a concrete auth-completion preparation race: validation could
accept an old challenge and a later unprotected read could capture a new challenge
ID for snapshot finalization. Three real-thread regressions (PC2 local solver,
seed auth probe, operator) all failed before the fix by confirming the newer
challenge. Preparation now holds the runtime lock across validation, scope/request
selection and expected-ID capture. The async path rechecks the captured ID under
the same lock before publishing manual-required state. Scheduling/finalization
remain outside that lock, preserving the existing finalizer lock order.

The regression verifies the newer receipt bytes, challenge ID, paused state and
solver outcome survive and that the old completion is not recorded as confirmed.
Existing direct/async lock-release, idempotent replay, target-binding and cleanup
tests remain intact. This closes the preparation race, not all legacy/scoped or
multi-file auth-finalization work.

Fresh verification on this worktree:

- New regression: 3 failing cases before the production patch, all 3 pass after it.
- Affected scope/status/target/cookie/source-contract group: 145 passed,
  pytest 11.97 seconds, runner 13.31 seconds.
- Official fast: 820 passed, 2 skipped, pytest 42.48 seconds, runner 43.61 seconds,
  exit 0 under the unchanged 60-second gate.
- Official security: 425 passed, 4 skipped, pytest 76.61 seconds, runner
  77.70 seconds, exit 0.
- Regression Ruff lint, source syntax/bug rules, official format checks and Python
  compilation passed. Legacy console F821 still identifies the same 21 unique
  facade names as before; no new unresolved name was introduced. Full native
  ownership and strict typing are not claimed for this module.
- Effective-line self-tests: 19 passed. Ratchet: 1196 files, no handwritten
  above-500 tiers. Edited console: 253 effective lines; regression file: 480.

Fast skips remain the two PostgreSQL seed-job status cases. Security skips remain
the two POSIX child-signaling and two PostgreSQL UTC migration cases. No fresh
PostgreSQL, Linux/PC2 or desktop-release acceptance is claimed. All test storage
was isolated and the business DB disabled. Deployment and application restarts
remain deferred; no business-data changes, commit or push.

### Close scoped auth-cleanup deletion failure verification (2026-09-25)

Resumed session `01a0d840-68b9-7c53-991a-0e06c68d29ce` at HEAD
`f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` with 217 inherited dirty/untracked
entries. The session had already applied the cleanup fix and regression tests
and recorded 191 affected tests passing; this continuation reviews and completes
the verification/documentation of that slice without reverting inherited work.

In `server_solver_state._clear_solver_challenge_state_locked`, deletion of a
matching legacy receipt now precedes deletion of the scoped receipt. Failure to
delete legacy state retains the authoritative scoped challenge; failure to delete
scoped state returns before switching the runtime recovery ID. A legacy receipt
belonging to another scope is retained. If only legacy deletion succeeds, startup
still restores the scoped latch via `_restore_solver_scope_states`; atomic rollback
of all files and stable legacy singleton selection across restart are not claimed.

`test_auth_completion_cleanup.py` contains eight fault-injection combinations
(seed/detail, finalizer/cooldown, legacy/scoped unlink failure), plus two cases
preserving another scope's compatibility receipt. The failure cases assert no
confirmation, retained manual pause and challenge ID, recovery after a fresh
RuntimeState, successful retry, and preservation of the other scope. Both official
fast and security manifests include the file. Independent read-only review raised
the missing legacy receipt after scoped unlink failure; direct inspection of
`initialize_runtime` and both restore functions confirmed scoped restore follows
legacy restore, and the fault-injection regression exercises that sequence.

Fresh checks on this worktree:

- Focused cleanup regression: 10 passed, pytest 1.77 seconds, runner 2.51 seconds.
- Official fast: 830 passed, 2 skipped, pytest 37.15 seconds, runner 38.20 seconds;
  exit 0 under the unchanged 60-second gate.
- Official security: 435 passed, 4 skipped, pytest 73.40 seconds, runner
  74.66 seconds; exit 0.
- Ruff lint for regression/manifest, source syntax/bug checks excluding existing
  facade F821, and Ruff formatting checks: passed. No full strict-type claim.
- Effective-line checker: 19 passed; ratchet: 1197 files with no above-500 tier.
  `git diff --check` passed.

Fast skipped two dedicated-PostgreSQL cases; security skipped two POSIX signaling
and two dedicated-PostgreSQL migration cases. Security stderr contained a request
handler exception header without a traceback; no test failed. The 191-test affected
run belongs to the prior session and is not counted as a new run. Test storage was
isolated with business DB access disabled. No deployment, restart, business-data
mutation, commit, or push occurred. R3 still includes scope-selection concurrency,
completion-confirmation publication, flag/multi-file failure semantics, and legacy
retirement; the nine-category plan remains incomplete.

### Preserve scoped cooldown challenges after confirmation failure (2026-09-25)

The next R3 slice reproduced a different failure: after cooldown cleanup had
deleted the challenge, an `os.replace` failure publishing the completion receipt
left a paused scope with no challenge ID. Both seed/detail fault-injection cases
failed before the patch. This could not be recovered by the existing startup
reader, which ignores inactive scoped receipts without a challenge ID.

The cooldown owner now captures the scoped state and recovery snapshot under its
existing runtime lock before cleanup. If confirmation publication returns an
error, it restores the original scoped generation and recovery challenge,
request, resume epoch and manual metadata. This preserves the original request's
retry identity. A failed scoped restoration is returned as `recovery_error` and
triggers a global manual-required flag as a restart-safe blocking fallback.
Failure to write that flag is also included in the recovery error; complete loss
of writable storage cannot be represented as successful durable recovery.

Four new regression combinations cover seed/detail and restoration success/failure.
Successful restoration retains manual-only state and the request across a fresh
RuntimeState, allows the original cooldown request to succeed on retry, and leaves
the other scope's receipt unchanged. Failed restoration reports the error and
keeps workers paused across restart through the manual-required flag. Independent
read-only review found no new false-success or direct cross-scope write regression.

Fresh verification after the production edit and official formatter:

- Focused cleanup/confirmation group: 14 passed, pytest 4.53 seconds, runner
  6.17 seconds. Regression lint and selected source syntax/bug rules passed.
- Affected auth/persistence/HTTP group: 195 passed, pytest 16.34 seconds, runner
  17.48 seconds.
- First fast attempt: 834 passed, 2 skipped, but runner 62.33 seconds exceeded
  the unchanged 60-second gate (exit 1). Static checks overlapped this attempt.
  Serial retry on unchanged source: 834 passed, 2 skipped, pytest 54.54 seconds,
  runner 56.02 seconds, exit 0. Timing variability remains; no threshold changed.
- Security: 439 passed, 4 skipped, pytest 92.34 seconds, runner 93.92 seconds,
  exit 0.
- Ruff format check and AST parsing passed. Effective-line checker: 19 passed;
  ratchet: 1197 files, no above-500 tier. `git diff --check` passed.

Fast skips are two dedicated-PostgreSQL cases; security skips are two POSIX
signaling and two dedicated-PostgreSQL migration cases. Tests used isolated state
and disabled business DB access. HEAD remains
`f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` with the inherited dirty worktree.
No deployment, restart, business-data mutation, commit or push occurred.

Scope limit: this fixes returned confirmation-publication errors for scoped
cooldowns, not process interruption between cleanup and commit, legacy-only
cooldowns, the cookie-finalizer compensation policy, or full R3 retirement.
Those boundaries and the wider nine-category inventory remain open.

### Preserve cookie-finalizer retry identity and share native rollback (2026-09-25)

The cookie finalizer previously compensated for confirmation publication failure
by calling `_begin_solver_challenge`, producing a new scoped ID. The retry worker
retains the original `expected_challenge_id`, so retrying that completion became
stale. Four new seed/detail fault-injection cases reproduced this: two observed
ID rotation, and two observed missing `recovery_error` when scoped compensation
could not be published.

Extracted the already-verified cooldown compensation into the typed native owner
`src/auth_cleanup_recovery.py`. It receives the current RuntimeState, captured
scoped/recovery state, and current persistence/manual-flag callbacks explicitly.
It captures no server globals and introduces no function-cloning source. The
existing 14 cases still passed after extraction, before changing the finalizer.
The finalizer now uses the same compensation only for confirmation errors with
an existing scoped challenge. Other cleanup failures and legacy fallback retain
their existing paths; finalizer lock order remains finalize_lock then runtime.lock.

The generalized fault test covers both entrypoints, both scopes, and successful
or failed scoped restoration. Successful restoration retains the original ID,
request and manual-only state across restart and permits same-request retry;
failed restoration reports `recovery_error` and attempts the global manual flag
to retain a restart-safe pause. Other-scope receipt bytes are preserved. A second
read-only review found no concrete new cross-scope, injection or lock-order defect.

Fresh evidence for the final native-module location and call sites:

- Affected auth/persistence/HTTP group: 199 passed, pytest 21.03 seconds, runner
  22.06 seconds; includes all 18 cleanup/confirmation regressions.
- Official fast: 838 passed, 2 skipped, pytest 55.00 seconds, runner 56.69 seconds,
  exit 0 under the unchanged 60-second gate.
- Official security: 443 passed, 4 skipped, pytest 92.90 seconds, runner
  94.33 seconds, exit 0. Broad checks ran serially without competing checks.
- New module/regression Ruff lint, strict mypy for the native module with imports
  skipped, selected legacy source syntax/bug rules excluding F821, official
  formatting and AST parsing passed. Full backend strict typing is not claimed.
- Effective-line checker: 19 passed; ratchet: 1198 files and no above-500 tier;
  `git diff --check` passed. No policy or baseline relaxation.

The initial attempt to place the helper in `server_solver_scope.py` encountered
that module's existing broader lint/type debt. The helper instead lives in its
own cohesive native module; the temporary edits to `server_solver_scope.py` were
removed without changing its behavior. The final new module passes its full lint
and selected strict-type gate.

Fast skipped two dedicated-PostgreSQL cases; security skipped two POSIX signaling
and two dedicated-PostgreSQL migration cases. Security emitted one HTTP handler
exception header without a traceback; no test failed. Tests used isolated storage
with business DB access disabled. Deployment, restart and business-data changes
remain deferred; no commit or push. Process interruption between cleanup and
confirmation, legacy-only compensation, finalizer scope-selection proof and wider
R3/R1 migration remain unfinished; scoped returned-I/O-error compensation is now
covered at both entrypoints.

### Recover scoped auth cleanup after process exit (2026-09-25)

Added native `auth_cleanup_journal.py`: publish a per-scope write-ahead intent
before destructive cleanup, publish the completion receipt, then delete the intent
as the commit step. Until commit, an existing receipt cannot confirm the pending
completion ID. Startup recovers intents before restoring latches or starting workers;
malformed intents or failed persistence prevent initialization and permit retry.
Finalizer, cooldown and direct operator completion use this protocol, including
the finalizer's anonymous completion path. Direct completion also shares native
returned-error compensation. Explicit reset/resume retires intents unless the
current cleanup context protects them; existing clear callback signatures remain.

Sixteen real subprocess exits cover both scopes, four entry modes and exits after
cleanup or receipt publication. Remaining cases cover prepare/finish failures,
corrupt intents, failed startup restoration, reset retirement, newer generations
and newer metadata. The same-ID metadata regression failed because startup replaced
the new node owner with the old journal snapshot. Recovery now preserves an existing
paused same-ID state. Intent remains pending until retry or explicit reset commits.
Automatic/manual flags on newer active state remain authoritative; recovery does
not force every live challenge into manual mode.

The first ratchet found `server_solver_state.py` at 505 effective lines. Extracted
scope-ID lookup into `solver_scope_runtime.py`, preserving the facade and injected
status callback. The final ratchet has no above-500 tier; no baseline was changed.

Evidence on HEAD `f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` plus inherited worktree:

- New metadata/startup-failure probe: 1 failed and 1 passed before the fix.
- Focused cleanup/startup: 51 passed, runner 34.95 seconds.
- Affected auth/persistence/startup/contracts: 236 passed, runner 77.62 seconds,
  before the scope lookup extraction. After extraction, focused scope/cleanup/
  startup: 71 passed, runner 29.94 seconds; subsequent cast is typing-only.
- Final official fast: 838 passed, 2 skipped, pytest 55.64 seconds, runner
  57.14 seconds, exit 0 under the unchanged 60-second threshold.
- Final official security: 472 passed, 4 skipped, pytest 117.17 seconds, runner
  118.39 seconds, exit 0. New crash cases are in security only. Broad runs serial.
- Journal/test/manifest Ruff lint and native journal strict mypy pass; formatting
  and selected source syntax/bug checks excluding legacy F821 pass. The existing
  scope runtime retains 5 Ruff findings and 5 skipped-import mypy errors outside
  the extracted function; full module/backend lint/type completion is not claimed.
- Effective-line self-tests: 19 passed; ratchet: 1200 files, no above-500 tier.
  Diff whitespace and UTF-8/BOM checks passed. Worktree has 220 dirty/untracked entries.

An independent review found no concrete pending-receipt/reset retirement defect;
its manual-flag concern did not establish a failing production path. All tests use
isolated storage with business DB disabled. Fast skips two PostgreSQL cases;
security skips two PostgreSQL and two POSIX cases. Security emitted an HTTP handler
exception header without a traceback. These are not fresh platform acceptance.

R3 remains open for legacy-only transactions, finalizer scope-selection concurrency
and broader multi-file durability/power-loss guarantees. R1 ownership migration and
the other inventory categories also remain. Deployment, application restarts and
business-data changes remain deferred; no commit or push was performed.

### Serialize finalizer scope selection with native scoped publication (2026-09-25)

The finalizer selected request scope and legacy fallback before acquiring its
existing finalize/runtime locks. A scoped state publication could finish after
the empty-scope status read but before finalization; singleton ID stayed at the
legacy value, so global cleanup then deleted the newly published scoped receipt.
Moved scope inference, ID lookup and fallback inside the existing
`finalize_lock -> RUNTIME.lock` section. Validation, cleanup and receipt publication
retain the same order; scheduling remains outside the runtime lock.

Added `test_auth_finalizer_scope_selection.py` to fast and security. Its real
competing thread calls `_persist_solver_scope_state` and compares exact persisted
bytes, ID, request owner and manual pause after finalization. Both scopes and
explicit/inferred scope are covered for publication before selection and during
selection. Before-selection cases reject stale completion. During-selection cases
now serialize publication after cleanup and retain the new receipt. This is proof
for the actual native scoped publication API; it does not assert that the combined
`_begin_solver_challenge` path, which also refreshes singleton ID, loses challenges.

Fresh evidence on the inherited worktree at HEAD
`f2d735ab20e60c1dce212dd86dd2b15fd22a8c40`:

- After correcting the test hook's `now` keyword signature, pre-fix regression:
  4 failed by deleted new receipt, 4 passed. Post-fix: 8 passed, pytest 1.58 seconds,
  runner 2.56 seconds.
- Affected authentication, persistence, startup and contracts: 244 passed, pytest
  56.69 seconds, runner 57.66 seconds.
- Official fast: 846 passed, 2 skipped, pytest 45.95 seconds, runner 47.19 seconds,
  exit 0 under the unchanged 60-second gate.
- Official security: 480 passed, 4 skipped, pytest 104.90 seconds, runner
  106.03 seconds, exit 0. Broad checks ran serially with no overlapping commands.
- New regression/manifest Ruff lint, selected legacy source syntax/bug checks
  excluding F821, formatting and 19 effective-line checker tests pass. Ratchet:
  1201 files, no above-500 tier, unchanged baseline. Diff/UTF-8 checks pass.

Independent review found no new lock-order issue in the changed path; the runtime
lock is reentrant and scheduling remains outside it. Tests use isolated storage
with business DB disabled. Two PostgreSQL fast cases and two PostgreSQL plus two
POSIX security cases remain skipped. Security emitted one HTTP handler exception
header without a traceback; no test failed. Existing full-module lint/type debt
is not resolved by this change.

The specific finalizer scope-selection race is covered. R3 still requires
legacy-only failure/recovery and a defined multi-file durability boundary; R1 and
the remaining inventory categories stay open. No deployment, application restart,
business-data change, commit or push occurred.


### Preserve legacy completion identity and reject ambiguous global cleanup (2026-09-25)

Legacy-only completion used global cleanup even when a distinct scoped challenge
remained active. All three entrypoints could confirm success after deleting those
scoped receipts. A second failure occurred after successful legacy cleanup when
completion publication returned an error: finalizer generated a replacement ID,
while cooldown/direct completion left the original ID absent. Initial tests, after
fixing a test callback keyword signature, reproduced all 15 cases.

`AuthCleanupIntent.prepare` now accepts an explicit scope reader. Each completion
entrypoint supplies it under the existing runtime lock. Unscoped completion is
refused if either scoped receipt or pending scoped intent owns a challenge, before
flags, state or intents are removed. Explicit operator global reset/resume remains
a separate path. Six extra tests cover pending intents with already-deleted scoped
receipts, verifying that legacy completion cannot retire their recovery evidence.

Extended the native `restore_auth_cleanup` owner with an injected legacy persister.
On completion-receipt errors with a retained legacy ID, it restores original ID,
request, resume epoch and manual metadata, republishes the legacy receipt and
restores its global manual flag. Legacy receipts do not encode manual-only state,
so that flag is needed even when legacy persistence succeeds. Restoration errors
are returned separately. If legacy receipt restoration fails, a surviving manual
flag still blocks restart; if only flag restoration fails, the restored receipt
retains the old ID and pause. Failure of every persistence path is not guaranteed.

The 21-case regression exercises finalizer, cooldown and direct completion; active
and pending seed/detail ownership; confirmation, legacy rollback and flag faults;
fresh RuntimeState restoration and same-ID retry. Scoped compensation and the
previous real-thread publication regression also passed. Review raised a proposed
missing flag-only case; the existing `restore_failure == "flag"` cases already
verify successful legacy publication plus failed flag write, restart and retry.

Fresh results on inherited HEAD `f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` worktree:

- Initial 15 regression cases failed before production changes. Final legacy
  regression: 21 passed, pytest 3.56 seconds, runner 5.06 seconds.
- Affected auth/persistence/startup/contracts: 265 passed, pytest 47.27 seconds,
  runner 47.97 seconds. A later test-only formatter adjustment changed no behavior.
- Final official fast: 867 passed, 2 skipped, pytest 40.47 seconds, runner
  41.66 seconds, exit 0 with the unchanged 60-second threshold.
- Final official security: 501 passed, 4 skipped, pytest 96.62 seconds, runner
  97.75 seconds, exit 0. Both broad suites ran serially with isolated storage and
  business DB disabled.
- Native journal/recovery full Ruff and strict mypy with skipped imports pass.
  New regression/manifest lint, selected legacy syntax/bug checks excluding F821,
  official formatting, 19 checker tests and ratchet for 1202 files pass. No
  above-500 tier, baseline relaxation or full-backend type claim. Diff/UTF-8 checks
  pass. Database/POSIX skips remain unverified; security emitted an HTTP handler
  exception header without traceback and no failed tests.

This closes returned completion-publication errors for a retained legacy ID and
protects scoped receipts/intents from ambiguous legacy completion. Legacy cleanup
still has no write-ahead intent: interruption before compensation and partial
cleanup failures remain R3 work, along with the wider durability contract. No
deployment, restart, business-data change, commit or push occurred.

### Recover legacy cleanup after process termination and repeated startup (2026-09-25)

Added legacy intents to the existing auth cleanup protocol. All three completion
entrypoints capture legacy ID, request, recovery epochs and manual mode, publish
`auth-cleanup-intent-legacy.json`, protect it during cleanup, then retire it only
after receipt publication. Completion replay checks include this intent. Startup
restores its state and manual flag before launching workers; corrupted intents or
failed receipt/flag restoration prevent initialization and retain retry evidence.
Anonymous finalizers use the same protocol without inventing a completion ID.

Scoped journals remain independent. New scoped or legacy challenge ownership
supersedes an older legacy intent at startup; matching legacy IDs retain newer
request metadata. Global reset retires all unprotected intents. A scoped clear
with an active challenge also retires a superseded legacy intent, preventing an
old singleton from returning after the newer scope was explicitly reset. A
scope-specific reset without active ownership does not discard unrelated legacy
recovery state.

Initial finalizer process-exit probes failed at all three boundaries: after manual
flag removal, challenge cleanup and completion receipt publication. The first
implementation then passed 296 affected cases. A later cold-start probe found
that legacy restoration did not load manual-only into the runtime snapshot, so
another cleanup could downgrade the durable manual-only flag. Seven additional
cases failed. The final capture reads the durable flag as well as the snapshot;
returned-error compensation uses that captured mode too. No legacy manual mode
is weakened merely because the process had already restarted.

`test_auth_legacy_crash_recovery.py` has 38 cases: 16 real child-process exits,
prepare/finish/partial-cleanup faults across three completion modes, corrupt and
failed startup restoration, metadata/generation/scoped supersession, explicit
resume and retirement failure, and three cold-start returned-error cases. It is
in security only. A scoped-startup assertion was corrected to exclude the normal
`updated_at_epoch` republication while comparing every other persisted field.

Distinct verification checkpoints at inherited HEAD
`f2d735ab20e60c1dce212dd86dd2b15fd22a8c40`:

- Before the cold-start follow-up: affected 296 passed, pytest 85.02 seconds,
  runner 86.19 seconds; fast 867 passed, 2 skipped, runner 51.80 seconds; security
  532 passed, 4 skipped, runner 132.72 seconds. These are superseded checkpoints
  for the subsequently edited production files, not final acceptance.
- Final focused legacy/scoped returned-error group: 77 passed, pytest
  28.65 seconds, runner 29.47 seconds.
- Final fast: 867 passed, 2 skipped, pytest 53.72 seconds, runner 55.36 seconds,
  exit 0 under the unchanged 60-second limit.
- Final security: 539 passed, 4 skipped, pytest 130.57 seconds, runner
  131.67 seconds, exit 0. Broad runs were serial without competing commands.
- Both native auth modules pass full Ruff and strict mypy with imports skipped.
  New regression/manifest lint, selected legacy syntax/bug checks excluding F821,
  official formatting and 19 effective-line checker tests pass. Ratchet: 1203
  files, no above-500 tier, unchanged baseline. Diff and UTF-8/BOM checks pass.

Independent review of the initial journal protocol found no concrete new
resurrection or lock-order issue; the later durable-flag bug was found and covered
by the main-thread follow-up. Tests used isolated storage and disabled business
DB access. Fast skips two PostgreSQL cases; security skips two PostgreSQL and two
POSIX cases. Final security emitted an HTTP handler exception header without a
traceback; no test failed. No full-backend typing or deployed-runtime claim.

The tested process-exit and legacy partial-cleanup boundaries are now covered.
Power-loss/directory-fsync behavior and byte-for-byte compatibility receipt timing
are not guaranteed by this protocol. R3 next checks mixed legacy/scoped manual-flag
ownership and retires legacy state only after callers and persisted-state migration
are covered. R1 and other inventory categories remain. No deployment, restart,
business-data change, commit or push occurred.

### Preserve independent legacy pause during scoped manual completion (2026-09-25)

Extracted manual cleanup to src/solver_pause_cleanup.py with injected runtime and
current facade callbacks. Under the runtime lock it compares the target challenge
ID with durable/runtime global owners and the global flag scope. Different owners
retain their flag, recovery/manual state and aggregate pause while the requested
scope is cleared. The legacy facade keeps its public signature and override
compatibility. Challenge clearing now compares exact IDs rather than inferred
request scope, preventing removal of an independent same-scope legacy identity.

Twelve initial cases failed because scoped completion removed the legacy flag.
The final test_auth_mixed_pause_ownership.py has 24 cases across seed/detail,
finalizer/cooldown/direct and unscoped/same-scope legacy requests, including
confirmation-publication failures. Success checks byte-identical legacy receipt
and flag, original recovery identity/manual epochs, cleared scoped pause, legacy
restart persistence and explicit global reset. Failure checks target rollback
without losing the independent legacy state.

Verification on inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus the
dirty worktree:

- Affected auth/scope/process-exit group: 150 passed, pytest 65.97 s, runner
  67.61 s. This precedes only a local exception-variable rename, explicit
  compatibility lint annotations and official manifest formatting.
- Final fast: 867 passed, 2 skipped, pytest 49.33 s, runner 50.73 s, exit 0.
- Final security: 563 passed, 4 skipped, pytest 130.37 s, runner 131.41 s, exit 0.
  New regression is security-only. Broad runs were serial, isolated, and disabled
  business DB access. The fast limit remains 60 seconds.
- Native owner/regression/manifest Ruff, strict owner mypy with imports skipped,
  selected facade syntax/bug checks excluding inherited F821 and formatting pass.
  Checker self-tests: 19 passed. Ratchet: 1205 files, no above-500 tier or baseline
  change. Final diff and UTF-8/BOM checks pass.

Independent review identified the adjacent automated-success helper's unconditional
singleton cleanup. It is outside the three manual-completion entrypoints covered
here and remains the next R3 slice, with reproduction still needed. Mixed-state
process-exit recovery also remains unverified; existing scoped/legacy crash tests
passed but do not imply that combined-state case. PostgreSQL/POSIX skips and full
backend typing remain open. R1-R9 and deployment are not complete. No deployment,
restart, business-data change, commit or push occurred.

### Preserve independent legacy pause after automated solver success (2026-09-25)

Four new scoped automatic-success regressions failed because the old helper
removed the independent legacy force_unlock.flag. Moved this helper into the
existing native solver_pause_cleanup owner and shared its ownership predicate
with manual completion. The facade retains its public signature and current
runtime/callback bindings. Ownership capture and cleanup are under the runtime
RLock. A different global owner receives no solved outcome, resume/manual reset
or authentication grace metadata from this scope's completion.

The protected branch reuses scoped manual cleanup; scoped flag/receipt deletion
failures leave the target retryable without changing legacy bytes or singleton
snapshots. Ordinary automated success keeps its existing challenge-error handling,
best-effort flag removal, inferred scope and operator-pause behavior. The new
regression adds 18 cases (12 independent-owner/fault/retry cases and 6 ordinary
ownership/operator cases); the full mixed-state file now has 42 cases.

Verification at inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus the
dirty worktree:

- Affected auth/scope/solver-run group: 91 passed, pytest 12.29 s, runner 13.62 s.
- Final-source fast initially passed 867 tests, 2 skipped, but FAILED the timing
  gate: pytest 69.53 s, runner 71.59 s. No source or test removal followed.
- Separate unchanged fast rerun: 867 passed, 2 skipped, pytest 52.62 s, runner
  54.27 s, exit 0. The 60-second threshold remains unchanged. Timing variation
  remains unexplained; the passing rerun does not erase the earlier failed gate.
- Security: 581 passed, 4 skipped, pytest 141.45 s, runner 142.80 s, exit 0.
  Broad runs were serial, isolated and disabled business DB access.
- Native owner/regression Ruff, strict native mypy with imports skipped, selected
  facade syntax/bug checks excluding F821 and official formatting pass. Checker:
  19 passed; ratchet: 1205 files, no above-500 tier or baseline change.
- Independent review found no new ownership or lock regression in the changed
  helper/wrapper/tests. Final diff and UTF-8/BOM checks pass.

Mixed-state process termination/startup recovery is the next R3 boundary. Existing
individual scoped/legacy process-exit tests passing does not establish it.
PostgreSQL/POSIX skips, full backend typing, power-loss durability and deployment
remain unverified. No deployment, restart, business-data change, commit or push.

### Restore both owners after mixed-state process termination (2026-09-25)

The first real child-process probe failed after removing the scoped flag: startup
preserved the legacy ID/request and durable flag, but recovery.manual_only was
False and required_epoch was absent. The existing journal correctly restored the
scoped owner; legacy runtime hydration was the missing boundary.

Added restore_legacy_manual_pause to the native auth_cleanup_recovery owner and
called it after restoring the legacy receipt, before workers start. It restores
manual mode/required epoch only from a valid JSON flag with matching request and
an active legacy challenge. It records the manual-required outcome and pause
reason, without republishing the legacy receipt or flag. Opaque, invalid and
different-request flags retain existing existence-based pause semantics without
assigning their metadata to this owner.

The new security-only test_auth_mixed_crash_recovery.py contains 23 cases. Eighteen
actual child exits cover finalizer/cooldown/direct, seed with unscoped legacy and
detail with same-scope legacy, after scoped flag removal, cleanup and confirmation
publication. Each performs two startups, checks both challenge owners and exact
legacy bytes, retries the original completion, then verifies deliberate global
reset. Five further startup cases cover matching manual-only/retryable metadata,
a different request owner, opaque flags and invalid timestamps.

Final-source verification on inherited HEAD
f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty worktree:

- Affected auth/crash/startup/import group: 235 passed, pytest 89.48 s,
  runner 90.44 s.
- Fast: 867 passed, 2 skipped, pytest 45.56 s, runner 46.88 s, exit 0.
- Security: 604 passed, 4 skipped, pytest 144.84 s, runner 145.95 s, exit 0.
  Broad runs serial, isolated storage, business DB disabled; fast remains 60 s.
- Native recovery/regression/manifest Ruff, strict native mypy with imports skipped,
  selected facade syntax/bug checks excluding F821 and formatting pass.
  Checker: 19 passed; ratchet: 1206 files, no above-500 tier or baseline change.
  Final diff and UTF-8/BOM checks pass.
- Independent review found no confirmed new ownership/recovery defect. Startup
  uses fake worker launches, so real worker scheduling races are not claimed.

R1/R3 next migrate legacy/scoped startup restore orchestration from the cloned
facade into explicit native ownership, preserving these acceptance boundaries.
Legacy schema/caller retirement, old flag challenge-ID binding, cross-process and
power-loss durability, PostgreSQL/POSIX skips and deployment remain open. No
deployment, restart, business-data change, commit or push occurred.

### Native startup recovery ownership (2026-09-25)

Moved legacy/scoped restore orchestration to solver_startup_recovery.py, with
explicit runtime, reader, flag-path and pause dependencies. Existing facade names
remain thin wrappers resolving the current runtime/callbacks at invocation. The
startup caller still invokes legacy then scoped restoration after pending intents.
No server bootstrap registration, cloning source or configuration dependency was
added. Legacy precedence, request handling, pause reasons and return values remain
unchanged. Removed now-unused os/Path imports from the facade.

Added direct native import isolation and two-runtime ownership tests to the
security manifest. Existing runtime tests cover facade replacement and concurrent
one-time initialization. Existing mixed/scoped/legacy crash tests supply behavioral
proof rather than copied implementation-level assertions.

Verification at inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty
worktree, with unchanged runner limits and isolated storage/business DB disabled:

- Combined affected attempts did not finish: the tool timed out at 180 s, then
  the original recovery group hit the runner's 180 s execution gate without
  reported assertion failures. No residual matching test processes were found
  after the tool timeout. Host CPU sampled at 100%; timing cause is not proven.
- Split mixed-state/legacy-completion group: 86 passed, pytest 73.05 s, runner
  74.19 s. Separate scoped/legacy crash/import group: 149 passed, pytest 127.20 s,
  runner 128.39 s. These are separate runs and preceded unused-import removal.
- Final-source native-owner/runtime group: 15 passed, pytest 3.16 s, runner 4.70 s.
- Native owner/regression/manifest Ruff and strict owner mypy with imports skipped
  pass. Formatting, selected facade syntax/import checks excluding F821,
  19 checker tests, ratchet for 1208 files and final diff/UTF-8 checks pass.
  No above-500 tier or baseline change.

Full fast/security were not repeated for this structural slice. Previous broad
numbers are historical, not acceptance for the extracted source. Next migrate
challenge receipt publication/clearing ownership, preserving reset retirement
and exact-ID ownership. R1/R3, remaining plan categories and runtime/deployment
acceptance are not complete. No deployment, restart, business-data change or commit.

### Native challenge receipt ownership (2026-09-25)

Moved legacy receipt publication, protected-intent retirement coordination and
locked challenge clearing to solver_challenge_receipts.py. The facade preserves
the existing names and resolves current runtime/readers/paths/clock at invocation.
The locked-clear override remains reachable from the public clear wrapper.
Publication still uses archive_json_io and retains original creation time on
same-ID refresh. Retirement precedes clearing under runtime.lock; matching legacy
mirror deletion precedes scoped deletion. Errors retain their prior string
contracts, partial failures keep affected latches, and recovery reassignment uses
exact challenge ID ownership rather than inferred request scope.

Extended the existing durability fixture with a directly imported native legacy
writer, exercising fsync/replace faults and retained pending snapshots. Extended
native import isolation to prove receipt-owner import does not bootstrap server
or server_context. No new cloning registration or runtime configuration was added.

Verification on inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty
worktree, with unchanged execution limits and isolated non-business storage:

- Focused durability/import/auth cleanup/mixed ownership/scope group: 104 passed,
  pytest 27.28 s, runner 28.75 s.
- Separate scoped/mixed process-exit group: 52 passed, pytest 115.62 s,
  runner 117.03 s.
- Separate legacy process-exit/returned-error group: 59 passed, pytest 54.33 s,
  runner 55.95 s. All groups ran serially; these are not one full-suite result.
- Native owner and test Ruff, strict native mypy with imports skipped, formatter,
  selected facade syntax/import checks excluding F821 and 19 checker tests pass.
  Ratchet: 1209 files, no above-500 tier or baseline change. Diff/UTF-8 checks pass.
- Independent review found no confirmed ordering/injection/locking regression.

Full fast/security were not rerun for this structural slice; previous broad
results remain historical. Next migrate challenge creation/reuse orchestration
with request policy, ownership, generation and publication behavior preserved.
R1/R3 and the remaining plan are not complete. No deployment, restart,
business-data change, commit or push occurred.

### Native challenge creation and reuse ownership (2026-09-25)

Moved creation/reuse orchestration to solver_challenge_creation.ChallengeCreation.
Runtime, request builder/scope/owner keys, receipt readers/writers, pause policy,
clock/ID generator and logger are explicitly supplied. The facade retains the
public runtime-lock boundary and resolves dependencies at invocation; no cloning
registration or configuration was added.

Explicit dict requests alone select independent scoped ownership. Scoped creation
retains cached/persisted ID and first-seen time, publishes scope then legacy mirror,
sets pause and updates recovery in the original order. Legacy calls retain
paused-owner reuse and complete-request persisted reuse before generating an ID.
Existing persistence failures are logged and continue as before; no new failure
policy or request-source semantics was introduced in this extraction.

Final-source verification on inherited HEAD
f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty worktree:

- Request/durability/native import/concurrency/API/scope group: 163 passed,
  pytest 30.93 s, runner 34.88 s.
- Separate legacy/mixed crash recovery group: 61 passed, pytest 95.52 s,
  runner 96.86 s. Groups ran serially with isolated storage and business DB
  disabled; execution limits remain unchanged. Not a combined broad-suite pass.
- Native module/regression Ruff, strict native mypy with imports skipped,
  formatter and selected facade syntax/import checks excluding F821 pass.
  Checker self-tests: 19 passed. Ratchet: 1210 files, no above-500 tier or baseline
  change. Final diff and UTF-8/BOM checks pass.
- Independent review found no introduced ordering, reuse, locking or return-value
  regression. Native creation import is included in the no-server-bootstrap test.

Full fast/security were not repeated for this structural slice. Prior broad
results are historical and do not establish current release/runtime acceptance.
Next migrate manual-required state transition/flag publication ownership, retaining
cancellation and compatibility ordering. The remaining plan is not complete.
No deployment, restart, business-data change, commit or push occurred.

### Native manual-required transition and flag publication (2026-09-25)

Extracted _mark_solver_manual_required and _write_solver_manual_required_flag
into solver_manual_pause with explicit runtime/callback dependencies. Public
facade signatures and callback substitution remain. The transition still marks
manual state, cancels a running solver, persists scoped state, pauses collection,
writes the scoped flag, then attempts the legacy mirror. Scoped failure takes
precedence when both writes fail. Direct flag write behavior and the existing
scoped-persist error handling policy were retained, not redesigned.

Added six real builtins.open fault cases for scoped/legacy/both flags across
seed/detail. They verify cancellation, two write attempts, first-error reporting,
manual-only pause preservation, successful counterpart contents and retry.
Extended native import isolation and registered the new fault tests in security.

Verification on inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty
worktree:

- API/manual/mixed ownership/returned-error group: 162 passed, pytest 28.12 s,
  runner 32.06 s. This precedes only addition of the native import parameter and
  security-manifest entry.
- Final import/legacy/mixed crash group: 66 passed, pytest 87.98 s, runner 88.88 s.
  Groups ran serially, isolated, with business DB disabled and limits unchanged.
- Native module/tests/manifest Ruff and strict native mypy with imports skipped
  pass. Full formatting passes for the owner, state facade and tests; the dispatch
  facade uses an official formatter range check for the edited function only.
- Selected facade syntax/bug checks excluding F821, 19 checker self-tests,
  ratchet for 1212 files and final diff/UTF-8 checks pass. No above-500 tier or
  baseline change.

Subagent exploration failed due to service authentication; the main thread read
the required contracts and reviewed the resulting extraction. No independent
review pass is claimed. Full fast/security were not repeated; earlier broad
numbers are historical. Next migrate flag reading/manual retry eligibility while
preserving opaque legacy flags and scoped precedence. Atomic flag publication,
remaining R1-R9 work and deployed-runtime acceptance remain open. No deployment,
restart, business-data change, commit or push occurred.

### Native flag reading and manual-retry eligibility (2026-09-25)

Extracted scope/manual-only/request flag readers and retry eligibility into
solver_manual_retry. Native functions receive runtime, path/normalization, scope
status and configuration callbacks; facade names still resolve current bindings.
Readers do not cache flag contents, preserve opaque/malformed/non-object/missing
fallbacks and string boolean compatibility, and skip normalization for invalid
payloads as before. Scope/manual-only, other-scope flag, active challenge and
global fallback precedence remain unchanged, including the existing early return
for another scope's flag.

Added 20 parameterized native/facade behavior cases: changing flag content followed
by opaque/non-object/missing content, plus nine retry precedence scenarios for
both entry styles. Added no-server-bootstrap import proof and security registration.
No retry policy, file publication or configuration semantics was redesigned.

Final-source focused validation at inherited HEAD
f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty worktree:

- API/stage/scoped/mixed ownership/native contract group: 191 passed, pytest
  21.35 s, runner 23.50 s, isolated storage with business DB disabled. An earlier
  191-pass result preceded a fallback-equivalence adjustment and is superseded.
- Native module/tests/manifest Ruff and strict native mypy (imports skipped)
  pass. Full owner/test formatting and edited dispatch-function range checks pass;
  inherited whole-dispatch formatting closure is not claimed.
- Selected facade syntax/bug checks excluding F821 and 19 checker self-tests pass.
  The static batch tool timed out before a ratchet result; a standalone ratchet
  completed successfully: 1214 files, no above-500 tier or baseline change.
  Final diff and UTF-8 checks pass. Tests preceded only one formatter-added blank line.

Full fast/security and actual retry-worker scheduling were not rerun for this
structural slice; older broad results remain historical. Next migrate retry request
construction and next-retry timing while preserving routing and runtime semantics.
Remaining R1-R9 and deployment acceptance are open. No deployment, restart,
business-data change, commit or push occurred.

### Solver dispatch exits function cloning (2026-09-25)

Converted all 28 server_solver_dispatch entrypoints into SolverDispatch bound
methods and removed the module from _CORE_MODULES / _IMPLEMENTATION_MODULES.
solver_dispatch_binding composes explicit callbacks against the live facade, so
retained exported methods still see replaced runtime, clock, executor and policy
providers. Publication keeps the identical method object in server and _CONTEXT.
Retry routing/fallback/next-epoch rules, CDP readiness cancellation and consecutive
probe requirements, reservation deduplication and submit-failure release remain
covered by the existing entrypoint tests. New retained-entrypoint tests exercise
two runtimes, executor failure/recovery, activation and replaced retry policies.
Both native modules have subprocess import-isolation proof.

The pre-change binding/API baseline passed 93 tests. An intermediate regression
changed the maximum-runtime environment key; the existing timeout test caught it
and it was corrected. The initial inline composition also exceeded server.py's
500-effective-line tier (535); moving only the typed binding composition into its
own module restored the ratchet without baseline changes or exceptions.

Final-source validation at inherited HEAD
f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty worktree:

- Focused native binding, API status, flag eligibility, startup, concurrency,
  logging and route-contract group: 147 passed, pytest 13.73 s, runner 15.16 s.
- Final fast milestone: 871 passed, 2 skipped, pytest 51.96 s, runner 53.30 s,
  exit 0 under the unchanged 60-second gate. An earlier pre-binding-extraction
  attempt passed the same 871 tests but failed timing at 74.78 s. The runs are
  separate evidence; the timing difference is not established as a code speedup.
- Both native modules pass strict mypy with follow-imports=silent. Native/test
  Ruff, formatting, selected facade syntax/bug checks excluding legacy F821,
  19 effective-line checker tests and the ratchet pass: 1215 files, no above-500
  tier, no baseline or policy changes. Final diff and UTF-8/no-BOM checks pass.
- A read-only independent review found no demonstrated dispatch regression;
  existing CDP tests supply live URL opener/event/clock replacement coverage.

Tests used the official isolated runner with business DB disabled. Full security,
PostgreSQL, desktop/package and installed runtime acceptance were not rerun.
Seven core and five handler cloning sources remain, plus PC2 cloning and the AVM
patch facade. Next remove solver-state facade cloning using its existing native
owners. R1-R9 remain incomplete. No deployment, restart, business-data change,
commit or push occurred.

### Solver state exits function cloning (2026-09-25)

Converted the 23 solver-state exports into native SolverState bound methods and
removed server_solver_state from the active cloning list. solver_state_binding
composes live runtime, clock, receipt, pause and policy callbacks. Existing native
creation, persistence, startup and cleanup owners retain their lock/publication
ordering and failure contracts. Source-target classification is injected into the
state owner at composition; selecting the general multi-source policy is still R2
work. Publication occurs before dispatch/status composition and handler loading.

Added ownership/identity assertions for every state export, retained-entrypoint
tests across two replacement runtimes, actual cancellation and terminal timestamps,
and cleanup compatibility proof: legacy no-keyword callbacks still work, while an
internal TypeError propagates without duplicate cleanup. Both state modules import
without server/context bootstrap. Strict types replace the old undefined Any
annotations, with numeric casts preserving existing runtime conversion behavior.

Validation on inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus the
dirty worktree, using isolated runner storage and no business DB:

- Entrypoint/API/scoped runtime/startup/lifecycle/manual-pause/durability group:
  171 passed, pytest 23.05 s, runner 25.94 s.
- Scoped process-exit recovery: 29 passed, pytest 52.78 s, runner 57.30 s.
- Legacy process-exit recovery: 38 passed, pytest 47.52 s, runner 50.11 s.
- Mixed-owner process-exit recovery: 23 passed, pytest 54.76 s, runner 58.22 s.
- Concurrent retries/challenge creation/completion receipts: 4 passed, pytest
  2.28 s, runner 3.95 s.
- The initial combined crash group exceeded the outer 155-second observation
  limit and returned no completed result. Process inspection confirmed no matching
  runner remained before the separate groups above. The incomplete run is not
  counted as passed, and the split groups are not a full-suite acceptance claim.
- Native owners/bindings/tests pass Ruff and formatting; both new native state
  modules pass strict mypy with follow-imports=silent. Selected facade syntax/bug
  checks excluding legacy F821, 19 checker self-tests and ratchet pass: 1216 files,
  no above-500 tier, baseline unchanged. Diff/UTF-8/no-BOM checks pass.

No full fast/security, PostgreSQL, desktop/package or installed-runtime run was
repeated. The previous 53.30-second fast result belongs to the dispatch checkpoint,
before this state migration. The 60-second threshold remains unchanged. Six core
and five handler cloning sources remain; next migrate server_auth_recovery's
request/status/completion-policy entrypoints. R1-R9, legacy schema/caller retirement,
power-loss guarantees and deployment acceptance remain open. No deployment,
restart, business-data change, commit or push occurred.

### Fast runner single-pass collection and budget recovery (2026-09-26)

- Investigated the preceding 67.91 s and 122.88 s fast failures without changing
  product code or weakening tests. Auth/receipt fault tests contain meaningful
  durability/retry work; no waits or safely removable repetition were found.
  Collection-only import probes took 9.72 / 11.56 s (diagnostic runs, not test passes)
  and did not reproduce the 52.80 s collection spike. Import-time evidence did not
  justify blaming a particular heavy product import or environmental contention.
- cProfile localized a repeatable mechanism in the installed pytest: per-file CLI
  arguments repeatedly collect the shared directory. The baseline collect-only
  sample had 14524 directory collect calls, 54456 ignore checks and 34812 stat calls,
  with 24.45 million calls and 18.01 s under profiling. This diagnoses redundant
  collection; it does not explain every historical timing fluctuation.
- Runner now supplies one tools/test directory and an explicit selection plugin.
  The plugin rejects unselected files/directories before their collectors are made,
  then selects requested files/functions/classes/parameters, preserves manifest
  execution order, deduplicates overlapping selectors and errors on missing nodes.
  python_files is limited to manifest filenames, retaining nonstandard filenames
  without enabling assertion rewriting for every imported Python module.
- Existing runner subprocess tests now require one directory collection, preserve
  root conftest isolation fixtures, reject unselected sibling collectors and tests
  in the selected module, and still prove pass/fail/process-exit and timing-report
  behavior. Added 7 selection cases; focused runner/selection: 13 passed, 5.17 s.
  Before/candidate collect-only node sets: 1384 / 1391, zero removed and exactly
  those 7 added. Full final fast: 1389 passed, 2 skipped, pytest 39.38 s, runner
  40.77 s; timing plugin reports collection 3.99 s and test loop 35.31 s.
  The unchanged 60 s budget passes at this worktree checkpoint.
- Strict mypy on the plugin passes with pytest available in the tool environment;
  Ruff/format: 4 files; syntax: 5 files; checker: 19 passed; ratchet: 1328 files,
  none above 500 effective lines. Diff/UTF-8/no-BOM checks pass. Independent review
  found no confirmed defect; arbitrary absolute/traversal/symlink selector semantics
  are outside current internal relative-path manifests and were not introduced as
  a supported public API. Other external pytest plugin combinations were not tested.
- Evidence: artifacts/fast-collection{,-candidate}.prof, fast-collection-cprofile.log,
  fast-collection-candidate.log, fast-collection-{import,uncaptured}-profile.log,
  quality-selection-{focused,fast,ruff,format,mypy,checker,ratchet}.log and
  quality-selection-fast-timing.json. Profiling and collect-only runs are diagnostic;
  only the final full fast run establishes the gate pass. No redundant full rerun
  followed that pass.
- R7 retains test organization and broader typing work; R1-R9 are not complete.
  No business-data access, security/PostgreSQL/desktop release acceptance, deployment,
  restart, commit or push occurred. Temporary storage and business DB disablement
  remain enforced by the runner.

### Server function-cloning machinery retired (2026-09-26)

- Removed ModuleExports.rebind, the FunctionType import, the no-op rebind call and
  dead handler loading loop. Removed _CORE_MODULES, _HANDLER_MODULES and
  _IMPLEMENTATION_MODULES instead of retaining empty compatibility inventories.
  The native publication sequence and runtime owner injection remain unchanged.
- Converted the obsolete clone-specific fixture into two native-publication cases
  proving object/alias identity, original globals, defaults, closure, annotations,
  metadata, context identity and repeated-publication stability. Existing runtime
  replacement and ownership tests remain; their old negative membership checks
  now assert removal of the retired registries. The facade-global test retains
  its exact predicate under a name describing actual facade-defined functions.
- Same focused boundary before: 127 passed, runner 6.49 s; after: 127 passed,
  runner 6.98 s. Strict mypy: 1 file; Ruff/format: 12 files; syntax: 4 files;
  checker: 19 passed; ratchet: 1326 files, no above-500 tier. Source search confirms
  no FunctionType, rebind calls or retired registries in src. UTF-8/no-BOM and
  git diff --check pass. PC2's separate clone implementation was not changed.
- Ran fast once at the native-server milestone: 1382 passed, 2 skipped, pytest
  65.83 s, runner 67.91 s. It FAILED the unchanged 60 s elapsed-time gate.
  To diagnose that unresolved failure, reran the identical worktree using the
  existing optional timing plugin: same 1382 passed / 2 skipped, pytest 120.59 s,
  runner 122.88 s, also FAILED the gate. The diagnostic report records collection
  52.80 s, test loop 67.60 s, setup 15.58 s, call 47.99 s and teardown 1.99 s.
  Native-import phases account for 11.16 s; the next largest files are auth cleanup
  4.98 s and quality-runner checks 4.51 s. Timing variation alone does not prove CPU,
  filesystem contention or plugin overhead. No speculative optimization was applied.
- Each run used temporary isolated storage and disabled business DB access. No
  security/PostgreSQL/desktop/package/live acceptance, deployment, restart or
  business-data modification was performed. R1-R9 remain incomplete; the next R7
  investigation should distinguish collection/import cost from execution cost.
  Evidence: artifacts/rebind-retirement-{before,focused,ruff,format,mypy,checker,
  ratchet,fast,fast-profile}.log and rebind-retirement-fast-timing.json.

### Native catalog/seed admission and server handler cloning exit (2026-09-26)

- Moved location catalog writes into LocationCatalogHandlers and seed batch admission
  into existing SeedTaskHandlers. Catalog still uses current DATA_DIR/RUNTIME lock,
  archive helpers, original code conversion and insert-only name merge. Seed keeps
  body-before-guard, async-only control-plane guard, mode lowercasing without trim,
  shallow payload copy minus mode and current submission callback at job execution.
- server_handler_analysis is now native composition, published through _NATIVE_MODULES.
  _CORE_MODULES, _HANDLER_MODULES and _IMPLEMENTATION_MODULES are empty. Existing
  direct-module archive corruption/concurrency tests still pass without changing
  their patch targets. Obsolete rebind machinery and other R1 facades remain.
- Added 14 seed/catalog cases, fast registration and five isolated native import
  probes, including the recent pipeline/evaluation/manual-review owners. Baseline:
  52 passed plus 2 subtests, runner 5.61 s. Focused: 66 passed plus 2 subtests,
  runner 7.31 s. After flattening the equivalent catalog condition for Ruff,
  affected native/HTTP/job/access/import/lifecycle tests: 317 passed, runner 23.28 s.
- Import-test expansion initially failed the ratchet at 502 effective lines.
  Extracted only its module inventory to server_native_import_cases.py, preserving
  every case and subprocess assertion; no baseline/threshold change. Final changed
  import suite: 131 passed, runner 11.14 s. Final ratchet: 1326 files, none above 500.
  Strict mypy: 2 native files; Ruff/format: 6 production/test files plus 2 import
  fixture files; syntax: 7 files; checker: 19 passed. Independent tail review was
  interrupted at its 10-minute limit without a result; main review and executable
  checks are the evidence for this tail slice.
- All runs used temporary isolated storage with business DB disabled. Earlier manual
  review and tail runs refer to their respective worktree checkpoints, not one full
  suite. Evidence: artifacts/analysis-exit-{before,focused,affected,ruff,format,mypy,
  checker,ratchet,import-ruff,import-format,import-final}.log.
- R1-R9 and historical full-fast 99.14 s / 60 s failure remain open. Deployment,
  restarts and business-data changes remain deferred; no commit/push occurred.

### Native manual-review receipt write ownership (2026-09-26)

- Moved receipt POST/preparation to ReviewWriteHandlers and explicit write contracts.
  Preparation retains read-only created/updated preview with failure degradation,
  deep-copied payload, trimmed notes/source, captured repository/path/callbacks and
  summary readers. Worker checkpoints still precede upsert, maintenance and finalize.
  Stage-specific errors, saved partial receipts and explicit async HTTP 200 remain.
- Added 10 cases proving no preparation writes, dependency snapshots, deep-copy
  isolation, preview degradation, exact stage ordering/failure codes and native
  descriptors/context publication. Existing actual HTTP queue-before-write,
  admission-fault, partial receipt, async response and selected DB-backed status
  regression remain. Independent read-only review found no behavior drift.
- Baseline: 73 passed plus 22 subtests, runner 11.58 s. Focused: 83 passed plus
  22 subtests, runner 8.89 s. Affected persistence/read/write/access/job/import/
  lifecycle: 214 passed, runner 14.78 s. Strict mypy: 2 files; Ruff/format: 4 files;
  syntax: 5 files; checker: 19 passed; ratchet at this checkpoint: 1322 files,
  none above 500. Temporary isolated runtime storage, business database disabled.
- Evidence: artifacts/review-write-native-{before,focused,affected,ruff,format,mypy,
  checker,ratchet}.log. This slice left catalog/seed bodies; the following code
  checkpoint (recorded above) removes the final server handler cloning source.

### Native evaluation and location inference admission (2026-09-26)

- Moved _read_execution_mode, _post_analysis_evaluate and _post_infer_location into
  EvaluationHandlers. Default/normalized execution modes, validation/error envelopes,
  request/item metadata and synchronous compatibility responses remain unchanged.
  Evaluation captures its service object and shallow payload at admission; inference
  captures its service and both LLM callbacks. Evaluation queue/response exceptions
  still propagate while inference maps them through its existing HTTP catch boundary.
- Added 15 cases covering invalid/default/normalized modes, rejected body ordering,
  service/callback replacement after admission, shallow-copy behavior, explicit null
  metadata, queue/response exception boundaries and native descriptors/context.
  The file joins fast. Existing HTTP jobs prove actual async receipts and failures;
  screen jobs exercise the shared mode reader through the native facade.
- Before: 48 passed plus 4 subtests, runner 9.56 s. Same focused groups plus new tests:
  63 passed plus 4 subtests, runner 8.30 s. Affected evaluation/inference/screen jobs,
  imports/exports/lifecycle and durable-job boundaries: 201 passed, runner 18.80 s.
  All runs used temporary isolated storage with business database disabled.
- Strict mypy: 1 native file; Ruff/format: 3 files; syntax: 4 files. Checker: 19 passed;
  ratchet: 1319 files, none above 500 effective lines. Independent review found no
  behavior drift. UTF-8/no-BOM and git diff --check pass. Evidence:
  artifacts/evaluation-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- The only remaining server cloning module still owns manual-review writes, location
  saving and seed submission. R1-R9, R4 client migration and the earlier full-fast
  99.14 s / 60 s budget failure remain open. Analysis/prediction remain migration
  inputs. No full-suite/release acceptance, deployment, restart, business-data change,
  commit or push is claimed.

### Native pipeline and maintenance admission (2026-09-26)

- Moved pipeline root resolution, pipeline run, three maintenance delegators and
  both all-subtasks entrypoints to PipelineSubmissionHandlers. Preserved guard/body
  ordering, resolved-root containment, numeric conversion/error order, config
  defaults, existing job submission methods and route-specific error codes.
  Native closures resolve current facade dependencies; direct-module aliases remain.
- Added 12 focused cases for rejected guard/body, root changes and sibling/traversal
  rejection, invalid fields, current resolver/factory replacement, exact maintenance
  delegation, descriptors and context publication. Added the file to fast.
- Baseline: source contracts 18 passed, runner 3.99 s; selected pipeline/maintenance
  HTTP contracts 35 passed, runner 5.72 s. After migration: same groups plus native
  tests 65 passed, runner 6.25 s. Affected import/export/lifecycle/durable-job/source
  boundaries: 201 passed, runner 16.78 s. Each run used temporary isolated storage
  with business database disabled. These separate runs are not full-suite acceptance.
- Strict mypy: 1 native file; Ruff/format: 3 files; syntax: 4 files. Corrected only
  test import formatting after the behavioral runs. Checker: 19 passed; ratchet:
  1317 files, none above 500 effective lines. Independent read-only review found
  no behavior drift. Git diff/UTF-8/no-BOM checks pass; 354 dirty entries at unchanged
  HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
  Evidence: artifacts/pipeline-native-{before,http-before,focused,affected,ruff,
  format,mypy,checker,ratchet}.log.
- One server cloning module remains. R1-R9 and the historical full-fast 99.14 s /
  60 s budget failure remain open. No deployment, restart, business-data mutation,
  commit or push occurred.

### Native area result and approval writes (2026-09-26)

- Moved _post_area_result and _post_approve_area into existing DetailIngestHandlers.
  Both parse/accept the body before acquiring the runtime index inside the HTTP
  exception boundary. IDs retain str(data.get('id')) without new trimming or empty-ID
  validation. Both mark processed; approval additionally forces done. Successful
  service results return intact and all non-ok statuses retain the compatibility 404.
  Route-specific exception codes/logging and worker/operator access remain unchanged.
- Reused the existing host's working-item/archive/database/queue operations; no
  persistence or locking policy changes. Analysis aliases the native closures and
  late owner publication preserves normal descriptors and server/context identity.
  The R2 service callback bundle remains unchanged and is not claimed consolidated.
- Added 14 cases covering missing/empty/padded IDs, exact patch/processed flags,
  approval's forced status, returned extra fields, rejected-body no-index access,
  caught index failures, non-ok 404 compatibility and native descriptors. Tests join
  fast. Existing real HTTP tests cover aliases, success, absence and service faults.
- Baseline with runtime-state and selected area HTTP tests: 33 passed, runner 3.33 s.
  Focused with source contracts: 53 passed, runner 4.75 s. Affected detail writes,
  archive faults, dispatch concurrency, database/working-item owners, HTTP access/
  routes, source/exports and selected DB write/eviction HTTP: 132 passed, runner
  11.42 s. Temporary isolated runtime storage with business DB disabled.
- Strict mypy: 1 native file; Ruff/format: 3 files; syntax: 4 including analysis.
  Checker self-tests: 19 passed; ratchet: 1315 files, none above 500 effective lines.
  UTF-8/no-BOM and git diff --check pass; 352 dirty entries at unchanged HEAD
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40. Evidence:
  artifacts/area-writes-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- One server cloning module remains. R1-R9 and earlier full-fast 99.14 s / 60 s
  budget failure remain open. No deployment, restart, business-data mutation,
  commit or push occurred.

### Native screening and ingest cloning exit (2026-09-26)

- Moved legacy _run_analysis_screen and _post_analysis_screen into ScreenHandlers.
  Effective threshold fallback/zero values, cache then DB lookup, copied item data,
  inline overrides, prediction degradation, risk/manual-review flags, margin sorting,
  UTC alert timestamps, alert writing before summary and response fields are retained.
  Control-plane checks still precede body parsing; mode/items validation and sync
  error envelopes remain. Async work uses the current host screen callback with a
  shallow copied payload stripped of execution_mode, preserving its existing contract.
- server_handler_ingest is now explicit native composition and moved to _NATIVE_MODULES.
  Required direct-module host imports and export order remain; late native handlers
  preserve server/context identity and descriptors. server_handler_analysis is the
  only remaining server handler cloning source. No core cloning sources remain.
- Five focused tests cover native/module exit, cache/DB/inline precedence and cache
  preservation, margin order/UTC alerts, lookup/prediction degradation, async callback
  replacement/copied payload and denied admission. Existing real HTTP tests cover
  manual-review/risk blocking, threshold/zero configuration and malformed requests;
  job tests cover early return, completion and failure receipts. New tests join fast;
  the module joins isolated import probes. Independent read-only review found no drift.
- Baseline screen/async/UTC/selected real HTTP: 16 passed, runner 3.78 s. Focused with
  source contracts: 35 passed, runner 5.25 s. Affected ingest owners, job lifecycle/
  stop boundaries, HTTP access/guards/routes, runtime lifecycle, import/export/source,
  selected DB-backed screen and real HTTP cases: 306 passed, runner 21.92 s. All used
  isolated temporary storage with business DB disabled; no broad fast rerun.
- Strict mypy: 2 native files; Ruff/format: 6 files; syntax: 7 including server.
  Checker self-tests: 19 passed; ratchet: 1314 files, none above 500 effective lines.
  UTF-8/no-BOM and git diff --check pass. HEAD remains
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 with 351 dirty entries. Evidence:
  artifacts/ingest-exit-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- Analysis/prediction remain migration inputs; this ownership move does not close R4
  compatibility or product gates. R1-R9 and earlier full-fast 99.14 s / 60 s budget
  failure remain open. No deployment, restart, business-data mutation, commit or push.

### Native client diagnostics and POST fallback (2026-09-26)

- Moved client-log and unknown-POST responses into existing HandlerCompatibility
  native closures. Accepted messages retain string conversion, 4000-character cap,
  literal logger format, error/info selection and status=ok. Rejected JSON never logs
  or emits a second response. API paths keep the guard JSON 404; ordinary paths and
  bare /api retain a bare 404. Query strings remain excluded from error path details.
- Ingest now aliases the closures; late native publication preserves DataHandler
  binding and server/context identity. Eight adapter cases cover truncation, both
  levels, rejected body, API/non-API distinctions, current guard replacement and
  native descriptors. The new adapter tests join fast.
- Added POST fallback to source introspection alongside GET fallback. Initial focused
  run: 75 passed / 1 failed because ast.walk attributed a closure's bare 404 both to
  its actual function and the outer binding function. The checker now records the
  innermost function owner for each call. A regression verifies that nested and outer
  calls are both retained; the current allowed-owner set is unchanged. Independent
  read-only review found no hidden-404 exclusion or handler behavior regression.
- Baseline adapters/HTTP guards/routes/API fallback: 57 passed, runner 16.05 s.
  Final focused including source contracts: 77 passed, runner 5.98 s. Affected
  HTTP access/guards/routes, native import/export/source, lifecycle and real log/JSON
  error/fallback HTTP contracts: 228 passed, runner 16.98 s. Isolated temporary
  runtime storage, business DB disabled; no broad historical suite rerun.
- Strict mypy: 1 owner file; Ruff/format: 4 files; syntax: 5 including ingest.
  Checker self-tests: 19 passed; 1312-file ratchet has no file above 500 effective
  lines. UTF-8/no-BOM and git diff --check pass; 349 dirty entries at unchanged HEAD
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40. Evidence:
  artifacts/ingest-adapters-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- Only screening bodies remain in ingest. Two handler cloning modules, R1-R9 and
  the prior full-fast 99.14 s / 60 s budget failure remain open. No deployment,
  restart, business-data mutation, commit or push occurred.

### Native next-visit dispatch (2026-09-26)

- Moved _post_detail_next_visit into the existing DetailDispatchHandlers owner.
  Body rejection still precedes snapshot/service access. Runtime indexes exposing
  state_snapshot use it; the tested legacy index fallback copies seen/dispatched
  mappings under its lock. Database mode omits legacy entries. Service calls retain
  current lock, cooldown and optional mark/get/prune callbacks. Snapshot exceptions
  remain outside the service catch; service failures retain AVM_NEXT_VISIT_TASK_FAILED.
- Ingest now aliases the native closure. The existing late native binding publishes
  it to the server/context and DataHandler; no new module or runtime owner was added.
  Extended the existing dispatch suite with next-visit body/error/descriptor coverage,
  DB/legacy callback-forwarding cases and snapshot-failure boundary. The existing
  fallback test still verifies lock-held mapping access with optional callbacks absent.
- Baseline dispatch/fallback and three real HTTP cases: 16 passed, runner 4.42 s.
  Focused with source contracts: 33 passed, runner 3.75 s. Affected runtime state,
  dispatch concurrency/retention/UTC, HTTP permissions/routes, native exports/source,
  selected DB next-task read and real HTTP cases: 95 passed, runner 8.70 s. Temporary
  isolated runtime/storage, business DB disabled; unchanged import suite not repeated.
- Strict mypy: 1 native file; Ruff/format: 2 files; syntax: 3 including ingest.
  Checker self-tests: 19 passed; ratchet: 1311 files, none above 500 effective lines.
  UTF-8/no-BOM and git diff --check pass. Evidence:
  artifacts/next-visit-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- Ingest still contains screening, client logging and POST fallback bodies. R1-R9,
  two remaining handler cloning modules and the earlier full-fast 99.14 s / 60 s
  budget failure remain open. No deployment, restart, business-data mutation,
  commit or push occurred.

### Native detail patch and HTML admission (2026-09-26)

- Moved detail item-update and HTML-submission POSTs into DetailIngestHandlers. Both
  retain index acquisition before body parsing and outside the HTTP exception catch.
  Body rejection never resolves the service. IDs, failed_timeout override, HTML size
  limit, missing-item 404s, unexpected-update 500s and successful response projections
  are preserved. HTML still returns the service response, including extra fields.
- The native owner delegates to the existing DetailCollectionService and uses the
  current working-item, archive, database, runtime eviction, queue and task callbacks.
  It does not alter persistence or dispatch locking. No extra state owner was added;
  the existing service callback bundle remains an explicit R2 consolidation task.
  Late native publication keeps normal handler descriptors and server/context identity.
- Ten focused cases cover current callbacks after saving the handler, exact payload
  and callback forwarding, HTML max-bytes, body rejection, index failure propagation,
  service-error envelopes and native descriptors. Tests join fast/security; the new
  module joins isolated import probes. Existing real HTTP archive/DB fault tests
  confirm failed writes do not consume pending work or advance in-memory records.
- Baseline with resource errors and archive failures: 51 passed, runner 4.70 s.
  Focused with source contracts: 70 passed, runner 5.08 s. Affected persistence faults,
  dispatch concurrency, working-item/database owners, HTTP security/routes,
  native import/export/source and selected DB lazy-load/failed-timeout HTTP cases:
  309 passed, runner 18.61 s. Temporary isolated storage, business DB disabled.
- Strict mypy: 2 native files; Ruff/format: 5 files; syntax: 6 including legacy
  ingest. Checker self-tests: 19 passed; ratchet: 1311 files, none above 500 effective
  lines. UTF-8/no-BOM and git diff --check pass. HEAD remains
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 with 348 dirty entries.
  Evidence: artifacts/detail-ingest-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- R1-R9 remain open. Ingest still owns screening, client logging, next-visit dispatch
  and fallback bodies; there are still two handler cloning modules. Earlier full-fast
  99.14 s / 60 s budget failure remains unresolved. No deployment, restart,
  business-data mutation, commit or push occurred.

### Native binary upload boundary (2026-09-26)

- Moved _resolve_upload_target and _post_upload into UploadHandlers. Validation still
  confines resolved targets to downloads/<item_id>, rejects invalid names/IDs, and
  uses exclusive binary creation to preserve existing archives. Framing rejects
  invalid/nonpositive Content-Length, Transfer-Encoding and oversized payloads before
  reading; short reads close the connection without creating a target. Invalid
  parameters consume only the declared bounded body. Error envelopes remain unchanged.
- The closure reads the active root, byte limit, path resolver, filesystem and logger.
  Optional host.open falls back to builtin open, preserving the real HTTP fault
  injection seam. Ingest aliases the native pattern/helper/handler; late native owner
  publication retains facade/context identity and DataHandler descriptors. Other
  ingest handlers remain cloned. This is no new symlink-race or durability guarantee.
- Twelve focused cases cover frame rejection without reads/writes, exact-limit save,
  truncated body, bounded invalid-target drain, original-byte preservation after a
  second upload, current resolver/root replacement and native ownership. Tests join
  fast/security; upload_handler joins isolated import probes. Independent review
  found no introduced behavior, error-boundary or dependency-replacement regression.
- Baseline with guards/routing and three real HTTP upload contracts: 64 passed,
  runner 4.17 s. Focused with source contracts: 82 passed, runner 6.88 s. Final
  affected HTTP access/guards/routes, archive preservation, runtime lifecycle and
  native import/export/source contracts: 260 passed, runner 23.14 s. All used
  isolated temporary roots with business database access disabled; no broad rerun.
- Strict mypy: 2 native files; Ruff/format: 5 files; syntax: 6 including legacy
  ingest. Checker self-tests: 19 passed; ratchet: 1309 files, none above 500 effective
  lines. git diff --check and UTF-8/no-BOM checks pass. HEAD remains
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 with 346 dirty entries.
  Evidence: artifacts/upload-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- R1-R9, the two remaining handler cloning sources and the prior fast 99.14 s /
  60 s budget failure remain open. No deployment, restart, business-data mutation,
  commit or push occurred.

### Native captcha-report admission (2026-09-26)

- Moved _post_captcha_report into CaptchaReportHandlers, preserving preflight order:
  stale challenge, pre-completion timestamp, scoped reset grace, auth/progress grace,
  blocked-node and manual-only handoff. Rejected preflight reports never refresh the
  last request, create a challenge or submit a solver. Grace seconds still clamp at
  zero and round up. Live host attributes retain monkeypatch/runtime replacement.
- Manual-lock force retry still passes scope and running-state preservation, checks
  the refreshed lock, and resumes an existing worker rather than starting another.
  Queued/running requests deduplicate; over-limit workers mark manual-required with
  flag errors exposed. Remote CDP creates the challenge then pauses its scope and
  defers to the node. Local creation stays outside the queue-error catch. HTTP error
  codes and response fields remain unchanged; no new retry or concurrency policy.
- Late native binding preserves DataHandler descriptors and server/context identity;
  ingest retains a direct-module binding with its runtime, scope and clock imports.
  Its other handlers remain cloned. Ten focused cases cover suppression side-effect
  boundaries, ceil/clamp responses, remote ordering, callback/runtime replacement,
  begin-error propagation and descriptor ownership. Tests join fast and security;
  the native module joins isolated import probes. Independent review found no drift.
- Before: 33 passed, runner 2.76 s, including 15 selected existing real captcha-report
  HTTP cases and stage-isolation tests. Focused with source contracts: 51 passed,
  runner 6.38 s. Ruff identified two redundant int(math.ceil(...)) wrappers; removed
  them without changing numeric results. Final affected auth/scope/request/solver,
  status, HTTP access/guards, native import/export/source and selected HTTP cases:
  397 passed, runner 20.62 s, isolated temporary storage, business DB disabled.
- Strict mypy: 2 files; Ruff/format: 5 native/manifest/test files; syntax: 6 files
  including legacy ingest. Checker self-tests: 19 passed; 1307-file ratchet has no
  file above 500 effective lines. UTF-8 without BOM and git diff --check pass.
  HEAD remains f2d735ab20e60c1dce212dd86dd2b15fd22a8c40; 344 dirty entries.
  Evidence: artifacts/captcha-report-native-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
- R1-R9 remain open. Two server handler cloning modules and persisted auth migration
  remain; the prior fast 99.14 s / 60 s budget failure is unresolved. No deployment,
  restart, business-data mutation, commit or push occurred.

### Native status adapter and get-collection cloning exit (2026-09-26)

- Moved /api/status into CollectionStatusHandler, preserving current host lookups,
  index acquisition outside the HTTP catch, lightweight early return, DB counters,
  legacy processed/file-capture union, UTC cooldown boundaries and read-only preview.
  Preview remains limited to ten results; legacy scanning stops after 100 candidates
  and the database reader receives limit=100. Repository enablement still controls
  data-supply projection independently from the preferred task-read mode.
- server_handler_get_collection now composes explicit native handlers and retains
  direct-module host dependencies and export ordering. It moved from _HANDLER_MODULES
  to _NATIVE_MODULES; late native handler publication retains facade/context identity
  and ordinary function descriptors. Two server handler cloning sources remain:
  server_handler_analysis and server_handler_ingest. No core cloning sources remain.
- Added 12 focused cases for counts, cooldown/preview bounds, no mutation, independent
  DB switches, lightweight bypass, callback replacement, exception boundaries,
  injected direct-module invocation and native descriptor/module membership. The
  direct-module test supplies missing lifecycle callbacks; it does not establish a
  standalone initialized server. The new module joins isolated import probes and
  the test file joins fast. Independent read-only review found no behavior defect.
- Baseline characterization/real HTTP guards: 40 passed, runner 2.77 s. Initial
  collection used datetime.UTC, unavailable in the project's Python 3.10; changed
  the fixture to timezone.utc before capturing the passing baseline. Final focused
  status/HTTP/source contracts: 62 passed, runner 4.77 s. Affected native owners,
  import/export/source, status readers, runtime lifecycle, HTTP access and selected
  DB/AVM status HTTP cases: 273 passed, runner 14.59 s. All use isolated temporary
  runtime storage with business database access disabled. No broad fast rerun.
- Strict mypy: 2 native files; Ruff and format: 6 files; syntax: 7 files. Checker
  self-tests: 19 passed; ratchet: 1305 files, none above 500 effective lines. A
  manifest line-ending-only formatter failure was corrected with official Ruff
  and the same format check passed; unchanged behavioral tests were not repeated.
  git diff --check passes. Source/docs remain UTF-8 without BOM. HEAD remains
  f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 with 342 inherited/current dirty entries.
- Evidence: artifacts/status-exit-{before,focused,affected,ruff,format,mypy,checker,ratchet}.log.
  Earlier full-fast 99.14 s failure against the 60 s budget remains unresolved.
  R1-R9 remain open; no deployment, restart, business-data change, commit or push.

### Native asynchronous report admission (2026-09-26)

- Moved drift/release-gate/recent-gap POSTs into ReportJobHandlers. Body parsing,
  inline numeric validation, zero/default/negative handling, job kinds/error codes
  and queue delegation are unchanged. Each admitted closure retains the original
  generator and root; release summary is also captured before enqueue. Gap output
  still uses atomic write_json, and summary failure keeps its trusted stage code.
- Added sixteen pre-move cases for numeric values, captured dependencies, rejected
  bodies and summary exception chaining. With existing real async HTTP/file-failure
  coverage: before 22 passed, runner 3.17 s. Added three descriptor/context checks;
  focused with route-source contracts: 42 passed, runner 5.59 s. New cases in fast.
- Affected real report/job HTTP, lifecycle/stop boundaries, write access and native
  import/export/source contracts: 233 passed, pytest 20.39 s, runner 21.98 s,
  isolated crow-quality-2mjwruct. Evidence: artifacts/report-handlers-native-*.log.
  Two source files pass strict mypy; Ruff, five-file format and six-file syntax
  pass. Checker 19 passed; ratchet 1303 files, no above-500 tier, baseline unchanged.
- get_collection has only _get_status left as a cloned function body. Three handler
  cloning sources still exist; tool-owned report generators and analysis/prediction
  remain migration inputs. R1-R9 and earlier full-fast timing failure remain open.
  No broad security/PostgreSQL or deployment acceptance claimed. Deployment,
  restarts and business-data changes stay deferred; no commit/push.

### Native legacy analysis read routes (2026-09-26)

- Moved prediction, health and collection-template GETs into AnalysisReadHandlers.
  Preserved ID validation/not-found errors, prediction logging, lazy template
  imports and its existing patch point, live facade service/repository/clock,
  nonnegative uptime, DB-count exception metadata and outer health failures.
  This migrates existing compatibility routes; analysis/prediction maturity is
  unchanged and remains outside the implemented collection-engine claim.
- Added four pre-move health cases for current clock/service, backward clock and
  degraded counts. With eight selected real prediction/health/template HTTP cases:
  before 12 passed, runner 2.42 s; after adding three native descriptor/context
  cases, 15 passed, runner 2.17 s. New tests are in fast.
- Affected lifecycle, collection status, routing and native import/export/source
  contracts: 266 passed, pytest 16.36 s, runner 17.50 s, isolated
  crow-quality-1na3mxqk. Evidence: artifacts/analysis-reads-native-*.log.
  Two source files pass strict mypy; Ruff, five-file format and six-file syntax
  pass. Checker 19 passed; ratchet 1301 files, no above-500 tier, baseline unchanged.
- get_collection retains status and three report-job POST bodies. Three handler
  cloning sources, R1-R9 and earlier full-fast timing failure remain open.
  No broad fast/security, PostgreSQL or deployment acceptance claimed; deployment,
  restarts and business-data changes remain deferred. No commit/push.

### Native manual-review read routes (2026-09-26)

- Moved six manual-review reads to ReviewReadHandlers: receipts, jobs, operations,
  control status, backup repairs and integrity history. Preserved active-root and
  DB selection, manager/snapshot/runtime/context order, running/queued/single-job
  fields, ten control-status keys, all error envelopes and callback replacement.
  History still applies limits before reversing and does not mutate loaded rows.
- Five selected real HTTP contracts plus native runtime/job-view tests passed
  before migration: 20 passed, runner 6.86 s. Added twelve descriptor and zero/
  positive/invalid-limit history cases; focused after: 32 passed, runner 4.34 s.
  Initial affected run: 208 passed, 12 subtests, 3 source-inventory failures because
  an extracted limit helper hid per-route validation. Restored explicit conversion/
  clamping in each handler without weakening the route inventory. Focused source
  and native cases then passed: 29 passed, runner 4.19 s.
- Final affected twelve real HTTP failure/limit cases, receipt storage/jobs/views,
  runtime ownership, routing and native import/export/source contracts:
  211 passed, 12 subtests, pytest 17.46 s, runner 18.80 s, isolated
  crow-quality-_ery7jbp. Evidence: artifacts/manual-review-reads-native-*.log.
  Two sources pass strict mypy; Ruff, five-file format and six-file syntax pass.
  Checker 19 passed; final ratchet 1299 files, no above-500 tier, baseline unchanged.
  Independent review found no handler behavior/binding regression.
- Three handler cloning sources remain. get_collection now retains status,
  prediction/health/template and three report-job POSTs. R1-R9 and earlier fast
  timing failure remain open. No broad fast/security, PostgreSQL or deployed-runtime
  acceptance claimed; deployment/restarts and business-data changes stay deferred.
  No commit/push.

### Shared snapshot contract and isolated desktop payload closure (2026-09-26)

- Moved immutable manual snapshot path validation and RecoveryError into
  src/auth_snapshot_contract.py. PC1 tool imports remain current public aliases
  of the same exception/function; NAS recovery downloads now import only the shared
  src contract. Ten cases cover alias identity, immutable path construction,
  invalid IDs/digests and a real synthetic manual snapshot download while tools
  imports are explicitly blocked. They are in fast and security.
- Isolated desktop payload checks exposed pre-existing missing native dependencies:
  cdp_cookie_transport, taobao_health, taobao_list_probe, cookie_snapshot_metadata
  and cookie_snapshot_storage. Added those and the new shared contract to the
  explicit installer list. A read-only transitive-import audit located the closure.
  Bundle probes now verify both src and tools originate inside the copied payload
  and strip ambient FAPAI settings. Corrected stale offline expectations to the
  existing api_not_configured short-circuit; production client logic is unchanged.
- Final focused contract, PC1 single/shared auth, real isolated payload/PowerShell
  launcher and NAS snapshot tests: 60 passed, pytest 14.50 s, runner 16.17 s,
  isolated crow-quality-8bj1tr3y. Initial package failures and intermediate attempts
  remain in artifacts/auth-snapshot-contract-*.log; they are not passing baselines.
- Affected NAS HTTP, native import/export/source, desktop API/settings group:
  179 passed, 1 failed, runner 54.58 s. Failure was the separate standalone-settings
  test's explicit file list missing the new contract; after updating that fixture,
  its isolated subprocess test passed separately: 1 passed, runner 1.31 s.
  These results are separate runs, not one full-suite pass.
- Two sources pass strict mypy; relevant Ruff, nine-file format/syntax and installer
  PowerShell parse pass. Checker 19 passed; ratchet 1297 files, no above-500 tier,
  baseline unchanged. No actual application was installed/restarted. This closes
  the snapshot-path dependency edge and verifies copied Python payload launch;
  full desktop packaging/runtime, other src-to-tools edges, three handler cloning
  sources, R1-R9 and earlier fast timing failure remain open. No business-data
  mutation, commit or push; deployment stays deferred.

### Bounded recovery snapshot download reads (2026-09-26)

- Closed the preceding snapshot resource-bound concern: the 5 MiB protocol limit
  previously applied only after read_bytes allocated the entire file. Downloads
  now read at most 5 MiB plus one byte from one opened binary stream, reject the
  extra byte before digest/base64 processing and close the stream on every path.
  No stat-before-read race or second file read was introduced.
- Added a tracked-stream regression which failed before the fix with read(-1)
  instead of read(5242881); initial file group: 1 failed, 5 passed. It now checks
  the actual read bound, closed stream, original rejection code and no success
  response. Existing exact-limit acceptance, one-extra-byte rejection, real NAS
  HTTP validation and immutable manual snapshot tests remain unchanged.
- Focused plus affected download/manual-handoff boundaries: 45 passed, pytest
  6.08 s, runner 7.30 s, isolated crow-quality-7cremfjk. Evidence:
  artifacts/recovery-snapshot-bounded-*.log. Strict mypy on the owner, Ruff,
  two-file format/syntax, 19 checker tests and 1295-file ratchet pass; no baseline
  or exception change. The regression is included through fast/security manifests.
- The src-to-tools snapshot-path dependency, three handler cloning sources, R1-R9
  and earlier fast timing failure remain open. No broad suite or deployment claim;
  deployment/restarts and business-data changes remain deferred. No commit/push.

### Native recovery state and snapshot reads (2026-09-26)

- Moved recovery state and authenticated snapshot download GETs into
  RecoveryReadHandlers. Preserved authorization before coordinator/path access,
  active identity/status validation, immutable manual-path selection, missing/empty/
  oversized/changed responses, SHA-256 normalization and base64 wire fields.
  Coordinator, authorization and path callbacks remain live facade dependencies.
- Added four pre-extraction cases: both unauthorized reads avoid state/path access,
  exact 5 MiB succeeds and one extra byte is rejected using synthetic temp files.
  Focused real NAS HTTP, manual snapshot and routing group: 60 passed before,
  runner 8.28 s; 61 passed after native descriptor checks, runner 10.30 s.
  The five new cases are registered in both fast and security.
- Affected stage/seed trust, HTTP guards and native import/export/source group:
  257 passed, pytest 21.08 s, runner 22.66 s, isolated crow-quality-9f9pwfoc.
  Evidence: artifacts/recovery-reads-native-*.log. Two source files pass strict
  mypy; Ruff, five-file format and six-file syntax pass. Checker 19 passed;
  ratchet 1295 files, no above-500 tier, baseline unchanged. Independent review
  found no authorization, identity, file-validation or response regression.
- Existing read_bytes before size checking and src-to-tools manual snapshot helper
  dependency were preserved and remain follow-ups. Three handler cloning sources,
  R1-R9 and earlier fast timing failure remain open. No broad security, PostgreSQL,
  desktop or deployed-runtime acceptance claimed. No deployment/restart, business
  data mutation, commit or push; activation remains deferred.

### Native collection console read routes (2026-09-26)

- Moved HTML/static asset serving and overview/items/regions/item GET handlers to
  CollectionReadHandlers with current host callbacks and repository. Preserved
  raw bytes, MIME and byte length, unquoted detail path-ID override on a copied
  query, empty-ID validation, storage capability checks and 400/404/503/500 errors.
  Existing HTTP error IDs/redaction remain in the common response layer.
- Six characterization cases cover response bytes/headers, encoded path override
  without input mutation and saved callback replacement. Focused static/resource/
  real HTTP error coverage before: 60 passed, runner 3.61 s. Added native descriptor/
  context checks for all six methods; focused after: 61 passed, runner 4.11 s.
  New test file is registered in fast.
- Affected observer query budgets, collection API/status, static resources, item
  errors, HTTP routing/access guards and import/export/source contracts:
  343 passed, pytest 21.47 s, runner 22.88 s, isolated crow-quality-ejz63iqv.
  Evidence: artifacts/collection-reads-native-*.log. Two sources pass strict mypy;
  Ruff, five-file format and six-file syntax pass. Checker 19 passed; ratchet
  1293 files, no above-500 tier, baseline unchanged.
- Three handler cloning sources remain, including manual-review reads, recovery
  snapshot transport and status/visit routes within get_collection. The earlier
  full-fast timing failure and R1-R9 remain open. No full security, PostgreSQL,
  desktop or deployment acceptance claimed; deployment/restarts and business-data
  changes remain deferred. No commit/push.

### Task-control handler cloning exit (2026-09-26)

- Moved item/pipeline reads, API/non-API fallbacks and recent-detail replay into
  TaskReadHandlers. server_handler_task_control now contains explicit composition
  and exports and is published as native; three handler cloning sources remain.
  DB-first lookup, get_seen/locked legacy runtime fallback, 400/404/503 distinctions,
  pipeline errors and original maintenance delegation remain unchanged. Dynamic
  facade repository/index/pipeline replacement still affects saved native methods.
- Added 13 characterization cases; baseline with runtime/route tests: 43 passed,
  runner 6.06 s. Added module-exit/descriptors check. Initial source-contract run
  exposed two inventory failures: its delegate scanner requires self-based calls.
  Retained self._submit_maintenance_job in the native replay adapter and explicitly
  indexed the two non-route fallback handlers. Expected route and bare-404 sets
  remain unchanged. Final focused including source contracts: 61 passed, 5.89 s.
- Affected all task-control native owners, runtime/access and import/export/source
  contracts plus four real item/merge HTTP cases: 269 passed, pytest 18.17 s,
  runner 19.48 s, isolated crow-quality-ido77fr2. Evidence:
  artifacts/task-control-exit-*.log. Two sources pass strict mypy; relevant Ruff,
  seven-file format and eight-file syntax checks pass. Checker 19 passed; ratchet
  1291 files, no above-500 tier, baseline unchanged. Independent review found no
  behavior, locking, binding or export regression. No new exception was added.
- Previous full-fast timing failure remains unresolved; no unchanged broad suite
  was repeated. R1-R9 remain active. Full security, PostgreSQL, desktop and runtime
  acceptance are not claimed. Deployment/restarts and business-data changes remain
  deferred; no commit/push.

### Native authentication command routes (2026-09-26)

- Moved force reset, auth completion and cooldown resume HTTP commands to
  AuthCommandHandlers. Preserved node authorization before parsing, CDP/cookie
  trust checks before completion, live callback replacement, stale success,
  400/409 rejection and existing exception boundaries. Force-reset callback
  exceptions still propagate; completion/resume callback exceptions retain their
  structured 500 responses. No state/persistence policy was changed.
- Added 22 pre-extraction characterization cases covering auth/body rejection,
  accepted/stale/rejected results, callback replacement, exception boundaries and
  trusted/untrusted target policy. Focused with HTTP guards and NAS API tests:
  65 passed before, runner 5.52 s; 68 passed after adding three native descriptor
  checks, runner 5.61 s. New tests are registered in fast and security.
- Affected scoped solver/cleanup, native cleanup, HTTP access/guards and import/
  export/source contracts: 273 passed, pytest 19.63 s, runner 20.80 s, isolated
  crow-quality-jhptngs6. Evidence: artifacts/auth-commands-native-*.log.
  Two sources pass strict mypy; Ruff, five-file format and six-file syntax pass.
  Checker 19 passed; ratchet 1289 files, no above-500 tier, baseline unchanged.
  Independent read-only review found no concrete behavior/binding regression.
- Dirty worktree: 321 entries including inherited changes. Four handler cloning
  sources remain; task-control still owns item/pipeline reads, fallback and
  maintenance. R1-R9 and the earlier full-fast timing failure remain open.
  No full fast/security, PostgreSQL, desktop or release/runtime acceptance claimed.
  Deployment/restarts and business-data changes remain deferred; no commit/push.

### Native operator command routes (2026-09-26)

- Moved region reset, item reanalysis, manual update and collection pause/resume
  into ObserverCommandHandlers. Late composition publishes ordinary HTTP functions
  with live host callbacks. Authorization precedes parsing; accepted/rejected/error
  envelopes, payload forwarding and path-only pause selection remain unchanged.
- Sixteen characterization cases passed before extraction with route/access/operator
  tests: 75 passed, runner 5.30 s. Four descriptor/context checks added afterward:
  79 passed, runner 3.73 s. The new test file is included in fast.
- Affected operator commands, runtime-control persistence failures, archive failures,
  HTTP guards and import/export/source contracts: 268 passed, pytest 12.12 s,
  runner 13.14 s, isolated crow-quality-3e1uyb4y. Evidence:
  artifacts/observer-handlers-native-*.log. Two source files pass strict mypy;
  Ruff, five-file format and six-file syntax pass. Checker 19 passed; ratchet
  1287 files, no above-500 tier, baseline unchanged. Independent read-only review
  found no concrete behavior/binding regression; new command cases exercise pause,
  while resume-specific new coverage was not added in this ownership-only slice.
- Dirty worktree: 319 entries including inherited changes. Four handler cloning
  sources remain. The earlier full-fast 60-second failure remains unresolved;
  no broad fast/security, PostgreSQL or release/runtime acceptance is claimed.
  Deployment/restarts and business-data changes remain deferred. No commit/push;
  R1-R9 remain active.

### Native cross-device recovery transition routes (2026-09-26)

- Moved the shared heartbeat/claim/snapshot_ready/pc2_restarting/result POST
  handler into RecoveryTransitionHandlers, using current authorization, coordinator,
  clock, JSON-reader and result callbacks. Kept authentication before parsing,
  exact heartbeat fields, recovery ID/claim normalization, numeric conversion
  exception boundary, 400/403/409 mapping and response fields.
- Added twelve pre-move characterization cases covering auth-before-body, invalid/
  valid heartbeat, missing IDs, claim normalization/staleness, snapshot conversion
  and original result payload. Added two native method/coordinator replacement
  cases afterward. Focused with real NAS API tests: 22/24 passed, runner 11.66 s /
  6.70 s. New handler cases are registered in both fast and security.
- Affected stage/seed auth target/scope, worker access, HTTP guards and import/
  export/source group: 243 passed, pytest 21.15 s, runner 22.34 s, isolated
  crow-quality-xja9o37s. Evidence: artifacts/auth-transition-native-*.log.
  Two files pass strict mypy; Ruff, five-file format and six-file syntax pass.
  Checker 19 passed; ratchet 1285 files, no above-500 tier, baseline unchanged.
- Four handler cloning sources remain. Full fast/security, cross-device runtime
  and release acceptance remain open, including the earlier fast timing failure.
  No deployment/restart, business-data mutation, commit or push. R1-R9 active.

### Native seed task claim and progress-report routes (2026-09-26)

- Moved _post_seed_next_task and _post_seed_progress into SeedTaskHandlers and
  published ordinary native functions through late handler composition. Preserved
  session validation before claim, default session, untrimmed valid session values,
  seed pause forwarding, generic task_key progress, logs and error distinctions.
  Existing worker-access rules and both modern/legacy route aliases are unchanged.
- Selected ten real HTTP contract cases plus write-access tests passed before
  extraction: 18 passed, runner 4.64 s. Added seven native binding, saved service/
  pause callback, max-length/default session, original payload and rejected-body
  cases. Focused after: 25 passed, runner 5.22 s.
- Affected seed service/status refresh, worker guards, service factories and
  import/export/source group: 193 passed, 2 skipped, pytest 14.80 s, runner 16.42 s,
  isolated crow-quality-uv2mr6dd. Evidence: artifacts/seed-routes-native-*.log.
  Two source files pass strict mypy; Ruff, five-file format and six-file syntax
  checks pass. Checker 19 passed; ratchet 1283 files, no above-500 tier.
- Seed batch/async handlers remain separate pending work, and four handler cloning
  sources remain. The previous fast timing failure remains open. No full fast,
  security, PostgreSQL or release acceptance; no deployment/restart, business-data
  mutation, commit or push. R1-R9 remain active.

### Native single and batch detail dispatch routes (2026-09-26)

- Moved _post_detail_tasks and _post_detail_next_task from two legacy handler
  modules into DetailDispatchHandlers. Ordinary native functions preserve route
  binding and current-host dependencies, body validation, batch pause response,
  300-item batch limit, UTC cooldown, service callbacks and response/error fields.
  Runtime index capture order and lock/callback publication are unchanged.
- Six characterization cases passed before extraction with existing UTC/runtime
  tests: 21 passed, runner 2.42 s. Added native descriptor/context identity coverage;
  matching focused group 22 passed, runner 2.75 s. First affected run found the
  source inventory skipped relocated closures (1 failed, 296 passed). It now reads
  actual registered DataHandler functions while retaining legacy delegate indexing.
  The expected route set is unchanged. Final focused with source contracts:
  39 passed, runner 3.83 s.
- Affected dispatch concurrency/retention, real detail service, HTTP status/guards,
  import/export/source group: 297 passed, pytest 15.54 s, runner 16.52 s,
  isolated crow-quality-28fsbhjr. Evidence: artifacts/detail-dispatch-native-*.log.
  Two native/composition files pass strict mypy; relevant Ruff/format/syntax pass.
  Checker 19 passed; ratchet 1281 files, no above-500 tier, unchanged baseline.
- Four handler cloning sources remain. No broad fast/security rerun, deployment,
  restart, business-data mutation, commit or push. The prior fast performance
  failure and R1-R9 completion remain open.

### Native solver lifecycle and core handler cloning exit (2026-09-26)

- Moved run_solver into SolverRunLifecycle with explicit runtime, clock, filesystem,
  solver and callback protocols. Preserved stale-preflight identity checks,
  reservation/activation, two attempts, quiescence/CDP deadlines, cancellation,
  scoped manual polling, outcome publication and finalization. The native ordinary
  function adapter preserves DataHandler descriptor behavior and executor arguments.
- File update and silent handler logging now use native adapters. Core handler has
  no implementation functions and exits the cloning list; four handlers remain.
  Late handler publication binds the server host before DataHandler construction.
  Direct-module solver execution still needs its dependencies supplied explicitly.
- Baseline focused 122 passed, runner 5.56 s; matching final group plus two native/
  callback cases 124 passed, runner 6.33 s. The affected group exposed a stale
  source-location logging assertion (1 failed, 335 passed). Replaced it with real
  preflight failure, traceback logging, token release, no execution and no stdout
  assertions. Final focused 130 passed, runner 12.59 s.
- Final affected solver/status/scope/auth-cleanup/import/export/source/logging:
  336 passed, pytest 31.62 s, runner 34.77 s, isolated crow-quality-0rc_0jbd.
  Evidence: artifacts/solver-run-native-before/focused/affected.log.
  Six source files pass strict mypy; Ruff, eight-file format and syntax checks pass.
  Independent review found no lifecycle or lock-order defect. Checker 19 passed.
  Initial ratchet received an empty git baseline-tree value; unchanged retry passed
  for 1279 files with no above-500 tier. Baseline and thresholds were not changed.
- No new full fast/security acceptance: the previous 99.14-second fast failure
  remains open. No deployment, restart, business-data mutation, commit or push.
  R1-R9 remain active; continue the remaining four handler ownership migrations.

### Native solver execution guards and manual polling (2026-09-26)

- Moved four current/resumed/cancelled/manual-poll helpers to SolverExecutionGuard.
  Direct handler and facade methods use their current runtime, clock and predicates.
  Added late native handler composition after legacy handler publication so the
  facade owner is not overwritten by the direct module's bindings.
- Existing run-ownership/request tests: 24 passed before extraction, runner 3.53 s.
  Added 14 cases covering both entrypoints, same-timestamp runtime replacement,
  independent cancellation causes, deadline, supersession and late callbacks.
  Focused 38 passed, runner 4.98 s. Existing real-thread tests continue to prove
  late solver outcomes do not mutate replacement runs and supersession wakes polls.
- Affected solver run/request/scope, HTTP status and import/export/source group:
  277 passed, pytest 19.18 s, runner 20.30 s, isolated crow-quality-iqcghxr6.
  Evidence: artifacts/solver-execution-guard-before/focused/affected.log.
  Strict mypy passes for two files; Ruff and five-file format checks pass;
  syntax passes. Checker 19 passed, ratchet 1275 files with no above-500 tier.
- run_solver and handler compatibility methods remain to migrate. Five handler
  cloning sources remain; the previous fast gate failure is unresolved and no
  broad rerun or release acceptance is claimed. R1-R9 remain active; no deployment,
  restart, business-data mutation, commit or push.

### Core operations exit function cloning (2026-09-26)

- Extracted confidence/summary policy into ScreenResultSummary and legacy alert
  I/O into ScreenAlertStore, preserving live host callbacks, paths and runtime lock.
  Removed server_collection_operations from core cloning sources; five handler
  sources remain. Direct DB preference stays local and facade ownership unchanged.
- Characterization before/after: 36/38 passed, runner 6.42 s / 6.70 s. Added 34
  direct/facade cases covering confidence edges, counters, duplicate blockers,
  numeric margins, invalid shapes, alert replacement/order, empty no-op, unreadable
  fallback and propagated entry/write errors. An initial missing postponed type
  annotation caused import failure; fixed before final focused verification.
- Affected HTTP contracts, async screening, import/export/source/runtime: 527 tests
  and 1207 subtests passed, runner 64.47 s, isolated crow-quality-zkf595c1.
  Three native/composition files pass strict mypy; Ruff, format and syntax pass.
  Checker 19 passed; ratchet 1273 files, no above-500 tier. Independent source
  comparison found no defect. Evidence: artifacts/operations-exit-*.log.
- Formal fast milestone: 1063 passed, 2 skipped; pytest 96.69 s, runner 99.14 s,
  isolated crow-quality-xwa2t798. Gate FAILED on the unchanged 60-second budget.
  Timing report shows collection 14.71 s, native import probes 16.26 s and runner
  tests 9.80 s, versus 10.88/7.54/4.70 s at the earlier data-runtime checkpoint.
  A later CPU sample was 96%; test-time resource contention is not established.
  Keep this performance gate open rather than treating passing assertions as a
  passed milestone. No full security, PostgreSQL, desktop or deployment acceptance.
- One focused import diagnostic passed 104 cases, runner 11.33 s; measured test
  phases 9.91 s versus 16.26 s in the full run. CPU samples immediately before/
  after were 63%/100%. This confirms timing variability, not its precise cause or
  fast-gate recovery. No speculative optimization or repeated broad run followed.
  Final slice whitespace and ten-file UTF-8/no-BOM checks pass.
- R1-R9 remain active. Legacy alert corruption fallback/non-atomic persistence
  remains unchanged; no durability improvement claimed. No deployment, restart,
  business-data mutation, commit or push.

### Native auction risk aliases and screening response (2026-09-25)

- Moved five risk payload/lookup/alias/signal/result callbacks into AuctionRiskPolicy
  under collection/adapters. Direct operations and server/context exports publish
  native bound methods, resolving current host callbacks and risk constants.
  Preserved top-level None fallback, false/zero/empty precedence, setdefault behavior,
  exact boolean risk selection, label order, price/margin call order and result schema.
- Added twelve before/after characterization cases plus two native ownership cases.
  Focused ingest/screening group: 16 passed before, 18 passed after; runner 5.59 s /
  4.42 s. Evidence: artifacts/auction-risk-native-before.log and -focused.log.
- Affected detail/archive/file-runtime, auction policies, ingest/screening and
  import/export/source group: 214 passed, pytest 15.82 s, runner 17.56 s, isolated
  runtime crow-quality-aey86y69 with business DB disabled. Evidence:
  artifacts/auction-risk-native-affected.log. Strict mypy passes for two native/
  composition files; Ruff and format pass for five files; syntax passes for six.
  Checker tests 19 passed; ratchet 1270 files, no above-500 tier, baseline unchanged.
- Remaining operations ownership: confidence/summary, alert persistence and direct
  DB preference. R1-R9 remain active. No full fast/security, release or deployment
  acceptance claimed; no restart, business-data change, commit or push.

### Native auction record patch and rebuild rules (2026-09-25)

- Moved structured reset and flat alias overrides into AuctionRecordPatch under
  collection/adapters. The legacy public alias table is still exported; direct and
  facade methods resolve their host's current table. Verified all 44 alias pairs
  and their iteration order match the pre-move source. Empty-string/None exclusion,
  zero/false acceptance, alias collision precedence and reset key set are unchanged.
- Added seven characterization/native/service-path cases. The real detail service
  test verifies alias application and removal of stale structured fields before
  adapter rebuild, then archive/DB writes before mutation of the working record and
  runtime queue action. Existing error-path tests retain the failed-publication proof.
  Focused before/after: 26 passed, runners 4.00 s and 2.58 s. Added an import probe.
- Affected persistence failure, HTTP routes and import/export/source group: 193
  passed, pytest 18.72 s, runner 20.31 s, isolated runtime crow-quality-uvloz4v0 with
  business DB disabled. Evidence: auction-record-native-before/focused/affected.log.
  Two files pass strict mypy; relevant Ruff, syntax and six-file format checks pass.
  Checker tests 19 passed; ratchet 1268 files, no above-500 tier and unchanged baseline.
  Git whitespace and changed-slice UTF-8/no-BOM checks pass.
- Remaining risk/result/summary and alert-write helpers still clone; no whole-plan,
  full fast/security or release acceptance is inferred. R1-R9 remain active and
  deployment/restarts stay deferred.

### Native auction price policy callbacks (2026-09-25)

- Moved parse_price, starting/predicted price field selection, margin and _safe_int
  into AuctionPricePolicy under collection/adapters. Server/context and direct
  operations-module entrypoints publish native methods; composite helpers retain
  live host parser replacement. Existing AVM money normalization was inspected and
  not reused because zero, signs and string tokenization differ from this contract.
- Added 34 characterization/native cases on both hosts covering units, commas,
  malformed/unsupported inputs, numeric versus string negative values, zero fallback,
  field precedence, margin boundaries, NaN/Infinity integer behavior and late parser
  replacement. The behavior suite passed before and after extraction: 53 passed,
  runners 3.06 s and 4.78 s. Added one fresh-process import probe.
- Affected seed publication, AVM screen jobs, ingest UTC, imports/exports/source
  group: 193 passed, pytest 18.97 s, runner 20.59 s, isolated runtime crow-quality-xskpr8mk
  with business DB disabled. Evidence: auction-prices-native-before/focused/affected.log.
  Two files pass strict mypy; relevant Ruff, syntax and six-file format checks pass.
  Checker tests 19 passed; ratchet 1266 files, no above-500 tier and unchanged baseline.
  Git whitespace and changed-slice UTF-8/no-BOM checks pass.
- Remaining record override, risk/result/summary and alert-write helpers still clone.
  This does not complete R1/R2, AVM analysis/prediction capabilities or full R1-R9
  acceptance. No full fast/security/deployment claim; deployment/restarts deferred.

### Native service construction and seed intake (2026-09-25)

- Migrated both collection service factories, build_sniff_stub and seed batch intake
  into CollectionServiceOperations. Direct operations and facade/context entrypoints
  bind native methods against their own live dependencies. Constructor replacement,
  data/job root replacement, detail root override, adapter selection and dispatch
  lock are preserved. Seed intake holds the collection lock and retains all existing
  parsing, repository, archive, persistence and queue callbacks/return identities.
- Added four native saved-factory/service/repository replacement cases and an import
  probe. Existing adapter environment, seed lock and failure/publication regressions
  remain. Baseline 50 passed, runner 5.16 s; focused final 54 passed, runner 7.67 s.
  Affected seed/HTTP jobs/startup/import/export/source group: 231 passed, pytest
  17.61 s, runner 19.27 s, isolated runtime crow-quality-j2ii375w with business DB
  disabled. Evidence: collection-services-native-before/focused/affected.log.
- Independent review found no demonstrated regression. Two files pass strict mypy;
  relevant Ruff, syntax and six-file format checks pass. Checker tests 19 passed;
  ratchet 1264 files, no above-500 tier and unchanged baseline. Git whitespace and
  changed-slice UTF-8/no-BOM checks pass. R2 source-policy/default and callback-bundle
  migration is not claimed by this ownership extraction. Remaining operations,
  handlers and R1-R9 work stay open; no full fast/security/release claim is made for
  this state, and deployment/restarts remain deferred.

### Native working-item cache and database lookup (2026-09-25)

- Migrated runtime-index access, eviction and working-item lookup into three native
  CollectionWorkingItems methods, with direct-module/facade live dependencies.
  Removed the overwritten runtime-index implementation from server.py. Preserved
  cache-first identity, cache acceptance of processed entries, DB sync-before-filter,
  no implicit DB-result caching, repository-error logging/None and propagation of
  subsequent sync errors. Eviction removes seen/pending without deleting dispatch.
- A new direct-module missing-date regression failed before edits with AttributeError:
  datetime.datetime had no datetime attribute (baseline 1 failed, 25 passed). Changed
  operations' datetime class import to the module used by the existing call contract.
  Facade behavior and local archive clock semantics are unchanged.
- Added ten direct/facade cases and one import probe. An initial owner-identity
  assertion exposed the existing CollectionStatusReaders ownership of the facade
  DB preference; kept that ownership and left the legacy operations helper unchanged
  instead of publishing a duplicate native policy. Final focused 34 passed, runner
  5.77 s. Affected DB/detail/runtime/HTTP/import/export/source group: 205 passed,
  pytest 20.09 s, runner 21.58 s, isolated runtime crow-quality-6vg0q34s with business
  DB disabled. Evidence: working-items-native-before/focused-final/affected.log.
- Two files pass strict mypy; relevant Ruff, syntax and seven-file format checks
  pass. Checker tests 19 passed; ratchet 1262 files, no above-500 tier and unchanged
  baseline. Git whitespace and changed-slice UTF-8/no-BOM checks pass. Full fast,
  security, release and R1-R9 closure remain unclaimed; remaining operations policy/
  service helpers and handlers still require migration. Deployment/restarts deferred.

### Native task submission and retry polling (2026-09-25)

- Moved submit_task into the existing CollectionFileRuntime and manual retry polling
  into SolverRetryLoop. Both facade/context and direct operations-module entrypoints
  publish native methods. Preserved original processing registry capture, atomic
  claim, current executor/worker selection, completion callback release, rejection
  release, retry policy exception scope and live poll cadence.
- Added two saved submission replacement cases and eight retry-loop cases covering
  queued, malformed optional request, inactive and failed policy results on both
  hosts; also added a fresh-process import probe. Existing completion/failure/cancel/
  rejection ownership and duplicate submission tests remain. Baseline 25 passed,
  runner 3.36 s; focused 44 passed, runner 3.08 s (includes adjacent scanner tests).
  Affected concurrency/startup/import/export/source group: 179 passed, pytest 11.32 s,
  runner 12.48 s, isolated runtime crow-quality-ik8ohoer with business DB disabled.
  Evidence: task-submission-native-before/focused/affected.log.
- Independent review found no demonstrated regression. Three files pass strict
  mypy; relevant Ruff, syntax and nine-file format checks pass. Checker tests 19
  passed; ratchet 1260 files, no above-500 tier and unchanged baseline. Git whitespace
  and changed-slice UTF-8/no-BOM checks pass. No formal fast/security rerun is claimed
  for this state; previous fast evidence stays time-scoped. Remaining operations
  helpers, handler cloning and R1-R9 work remain open; deployment/restarts deferred.

### Data runtime fully exits function cloning (2026-09-25)

- Moved process_single_file/background_file_processor into CollectionFileRuntime,
  with an explicit live host protocol and lazy type-only detail-service dependency.
  Preserved service callback forwarding, runtime queue owners, TXT/new HTML/legacy
  HTML scan ordering, processing skip, one-second cadence and five-second error
  backoff. The detail service still owns archive/DB/runtime commit behavior.
- server_data_runtime now contains only direct native aliases. Moved its publication
  from _CORE_MODULES to _NATIVE_MODULES, preserving all public exports including
  load_json_file. Server/context methods bind to the facade's live dependencies.
  One core and five handler cloning sources remain.
- Added nine export/native dependency/scanner regressions and one import probe.
  Baseline group 40 passed, runner 8.08 s; final focused group 49 passed, runner
  7.75 s, covering existing DB-only processing and persistence failure paths.
  Milestone formal fast: 942 passed, 2 skipped, pytest 57.15 s, runner 58.97 s,
  exit 0 with unchanged 60-second threshold, isolated runtime crow-quality-2dw5yyaq,
  business DB disabled. Logs: data-runtime-exit-before/focused/fast.log; timing:
  data-runtime-exit-fast-timing.json. The 1.03-second gate margin is narrow; this
  pass does not establish stable performance across machine load conditions.
- Independent review found no demonstrated regression. Two files pass strict mypy;
  relevant Ruff, syntax and seven-file format checks pass. Checker tests 19 passed;
  ratchet 1258 files, no above-500 tier, unchanged baseline. Git whitespace and
  changed-slice UTF-8/no-BOM checks pass. Full security/release acceptance and R1-R9
  closure remain open. No deployment, restart or business-data change occurred.

### Native index bootstrap and interrupted-file recovery (2026-09-25)

- Moved load_data and cleanup_orphaned_files into CollectionIndexBootstrap with
  explicit live host dependencies. Both facade/context and direct-module entrypoints
  retain native bound methods. Index container identity, DB preference/fallback,
  injected record/path/clock callbacks and loader exception behavior are unchanged.
- Orphan recovery retains failed-processing-first ordering, evidence bytes, recovered
  markers and per-file log/continue behavior; old failed markers are not cleaned.
  Removed the obsolete commented-out destructive marker cleanup from the old owner.
  Added six real-file/native replacement cases and one fresh-process import probe.
- Baseline 17 passed, runner 2.66 s. First new-test run had two fixture failures:
  pending auction status is not eligible for the AI queue. Corrected the fixture to
  done without changing production rules. Final focused 23 passed, runner 2.19 s;
  affected index/startup/import/export/source group 151 passed, pytest 11.80 s,
  runner 12.75 s, isolated runtime crow-quality-p3cx574n with business DB disabled.
  Evidence: index-bootstrap-native-before/focused-final/affected.log; the initial
  failed attempt remains separate in index-bootstrap-native-focused.log.
- Independent review found no demonstrated regression. Two files pass strict mypy;
  relevant Ruff, syntax and six-file format checks pass. Checker tests 19 passed;
  ratchet 1256 files, no above-500 tier and unchanged baseline. Git whitespace and
  changed-slice UTF-8/no-BOM checks pass. Remaining data-runtime cloning is file
  processing/scanning. Full R1-R9, security and deployment acceptance remain open;
  deployment and restarts stay deferred.

### Native serialized collection startup (2026-09-25)

- Moved initialize_runtime into CollectionStartup, with explicit runtime, journal,
  repository, seed, worker, recovery and clock dependencies declared by its host
  protocol. Facade/context and direct-module entrypoints retain native bound methods;
  saved methods resolve current host dependencies on each call.
- Preserved initialization_lock then runtime.lock ordering, cleanup journal replay
  before latch restoration/workers, cleanup/index/DB ordering, retry after failed
  index loading, optional DB/seed/sample exception handling, active worker selection,
  and the final started_at/initialized publication. Legacy journal callback argument
  types were checked against their real persistence/flag implementations.
- Added four lifecycle cases for native identity, replacement runtime/clock and
  optional database/seed/sample failures, plus a fresh-process import probe. Baseline
  46 passed, runner 40.64 s; focused final 50 passed, runner 27.14 s. Affected startup,
  scoped/legacy/mixed real process-exit recovery and import/export/source group:
  230 passed, pytest 88.57 s, runner 89.50 s, isolated runtime crow-quality-oz5od6k8
  with business DB disabled. Evidence: bootstrap-native-before/focused/affected.log.
- Independent review found no demonstrated regression. Two files pass strict mypy;
  relevant Ruff, syntax and five-file format checks pass. Checker tests 19 passed;
  ratchet 1254 files, no above-500 tier, unchanged baseline. Git whitespace and
  changed-slice UTF-8/no-BOM checks pass. No full fast/security/deployment acceptance
  is inferred. R1-R9 remain open, including index loading, orphan recovery and file
  processing/scanning; deployment and restarts remain deferred.

### Native collection database write callbacks (2026-09-25)

- Moved persist_item_to_db and mark_item_deleted_in_db to CollectionDatabaseWrites,
  with an explicit repository protocol and live host binding. Both direct-module
  and server facade entrypoints retain the same native implementation; saved
  methods observe subsequent repository replacement. Payload identity, deletion ID
  coercion, disabled repository behavior and failure propagation are unchanged.
  Existing archive/DB/runtime publication ordering and storage transactions remain.
- Added six native/context identity, replacement, payload and exception cases plus
  one fresh-process import probe. Baseline failure-path group: 37 passed, runner
  4.75 s; focused final: 43 passed, runner 2.91 s. Affected HTTP/archive failure,
  seed publication, dual-write, import/export/source contracts: 185 passed, pytest
  9.07 s, runner 10.06 s. Isolated runtime crow-quality-17j2_thn with business DB
  disabled. Logs: db-writes-native-before/focused/affected.log.
- Independent review found no demonstrated behavior regression. Two native and
  composition files pass strict mypy; relevant Ruff, syntax and six-file formatter
  checks pass. Checker tests: 19 passed; ratchet: 1253 files, no above-500 tier,
  baseline unchanged. Git whitespace and changed-slice UTF-8/no-BOM checks pass.
- No full fast/security or deployment claim is made for this worktree state. The
  preceding archive fast checkpoint remains time-scoped. R1-R9 stay open, including
  data runtime initialization/processing/scanner and the remaining cloning sources.
  Deployment and restarts remain deferred; no business data was changed.

### Native collection archive paths and record mutations (2026-09-25)

- Moved eight archive exports into CollectionArchivePaths/CollectionArchiveRecords:
  data/detail/list paths, raw list payloads, detail artifacts, global record update,
  append/update and removal. Preserved local date naming, suffix handling, unexpected
  parser exception propagation, relative evidence paths, locks, missing-ID no-ops,
  atomic record publication and logged/re-raised failures. Raw list publication
  retains its existing behavior; no new crash-safety claim is made for that path.
- Added typed record I/O signatures without changing archive_json_io behavior.
  Existing preservation tests now also exercise independent native owner instances,
  retaining all corruption, fsync/replace, serialization, evidence and no-op checks.
  Four new facade tests cover native identity, saved path/root replacement, raw
  payload evidence and shared detail adapter replacement; four import probes added.
- Centralized explicit owner composition in server_native_bindings, preserving
  prior publication order and adding archive owners. This removes the growing
  inline binding expression from server.py without relaxing the effective-line gate.
- Baseline 21 passed. Initial fast found 34 failures (879 passed, 2 skipped): direct
  server_data_runtime callers still required the extracted entrypoints, including
  load_data's path dependency. The module now publishes the same native classes
  against its own live dependencies, while server publishes facade-bound instances.
  No duplicated function bodies/cloning were restored. Focused failure/consumer
  retry: 73 passed, runner 3.97 s, isolated runtime crow-quality-f6j143qr.
- Pre-alias formal fast: 913 passed, 2 skipped, pytest 34.12 s, runner 35.42 s, exit 0,
  isolated runtime crow-quality-5vl9i2dq with business DB disabled. Timing artifacts
  are archive-native-fast-final.log and archive-native-fast-final-timing.json.
  The unchanged 60-second threshold includes diagnostics overhead. The earlier
  failed attempt remains recorded separately; it is not counted as acceptance.
- Final static review found Ruff F822 on dynamically published direct-module exports.
  Replaced that publication loop with eight explicit native bound-method aliases.
  Final focused: 73 passed, runner 4.19 s. Final formal fast: 913 passed, 2 skipped,
  pytest 40.15 s, runner 41.56 s, exit 0; isolated runtime crow-quality-z87ejs5l,
  business DB disabled. Evidence: archive-native-alias-focused.log,
  archive-native-alias-fast.log and archive-native-alias-fast-timing.json.
  Final syntax/format checks and 1251-file ratchet pass; no baseline change.
- Independent reviews found no demonstrated remaining regression. A suggested
  underscored export mismatch was checked against the native declaration and was
  not present (update_file_global has no leading underscore).
- Five native/I/O/composition files pass strict mypy. Relevant Ruff, formatter and
  syntax checks pass; 19 checker tests and 1251-file ratchet pass, baseline unchanged.
  Git whitespace and UTF-8/no-BOM checks pass. Remaining data runtime initialization,
  DB writes, processing/scanner and R1-R9 work stay open; activation remains deferred.

### Collection control fully exits function cloning (2026-09-25)

- Migrated the final eight server_collection_control exports into CollectionObserver
  and CollectionRuntimeControl, with collection_control_binding providing live
  repository/runtime/filesystem/clock/status callbacks. Removed the module from
  _CORE_MODULES. Two core and five handler cloning modules remain.
- Kept lazy query/command imports, public payloads and repository replacement.
  Resume holds the runtime lock and remains paused until flag and challenge cleanup
  succeeds; failures preserve resume epoch and solver state. Optional status failure
  still falls back to pause state, now with an explicit local lint rationale.
- Baseline 125 cases passed. Added five native identity/saved repository/resource/
  status-fallback cases plus two fresh-process import probes. Final focused group:
  132 passed, runner 5.44 s. Final affected group: 296 passed, pytest 11.05 s, runner
  11.83 s, isolated runtime crow-quality-yhj3rf4b with business DB disabled. Covers
  the existing full collection API status module, HTTP route/guard contracts,
  durable resume failure/concurrency, observer commands and source/import/exports.
- Independent read-only review found no demonstrated regression. Two native files
  pass strict mypy, native/test Ruff and applicable format/syntax checks pass;
  checker tests 19 passed; ratchet 1246 files with no above-500 tier, baseline
  unchanged. Git whitespace and UTF-8/no-BOM checks pass.
- No full fast/security/deployment claim follows from this affected-group pass.
  R1-R9 remain incomplete; deployment/restarts stay deferred.

### Native authentication cleanup and cooldown transactions (2026-09-25)

- Extracted four control exports into AuthCleanupCompletion: confirmation-state
  validation, healthy-cookie finalization, node challenge matching and cooldown
  resume. Binding reuses explicit live dependency providers and preserves facade
  replacement seams between public methods. Control now retains only observer
  query/command wrappers and pause/resume orchestration.
- Preserved finalize_lock then runtime.lock ordering, scope fallback within the
  lock, challenge generation checks, prepare/clear/receipt/finish ordering and
  returned-error compensation. Cooldown still records its existing grace metadata
  without claiming a manual solve, and returns a skipped cookie snapshot.
- Reused the preceding unchanged-source affected pass as baseline. Added three
  native identity/saved-runtime/validator-veto regressions and one fresh-process
  import probe. Focused cleanup/scope/generation/legacy group: 70 passed, runner
  7.22 s. Final affected suite: 306 passed, pytest 78.71 s, runner 79.59 s, isolated
  runtime crow-quality-ncg8duir with business DB disabled. Includes actual scoped,
  legacy and mixed process exits, receipt replay, HTTP guards and source contracts.
- Independent read-only review found no demonstrated regression. Two native files
  pass strict mypy; native/test Ruff, relevant format/syntax, 19 checker tests,
  1244-file ratchet, Git whitespace and UTF-8/no-BOM checks pass. Baseline unchanged.
- First combined extraction patch exceeded Windows command-line length before
  apply_patch launched; separate add/remove patches succeeded. No source policy or
  validation was weakened. Full security/fast and deployment acceptance are not
  inferred from this affected run; R1-R9 remain open and activation remains deferred.

### Native authentication confirmation receipt boundary (2026-09-25)

- Moved six confirmation helpers out of server_collection_control cloning into
  AuthCompletionReceipts: ID normalization, path resolution, durable reads,
  recovery-state lookup, replay checks and confirmation publication. The existing
  auth-completion binding now publishes receipts and completion owners together.
- Preserved state-directory precedence and live facade path/runtime/recovery/clock
  replacements. Replay still checks pending scoped/legacy cleanup intents under
  runtime.lock before trusting either cached or durable confirmation. Store/journal
  serialization, retention and write-error/cache behavior are unchanged.
- Baseline before/after: 52 passed. Five new cases cover native/context identity,
  saved callbacks following separate recovery/path/clock providers, and pending
  seed/detail/legacy intents blocking confirmed receipts until intent retirement.
  Final focused group: 57 passed, runner 4.80 s. Added one fresh-process import probe.
- Affected group: 295 passed, pytest 99.79 s, runner 100.84 s, isolated runtime
  crow-quality-dtew_cwk with business DB disabled. Covers receipt corruption,
  cleanup failures, scoped/legacy/mixed process exits, completion generation races,
  runtime replacement, source contracts and imports. No full security/fast rerun or
  deployment/power-loss acceptance is claimed for this checkpoint.
- Independent read-only review found no demonstrated extraction regression.
  New owner/binding pass strict mypy and Ruff; applicable format/syntax checks,
  19 checker tests, 1242-file ratchet, Git whitespace and UTF-8/no-BOM checks pass.
  No baseline changes. The other control functions remain cloned; R1-R9 and
  deferred deployment/restart gates remain open.

### Native operator/node authentication completion (2026-09-25)

- server_collection_console now owns AuthCompletion with explicit typed ports;
  auth_completion_binding reads live facade callbacks/runtime at invocation time.
  Removed console from the FunctionType cloning set and published the same bound
  method to server/context. Three core and five handler cloning sources remain.
- Preserved generation/target validation, lock ordering, write-ahead cleanup,
  scoped/legacy rollback, receipt replay and healthy-cookie two-phase completion.
  Seed-specific target comparison remains in the Taobao adapter, injected at
  composition. Invalid targets are passed unchanged to its existing validator.
- Baseline before and after migration: 41 tests passed. Added five cases proving
  native method identity, saved callback/runtime replacement and malformed target
  rejection before scheduling. Final focused group: 46 passed, runner 4.16 s.
- Affected suite: 304 passed, pytest 104.91 s, runner 105.86 s, isolated runtime
  crow-quality-okubmo8v. Covers scoped/legacy/mixed process exits and retries,
  real-thread generation races, cleanup failure compensation, HTTP guards,
  source contracts and native imports (including two new fresh-process probes).
  Process-exit proof is not power-loss or installed-runtime acceptance.
- Independent read-only review found no demonstrated migration regression.
  Three native files pass strict mypy; changed owners/binding/contracts/tests pass
  Ruff and format. Checker tests: 19 passed; ratchet: 1240 files, no above-500 tier,
  unchanged baseline. Git whitespace and UTF-8/no-BOM checks passed.
- No new full fast/security run was needed after the affected slice. The earlier
  31.20-second fast pass predates this migration and does not validate this newer
  state. R1-R9 remain incomplete; deployment/restarts remain deferred.

### Optional phase timing and a completed fast checkpoint (2026-09-25)

- Added --timing-report to the isolated quality runner. The opt-in pytest plugin
  records collection/test-loop wall time, setup/call/teardown sums and counts,
  per-file totals and bounded atomic checkpoints. It excludes parameter IDs,
  captured output, assertion payloads and environment values. Default runs do not
  load the plugin; inherited report paths are removed from child environments.
- Reports distinguish incomplete stages from a finished pytest session. Their
  exit_status is pytest's status; the parent runner remains authoritative for the
  unchanged 60-second fast gate and 180-second execution limit. Diagnostic overhead
  is included in elapsed time, never subtracted.
- Six isolated integration cases passed: success, failure and abrupt os._exit(7),
  each with timing enabled/disabled. They preserve explicit-only collection and
  business-DB isolation, failure exit codes, accurate final counts, incomplete
  crash checkpoints and absence of assertion payloads in reports.
- The initial diagnostic attempt left an incomplete 500-test checkpoint; its
  execution handle disappeared and no matching process remained. No terminal
  status was recovered, so it is not gate acceptance. Collection was 23.03 s and
  native-import phases were 22.68 s at that checkpoint.
- Completed diagnostic fast on the final timing implementation: 881 passed,
  2 skipped, pytest 29.89 s, parent runner 31.20 s, exit 0. Collection 5.36 s;
  test loop 24.47 s; setup/call/teardown sums 4.09/18.26/1.50 s. Native-import
  phases totaled 2.98 s. Artifacts: artifacts/fast-phase-timing.json and .log.
  Storage was isolated at crow-quality-x_i1reht with business DB access disabled.
- This is one passing fast checkpoint, not evidence that diagnostic code fixed
  the earlier 92.00-second run. Timing variability remains unexplained. No unchanged
  broad suite was rerun to manufacture another pass. Security, other R7 work and
  R1-R9 overall completion remain open; deployment/restarts remain deferred.
- Ruff and format passed for the three changed Python files; checker self-tests
  passed 19 cases; ratchet passed 1237 files with no above-500 tier and unchanged
  baseline. Git whitespace and UTF-8/no-BOM checks passed.

### Fast gate profiling and equivalent probe scheduling (2026-09-25)

- Investigated the preceding 70.77-second fast failure without raising its limit.
  cProfile on the isolated source-contract group found 1209 delegated-source
  traversals, repeated whole-file splitting per extracted function, and duplicated
  full AST walks in asserted-code discovery. Profile artifacts are
  artifacts/source-contract-profile.prof and source-contract-profile-after.prof.
- Source extraction now indexes UTF-8 lines once per source file. AST node tuples
  cache by complete source text, so changed input is parsed afresh. Asserted-code
  discovery walks the outer tree once while retaining nested assertion scans.
  Three new cases compare extraction directly with ast.get_source_segment for
  Unicode byte offsets, CRLF, multiple statements and nested functions.
- Control-import tests still launch 22 independent Python processes; bootstrap
  path tests still launch four independent processes with their original matrix.
  Each has a private working directory and original 20-second timeout. Module
  fixtures schedule at most four probes concurrently while preserving each
  parametrized test and original success/no-created-state assertions. No shared
  interpreter import cache or removed coverage is used for speed.
- Diagnostic source group: 14 passed before and after; cProfile runner timing
  18.19 s before, 7.01 s after. Instrumentation changes timing and cannot establish
  gate acceptance. Focused source/import: 96 passed (runner 22.03 s). After adding
  extraction equivalence cases, final source group: 17 passed (runner 10.05 s).
- Independent review found no demonstrated coverage/isolation loss in this
  scoped change. Ruff/format passed; checker tests: 19 passed; ratchet: 1236 files,
  no above-500 tier, baseline unchanged. Git whitespace and UTF-8 checks passed.
- Formal fast rerun after changes: 877 passed, 2 skipped (pytest 88.65 s, runner
  92.00 s), exit 1: unchanged 60-second gate exceeded. This is NOT full-suite
  performance acceptance, and the new whole-suite duration is worse than the prior
  result despite cheaper profiled helpers. Collection/startup/test phase attribution
  is still needed; do not blindly rerun or claim the failure is merely environmental.
  Full security's earlier 180-second timeout, R1-R9 completion and deployment remain open.

### Cookie facade exits function cloning; fast timing remains open (2026-09-25)

- Migrated all 19 remaining server_auth_cookie exports into AuthCookieSnapshot,
  AuthCookiePaths and SolverCaptchaReports, composed by auth_cookie_binding with
  live runtime/environment/clock/callback providers. Removed server_auth_cookie
  from _CORE_MODULES. Native owners publish identical bound methods to server
  and context; report, path and refresh/state code no longer needs shared globals.
- Preserved configured-path precedence, node/path containment, candidate roots,
  CDP permission checks, healthy-only writes, blocked-report epoch/max attempts,
  persist-before-pause ordering and existing error envelopes. New tests cover
  native/context identity, saved callback/runtime replacement, endpoint rejection
  before export and blocked-report persistence failure. Four import-isolation
  cases added. Independent review found no demonstrated migration regression.
- Initial affected group: 159 passed (runner 16.61 s). Final focused cookie/report/
  path/status/retry/scheduler/runtime/export/startup/NAS group: 201 passed (pytest
  17.68 s, runner 19.22 s). Separate source-contract/native-import group: 96 passed
  (pytest 26.85 s, runner 29.28 s). Official isolated storage in each run.
- Four native modules passed strict mypy and full Ruff/format; changed tests also
  passed Ruff/format, and server passed syntax/bug rules excluding inherited F821.
  Checker self-tests: 19 passed. Initial ratchet failed because server.py reached
  501 effective lines; combined the two native-owner publication loops, preserving
  lazy callbacks, then ratchet passed: 1236 files, no above-500 tier. No baseline
  changes or exceptions were introduced.
- After the publication-loop adjustment, ran milestone fast once, serially:
  874 passed, 2 skipped (pytest 68.60 s, runner 70.77 s). Command exit 1 because
  the unchanged 60-second gate was exceeded. This is a FAILED timing gate despite
  passing executed tests. No full fast acceptance is claimed. Diagnose R7 timing
  before repeating it. Full security remains open after its earlier 180-second
  timeout; neither timeout nor skipped tests were waived.
- Remaining R1 server owners are collection control/console/operations/data plus
  five handler modules; other cloning/tool facades and R2-R9 also remain. Deployment
  and application restarts remain deferred until the code plan is complete.

### Manual retry monitoring exits function cloning (2026-09-25)

- Added SolverRetryMonitor with explicit runtime, clock, policy and effect
  dependencies, composed by solver_retry_monitor_binding. Server publishes its
  three bound entrypoints into both facade and context. Removed their previous
  server_auth_cookie definitions/exports; that module retains 19 other exports.
- Preserved nonblocking retry locking, release in finally, operator-pause guard,
  state comparison after CDP probe, unhealthy cooldown, PC2 delegation, scoped
  pause cleanup and restoration after submit failure or a rejected default submit.
  An explicitly injected submit callback returning False retains its prior meaning.
- Added regression checks for saved entrypoints seeing current runtime/callbacks,
  native owner/context identity, probe-time state changes, submit error/default
  False/custom False behavior and exception-time lock release. Added standalone
  import checks for owner and binding to the startup recovery test group.
- Initial status/concurrency/export group: 101 passed (runner 18.00 s). Final
  retry/status/concurrency/export/startup/mixed-pause group: 165 passed (pytest
  14.97 s, runner 16.64 s), official isolated storage. These are scoped checkpoints.
- Both native modules passed strict mypy; native/test Ruff and formatting passed.
  Changed server/cookie facade passed syntax/bug checks (inherited F821 excluded).
  Checker self-tests: 19 passed. Ratchet passed with baseline unchanged.
- Report/path/refresh-state ownership still prevents retiring server_auth_cookie;
  remaining R1 owners and R2-R9 continue. No broad fast/security rerun or deployment;
  earlier full security timeout is still an open milestone acceptance gate.

### Cookie health uses native source adapters (2026-09-25)

- Added src/auth_cookie_health.py for per-sample probe aggregation and native
  collection/adapters/taobao_health.py / taobao_list_probe.py for source-specific
  classification, redaction, payload parsing, cookie sessions and navigation.
  Tool facades re-export these functions and constants; source no longer imports
  tool implementations. server_auth_cookie now contains no tools imports.
- Preserved healthy-only snapshot promotion, CDP user-agent propagation, shared
  session per probe batch, 15-second per-sample timeout, classification precedence,
  Chinese challenge/login markers, safe snippets and per-sample error envelopes.
  The existing user-agent test now injects the native owner rather than tools.
  New tests prove standalone import isolation, sample failure isolation and native
  tool export identity. Independent read-only review found no concrete regression.
- Before final constant ownership cleanup, 237 affected tests passed (runner
  37.17 s). Final native/browserless/health/API/stage/PC1-handoff/redirect/parser/
  cookie-retry/scheduler group: 257 passed (pytest 39.04 s, runner 41.70 s), using
  isolated storage. These results are separate checkpoints, not a full-suite pass.
- Three native modules passed strict mypy with ephemeral types-requests,
  websocket-client and playwright tool dependencies. Native/test Ruff and format
  passed; changed legacy modules/tests passed syntax/bug checks excluding inherited
  F821. Checker self-tests: 19 passed; ratchet: 1229 files, no above-500 tier,
  baseline unchanged. No business database, browser, deployment or restart action.
- Remaining: retire server_auth_cookie cloning through explicit retry/report/path/
  state dependencies, then continue the other R1 owners and R2-R9. Full security
  remains open after its previous unchanged 180-second timeout; full fast was not
  repeated. Health native ownership does not complete the overall plan.

### CDP cookie transport exits tool-owned function cloning (2026-09-25)

- Added src/cdp_cookie_transport.py as the native transport owner. It owns raw
  websocket cookie export, lazy Playwright fallback, retry/health behavior,
  endpoint discovery, websocket rewriting/cache and user-agent lookup. Runtime
  cookie export now calls it directly. Tool context imports shared constants;
  all 14 former transport exports bypass cloning. Explicit partial bindings keep
  saved tool entrypoints observing later transport/Playwright replacements.
- Preserved websocket-first fallback order, bounded retry/backoff, trust_env=False,
  connect/probe timeouts, read-only cache tolerance and existing origin filtering.
  Cache read catches are limited to OSError/ValueError (including invalid UTF-8);
  broad transport fallback catches remain explicit compatibility boundaries, with
  local explanatory lint annotations. This is not a full R9 exception audit.
- Added regressions for native import isolation without tools/server/Playwright,
  socket cleanup on malformed responses, invalid cache documents and saved facade
  entrypoints observing replacement. Independent read-only review found no concrete
  migration regression; it did not substitute for runtime test execution.
- Initial transport/browserless/API/metadata/storage group: 136 passed (runner
  12.97 s). Final transport/browserless/API/health/handoff/retry/scheduler group:
  218 passed (pytest 17.15 s, runner 18.53 s), official isolated storage, no live
  browser or business database mutation. These are separate scoped results.
- Strict mypy passed for native owner and tool binding using ephemeral uv tool
  dependencies types-requests, websocket-client and playwright. Native/binding/test
  Ruff and formatting passed; changed legacy facade/context/server passed syntax
  and bug checks (inherited F821 excluded). Checker self-tests: 19 passed.
- Health orchestration and server_auth_cookie cloning remain open, as do the
  larger R1 inventory and R2-R9. Full security remains unaccepted following its
  earlier unchanged 180-second timeout. No broad fast/security rerun or deployment.

### Cookie metadata exits tool-owned function cloning (2026-09-25)

- Added src/cookie_snapshot_metadata.py with typed summary fields and explicit
  standard-library dependencies. Moved expiry normalization, both fingerprints,
  cookie keys, summaries and comparisons. The tool cookie slice is now an export
  list; all eight public functions reference native owners. Runtime summaries
  no longer import tools. CLI names and return fields remain compatible.
- Preserved local-time formatting, milliseconds/seconds handling, list ordering
  normalization, session-cookie classification and value-safe reports. Added
  regressions for numeric/text expiry, invalid/session expiry, one-shot iterators,
  reordered inputs, safe output and actual native export identity.
- Focused metadata/browserless/collection-status/Taobao-health group: 203 passed
  (pytest 17.13 s, runner 19.44 s). After lint-only f-string/import/export-order
  cleanup, metadata/browserless: 43 passed (pytest 3.42 s, runner 5.02 s).
  Both used the isolated official runner; no business data was modified.
- Final native strict mypy, changed native/tool/test Ruff and formatting, legacy
  server syntax/bug rules (inherited F821 excluded), 19 checker self-tests and
  ratchet passed. Ratchet: 1223 files, no above-500 tier, baseline unchanged.
- This completes metadata ownership only. CDP transport, health probes and the
  server_auth_cookie native-owner migration remain R1 work; R2-R9 remain open.
  Full security still lacks completion after its earlier 180-second timeout.
  No broad fast/security rerun, deployment or application restart in this slice.

### Cookie snapshot storage moves into the runtime (2026-09-25)

- Added src/cookie_snapshot_storage.py as the shared atomic persistence owner.
  Server refresh writes now depend directly on this module. Existing browserless
  tool read/write exports retain their names and reference the native functions
  without cloning; summaries and transport are still tool-owned.
- Preserved same-directory staging, UTF-8 JSON, fsync, atomic replacement,
  failure cleanup, private temporary-file permissions and loader ValueError.
  New regressions cover serialization/fsync failures preserving existing bytes
  and removing temporary files, invalid documents and native export identity.
- Before changes: 47 runtime-safety/browserless tests passed (runner 4.01 s).
  After changes: 155 storage/runtime-safety/browserless/collection-status/cookie
  retry/cookie scheduler tests passed (pytest 9.53 s, runner 11.25 s), using the
  official isolated-storage runner with business database access disabled.
- Strict mypy passed for the native owner; new-file Ruff and formatting passed.
  Changed legacy modules passed syntax/bug rules (inherited F821 excluded).
  Checker self-tests: 19 passed; ratchet: 1221 files, no above-500 tier, baseline
  unchanged. Diff whitespace and all four edited Python files' UTF-8/no-BOM
  checks passed. HEAD remains f2d735ab20e60c1dce212dd86dd2b15fd22a8c40;
  worktree contains inherited changes (244 entries at this checkpoint).
- R1 remains open: cookie summary/export/health/retry ownership and the remaining
  facade inventory still need migration. R2-R9 remain open. Earlier full security
  exceeded its unchanged 180-second limit; no full security/fast acceptance is
  claimed here. Deployment and restarts remain deferred until code tasks finish.

### Authentication recovery exits function cloning (2026-09-25)

Removed server_auth_recovery from _CORE_MODULES and published its 18 facade
entrypoints from three native owners: SolverStatusReader, SolverAuthHistory and
AuthRecovery. auth_recovery_binding composes current runtime, repository,
coordinator, token reader, clocks, grace configuration and source-target policies.
Status aggregation, legacy receipt reading, challenge identity, reset/auth/detail
progress grace, NAS sampling/authorization/results and watchdog scheduling now
have explicit dependencies. Stage challenge/target validation and pause cleanup
remain under the original transaction locks; constant-time token comparison,
operator-pause precedence and public result envelopes are unchanged.

Replaced the test's obsolete module-global repository patch with an independent
native owner and a retained live facade reader. Added watchdog error-continuation
proof with replaced sample/poll providers, native publication identity assertions
for every migrated entrypoint, and no-server-bootstrap imports for all four native
modules. A read-only independent review found no demonstrated behavior regression.

Validation at inherited HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus dirty
worktree, official isolated storage, business DB disabled:

- Pre-change NAS API/stage/target/progress baseline: 39 passed, runner 6.97 s.
- Final NAS API/stage/target/progress, owner bindings, native imports, collection
  status, report-stage isolation, scoped restart, guard ownership and logging:
  179 passed, pytest 14.72 s, runner 16.30 s.
- Final source-route contracts and server bootstrap/import contracts: 96 passed,
  pytest 28.06 s, runner 29.67 s.
- Four native modules pass strict mypy with follow-imports=silent. Native/tests
  Ruff and formatting, selected facade syntax/bug rules excluding legacy F821,
  19 checker self-tests and ratchet pass: 1219 files, no above-500 tier and no
  baseline/policy changes. Final diff and UTF-8/no-BOM checks pass.
- Full security milestone was attempted once and failed the runner's unchanged
  180-second execution limit. It has no completed suite result and is not counted
  as passing. The focused groups above do not substitute for this open gate.

Full fast was not repeated; its earlier dispatch checkpoint does not establish a
pass for the current source. PostgreSQL, desktop/package, deployment and actual
multi-machine behavior remain unverified here. Five core and five handler cloning
sources remain; next migrate server_auth_cookie's retry monitor, then the remaining
collection/data handlers. R1-R9 remain incomplete. No deployment, restart,
business-data change, commit or push occurred.
