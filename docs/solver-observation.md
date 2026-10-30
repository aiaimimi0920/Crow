# 24 小时自动求解只读观察

入口：`python -m tools.solver_observation --container <canonical-name> --output <private-directory> --source-revision <commit> --hours 24`。

在 PC2 Docker 主机运行；程序只读取 Docker inspect/logs 和容器内现有内部 `/status` GET。不要用 `live_slider_monitor.py` 代替：后者会导航、清理页面并主动求解。监测器不调用 solver、不写 Cookie、不点击/关闭页面、不修改冷却或轨迹。

## 统计口径

- `started/completed`：窗口内可观察的 solver 调用日志数，不等于唯一业务请求数。
- `automatic_local_success`：同一生命周期必须观察到 pyautogui 自动拖动、verified 阶段及 success=true；健康页面直接返回 true 不算自动解滑块。
- `automatic_auth_confirmations`：来源为 pc2_local_solver 的唯一 completion ID 确认数。
- `auth_confirmed`：还必须通过 target/challenge 与同一容器、同一 scope 的唯一已结束且 success=true 调用关联。认证恢复不一定发出 verified 阶段；该字段不要求滑块成功证据，也不将恢复算成自动解滑块。缺字段、错 scope 或有歧义时保留为 unlinked，不按时间接近猜配。
- `auth_confirmed_without_verified_drag`：已关联认证确认、但缺少完整自动拖动及 verified 证据的调用数，是 `auth_confirmed` 的子集。健康页面直接恢复或后续目标验证成功均可能走这条路径；不能据此推断上游滑块接受或优化因果。
- `bound_health_verified`：已关联确认携带对应 scope 的健康证明。详情页证明不升级为全站授权。
- `collection_delta`：全窗口业务计数变化；不能直接归因于某一次验证。
- `local_success_without_auth_confirmation`：有完整自动本地成功证据、但窗口内尚未关联到明确认证确认的调用数。不是求解失败数，也不表示运行实例当前仍在重试。

成功调用关联到首次认证确认时，`auth_confirmation_seconds` 记录本地结束至首次确认日志的耗时（包含后台验证、网络与客户端等待，不能单独解释为 HTTP 耗时）。重复 ACK 不覆盖首次 `auth_confirmed_at` 或拉长这个耗时；负时间差保留为未知，不伪造零耗时。

`auth_complete_retry_pending` 也纳入白名单观察。仅当 completion ID、容器、scope 与既有成功调用相匹配时，记录 `last_pending_snapshot_status`、`last_pending_snapshot_reason`；retry 还须明确来自自动调用。原因只保留已知枚举，例如 `cookie_snapshot_candidate_unhealthy`、`refresh_already_running`，其他值统一为 `other`，不保存原始正文或异常。这些是最后一次观察到的未确认诊断，不替代实时状态，也不改变求解、验证或重试行为。旧事件没有这些字段时保持未知，不能据此反推健康或失败。

认证日志通过 `auth_complete_result.request` 固定 ACK 清状态之前的请求身份；首次请求超时且响应没有 completion ID 时，也能用请求 ID 关联之后的确认。观察器仍须核对 completion ID、challenge、target、scope 和容器身份；旧版本日志缺少绑定时不能补猜成功。此处的脱敏承诺仅针对观察产物，原始运行日志仍可能包含业务 URL。

Linux 的 `slow_exact_v4`、`slow_settle_v4`、`slow_dense_v4` 保留各自 profile 名称，未知名称仍映射为 `other`。`solver_cooldown_started` 保留实际 `seconds`、`until`、`cycles`；旧版运行日志的 `seconds` 可能只表示基础冷却值，核查旧窗口应结合截止时间和持久状态，而不能据此认定指数退避未生效。

这些日志不独立证明每一次上游 `/slide` code=0，也不能排除同时发生的人工输入。保留该限制，不将应用上报偷换成无条件的站点通过率。

### NC 成功标记与活动挑战

可见的 `.nc-container.nc-success` 是已有的明确完成证据，不能再仅因其容器、内部轨道或包装层仍显示而把自己判为活动挑战。仅当该组件中没有可见操作柄和错误控件时，才排除这些完成后的容器节点；嵌套的未完成 NC 组件不能继承父组件的成功标记，其他组件和可见 iframe 仍可否决成功。隐藏的第一个容器不能遮蔽后面的可见完成组件。

