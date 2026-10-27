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

成功轮询只在连续两次取得完整、目标绑定的 NC 重试状态时提前返回原重试策略：页面 complete、探测无失败、明确且可重试的错误、活动 NC 组件仍存在而滑块已消失、非登录页且未认证。任何不完整或过渡状态都会清零连续计数；普通错误文案、交互中页面、异目标或缺字段均保持原轮询预算。明确成功和已验证业务载荷仍优先；本地 mock、取消和截止保护不变。不增加拖动、重试或请求预算，也不把提前结束失败等待算成成功。回归为 `tools/test/test_captcha_verification_terminal_failure.py`。

显式 seed 请求的选页必须与成功证明使用同一列表身份：类别路径、`location_code`、`st_param`、`auction_start_seg`、`page` 均不能仅因同属 seed 而替换。忽略既有非身份追踪参数及挑战后缀，复用匹配页；缓存 socket 也须核对当前页面目录，目录读取失败时只能使用已有绑定身份。请求页无法打开时，不再借后台标记、品牌标题或旧 scope 页面绕回错误目标；保留既有登录页人工处理及非 seed 兼容行为。不放宽成功证明或扩大求解预算。回归为 `tools/test/test_captcha_seed_target_binding.py`；离线错配反例不代表所有线上失败均由错配引起。

求解循环和 NC 重试后的无滑块分支沿用首次预检已有的加载宽限：只在 `readyState=loading` 且无滑块时，最多等待 8 秒、32 轮，并受同一次求解的截止时间和取消约束。加载后出现滑块时，只有就绪且目标匹配才额外读取一次位置，不能仅凭旧位置继续拖动；恢复的真实业务载荷仍由原目标绑定验证判定。持续加载、探测失败、空白页及其他目标不升级为成功；不增加拖动次数、重试额度或全局超时，本地 mock 保持原行为。回归为 `tools/test/test_captcha_solve_loading_transition.py`；离线恢复反例不独立证明站点已经接受自动拖动。

### 页面去重的节点归属

后台 scope 去重必须先核对该 scope 当前请求的节点归属，再访问本地 CDP 页面目录。请求和执行器均有明确 `node_id` 时，以节点是否一致为准，不能用相同的 loopback CDP 地址覆盖明确的异机归属；旧请求没有节点身份时，保留原 CDP 端点匹配兼容。节点一致时仍允许安装配置中的公网地址与容器内地址不同。

没有归属本机的有效 challenge 时，不读取页面目录，也不创建去重 solver；混合 scope 只处理本机归属部分。已准入 scope 的同类页面去重、人工窗口、冷却、输入和请求预算规则保持不变。对应回归为 `tools/test/test_pc2_solver_scope_ownership.py`；该边界修复不独立证明真实求解成功率改善。

## 产物与恢复

私有输出目录包含 `run.json`（固定开始/结束时间）、`events.jsonl`（白名单脱敏事件）、`business.jsonl`、`issues.jsonl`、`checkpoint.json` 与原子更新的 `report.json`。不保存原始日志、响应体、Cookie、完整 URL、令牌或异常消息；目标与 completion ID 仅保留可关联哈希。

建议由独立 systemd service 运行，使用唯一 unit 和输出目录，不依赖 SSH 会话。重启同一命令会复用原窗口和已持久化事件；文件锁拒绝重复实例。日志读取或事件持久化失败均保留 cursor，只有本批事件全部落盘后才推进检查点；恢复后补采未持久化事件，已落盘事件按 ID 去重。容器更换补采保留的旧 exact ID，重启边界使旧未完成调用不能跨生命周期完成。日志轮转或应用未发出的事件仍可能无法检测。

`window_finished` 表示时间窗口结束，不等于无缺口；同时查看 `logs_read_through_deadline` 与 `coverage_issues`。未到期只能报告阶段数据。若达到结束时间仍不能读取，记录缺口后停止，不无限延长采样或假装统计完整。

## 本轮验收与部署原则

先跑 `tools/test/test_solver_observation*.py`、真实日志发射合同回归 `tools/test/test_pc2_observation_contract.py`、Ruff 和仓库有效行门禁。生产求解算法不随本次观察器修改。发布使用已验证基底的离线源码层，原配置/挂载/浏览器资料/数据库保留，exact-ID 切换保留旧容器，不使用 service-wide Compose recreation。桌面构建输入未变时可复用已验证 EXE，仍需核对安装 SHA、运行路径及 Crow.lnk。

满 24 小时后先核对覆盖缺口，再提取成功调用和相邻失败的时序、scope、profile、确认链和业务变化。只有发现可复现的程序缺陷才修改；单次成功不证明稳定有效，也不支持直接提高重试频率。
