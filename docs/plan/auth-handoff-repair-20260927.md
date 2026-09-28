# 认证交接修复与实际验收：2026-09-27

本轮已修复并部署 PC2 的旧挑战页面复用问题和详情交接缺少页面复验的问题。当前站点仍对新请求返回挑战页；新的完整认证交接尚未成功验收，需要一次新的有效人工认证。代码未提交。

## 找到并修复的原因

1. 详情 worker 的内存 browser_pages 中只要有旧验证码 HTML，就会在尝试新请求前直接抛出 open browser detail page 错误。导入新 Cookie 不会改变这份已经读入的 HTML。新增回归在修复前稳定失败，证实该路径会阻断健康的新请求。现已改为：旧挑战缓存触发新 HTTP 请求；新响应仍有挑战时再进入浏览器 fallback。
2. 浏览器 fallback 枚举共享浏览器所有淘宝 tab，只要任何 tab 有挑战就抛出 existing browser detail page 错误，连其他商品、列表阶段的旧挑战也会阻断当前详情请求。部署后的真实验证捕获了这个错误。现已改为：保留登录页保护；旧挑战不能直接决定新目标请求失败；只操作本次新建页面，不切换旧页面到前台，不关闭既有人工页面。若同一目标已有挑战页，新请求仍失败时关闭本次重复页，避免不断累积相同挑战页。
3. PC2 接收详情 Cookie 后此前默认 authenticated=True，没有验证详情页面。现在在 PC2 原浏览器 context 新建探测页，要求目标商品一致、非登录/挑战页面、包含真实详情字段后才提交成功探测回执；仅关闭本次探测页。失败或异常分别返回 stage_probe_failed / stage_probe_unavailable，NAS 不清除原挑战。
4. NAS 返回 verifying 时，PC2 此前仍记录 recovery_confirmed。现记录 recovery_verifying；最终是否恢复仍由 NAS 结合实际采集进展和挑战状态确认。

对应文件：tools/live_smoke_browser.py、tools/pc2_detail_auth_probe.py、tools/pc2_auth_recovery.py。未删除 NAS 的 blocked_scopes 验收条件，也未用计数增长掩盖仍存在的挑战。

## 为什么本轮仍不能宣布认证全部恢复

20:08 UTC 使用现有 PC1 人工详情页尝试真实交接，没有刷新、关闭或重启该浏览器。请求 auth-recovery-ef455d29a8674256b2fbf90baa62a1e9 返回 pending_human / session_not_reusable，尚未发布 Cookie 快照，PC2 没有接收本次新快照。

随后只读检查显示 PC1 已打开的详情 DOM 仍看起来健康，但导出约 151 个 Cookie 发起新的 HTTP 请求时，目标 610925725633 返回 HTTP 200、2329 字节、body_has_punish=true、body_has_challenge=true。929094175383 的 HTTP 健康检查也未通过。已安装本机 handoff 文件与仓库一致；Cookie builder 禁用环境代理，沿用 Cookie domain/path，请求使用浏览器 UA。未发现足以证明 Cookie 传输损坏的证据，也不能据此断言是 IP 或指纹绑定。

PC2 的页面状态也会变化：本轮早期同目标的新导航曾返回正常详情字段；之后已安装的新详情探针返回 false。第二轮修复后的实际 worker 请求已越过旧页面阻塞，最终在新导航处报 browser detail request returned anti-bot challenge。这证明旧页面短路已消除，同时证明当前仍有真实站点挑战。该次在线请求验证没有通过，不能以单元测试或容器健康替代端到端验收。

已请用户在现有人工认证窗口确认商品 610925725633 并点击认证完成/同步。没有绕过 PC1 健康检查，没有伪造 NAS 成功回执。站点何时解除当前会话限制仍需实际验证。

## 已部署范围与回滚

只变更 PC2 browser-solver 和三个详情 worker；NAS、PC1 桌面 EXE、人工浏览器、AI 服务未变更。本轮没有本地桌面构建或快捷方式更新需求。所有本地诊断 subprocess 使用 windowsHide；未启动前台 PowerShell。

- browser-solver 当前容器：e74597aebc9b；镜像 sha256:c7404250d51053881ccbca10022de40337710a1051b3d1a10b1d09a3d31b62d5。
- 最终详情 worker：a3ad8deb8f23、06f8b7cea720、94eacbaf8247；镜像 sha256:d96c088541ae27cba50374d8c9ecf6361238a4a7a44ebf70e94dbed129944d7e。
- 私有备份、候选构建和安装回执目录：/srv/apps/fapaifang-worker/releases/20260927-detail-proof/、/srv/apps/fapaifang-worker/releases/20260927-detail-revalidate/。
- 原容器保留为 -before-detail-proof-20260927 和 -before-detail-revalidate-20260927，可按记录中的精确 ID 回滚。
- 部署前检查 Compose project/service 标签，发现同标签历史备份容器，因此全部按精确 ID 替换，没有服务级 Compose recreate。
- 环境变量、挂载、端口、重启策略保留；实际安装源码 SHA-256 和健康检查通过。

线上 browser-solver 的基础 live_smoke_browser.py 比详情 worker 旧。第一轮预检阻止了直接覆盖；核对后分别基于原镜像制作最小补丁，保留各自无关实现。最终详情 worker 使用本地最新已验证文件；browser-solver 保留原版本其他代码，仅接收它所需的首轮缓存修复及独立新详情探针。第二处 fallback 修复在实际消费该函数的三个详情 worker 中部署。

## 验证记录及边界

- 缓存挑战回归：修复前 3 failed，修复后通过。
- 第一轮缓存、PC2 页面探针、恢复状态机测试：44 passed；当时相邻抓取测试 34 passed。
- 第二轮跨页面重试、登录保护、重复页面清理及相关抓取测试：29 passed。
- 第二轮完成后的相邻抓取测试：34 passed，7.22 秒。
- 新文件 Ruff 格式及选定静态规则通过。有效行 checker 测试 19 passed；最终 ratchet 扫描 1388 文件，无超过 500 有效行的文件。
- 两轮远程候选镜像均先执行断网回归预检，再激活并检查实际文件哈希和运行健康。
- 第一轮独立只读审查未发现直接 bug；第二轮扩大了页面重试边界并增加了相应回归。
- git diff --check 通过。既有静默任务、详情等待等未提交修改保留，未把不同时间结果合并成一次全量验收。

20:36:30 UTC：链接 331441、详情 156096、AI 完成 121099。相比 20:08 的详情 155949 有累计增长，但其间会话和挑战状态变化，不能把全部增量归因于本轮补丁。最终查询时 seed/detail 均出现新挑战；人工验证请求仍处于 pc1_claimed，snapshot=null。完整的新交接仍未验收通过。
补充：2026-09-27T20:39:33.921641+00:00 查询确认本轮未发布的验证请求已按正常时限结束，结果 failed / pc1_claimed_timeout，active=null；未遗留占用中的人工恢复任务。