这不把空白页、组件消失、通用 success 文案或 iframe 单独成功当作主页面成功。页面就绪、请求目标绑定、错误提示和活动控件约束不变；业务数据健康仍须独立核对结构和目标，不能用 NC 标记替代 `bound_health_verified` 或采集完成。对应回归为 `tools/test/test_captcha_nc_success_verification.py`。

### 可操作控件的候选筛选

滑块、轨道和重试控件查找不能只检查 `querySelector` 的第一个匹配：隐藏旧组件或尺寸不足的占位元素后面仍可能有有效控件。按既有 selector 优先级逐个检查候选，只接受可见且达到该入口原有尺寸要求的元素；固定定位不等于隐藏。查找滑块和轨道时不读取隐藏 iframe，重试控件继续使用同一可见性规则。保留主文档优先、单层同源 iframe、原坐标偏移、轨道回退及请求目标保护；不改变轨迹、重试预算或请求间隔。回归为 `tools/test/test_captcha_visible_target_selection.py`，这些离线反例不能直接认定为线上每次失败的原因。

祖先元素的 `opacity:0` 同样使子控件不可见，即使子元素自身的 computed opacity 为 1、尺寸正常且 offsetParent 不为空。该检查同时用于成功标记、活动挑战、滑块和重试候选；非零透明度不额外排除，也不以祖先的 visibility 代替子元素最终 computed visibility。回归为 `tools/test/test_captcha_ancestor_visibility.py`。

`verification` 诊断可携带 `error_text`、`error_widget` 两个布尔值，分别表示原整页错误关键词规则命中及可见 NC 错误控件命中；只保存来源，不保存文案。可见单层 iframe 的错误仍合并否决主文档成功，整页文字规则、目标和就绪检查没有放宽。旧日志无字段时保持未知，不能补成 false，也不能将这些布尔值解释为站点内部拒绝原因。

`challenge_failure` 的既有诊断在观察产物中保留 `code` 与严格布尔值 `retryable`，每次未完成调用只在报告的 `last_challenge_failure` 中保留最新一条及其时间。代码仅允许 `error:` 加 1—6 位 ASCII 数字、`none` 或 `other`；未知值归 `other`，缺字段保持缺失，不保存标题、路径、页面正文或令牌。调用结束、容器边界或 observer 重启边界之后的诊断不能覆盖之前调用。该元数据仅说明原运行逻辑报告了什么，不授权重试，不改变成功计数，也不能由 `retryable=true` 推断站点允许增加尝试。回归为 `tools/test/test_solver_challenge_failure_evidence.py`。

诊断字符串在生成源头也不再拼接不透明错误串、标题、class 或 URL，避免仅依赖求解子进程的后置过滤器。新增 `code_kind`（`absent/numeric/opaque/invalid`）、`ready_state`、严格布尔值 `target_ready/probe_failed`，全部复用已有摘要，不增加页面读取或请求。带后缀的 `error:300/…` 仍按 `other/opaque` 处理，不从不透明串中猜出数字错误码，更不能据此推断站点内部拒绝原因。旧格式日志继续可读，但缺失的新字段保持未知；报告重读旧事件文件时仍重新校验。回归为 `tools/test/test_captcha_failure_diagnostic_privacy.py`。这些字段不参与求解、认证、重试或成功计数。

`target_binding` 进一步复用预检、拖动后及 NC 点击前的已有摘要，分别标记 `preflight/post_drag/retry_preclick`。`binding` 仅区分请求或当前地址无法规范化、scope/路径变化、身份查询变化或相同；四个列表身份参数各自只记录缺失、相同、不同、双方不存在或未比较的枚举，不记录值、原始 URL、哈希或挑战令牌。使用原 `canonical_auth_target`，保留查询重复项与排序语义，不放宽输入或成功证明。`match` 只表示地址身份相同，不表示页面就绪、探测成功、认证或站点接受拖动；需结合原 `target_ready/probe_failed` 等状态判断。每次调用的 `target_binding_events` 最多保留 64 条，旧日志无字段时不补猜；报告重读事件时再次校验白名单。这也能区分在 `retry_preclick` 因身份不符拒绝输入与初次找不到滑块，既有失败原因和退避不变。回归为 `tools/test/test_captcha_target_binding_diagnostics.py`，不增加读取、点击、导航、等待或重试额度。发现阶段的无查询挑战跳转不等于业务身份已绑定，不能仅凭该差异归因失败。

