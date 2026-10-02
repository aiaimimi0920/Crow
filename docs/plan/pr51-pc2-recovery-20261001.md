# PR #51 PC2 恢复与运行验收

本文接续 `pr51-naming-verification-20261001.md`，前文是上一阶段快照，不代表最终部署状态。

## 修复依据与范围

- seed 停滞时取得真实 Python 栈：`seed_scan_candidates` → SQLAlchemy → psycopg `cursor.execute` / `connection.wait`。NAS 同时没有长时间执行或阻塞查询；PC2 旧连接长时间无收发。最后的 `captcha_solver_running` 日志不是足够的根因证据。
- PostgreSQL 连接新增 `pool_pre_ping` 和 libpq dead-peer 检测默认值：connect timeout 10 秒、keepalive 30/10/3、TCP user timeout 60 秒。显式 URL 参数优先，不更改数据库名、事务，不自动重放 SQL；这不是任意查询的总时限。
- controller 的 `SettingsRuntime.snapshot()` 因实际镜像/环境与 `active.json` 不一致而在 poll 前拒绝继续。保留漂移门禁，部署时对真实配置做私有快照和核对，而非放宽检查；错误日志增加不含凭据的分类。
- 旧 browser 镜像以 root 运行，新版 launcher 拒绝 root。非 root Chromium 又被默认 seccomp/AppArmor 阻止建立 sandbox。新增仅 browser 使用的受限策略，不使用 privileged、SYS_ADMIN、unconfined 或 `--no-sandbox`。
- syscall 基础目录固定到 Moby commit `2ceae35d351c156cb5a8efc0fdc4a08cf94569d8`。仅 native x86_64，拒绝兼容 ABI 旁路及 setns；clone/unshare 按 flags 限制，socket domain 限定，clone3 返回 ENOSYS。
- AppArmor 保留 mount、proc/sys 保护，仅补 userns。profile 名称由模板摘要派生，新旧并存，避免同名 reload 改变旧容器而破坏回滚。该摘要不包含宿主 include 展开结果。
- 非 root 浏览器首次切换遇到共享 X11 的 root-owned `X99` socket，旧 launcher 删除它时报 `Operation not permitted`。新 launcher 在最多 64 个显示编号内选择未占用编号，不删除已有 socket、lock 或断链符号链接；保留 host-display 分支。
- 既有认证 token 为 root:root、0600，非 root 浏览器读取报 `PermissionError`。仅通过 ACL 给 UID 1000 增加只读权限；内容摘要、owner 均保持不变，未放宽为全局可读，原 ACL 留作回滚。
- AI 模型池续期顺序存在饥饿：实际目录 219 个候选，曾通过 5/5 的显式首选因到期被排在第 77 位，前方 76 个未测别名不断遇错退避。修复后先按显式配置顺序重新测试，再续期曾合格模型，其余仍先探测未测模型；保留五例评分、4 分阈值、TTL、单模型冷却、账号冷却、并发租约及限速，不清空池或伪造分数。

## 分阶段验证

以下不是同一工作区时点的一次全量运行：

| 范围 | 结果与边界 |
| --- | --- |
| PostgreSQL 连接策略、真实 socket 参数及并发认领 | 16 passed；隔离 loopback `crow_quality`，只终止测试自身 backend |
| controller 诊断、watchdog、连接策略 | 43 passed |
| 首次恢复版 Linux fast | 1701 passed、35 skipped；61.21 秒，**时间门槛失败** |
| 修正后的 core/controller Linux fast | 1706 passed、35 skipped；50.38 秒，通过 60 秒门槛；早于 sandbox 策略新增 |
| sandbox、回滚、shell focused | 11 passed |
| 新增策略后的 Linux security | 777 passed、18 skipped；66.10 秒；早于最后 profile 内容寻址小改 |
| 内容寻址修复后的 profile/rollback focused | Linux 8 passed；Windows profile 5 passed |
| 最终有效行数 checker | 19 passed；ratchet 1453 files，所有超过 500 行档位为 0 |
| 最终相关 Ruff、git diff --check | 通过 |
| X11 修复后的相邻边界 | Linux 57 passed；非 root Xvfb/Chromium 实机隔离夹具选择 `:100`，root-owned X99 哨兵保持不变 |
| 模型池续期 focused 与相邻边界 | 79 passed，覆盖续期优先级、资格过期、单模型冷却、跨进程限速、账号退避与取消 |
| 续期候选 Linux llm | 271 passed；pytest session 5.91 秒 |
| 续期候选 Linux fast | 1727 passed、35 skipped；pytest session 45.87 秒，runner 通过后才启动 security |
| 续期候选 Linux security | 787 passed、18 skipped；pytest session 55.52 秒，exit_status=0 |
| 当前有效行数 checker | 19 passed；ratchet 1455 files，所有超过 500 行档位为 0 |
| 当前源码与密钥检查 | 1342 文件与隔离 `/workspace` 摘要一致；18,751 文件公开快照 gitleaks v8.30.1 未发现泄漏；修改文本 UTF-8 无 BOM |

