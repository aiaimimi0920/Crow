# 常用 Edge 人工认证入口

## 范围

保留专用 Chrome/CDP 入口；新增普通 Edge 配置内的手动认证扩展。
不复制浏览器配置，不开启日常浏览器调试端口，不自动点击验证码，不读取密码库或浏览历史。
扩展没有后台 worker 或 content script；仅显式提交时读取白名单淘宝域会话。

## 流程与边界

1. 桌面创建 10 分钟、随机 nonce、绑定阶段/目标/API/challenge 的本机任务。
2. 用户在常用 Edge 配置安装扩展，点击连接并打开页面；首次绑定扩展本地 profile 标识。
3. 用户手动认证后，扩展按精确 tab/cookie store 提交白名单会话。
4. Native Messaging 校验来源 ID、帧长度、任务、profile、有效期、目标与 Cookie 格式；不接受目的 API/文件路径。
5. Crow 中点击“已完成挑战”才执行 HTTP 会话可复用检查和原有 shared handoff。
6. NAS/PC2 分阶段验证，提交、导入和 HTTP 通过均不代表 PC2 已恢复。

同一 shared job 的重试保持幂等；重新打开 Edge 入口总是生成新的 request ID，不把新快照误认为旧 job 的替换。
敏感快照保存在现有数据根的 secrets/edge-auth 与原有不可变快照目录，不进入普通日志。
过期意味着拒绝继续使用，不自动删除文件。分区 Cookie 当前明确拒绝，不静默丢弃分区属性。
profile 标识是本地扩展实例配对，不是抵御同一 OS 用户修改文件的身份认证机制。

## 首次安装

完整桌面部署会安装组件并在 HKCU 注册 `com.crow.manual_auth`，不需要管理员权限。
在实际常用的 Edge 配置中打开 `edge://extensions`，开启开发人员模式，加载已解压扩展：

```text
%LOCALAPPDATA%\FapaiFangCollectorDesktop\browser-extension\crow-auth
```

扩展 ID 必须为 `hkpcgieobdbcophagofgeglpiofmedhg`。只需安装一次；以后可从 Crow 的 Edge 入口或工具栏图标进入。
多个 Edge 配置时，如果系统打开了另一个配置，应在已安装/首次配对的配置中点击扩展图标连接，不改用那个空配置。
安装/替换扩展代码后，在扩展管理页点击重新加载；不需要重启 Edge。
首次安装与实际站点认证由用户完成，不能用模拟桥接测试代替验收。

## 验证记录

- Python 认证受影响边界最终同轮：104 passed（包含 Edge contract/store/host/启动参数，以及现有 shared、desktop、recovery 测试），12.93 秒。
- 扩展纯逻辑 Node 测试：2 passed。
- 桌面认证 Playwright smoke：1 passed，验证双入口、Edge 参数、重新认证的新 ID、处理中禁止重开，以及原有状态流程。
- 前端 build、typecheck、lint 通过；新增 Python 模块 Ruff 通过。
- 桌面认证 TypeScript 单测 13 passed；Rust auth_bridge 定向测试 2 passed；PowerShell 三个变更脚本语法解析通过。
- effective-code-lines 自测 19 passed，ratchet 通过；Tauri release 构建通过。
- 真实 Edge 扩展授权、常用 profile 配对、手动验证及 PC2 实际恢复尚待人工验收，不能声称已完成。

## 本机部署

- 仅更新 PC1 观察台、本机认证助手与新扩展；未改 NAS/PC2 服务，未重启任何认证浏览器。
- EXE SHA-256：`059D8FB84B3229268E4F598F749C864F4BD1568BC0DCC40D03E1AD4FE7657F18`。
- 安装路径：`%LOCALAPPDATA%\FapaiFangCollectorDesktop`；`Crow.lnk` 的目标、工作目录、图标已刷新核验。
- 配套 14 个文件与候选逐一 SHA-256 相同，既有 runtime config 和 launcher 保持不变。
- 实际已安装 `.cmd`/Python Native Messaging 往返测试通过，拒绝错误扩展来源；该测试不读取 Cookie，不请求真实站点。
- 备份：安装目录 `backup/edge-auth-20261018-062855`，包括旧 EXE、被替换的助手文件和原注册表默认值记录。
- 候选、安装回执和部署脚本位于工作区外的 `AI/GameEditor/linshi/crow-edge-20261018`；进程核验 PID 36140。
- 首次安装脚本在激活前遇到 Windows PowerShell 模块搜索路径问题，恢复 Machine PSModulePath 后助手安装验证通过；随后停止旧 Crow 后立即复制 EXE 遇到短暂文件锁，等待旧进程完全退出后单独激活成功。未激活失败构建。