成功轮询只在连续两次取得完整、目标绑定的 NC 重试状态时提前返回原重试策略：页面 complete、探测无失败、明确且可重试的错误、活动 NC 组件仍存在而滑块已消失、非登录页且未认证。任何不完整或过渡状态都会清零连续计数；普通错误文案、交互中页面、异目标或缺字段均保持原轮询预算。明确成功和已验证业务载荷仍优先；本地 mock、取消和截止保护不变。不增加拖动、重试或请求预算，也不把提前结束失败等待算成成功。回归为 `tools/test/test_captcha_verification_terminal_failure.py`。

拖动返回后，live 首次明确成功读取不再先等待固定的 1.8—2.4 秒；完整成功判据、目标绑定及可见 iframe 否决规则不变。首次未成功时仍在原 solve 预算内等待这段稳定期，再采集第一份失败或业务认证摘要，后续最多六次验证、五个原轮询间隔不变，不追加 CDP 读取或输入。本地 mock 原 0.15 秒前置等待保持不变。若明确成功仅在稳定期中出现且尚无业务认证载荷，需要下一个原验证槽才能确认，可能比原路径晚一个 0.6—1.1 秒间隔；单次检查不追加第二次读取。该优化仅加速立即已有充分成功证据的场景，不承诺所有场景都提速或长期通过率提高。回归为 `tools/test/test_captcha_verification_fastpath.py`。

明确的 WebSocket 关闭异常或严格的 `connected=False` 会终止该 socket 的后续 CDP 命令，不再消耗发送或请求 ID；验证轮询也不再对已关闭连接执行剩余等待。关闭标记只绑定当前 socket，新连接不继承旧故障；未知连接状态、普通超时、普通 `OSError` 和单次 `probeFailed` 仍保留原恢复窗口。沿用 `cdp_unavailable`、取消/截止优先、鼠标释放清理和恢复页保留，不增加重连、导航、输入或请求预算。回归为 `tools/test/test_captcha_cdp_closed_socket.py`；这修复的是已断连后的无效工作，不证明最初连接关闭的原因已消除，也不等于线上挑战通过率已经提高。

限定更新 browser-solver 时，单次 `polling`、没有输入 child 或自然冷却只证明瞬时状态，不证明后续 Cookie checkpoint、候选创建和停止之间持续安静。部署端应在既有操作锁与 detail 协作排空保护下，复用 `solver-manual-window.json` 的完整迭代边界 ACK；绑定当前 canonical 容器、已安装 gate 源码、本次唯一请求、真实 solver PID、相同到期时间及新鲜 `manual_window` 心跳，同时拒绝输入 child、pending 控制或非静止控制面。旧实例停止前须再次校验剩余窗口；新实例启动也须确认仍停在同一有界 gate。窗口最多 600 秒、不续租，只能释放自己的原始请求；失败不清冷却、计数、challenge 或他人窗口。`tools/pc2_solver_cutover_window.py` 提供部署端准入和所有权校验，回归为 `tools/test/test_pc2_solver_cutover_window.py`，不替代安装哈希、Cookie、持久退避与真实业务验收。

显式 seed 请求的选页必须与成功证明使用同一列表身份：类别路径、`location_code`、`st_param`、`auction_start_seg`、`page` 均不能仅因同属 seed 而替换。忽略既有非身份追踪参数及挑战后缀，复用匹配页；缓存 socket 也须核对当前页面目录，目录读取失败时只能使用已有绑定身份。请求页无法打开时，不再借后台标记、品牌标题或旧 scope 页面绕回错误目标；保留既有登录页人工处理及非 seed 兼容行为。不放宽成功证明或扩大求解预算。回归为 `tools/test/test_captcha_seed_target_binding.py`；离线错配反例不代表所有线上失败均由错配引起。