续期门禁曾误在不完整的 `/app` 目录运行，因缺失测试依赖/静态文件失败，不计作通过。最终是在无生产挂载的完整 `/workspace` 源码运行；以上 llm、fast、security 是相同产品源码时点的结果，没有调用真实模型或生产数据库。当前扩大 Ruff 核验时，两个既有测试文件的 `I001` 在 HEAD 原文件中亦可复现；未将它们写成通过，其余 21 个修改/新增 Python 文件通过。

隔离 browser 使用 network none、无生产挂载；实测非 root、CapEff/CapBnd 为零、NoNewPrivs=1、AppArmor enforce。renderer 与 browser 的 user/PID/net namespace 不同，renderer 多一层 seccomp filter；外层 mount/chroot/AF_ALG/AF_VSOCK 负向探针拒绝。此结论不等于移除了原有 X socket、DRI 等业务挂载。

## 部署与回滚

首次 exact-ID 候选未通过 browser 健康检查，已完整回滚；未把失败候选投入服务。历史同 Compose labels 的容器均保留，未执行 service-wide recreate 或 remove-orphans。

最终候选源码摘要：`724d7ece9477dcec52e0d81ce0572652b0752618165eefa1ef756aabf2a8ea47`，1339 个源码文件，镜像导入与连接策略预检通过。最终激活过程的私有配置、旧容器清单、浏览器 profile/state 备份位于 PC2 `shared/collection-control/deploy-pr51-recovery-final-20261001`。只对这两个数据目录内 UID 0 条目迁移 owner，保留 Cookie、Local State、Preferences 内容摘要验证；不清空 profile 或数据库。

NAS 已激活 DB/controller 修复镜像 `sha256:1a2190f251cdb649f7021d88d30f57232b1d74bbfbae4b084aaa56015a224d14`，canonical `crow-api` ID 为 `7cc7dc16e831126ca2fb66c611aa5f1cd4bc730b64feec4c28cba4f67a78c6c0`。原数据库和挂载保留，旧容器 `crow-api-before-pr51-recovery-20261001` 留作回滚。PC2-only sandbox 改动不需要无意义重启 NAS。

本机桌面本轮没有新的 EXE 或 bundle helper 变更，继续使用上一阶段验证并安装的版本。

## PC2 已验证激活状态

- X11 修复版已 exact-ID 激活全部 9 个容器：browser、1 个 seed、3 个 detail、4 个 AI。browser 镜像为 `sha256:9d12cb68179326b50c46e678f705a65faf0084a109c2a7b168d438b556bc537d`，seed/detail 镜像为 `sha256:67e318f1c2a0765099028699cb2ee3f3cd7c7b1911f063f8c53b1c4577db3811`。
- 本次仅再次切换 4 个 AI worker 到续期修复镜像 `sha256:fd59e5a1a78c82b4c1b26b1194914208d6606681b359ea5c5d0bcd4308418269`，源码摘要 `b899381735ac7505d12b2a3321a68f07b92a4c0b90997f5c49b04449a7b30b1f`。其余 5 个正式容器未重建或重启。
- 2026-10-01 05:59 UTC 核验：9 个正式容器全部 running/healthy、RestartCount=0；controller active/running，WorkingDirectory 为已验证 staging。设置与运行环境一致，原业务配置及挂载保持不变。
- staging 1342 文件、4 个 AI 容器各 1342 文件，以及其余 5 个容器各 1341 文件，按各自实际发布清单核验，missing/mismatched 均为空；没有把不同镜像的摘要混为同一版本。
- 旧 9 个容器及本次旧 4 个 AI 容器保留、停止并设置 restart=no。X11 切换记录在 `shared/collection-control/deploy-pr51-xvfb-20261001`；本次 AI 切换、私有配置、旧源文件及 SQLite 在线备份在 `shared/collection-control/deploy-pr51-renewal-20261001`。
- 浏览器完整状态备份为 3,372,636,160 bytes，第二次切换保留增量链；本次只更新 AI，不再次搬动浏览器 profile、Cookie、认证文件或数据库。

