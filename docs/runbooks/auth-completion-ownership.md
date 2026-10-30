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

## PC2 已受理刷新不重复短重试

认证完成 POST 返回 `ok=true`、`auth_state_confirmed=false`，且后台快照为 `pending/running`、尚未刷新，只有 response 与快照的 completion ID、scope 以及快照的 expected challenge ID 均匹配本次显式请求时，PC2 才结束本次短重试，将原响应交给既有 pending 控制器。它仍是未确认状态，不清暂停、不重置成功状态，不绕过最终 ACK 校验。

这样不再把同一已受理刷新连续发送的相同 POST 计成多次请求并抬高外层指数退避。外层退避公式、上限及实际请求次数计数不变；网络失败、其他请求/范围/代次、`busy/failed/completed` 但未确认的响应、未知字段和旧版无绑定调用保留原短重试策略。不增加后台健康检查、站点请求、请求次数上限或模型调用，也不改变最终认证证明。对应回归为 `tools/test/test_pc2_auth_refresh_pending.py`；mock 中的等待缩短不能代替真实网络时延或通过率验收。

## PC2 最终 ACK 的 scope 归属

显式 `seed/detail` 认证完成请求必须收到相同 scope 的最终 ACK，不能仅凭 completion ID 相同就消费另一 scope 或旧版 aggregate-only 响应。短重试发送端与 pending 消费端使用同一提交 scope；旧 pending 缺少 scope 时，仍按原目标 URL 推断并将同一结果用于确认。错误 scope 保留原 pending、失败次数、滑块预算与冷却，沿用现有请求次数和退避；相同 scope 已清除、另一 scope 仍暂停及幂等重放继续兼容，无 scope 的旧调用保留原模式。

此检查只补充客户端 scope 一致性，不替代服务端 challenge generation、目标、Cookie 健康检查及最终解锁事务。失败后新业务页恢复健康可以产生独立 completion，并不表示前一次拖动成功。对应离线回归为 `tools/test/test_pc2_auth_ack_scope.py`；不通过主动挑战或付费调用验收，也不将此安全修复当作站点接受率提升证明。

## 健康检查的 HTTP 会话归属

一次健康检查拥有一个 HTTP Session，批内样本复用该会话，整次检查结束后关闭。正常返回、探测失败、会话创建后的初始化异常和取消均执行释放；不关闭外部调用者的会话，也不改变认证判定、请求数量、超时或重试策略。资源释放修复不能代替健康证明，也不能据此认定历史认证失败的根因。

## detail 同商品重定向与健康请求预算

显式 detail 快照重试任务可以在原有 HTTP 请求额度内，跟随一次严格白名单内的同商品重定向：只接受两个现有详情域名的精确路径和同一商品 ID，HTTPS/443，无 query、fragment、userinfo 或歧义字符。裸 `?`、`#`、自跳、登录/挑战、其他商品、外域和私网字面地址均拒绝；不能把仅用于诊断的 `same_detail` 分类直接当作传输授权。query 的实际必要性尚未证实时保持拒绝，不重放挑战 token。

每跳均使用 `allow_redirects=False`，最多两次 GET，第二个响应仍为重定向时不继续。两个 GET 占用原快照任务的重试额度；三次额度不会扩成六次请求。额度在 transport 前消耗，异常也计数，停止后不新增下一跳；退避仍按 refresh 轮次计算，耗尽终态保留 `attempts=max_attempts`。预算只存在于当前同步工作线程的 ContextVar，退出和异常时恢复，不接受 payload 中伪造的预算，也不持久化；无上下文、旧调用和非 detail 保持一次请求行为。

第二跳使用原 15 秒探测预算的剩余整数秒，超时或晚到响应不构成认证证明；Requests 的 timeout 不是完整下载的硬墙钟截止。最终仍要求实际请求地址一致、同商品 2xx、ready marker 和无登录/挑战正文；详情成功不升级全局健康。诊断仅增加是否跟随和请求次数，不记录原始 Location 或 query。精确域名白名单不等于已实现 DNS 重绑定防护。回归：`test_auth_detail_redirect_policy.py`、`test_auth_detail_redirect_retry.py`、`test_auth_cookie_probe_budget.py`。

## Cookie 导出的 CDP 响应归属