显式 detail 请求同样按既有 `canonical_auth_target` 的商品身份准入，不能因同属 detail 而复用另一商品页。缓存重连、目录筛选与后台/标题回退受相同约束，目录刷新后不得重新放入异商品页；忽略已有挑战后缀和追踪参数，兼容既有同商品规范化地址。detail 去重仅关闭同一商品的重复挑战，不关闭其他商品、seed 或登录页。没有匹配页且无法打开请求页时返回既有不可用状态，不读取异目标 DOM 或消耗拖动。成功证明、预算、取消、重试及冷却不变。回归为 `tools/test/test_captcha_detail_target_binding.py`；历史失败没有实际选页身份日志时，不能据此断言错配就是那次站点拒绝的原因。

去重后的目录刷新也必须重新核对缓存页的绑定身份：若该页已消失或跳到其他商品/列表，清除旧连接并继续原请求发现流程，不重连已失效的 socket；仍为同一身份时直接复用，不额外请求目录。该约束同时覆盖 seed 和 detail，目录读取失败时的既有已绑定缓存兼容行为保持不变。

CDP 目录入口须校验 HTTP 成功状态和对象数组结构，错误响应不等于有效空目录。失败沿用原有三次 I/O 尝试和取消/截止保护，耗尽后返回不可用；只有有效空数组才允许按原规则开页。已有绑定缓存仍可在目录不可用时复用，不因错误对象清除缓存或重复创建页面；日志不保存响应体。回归为 `tools/test/test_captcha_target_metadata.py`。

去重、容量整理或缓存连接失败后的目录重查同样区分不可用与有效空数组：重查不可用时结束本次发现，保留 `cdp_unavailable`，不继续使用整理前的目录，也不将失败当成空目录再开页。同时关闭仅属于 solver 的 socket，防止耗尽后的恢复分支继续经旧连接导航；不关闭页面或清除目标缓存。取消和截止原因优先；后续独立调用仍可重新发现，初次目录不可用时复用已绑定缓存的兼容路径不变。不增加目录重试、页面操作或求解预算。回归为 `tools/test/test_captcha_directory_refresh_failure.py`；这些离线故障注入不能证明线上加载停滞或挑战拒绝的根因。

开页返回有效 target ID 后先保留已创建页面的所有权记录，再检查取消和截止，停止后不继续连接、准备或导航。准备返回后同样检查停止，末轮的 `SolveStopped` 必须向外传播，不能被普通异常重试吞掉或作为成功开页返回；停止后的恢复页保留，发送导航前的普通准备失败仍复用同一页面及原三轮预算。回归为 `tools/test/test_captcha_target_open_recovery.py`，并覆盖真实 `solve()` 的停止原因、锁释放和恢复页保留；这不独立证明上游挑战通过率提升。

`Page.navigate` 已调用却没有确认时，不能推断导航未执行。此时立即结束本轮求解，保留该恢复页与所有权记录、关闭 solver socket，沿用 `cdp_unavailable` 退避，不再重发导航、进入其他求解分支或清理该页；取消与截止原因优先。不确定导航与 NC 输入的失败状态和 socket 清理必须在本轮锁释放前完成，避免影响同一 solver 的后续调用。后续独立求解须重新读取目录和页面状态，不能把失去确认的导航当作成功证明。健康导航、本地 mock 和发送导航前的连接重试不变。固定日志不包含 URL、页面内容或原始异常；回归为 `tools/test/test_captcha_target_navigation_uncertain.py`。该修复不证明页面/CDP 失响应的根因已经消除。

求解循环已找不到滑块时，`slider_missing` 诊断复用本轮已有摘要，只保留 `ready_state` 枚举及探测失败、目标就绪匹配、挑战、登录、硬拦截、明确错误、业务认证标志。未知就绪状态归为 `unknown`，观察产物只接受严格布尔值，不保存 URL、标题、页面文本或异常正文。沿用每阶段 64 条上限，不新增 DOM 探测、等待、开页或拖动，不改变失败原因及预算。`target_ready` 仅表示既有摘要的就绪及目标身份匹配，不能代替认证或自动成功证明；旧日志没有这些字段时保持未知。回归为 `tools/test/test_captcha_missing_slider_diagnostics.py`。