## 业务验收与提交门槛

05:59 UTC 实际 HTTPS 状态为 captured_count=164533、seed_occurrence_total=1308599，均较 04:04 UTC 的 164325、1308441 增长；AI finalized 暂停在 121796，不能把容器健康表述为全链路恢复。

本次保留共享冷却等待自然到期，并取得 21 次只读观察。06:34 UTC，captured_count 从本次观察起点的 164544 增至 164618（+74），AI finalized 仍为 121796（+0）；因此 AI 业务验收明确未通过。06:26 UTC 的运行网关日志确认：`/v1/models` 为 200，首选部分 chat 为 200，但 deepseek-v4-flash/pro/vision 的实际路由出现 `403 insufficient_user_quota`，其他路由出现 `503 model_availability_filtered`。资格续期尚未完成完整五例，也没有把过期 5/5 分数作为当前通过。账号冷却再次生效，不应清空它或反复重发请求来制造验收通过。

等待期间 seed 出现新验证码挑战，随后现有认证链路正常完成；06:32 UTC 核验时 seed/detail 的 paused 均为 false、auth recovery active=null、last_result=succeeded。06:37–06:38 UTC 末次核验又出现新的 detail 验证码挑战：seed 仍为 idle/unpaused，detail 为 running/paused，挑战年龄约 257 秒。因此不声称持续无人值守全链路已通过。没有人工清除暂停、绕过认证、重启 PC1 人工认证浏览器或修改其 profile。

运行证据位于 PC2 `releases/pr51-20261001/ai-recovery-observation.jsonl`、`ai-recovery-receipt.json`；脱敏网关额度证据仅保存到本机 `linshi/crow-pr51-20261001/resume-20261001/gateway-quota-evidence.json`，不纳入 Git。本次只读观察进程已停止，生产 worker、配置与冷却保留；没有新增人工 chat 请求、充值、修改 CPA 路由或凭据。

**06:38 UTC 的历史停点：提交门槛尚未达到，未提交、未推送。** 当时需要上游恢复足够额度或另行明确选择可用非 GPT 服务入口，再等待合法冷却到期，补齐完整资格续期和实际 AI finalized 增长。不以源码门禁替代业务验收。以下新增验收依据用户随后授权的临时 GPT 验证，不将前述失败观察改写为通过。

## 临时 GPT 真实归档验收

用户随后明确授权临时使用 `gpt-6.1-sol`、`reasoning_effort=low`，以完整归档流程验证作为提交条件，并要求推送前关闭 GPT。2026-10-01 06:58:03–06:59:10 UTC 完成一次有界验证，耗时 66.117 秒。