原生 WebSocket 导出只接受本次 `Storage.getCookies` 请求的整数响应 ID；通知和其他 ID 的响应不代表导出成功。匹配响应包含 `error` 或缺少合法 Cookie 数组时抛出安全错误，进入原有备用导出/有限重连路径，不再默认为空 Cookie。明确返回 `cookies=[]` 仍是合法导出，但不构成认证健康证明。

接收过程共享原有 20 秒窗口，事件流不能反复重置等待预算；WebSocket 在正常返回、异常和取消时关闭。保留 Cookie 过滤范围、重连次数、健康校验及最终 ACK；错误不回显响应正文或 Cookie 值。离线回归为 `tools/test/test_cdp_cookie_response_identity.py`，不能据此断定历史滑块拒绝由导出故障引起。

## PC2 pending 回执超时的范围归属

pending 回执到达原有最大等待时间后，只有该回执所属 scope 仍明确暂停且要求认证，才交回挑战处理；另一 scope 的全局暂停不能清除该回执。显式 scope 优先，旧回执仅在缺少 scope 时使用其目标 URL 的范围提示。多 scope 状态缺少所属范围、格式异常或归属未知时保留回执，不猜选另一任务；旧版无 scope 集合的单范围状态保持兼容，但显式不同 scope 不可覆盖回执。

同范围的新 challenge generation 仍可在超时后接管；保留失败历史、冷却与滑块预算。未超时逻辑、最终 ACK 校验、请求次数及退避不变，不把 pending 或独立认证恢复算作本地求解成功。对应离线回归为 `tools/test/test_pc2_pending_auth_scope_timeout.py`。

### detail 健康检查耗尽后的等待释放

自动 detail challenge 的 `manual_required=false` 不表示认证已成功。超过现有 pending 最大等待时间后，若现代 scoped 状态、当前节点归属和 canonical detail 目标仍对应原 challenge，且同 completion/scope/challenge 的快照明确为 `failed`、`refreshed=false`、`retry_queued=false`、无下一次重试、尝试次数已耗尽、已请求 finalization，原因仅为 `cookie_snapshot_candidate_unhealthy`，PC2 才释放本地确认等待。当前失败快照可以缺少 `auth_state_confirmed`；显式成功或畸形值不能释放。全局人工暂停、操作员暂停、执行占用、人工/blocked 状态和未知归属保持保守。

释放只清本地 ACK 等待字段，不清服务端暂停、challenge、失败历史、滑块预算、冷却或 blocked-report 义务，也不提交新的认证请求。待处理 `force_reset_required` 保留并交回原控制链；后续重新读取状态、执行冷却/重置及执行前门禁。日志 `auth_confirmation_wait_released` 仅记录固定原因、scope、年龄和身份指纹，不记录目标 URL 或响应正文。这不是认证成功，也不表示该回执以后不可能由其他客户端更新。回归：`test_pc2_pending_unhealthy_release.py`、`test_pc2_pending_release_control.py`。

## PC2 失败后页面操作的请求归属

本地失败不代表原请求仍有权关闭或重新打开页面。带请求上下文的明确失败，在轮换、参考页浏览和人工升级之前重新读取一次控制面，按原 scope 核对 challenge generation、节点归属、目标身份及人工/重置保护；不能选择另一条活动 scope 顶替。已完成、换代、转交或状态不可读时保留页面，不执行这些失败后操作，也不据此宣告认证成功。

真实失败仍计入原有失败预算、重试间隔和冷却；原任务仍有效时维持现有轮换与升级规则。成功路径不增加查询；取消、截止时间、CDP/执行不确定结果仍走原保留页面路径，不额外读取状态。控制面读取使用现有 10 秒超时，不增加站点、模型调用或求解预算。该检查缩小失败收尾的陈旧状态窗口，不替代跨进程锁、服务端 ACK 或原有页面目标绑定。对应回归为 `tools/test/test_pc2_solver_failure_guard.py` 和 `tools/test/test_pc2_solver_failure_ownership.py`。

## 工作调度与稳定回执投影分离

某一已归属本节点的 scope 明确处于 `paused/manual_required/manual_only` 人工等待，且没有 blocked/reset、待确认回执或共享冷却义务时，不应仅因旧 challenge ID 被固定选中而阻塞另一 scope 的自动任务。初始工作仲裁可选择同节点、目标与 scope 一致、明确允许自动处理的任务；全局人工窗口、操作员暂停、NAS 执行、force unlock、未知状态及冷却/恢复 ACK 仍优先。