求解循环和 NC 重试后的无滑块分支沿用首次预检已有的加载宽限：只在 `readyState=loading` 且无滑块时，最多等待 8 秒、32 轮，并受同一次求解的截止时间和取消约束。加载后出现滑块时，只有就绪且目标匹配才额外读取一次位置，不能仅凭旧位置继续拖动；恢复的真实业务载荷仍由原目标绑定验证判定。持续加载、探测失败、空白页及其他目标不升级为成功；不增加拖动次数、重试额度或全局超时，本地 mock 保持原行为。回归为 `tools/test/test_captcha_solve_loading_transition.py`；离线恢复反例不独立证明站点已经接受自动拖动。

加载宽限内的摘要读取也共享该单调时钟截止：剩余时间约束同一次 CDP 发送和接收，不再为末轮读取另开完整 5 秒窗口；睡眠后窗口已耗尽则不发起读取，晚到结果不授权后续输入或认证成功。局部超时保留最后一份加载摘要，沿用 `challenge_loading`；窗口内真实探测失败仍是 `cdp_unavailable`，取消和整次求解截止优先。原命令时限只能缩短，socket timeout 随后恢复；不影响其他调用的默认时限，也不增加读取次数。这仅约束加载宽限，不是整个 preflight 或 solve 的 8 秒总上限。回归为 `tools/test/test_captcha_loading_probe_deadline.py`，不将离线越界修复表述为线上挑战通过率已提高。

验证失败后的 NC 重试返回未恢复时，同样必须重新读取页面摘要，不能用点击前的 `explicitFailure/retryableFailure` 直接判定耗尽。复用上述加载宽限及既有目标绑定证明：真实业务载荷恢复可结束调用；探测失败或仍加载分别保留 `cdp_unavailable`、`challenge_loading`；晚到且目标匹配的滑块只使用剩余的原重试额度，并在下一轮重新读取几何位置。空白页、异目标和未知状态不算通过，不额外导航或提高预算。只有本地 mock 或重试额度已耗尽时保留原路径；新回归为 `tools/test/test_captcha_failed_retry_transition.py`。这些离线状态转换反例不能证明某次线上 `target_unavailable` 实际是认证成功。

首次预检中的即时 NC 重试也必须在返回未恢复后重新读取摘要，并复用原加载宽限；仍加载、探测失败或已取消时，不再进入登录等待或另一轮重试点击。硬拦截等待结束后的新加载文档同样不授权点击。预检明确返回 `retryable_failure` 时，外层 `solve()` 结束本轮并保留原原因，不继续调用 headed fallback、重连、找滑块、刷新或恢复导航；普通未连接且没有该标志的结果仍保留原重连合同。取消和截止时间沿用同一次求解预算，不增加重试、请求或等待上限。回归为 `tools/test/test_captcha_preflight_defer.py`；这是控制流反例修复，不能据此认定某次线上失败已恢复或通过率已提高。

NC 重试后的连续三次稳定滑块样本，还须逐次核对当前摘要已就绪且与显式 seed/detail 请求身份匹配。列表地区、分页等身份参数丢失、跳到其他商品、跨 scope 或身份不完整时，返回不确定结果，停止本次重试候选点击，不再把稳定坐标当作原请求的恢复证明。沿用已有 `ready_target_matches`：正确目标的 `interactive` 和 `complete` 均可继续，加载文档仍使用原轮询，已验证业务载荷优先且须目标匹配。未绑定的其他调用场景不变，不提高点击、拖动、等待或重试预算；外层继续读取新摘要后按原规则分类。回归为 `tools/test/test_captcha_nc_retry_target_binding.py`；本修复不清除既有人工状态，也不证明上游已接受自动拖动。

拖动残距必须统一为视口 CSS 像素：`offsetWidth/offsetLeft` 是布局像素，只有轨道和操作柄的布局尺寸完整时，才按轨道 `getBoundingClientRect().width / offsetWidth` 转换后覆盖视口残距；缺少布局尺寸则保留视口几何结果。物理屏幕 DPR 换算仍在原输入层执行，不能用 DPR 代替元素缩放。终点最多 2 CSS 像素的边框溢出、最小 1 像素动作及距离上限不变，不改轨迹、调用次数或预算。回归为 `tools/test/test_slider_endpoint_distance.py`；该缩放反例尚未与生产失败页面建立因果关系。