- 仓库没有正式 GPT opt-in 配置：`require_non_gpt_analysis_model()` 默认拒绝 GPT。验证仅在一次性 `docker exec` Python 进程内临时允许 exact `gpt-6.1-sol`，不改产品源码、镜像、Compose 环境、controller 设置或 CPA 配置；诊断脚本留在本机 `linshi`，不纳入 Git。
- 复用实际网关与凭据，先确认认证目录包含 exact model，再运行原有 `collection-exact-v2-evidence` 五例资格测试。五次真实请求全部 HTTP 200，精确评分 5/5、matches=`[1,1,1,1,1]`；未跳过评分、降低阈值或伪造结果。只将诊断候选限定为用户批准的模型，不向其他模型扩散。
- 资格 SQLite 使用独立诊断目录，不清空或修改正式 `/data/datas/model-pool/pool.sqlite3`，不解除非 GPT 路由的共享冷却。五例通过后，以正式 `run_detail_worker_batch()`、`analysis_only=true`、target_success=1、max_attempts=1 处理真实已采集记录，保留正常认领、租约及 `WorkerLifecycle` 释放路径。
- 记录 `665573465986` 有 1 条粗采发现 occurrence，原详情 HTML 来自正式 `detail_worker_3`，103205 bytes，源与分析 staging 的 SHA-256 均为 `792dd897253978216e731d3dcf3982fbbb54eacaabc7d7bb124b8ec76f7ee0a9`。没有使用合成 HTML、缓存 AI 答案或只做 tiny chat 验收。
- 第六次真实模型请求用于业务抽取，HTTP 200、非空响应 641 characters；生成 `extracted.json`（44 个规范化字段）、`final.json` 和 `selected.json`，worker 返回 `detail_analysis_completed`、attempts=1、completed=1。
- 使用新 repository/数据库连接复核提交：seed 为 `detail_completed`、租约已释放、商品 listing 存在，归档事件 ID=`1037684`、类型=`detail_analysis_completed`，事件保留原始 artifact 引用，final path 与 seed 一致。数据库 `seed_item_detail_completed` 从 121796 增至 121797。
- `finally` 已关闭进程内临时 GPT 许可，完整恢复原环境和模型策略；恢复后再次确认 GPT 被拒绝。后续独立只读检查确认诊断 heartbeat=`stopped`、进程已退出，4 个正式 AI worker 均仍为原续期镜像、healthy、RestartCount=0，模型=`deepseek-v4-flash`、reasoning_effort=`none`、正式模型池路径不变，均拒绝 GPT。
- 07:00:46 UTC 使用真实客户端 HTTPS/CA/凭据读取 NAS `/api/status`：ai_finalized_count=121797、captured_count=164685、seed_occurrence_total=1308699，seed/detail 均未暂停。07:02:39 UTC 复核全部 9 个正式容器 healthy、设置与运行环境一致、controller active/running/enabled、旧 9 个回滚容器保留；本机运行 EXE 的 SHA-256 与上一阶段安装记录一致，`Crow.lnk` 的 target、working directory、icon 均正确。本轮没有新的桌面或 NAS 构建，不作无关重启。

证据保存在 PC2 数据卷 `output/nodes/pc2/gpt-validation-pr51-20261001/receipt.json` 与 release `gpt-validation-restoration.json`；本机脱敏副本为 `linshi/crow-pr51-20261001/resume-20261001/gpt-validation-restoration.json`。原 HTML、商品 JSON、凭据、池文件与临时脚本不纳入 Git。

**结论：粗采发现 → 真实详情 HTML → AI 抽取 → 商品持久化 → seed finalized 的生产代码路径已闭环，满足用户更新后的提交条件；临时 GPT 已关闭。** 这不证明非 GPT 上游额度已经恢复，也不代表多模型 module B、长期网络稳定或持续无人值守挑战处理已完成验收。正式非 GPT worker 保留原配置与冷却，不为使数字继续增长而永久开启 GPT。

当前生产保留同 Compose labels 的回滚容器。后续部署/回滚必须沿用本次 exact-ID 路径；`ops/pc2-linux/deploy.sh` 的 service-wide `up`/`--remove-orphans` 入口不能直接用于当前生产状态。此次验证和提交收口没有调用这些入口、重建容器或重启应用。

## 网络与版本边界

PC2 内核曾记录 r8169/enp2s0 link down、速率重新协商和 CIFS 超时，探测出现丢包。offload 对照无改善，已恢复原值；没有更改 MTU、路由或重启机器。限速续传解决了部署包传输，但**不证明物理网络故障已修复**。仍需独立排查网线、端口或网卡链路。

本轮验收基于 PR #51 merge `7b2467ab38c8872d2c2847a967eb89499a47be8f` 加工作区修复。末次 fetch 发现远端已新增 #52/#53，`origin/master=a95734d29525eae4e59d05db77746f8781a8101e`；这些 86 个文件的安全改动不属于此前已完成的部署测试证据，不能合并后沿用原验收结论。
