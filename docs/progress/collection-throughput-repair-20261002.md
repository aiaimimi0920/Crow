# 链接与原始详情吞吐修复记录（2026-10-02）

## 范围与验收状态

本轮只处理链接发现和原始详情采集，不处理 AI 额度、模型路由或分析能力。
没有发起 AI 验证请求，没有重启 AI worker，没有修改其配置。

已修复并部署可复现的查询传输、详情上下文和恢复后退避问题；**业务吞吐验收仍未完成**。
截至 03:44 UTC，链接 occurrence 计数仍为 1,312,718，没有发布后新增链接证据。
截至 03:47 UTC，详情 worker 的已结束正式批次合计完成 65 件原始详情；未结束批次不计入此数。
详情已恢复采集，在 seed scope 仍暂停时也完成新的原始详情；链接范围仍有活动来源挑战。
不能据此声称两个长期吞吐问题已全部解决，也不能把暂停解释为全部根因。

## 已确认的机制与最小改动

### 链接认领查询

候选窗口原来同时加载完整 progress/job ORM，包括历史错误、URL 等大字段。
同一生产数据库的只读对比中，完整窗口读取为 17.072 秒，薄身份窗口为 1.174 秒，
PostgreSQL EXPLAIN 的服务端执行约为 99 ms。

`src/storage/seed_scan_candidates.py` 改为只取候选身份、归属 metadata 和排序字段；
正式锁定时才读取完整 ORM。保留 128 行 keyset 窗口、归属过滤和锁语义。
`repository_seed_scan_pages.py` 对同 job 的后续候选仍取回真正 ORM，不能将薄候选作为最终 payload。
部署后 generator 首窗口实测 1.016 秒、identity map 为 0；另一个真实页面认领仍耗时 8.238 秒，
其中窗口 SQL 为 5.887 秒，说明现场抖动未消失。
上述数字是认领阶段证据，不是全业务速度提升倍数。

### 浅页覆盖

新增显式 `--breadth-first` / `CROW_SEED_BREADTH_FIRST=1`。
仅在 parallel sorts 模式把 next_page 放在排序前部，优先覆盖各地区浅页。
默认地区顺序保持不变；不重置、删除或丢弃深页任务。
PC2 seed 已开启该选项，但“是否增加真正新商品”尚无线上通过证据。

### 浏览器 fallback 的任务身份

未暂停窗口再次实测发现：认领 `445302` 地区第 1 页时，fallback 返回的是浏览器里
`371602` 地区第 15 页的历史挑战，且两者分类路径也不同。
`tools/live_smoke_browser.py` 现在将当前 target 传入复用检查，按规范化后的 URL 身份比较，
不再把另一地区、分类或页码的旧列表挑战当成当前 job 的结果。
不关闭那个旧页面，不改变人工登录页的复用逻辑，匹配当前 job 的挑战仍复用而不反复新建。
这修复了客户端的错误页面归属，不表示来源网站的真实验证已经成功。

### 详情启动与恢复等待

`tools/detail_worker_artifacts.py` 不再默认预读共享浏览器全部打开页面。
现场曾出现认领前上下文刷新耗时 35.141 秒，另一次为 2.368 秒，不能将慢样本描述为每批固定成本。
显式 `CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES=1` 仍可恢复旧行为；Cookie 导出、HTTP/browser fallback、
完整 HTML、异步描述和归档证据均保留。

详情恢复等待只在 API 确认 detail scope 清晰解除暂停、无人工要求且无 challenge_id 时唤醒，
不再继承 seed-only 的聚合暂停。未知聚合暂停和非挑战退避仍保留。

`tools/seed_collector_wait.py` 为链接挑战退避补充同样的有界恢复轮询。
现场日志证明 worker 曾在已恢复的 API/seed scope 下仍等满 900 秒。
每 30 秒检查一次确认状态，不改正常页间 pacing，不提前放行网络错误、未知状态或活动挑战。

## 验证证据及各自代码状态

- 原七个产品模块改动：Windows 相关 suite **228 passed, 2 skipped**，150.62 秒。
  两个 skip 是未配置本机 PostgreSQL 测试 URL，不能计为 PostgreSQL 通过。
- 原七个模块 Linux 候选：seed **33 passed, 2 skipped**，14.87 秒；detail **15 passed**，1.33 秒。
- NAS 独立 PostgreSQL 门禁：**4 passed, 19 deselected**，39.02 秒；覆盖 keyset 后窗口和并发页面认领。
  独立数据库/网络，无生产数据挂载；测试和数据库容器均已停止。
- 后续 seed 唤醒与 loop 改动：Windows **82 passed**，85.05 秒；Linux **37 passed, 45 deselected**，29.43 秒。
  这是后续源码状态的专项结果，不能与前述结果相加称为一次完整全套通过。
- 最后 seed 页面身份修复：Windows 独立回归 **28 passed**，1.81 秒；
  相邻 browser/facade 检查 **43 passed, 79 deselected**，5.99 秒；
  无生产挂载、network=none 的 Linux 候选同一相邻检查 **43 passed, 79 deselected**，1.16 秒。