操作柄及其轨道在同一次 DOM 读取中关联，不能拼接另一组件或主文档的轨道。明确 NC ID 冲突、重复配对 ID、不同 NC 容器均不能被祖先或同容器回退绕过；布局 offset 仅在操作柄的真实 `offsetParent` 就是该轨道时采用。iframe 边框和轨道坐标统一转换到视口 CSS 像素；主文档优先及单层可访问 iframe 范围不变。无法证明关联时保留同快照的未知轨道和既有距离回退，不另扫其他组件。

Linux 聚焦后的复测消费限时节点引用，重新读取同一操作柄和轨道；节点或轨道断开、文档替换、ID/祖先链/容器归属变化、引用过期时不重新按 selector 选择别处。按下前再检查轨道和操作柄几何变化，失效则结束该次动作，不追加尝试。引用有独立截止检查和定时清理；不新增外部请求、导航或模型调用，不改变取消、截止和拖动预算。回归为 `tools/test/test_captcha_track_association.py`、`tools/test/test_captcha_slider_binding.py` 及 CSS 距离流程测试；这些确定性离线反例尚不能证明生产失败的归因或通过率提升。

Linux 的 `windowactivate --sync` 超时或非零返回不等于原生输入焦点未取得。执行后先按原生窗口 ID 复核焦点，已取得则不再执行备用 raise/focus；未取得仍走原有备用路径。备用 raise/focus 异常或非零返回时也复核原生焦点，不把命令确认失败直接当作焦点失败，不增加后续激活命令。之后仍须重新激活精确 CDP 目标并再次检查原生焦点，按下前仍检查绑定和可信指针。取消、单命令及 solve 截止时间均保留，不因确认丢失而增加激活次数。回归为 `tools/test/test_captcha_focus_lost_ack.py`；该离线假阴性反例尚未与某次生产指针失败建立因果关系。

X11 映射被拒绝时，既有 WARNING 通道额外保留固定 `check` 原因：目标激活未确认、原生几何不可用、CDP 几何不可用、数值无效、原生/CDP 几何不匹配或非等比缩放。诊断不包含页面文本、标题、URL、窗口 ID、原始几何或异常正文，不增加 I/O、等待、输入或探测；Windows 不输出该 Linux 诊断。原生映射返回值、阈值、截图回退、按下前指针检查及取消/截止保护不变。回归为 `tools/test/test_captcha_x11_mapping_diagnostics.py`；后台页的 outerHeight 与前台窗口不一致不能单独证明前台映射算法有错，也不能据此放宽映射验证。

观察器保留已有 `slider_geometry`、`drag_distance`、`pointer_failure`、`pointer_hit`、`cursor_position` 阶段的时间，以及固定原因/检查枚举和有界尺寸、误差、修正次数；不保留新阶段的页面坐标、selector 或节点引用。每次未完成调用的 `pointer_events` 最多 64 条，不跨容器或调用结束边界关联，也不作为成功或认证依据。`execution_unavailable` 保留原失败类别，不再归为 `other`。

指针打开检查区分 `open_native_focus`、`open_snapshot`、`open_binding`；已有绑定失效时进一步区分缺失、文档替换、过期、关系变化及节点/iframe/轨道不可用。只输出固定枚举，未知返回仍按原快照失败处理。失效结果不含有效几何，不能绕过原拒绝输入、监听清理、目标保留和冷却规则；不延长绑定寿命、不增加读取或动作。回归为 `tools/test/test_captcha_pointer_failure_evidence.py`。滑块定位至失败的时间接近引用上限，并不单独证明该次失败就是过期。

OS 拖动出现 `mouse_drag_exception` 时，输入可能已经部分送达，释放鼠标也不代表页面或操作柄已恢复原状，因此禁止在同轮使用动作前的旧坐标追加 CDP 拖动；沿用原失败恢复和下一轮重新定位流程。OS 后端尚未执行输入就不可用时的原有回退、成功动作后的验证、本地 mock、取消及截止保护不变，不增加任何尝试预算。回归为 `tools/test/test_captcha_os_drag_fallback.py`，通过注入指针覆盖按下、部分移动、释放及释放后异常；不将这些离线反例反推为某次线上 `code=300` 的原因。