此选择不清除服务端人工等待、不操作其页面；切换只清理旧 generation 的本地 latch，保留共享失败次数、重试时间及冷却历史。执行前仍重新核对选中 challenge；认证回执和失败收尾继续绑定该 scope，不改用工作选择器。旧格式或字段不完整时保留原投影，不猜测可执行性。该修复减少跨 scope 的无谓等待，不增加求解预算，也不能作为站点接受率提升证明。回归：`test_pc2_solver_work_selection.py`、`test_pc2_solver_work_selection_loop.py`、`test_pc2_solver_work_dispatch.py`。

## PC2 显式操作员暂停

`paused=true, pause_reason=operator` 或严格布尔 `operator_paused=true` 阻止新的自动工作。轮询入口在页面整理、强制重置、scope 切换及探测前等待；探测期间刚发生的暂停仍由执行前 fresh guard 阻止启动。失败收尾先检查全局暂停，不能被 scoped 投影中缺少的同名字段擦除，不执行轮换、参考页浏览或人工升级，但真实失败仍计入原有失败预算和冷却。

普通 `captcha_solver/manual_required` 暂停、未知原因和缺少新字段的旧状态不因此被解释为操作员暂停；恢复后保留原任务、Cookie、重试时间和失败历史。既有 pending 回执优先级不变，本门禁不是对正在执行的子进程的即时取消或跨进程原子锁，也不授权解除服务端暂停。对应离线回归为 `test_pc2_solver_operator_pause.py`；不通过修改线上控制状态或触发挑战验证，不将此控制保护算作站点接受率提升。

## 挑战页去重的列表身份归属

seed 的常规挑战页去重只处理与当前请求类别路径、`location_code`、`st_param`、`auction_start_seg`、`page` 一致的重复页；不能以同属 seed 为由关闭其他列表任务。缺少身份参数的挑战页不能被推定属于带参数请求，反向也不能据此关闭完整身份页面。相同身份的挑战后缀、追踪参数差异仍允许去重，登录页、正常业务页和 detail 的既有隔离不变。

求解前选页和后台 scope 整理复用同一准入规则，不增加页面读取、导航、输入、超时或重试预算；这不是认证放宽，也不能据此认定历史站点拒绝的根因。对应离线回归为 `tools/test/test_captcha_seed_challenge_compaction.py`。

## scoped 人工标记与全局兼容镜像

`force_unlock_flag_exists` 保留文件存在性的旧语义，不表示已证明发生全局人工暂停。新状态字段 `global_manual_pause_active` 只有在 legacy 文件具有明确的 scoped mirror 来源、publication ID、challenge ID，且与 scoped 标记及 active/paused/manual-required 持久 receipt 的 scope、manual-only 策略和完整请求身份一致时，才返回 `false`。读取异常、发布不完整、换代、旧格式或未知来源均保守视为全局门禁，不自动改写或删除历史标记。

人工转移在同一 runtime 锁内捕获所属 scope 的请求并原子发布每份文件；已有真实或未知全局标记不会被 scoped 写入覆盖。新镜像的 `scope` 保留真实 owner，防止另一 scope 的完成清理将它误删。aggregate 仍保持暂停，所属 scope 仍等待人工，只有另一明确允许自动处理的 scope 不再被已证明的兼容镜像扩大暂停。PC2 只接受严格布尔 `false` 的新字段；旧 API、未知字段、操作员暂停、执行占用、归属、pending ACK、预算和冷却门禁不变。状态双读用于发现变化，不代替跨进程事务或执行前重新校验。回归：`test_solver_manual_mirror.py`、`test_solver_manual_pause.py` 和 `test_pc2_solver_work_selection*.py`。

## 回归入口

- `tools/test/test_auth_snapshot_request_ownership.py`：跨请求、跨 scope、跨 generation 的隔离，真实线程的完成发布/退出窗口，以及同请求缓存复用。
- `tools/test/test_auth_cookie_snapshot_scheduler.py`：single-flight、请求副本和启动边界。
- `tools/test/test_solver_scope_runtime.py`：状态发布、完成事务、幂等回执与新挑战并发。
- `tools/test/test_auth_cookie_health_resources.py`：健康检查自有会话的批内复用、正常/异常/取消释放及原有失败判定。

这些检查使用合成状态和隔离文件，不执行第三方验证码，不读取真实 Cookie 或浏览器 profile。