- effective-code-lines 单测 **19 passed**；最终 ratchet 扫描 1,485 个文件，所有 >500 档为 0。
- 新小文件 Ruff/format、相关旧文件致命静态错误检查、`git diff --check` 通过。
  既有文件的其他历史 lint 未顺手清理，历史 fast/security 全套未运行。
- 较宽 Linux suite 超出 150 秒预算，未完成，未计通过；未反复重跑同一未变化的大套件。

## 部署与真实通路

所有部署使用 exact container ID。停止旧容器并保留回滚，不使用 service-wide Compose recreate，
不删除容器、数据、Cookie、profile 或凭据。PC2 controller 的 active model 同步已验证镜像，
AI worker 和共享浏览器的 ID 未在本轮切换中改变。

NAS 首次候选因 Synology legacy Docker API 的 HostConfig.Env 覆盖新 build Env 而失败并回滚。
后续发现停启/回滚后的旧容器 inspect 不再包含原端口映射，导致实际 PC2 HTTPS 请求返回 502。
按首次切换前的私有快照恢复 `127.0.0.1:19520 -> 8001`，不是修改代理到临时容器 IP。
最终已核对 NAS 外部代理路由、source digest，以及 PC2 原 CA/凭据的真实 HTTPS 请求。
不能把此前容器内部 API 200 当作外部通路恢复证据。

激活结果与镜像：

- NAS API：`d48b19f8e5d12bfa100815b17d158f3d518d24803d121cca64a17623ee16ad05`；
  image `sha256:9729ee86a720ce674271596840645c1092cb69bee671a7a78166de6baba8d9e4`。
- PC2 seed：`3545297c6c8871cbe3b5da4bc2435ca887e5ef3077d8bade6b4b103ed445e306`；
  image `sha256:1f71d6084c4f64461f71ad49e8ed8f134cf136bc7708e50c0dbf103b4ebfe551`。
- PC2 detail image：`sha256:7137b92facca474ac44e3baa3ea4a7b0a03cea7dddb94104bf5076ef016adba3`。

镜像为各角色已运行 base 上的最小源码 overlay，不代表整个 Git master 被重新完整部署。
03:47 UTC 最后核验 PC2 seed 的 10 个修复模块、detail 的 7 个模块哈希正确，controller model 匹配；
共享浏览器和未切换的 worker ID 不变。最后一个页面身份改动仅影响 PC2 seed 的列表导航分支，
没有对不执行这个分支的 API、detail worker 或本地观察客户端做无意义重启/重新打包。
本地桌面是观察/控制客户端，本轮没有修改 EXE 所属 UI 源码；保留既有已验证 EXE，
仅正常重启 Crow 并刷新核验稳定 `Crow.lnk`。未重启 PC1 人工认证浏览器。
本地按安装配置和 CA 读取真实 API 于 03:32 UTC 返回 db_mode=true、正确的新 build digest，耗时 0.796 秒。
已用 PrintWindow 获取 Crow 本身的窗口，确认显示两类采集待认证，而非只检查 EXE 进程存在。

## 仍未通过的运行边界

未暂停时的一件旧详情实测 37.102 秒，其中 HTTP HTML 26.637 秒、描述读取 2.677 秒、
认领 2.05 秒、统计 1.675 秒。没有删去描述证据或粗暴缩短全部 HTTP timeout。

NAS 通路恢复后，一页正式 seed profile 耗时 26.204 秒，但返回实际 browser challenge，未产生链接。
随后一次直接 HTTP 诊断触发 `ReadTimeout (read timeout=30)`；没有证明外部来源网络抖动已修复。
03:38 UTC 的直接 HTTP 诊断返回 200，但无列表数据 script，包含真实的
`霸下通用 web 页面-验证码`，不是把包含正常列表 payload 的页面误判为验证码。
页面身份缺陷已修复；03:48 UTC 的浏览器证据是当前地区/浅页本身仍有真实挑战、没有列表 payload。
未将未知页面当成健康采集结果，也没有强制解除认证安全门禁。

后续需在来源页面允许正常采集后，用同口径时间窗口分别记录：

1. 真正新商品 first_seen 增量；
2. occurrence 增量，不能将它等同于新商品数；
3. 正式 raw capture 完成数，不能用 AI 更新的 detail_completed_at 或 raw 库存下降替代。

## 证据与回滚位置

本地本轮诊断目录：`AI/GameEditor/linshi/crow-collection-speed-20261002013331/`。
PC2 release：`/srv/apps/fapaifang-worker/releases/collection-speed-20261002/`；
NAS release：`/volume1/docker/fapaifang/releases/collection-speed-20261002/`。
最终 NAS 端口回执在 `activation-nas-port-completion/`，最初映射快照在 `activation/`；
PC2 seed 唤醒回执和 controller 旧快照在 `seed-wakeup/activation/`；
最终页面身份回执和 controller 旧快照在 `seed-page-identity/activation/`。
私有快照包含运行配置，只作为受保护回滚材料，不加入 Git，不打印凭据。

NAS 回滚必须使用切换前快照核对并恢复端口映射，不能直接依赖停止后容器的空 PortBindings。
PC2 回滚需同时恢复对应镜像和 controller model，防止下一次协调重新切换。
旧容器和失败候选均保留；源码提交与推送状态以 Git 历史和远端核验为准。