NC 重试点击同样不能把 CDP 回执丢失当作“没有点击”：按下或释放未确认时，只做已有的鼠标释放清理，立即结束本次求解并保留恢复页面，不再点击下一候选、刷新、恢复导航或重新拖动。沿用 `cdp_unavailable` 和原有退避；取消及截止原因保持优先。完整收到回执及尚未执行输入的原生定位失败仍保留原流程，不扩大任何预算。回归为 `tools/test/test_captcha_nc_retry_input_uncertain.py`，覆盖预检、无滑块恢复及拖动后重试三条入口；它不证明某次线上挑战拒绝由回执丢失造成。

显式 seed/detail 请求的每一个 NC 重试点击候选，在发送输入前也必须读取当前摘要，核对就绪状态及原请求身份，不能只依赖点击后的恢复检查。探测失败、仍加载、身份不完整或异目标分别保留既有 `cdp_unavailable`、`challenge_loading`、`slider_not_found` 状态，立即结束本次求解并保留恢复页，不继续候选、导航或页面清理。已绑定的真实业务认证证明无需再点击；普通已绑定重试候选、其他调用场景、原预算、取消及截止优先级不变。回归为 `tools/test/test_captcha_nc_retry_preclick_binding.py`。自然日志中已有 `target_ready=false` 后仍重试点击的样本，但这不能证明它是此前 detail 拒绝的原因或量化长期提速。

Linux 在原指针监听清理请求中返回 `input_receipt`：首次可信左键按下是否命中绑定操作柄、按下至释放间持左键移动事件数（最多 10000）、可信释放和文档是否仍为原文档。`backend_completed` 只表示原输入函数正常返回，不代表页面或站点接受了拖动。操作柄成功后隐藏/移除不丢弃已收到的事件；导航、超时或无效结构导致收据缺失时保留 `input_receipt_unavailable`，不判为输入失败或成功。只保存严格布尔值和有界计数，不保存坐标、节点、URL 或页面内容；沿用同调用/容器绑定及 64 条上限，不改成功计数。不增加 CDP 往返、等待或输入预算，不以收据缺失触发额外尝试。回归为 `test_captcha_input_receipt.py` 与 `test_captcha_input_receipt_evidence.py`；该诊断缺口不等于已证实生产失败就是输入丢失。

### 导航回执与文档关联

`Page.navigate` 返回非空结果或 `frameId`，都不等于导航成功。明确 `errorText`、下载或畸形回包统一走既有不确定导航退避：保留页面，不重放导航，不执行后续输入；取消和截止原因保持优先。合法 ACK 允许同文档导航省略 `loaderId`，但不能仅凭 ACK 判为页面已加载或业务已认证。

当前实例为自有目标收到合法 ACK 后，仅在已有 `preflight`、`post_drag`、`retry_preclick` 日志点有界读取 `Page.getFrameTree`。每份回执最多 3 次，沿用既有 CDP 超时和同次 solve 截止；没有回执或目标、请求、归属改变时不新增读取。不订阅导航事件，不导航、不输入，不使用缓存快照冒充新读取。新导航尝试、切换或重置目标都会使旧回执失效。

日志只追加 `navigation_probe`、`navigation_frame`、`navigation_loader`、`navigation_url` 的固定枚举。`navigation_probe` 表示本次读取状态，`navigation_frame` 比较 ACK 与当前根 frame，`navigation_loader` 比较 ACK 与当前根 loader，`navigation_url` 比较当前根 URL 与已有摘要的规范化业务身份（忽略 query 顺序，保留重复参数）。它们不是原始 URL 相等证明，摘要与根树也不是原子快照；即使全部匹配，也不能据此放宽缺参页输入绑定或确认业务认证。回执中的 target/frame/loader/URL 仅留在私有内存，不输出到日志或报告；观察器保持二次白名单校验、每次调用 64 条上限和旧日志兼容。回归为 `test_captcha_navigation_reply.py`、`test_captcha_navigation_receipt.py`、`test_captcha_navigation_evidence.py`；离线导航错误反例尚不能归因为某次自然挑战失败。

### 页面去重的节点归属

页面数量阈值不是共享浏览器页面的所有权证明。page-limit 清理只允许关闭当前 solver 已记录创建、且仍出现在页面目录中的 page ID；其他 scope、人工恢复、普通页面及仅被复用的页面不因数量压力被认领。没有可清理的自有页面时，不开 keepalive、不关闭页面、不重置已有连接；只在成功关闭当前自有目标后重置其绑定。仅当全部页面均为自有页面时保留原 keepalive 保护，创建失败仍保留一页。该阈值是清理触发线，不升级成跨进程强制容量管理，不改变开页、重试、取消或截止预算；独立的同身份重复挑战去重规则不变。回归为 `tools/test/test_captcha_compaction_ownership.py`，离线反例不证明此前某次线上页面消失就是该清理导致。

后台 scope 去重必须先核对该 scope 当前请求的节点归属，再访问本地 CDP 页面目录。请求和执行器均有明确 `node_id` 时，以节点是否一致为准，不能用相同的 loopback CDP 地址覆盖明确的异机归属；旧请求没有节点身份时，保留原 CDP 端点匹配兼容。节点一致时仍允许安装配置中的公网地址与容器内地址不同。

没有归属本机的有效 challenge 时，不读取页面目录，也不创建去重 solver；混合 scope 只处理本机归属部分。已准入 scope 的同类页面去重、人工窗口、冷却、输入和请求预算规则保持不变。对应回归为 `tools/test/test_pc2_solver_scope_ownership.py`；该边界修复不独立证明真实求解成功率改善。

### 人工 scope 与自动工作的调度隔离

初始工作仲裁与回执身份投影分离：已登记的 seed/detail 人工-only challenge 不应仅因 preferred ID 稳定而长期遮蔽另一个明确归属本机的自动候选。仅当人工源 scope 和自动候选的请求、目标类型、布尔状态完整，且全局控制状态允许时，才切换初始工作选择；原稳定 selector、认证完成绑定及执行前重新读取状态的门禁保持不变。返回结果保留全部 scopes，不清除人工 scope，也不发送其完成或恢复通知。

全局人工操作窗口、operator pause、legacy force-unlock 标记、NAS 运行/排队、未确认的 auth/resume/terminal 回执和自动冷却均不允许通过换 scope 绕过；冷却到期仍须完成原 ACK 路径。无 generation 的历史人工 latch 保守等待，不以清 latch 方式恢复。跨 scope 沿用既有共享失败计数、重试时间和冷却预算，不增加拖动、请求或尝试额度。资格未知、异节点、人工/硬拦截页面均不因仲裁获得执行授权。回归为 `tools/test/test_pc2_solver_work_selection.py` 与 `tools/test/test_pc2_solver_work_selection_loop.py`；这是离线调度反例修复，不等于当前存在双 scope 候选或真实求解成功。

## 产物与恢复

私有输出目录包含 `run.json`（固定开始/结束时间）、`events.jsonl`（白名单脱敏事件）、`business.jsonl`、`issues.jsonl`、`checkpoint.json` 与原子更新的 `report.json`。不保存原始日志、响应体、Cookie、完整 URL、令牌或异常消息；目标与 completion ID 仅保留可关联哈希。

建议由独立 systemd service 运行，使用唯一 unit 和输出目录，不依赖 SSH 会话。重启同一命令会复用原窗口和已持久化事件；文件锁拒绝重复实例。日志读取或事件持久化失败均保留 cursor，只有本批事件全部落盘后才推进检查点；恢复后补采未持久化事件，已落盘事件按 ID 去重。容器更换补采保留的旧 exact ID，重启边界使旧未完成调用不能跨生命周期完成。日志轮转或应用未发出的事件仍可能无法检测。

`window_finished` 表示时间窗口结束，不等于无缺口；同时查看 `logs_read_through_deadline` 与 `coverage_issues`。未到期只能报告阶段数据。若达到结束时间仍不能读取，记录缺口后停止，不无限延长采样或假装统计完整。

## 本轮验收与部署原则

先跑 `tools/test/test_solver_observation*.py`、真实日志发射合同回归 `tools/test/test_pc2_observation_contract.py`、Ruff 和仓库有效行门禁。生产求解算法不随本次观察器修改。发布使用已验证基底的离线源码层，原配置/挂载/浏览器资料/数据库保留，exact-ID 切换保留旧容器，不使用 service-wide Compose recreation。桌面构建输入未变时可复用已验证 EXE，仍需核对安装 SHA、运行路径及 Crow.lnk。

满 24 小时后先核对覆盖缺口，再提取成功调用和相邻失败的时序、scope、profile、确认链和业务变化。只有发现可复现的程序缺陷才修改；单次成功不证明稳定有效，也不支持直接提高重试频率。
