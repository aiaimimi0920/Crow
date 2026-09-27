# FapaiFang 运维观察台桌面版

这是一个 **Rust + Tauri** 独立桌面应用，用来观察和少量修正当前采集模块的实际数据。
它不在 PC1 运行 seed/detail/analysis worker；PC1 只承担人工认证，采集和分析 worker 均部署在 PC2。

它不复制采集逻辑，不包含房价分析引擎。默认浏览、翻页、查看详情都是读取现有采集 API；只有用户显式点击 **暂停/开始**、**认证**、**重启**、**地区重置**、**AI 再分析** 或 **手动更新** 时，才会通过 API 改变运行状态、请求引擎重启、提交认证任务、写入数据库或重新加入 AI 分析队列。

## UI 设计基线与离线预览

观察台采用 [Neuro 设计基线](../docs/design/neuro/README.md)：近黑壳层、紧凑采集侧栏、
连续运行板、黄色激活/主操作、绿色运行/完成状态。原始规范与颜色 token 已归档，
不修改 Neuro 或 Loom 原项目。样式入口为 `src/styles.css`，按责任拆分到 `src/styles/`。

窗口默认 1120×760，侧栏 186px（折叠后 52px），自绘顶栏 50px，与 Loom 壳层对齐。
左下角固定“设置”，API 地址和连接状态移入独立设置页；右上角是刷新和原生窗口控制，
普通浏览器中不显示不可用的最小化、最大化和关闭按钮。

左侧统一为“采集”。总览固定五栏：运行状态与开始/暂停、重启；当前挑战与认证；
商品链接、商品详情、商品分析。三个计数只统计唯一商品，增量使用约一分钟前的实际快照，
不会把短间隔刷新折算成一分钟；首次打开、换 API 或断线后等待采样，数量回退会明确显示。
删除运行细节开关及常驻二级统计。地区面板提供“链接/详情/分析”单选筛选：分别为已发现但
未采集详情、已采集详情但未完成分析、已完成分析。地区徽章仍表示该阶段在地区内的整体
采集进度，不是筛选后列表的数量。断连及旧快照警告保持可见。
切换设置页不会清空当前地区、分页、详情或编辑内容。手动编辑仍分别反馈未保存、
提交失败以及“已提交但刷新失败”，避免误导用户重复提交。

重启使用独立鉴权的 NAS 请求队列和 PC2 主机控制器，需二次确认；普通开始不清除认证标记。
重启授权只保存在当前窗口，切换 API 清除。未配置或控制器未连接时按钮不可用。
控制器未随源码修改自动部署，接入边界见 [重启通道说明](../docs/runbooks/collection-engine-restart.md)。
最新实现、截图和验证边界见 [采集控制改版记录](../docs/design/neuro/COLLECTION-CONTROLS.md)。

采集运行设置已有离线候选：Worker 数量、间隔、尝试上限与 AI 连接参数可在设置页编辑，
但必须先通过安全控制通道读取 PC2 的真实配置。当前尚未线上激活；人工认证阈值、跨版本
持久化及与旧重启控制器的协调仍待完成，详见 [运行设置接入门槛](../docs/runbooks/collection-runtime-settings.md)。

验证 UI 时优先使用离线夹具，不连接生产 API。在仓库根目录运行：

```powershell
npm --prefix collector-desktop run build
python tools/test/collector_ui_preview.py --port 1436
```

打开 `http://127.0.0.1:1436`。此预览仅监听回环地址，所有采集/认证/编辑 API 均为
内存中的合成数据，不读取数据库、不转发请求、不控制 PC2/NAS。测试认证按钮前应在
独立测试浏览器中阻断外部导航；否则既有认证逻辑仍可能打开外部认证网页。
按 Ctrl+C 结束预览。不要用这个夹具替代生产服务。

本地前端构建不等于桌面安装包更新，也不会自动部署或重启任何生产服务。

## 依赖

- Rust / Cargo
- Node.js / npm
- 正在运行的 `crow-api`
  - 默认地址：`http://127.0.0.1:8001`（桌面端；Web 预览仍使用当前页面地址）
  - 如需覆盖，设置环境变量：`FAPAI_COLLECTOR_API_BASE`

## 开发运行

```powershell
cd collector-desktop
npm install
npm run tauri:dev
```

如果当前仓库路径是 UNC 路径，例如 `\\192.168.15.200\...`，Windows `cmd.exe` 不能直接把 UNC 当当前目录。此时使用：

```powershell
$collectorDir = (Resolve-Path .\collector-desktop).ProviderPath
cmd /c "pushd `"$collectorDir`" && npm run tauri:dev && popd"
```

## 打包

```powershell
cd collector-desktop
npm install
npm run tauri:build
```

UNC 路径下对应使用：

```powershell
$env:CARGO_TARGET_DIR = Join-Path $env:TEMP 'fapaifang-collector-desktop-target'
$collectorDir = (Resolve-Path .\collector-desktop).ProviderPath
cmd /c "pushd `"$collectorDir`" && npm run tauri:build && popd"
```

说明：`CARGO_TARGET_DIR` 指向本机临时目录，是为了避免 Windows 在 UNC/NAS 路径下写 Cargo `target` 目录时出现权限或文件锁问题。

成功后 Windows 安装包位于：

```text
%TEMP%\fapaifang-collector-desktop-target\release\bundle\msi\
%TEMP%\fapaifang-collector-desktop-target\release\bundle\nsis\
```

## 本机稳定部署

### 仅更新观察台 exe

已经安装本机观察台、仅更新 UI 时，优先按 [本机 exe 更新说明](../docs/design/neuro/LOCAL-EXE-UPDATE.md)
使用 `scripts/update-collector-desktop-exe-only.ps1`。默认只检查，`-Apply` 必须提供预期
SHA-256；先验证备份，再原子替换 exe。它不启动/停止程序、不修改启动器与认证配置、
不清理历史备份，不连接或部署 PC2/NAS。成功更新后自动创建或刷新桌面 `Crow.lnk`；
即使 EXE 已是相同版本，显式使用 `-Apply -ExpectedSha256 ...` 也会修复缺失或过期的快捷方式。
检查模式不修改桌面。

### 完整本机部署

不要直接从仓库的 UNC/NAS 路径运行 `fapaifang_collector_desktop.exe`。Windows 在网络路径下运行 Tauri 可执行文件时，容易触发 `0xc0000006` 一类的访问异常。

统一使用仓库根目录脚本部署到本机：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy-collector-desktop-local.ps1
```

该脚本会：

- 在 `%TEMP%\fapaifang-collector-desktop-target` 下执行 `npm run tauri:build`
- 把可执行文件复制到 `%LOCALAPPDATA%\FapaiFangCollectorDesktop`
- 同步本地 runtime 所需脚本：
  - `open-remote-auth-browser.ps1`
  - `start-pc1-manual-auth-session.ps1`
  - `start-pc1-auth-bridge.ps1`
  - `start-pc1-analysis-proxy-bridge.ps1`
  - `register-pc1-analysis-proxy-bridge-task.ps1`
  - `start-taobao-cdp-browser.ps1`
  - `export-taobao-cookie-snapshot.ps1`
- 同步 cookie 导出依赖的 Python helper：
  - `browserless_seed_probe.py`
  - `taobao_login_health.py`
  - `internal_api_http.py`
- 生成本地启动器：
  - `%LOCALAPPDATA%\FapaiFangCollectorDesktop\start-fapaifang-collector.ps1`
- 生成安装目录中的 `crow-desktop.runtime.json`，保存 API 地址、数据目录、凭据文件路径和认证浏览器配置；不保存凭据或 Cookie 内容。直接双击 EXE 也读取此配置，不再依赖启动器环境变量。
- 更新桌面快捷方式：
  - `Crow.lnk`，每次成功更新刷新同一个名称，不累积旧版本快捷方式，也不删除其他桌面文件。

两个更新入口共用 `scripts/update-collector-desktop-shortcut.ps1`，写入前核验已安装 EXE 的
SHA-256，保存后核验目标、工作目录和图标。当前安装的快捷方式直接指向本地 EXE，读取
相邻的运行配置，不弹出 PowerShell 窗口；只有缺少运行配置的旧安装才沿用原启动器。
桌面路径通过 Windows 的 Desktop 已知文件夹获取，支持用户重定向桌面；测试或定制部署
可显式传入 `-DesktopDirectory`。完整部署原有的显式 `-SkipShortcut` 仍受支持，默认不跳过。

这样桌面应用在打开认证窗口、导出 cookie 快照时，会优先使用 `%LOCALAPPDATA%\FapaiFangCollectorDesktop` 下的本地脚本与 helper，而不是再次回退到仓库 UNC 路径。

运行配置优先级为显式环境变量、当前安装 bundle 的配置文件、项目本地默认值。配置不向父目录或其他安装目录搜索。首次安装或更换认证路径时由 `scripts/write-collector-desktop-runtime-config.ps1` 生成配置；EXE-only 更新会保留该文件。完整部署会将旧配置纳入安装备份。

状态、地区和商品列表由 WebView2 直接发起 HTTPS 请求，使用 Windows 的证书信任存储。
`FAPAI_API_CA_FILE` 供 Python helper 校验证书使用，不会自动让 WebView2 信任该 CA。
部署使用私有 CA 的 API 时，先核对配置中的 CA 来源和指纹，并用该 CA 验证实际 API；
随后将已确认的 CA 导入运行 Crow 的用户的 `Cert:\CurrentUser\Root`，重启 Crow。
当前部署脚本不自动导入根证书。不要关闭 TLS 校验或改回远程明文 HTTP。
部署验收必须在安装版窗口中确认状态、地区和商品列表加载成功，并点击“刷新数据”复核；
仅检查 API 返回 200、EXE 哈希、进程或快捷方式不足以证明桌面连接正常。

认证启动脚本使用 `FAPAI_DESKTOP_PYTHON_PATH` 指定的绝对解释器路径，不依赖桌面进程的 `PATH`；仅未配置解释器的旧安装或开发环境允许从 `PATH` 查找。模块工作目录和 `PYTHONPATH` 固定为当前 bundle。启动失败会在该 bundle 的 `FPFData/desktop-auth/last-launch-failure.json` 留下最近一次失败的时间、操作、分类和退出码，不保存原始错误输出、URL、Cookie 或凭据；历史失败记录不代表当前认证状态。

完整安装必须包含 `browserless_seed_probe` 和 `taobao_login_health` 的全部拆分模块，以及 `start-taobao-cdp-browser` 的两个 PowerShell 子模块，不能只复制入口文件。`tools/test/test_desktop_auth_bundle.py` 按部署脚本的实际清单构造独立安装目录，验证真实认证模块在隔离解释器及非仓库工作目录下可加载；测试不启动浏览器或提交线上认证任务。

### 可编辑的采集运行配置

设置中的采集运行配置无需等待线上连接即可编辑。**保存草稿**仅保存到本机，并按 NAS API 地址隔离；重开程序可恢复，AI 密钥不写入草稿。**保存并应用**先保存草稿，再读取线上版本、校验控制器状态、确认并提交，最后自动查询 PC2 回执。

当前 NAS 尚未启用设置接口时会明确显示“草稿已保存，未应用”，不会把本机默认值冒充线上配置。线上应用仍须满足 [运行配置启用条件](../docs/runbooks/collection-runtime-settings.md)；不可将 AI 密钥或控制授权改为经远程明文 HTTP 发送。读取线上配置覆盖已有草稿前需确认；版本冲突、结果未知均不能继续覆盖线上配置。

### PC1 人工认证、PC2 继续采集

当前桌面认证使用显式人工挑战与 NAS 快照交接：

1. 点击 **认证** 只打开含两个按钮的弹窗，不会因此暂停采集或自动打开浏览器。
   点击 **打开挑战页面** 后，在 PC1 专用 CDP Chrome `127.0.0.1:9225` 打开实际挑战页面。
2. 人工认证必须在同一浏览器进程、同一详情页完成；成功显示详情后不要关闭、刷新或
   重新导航页面。
3. 点击 **已完成挑战** 后，桌面端原地读取当前目标页 DOM，并从同一进程导出 Cookie；
   不会关闭或重启 Chrome。
4. 验证成功后发布按任务 ID 和内容哈希隔离的不可变快照，并通知 NAS；PC2 自行接收并验证。
   不向 PC2 暴露 PC1 的 CDP 端口，也不直接调用普通开始采集接口解除认证阻塞。
5. 只有 PC2 确认恢复且采集数量增长，界面才显示认证完成。正在接收快照或等待验证不等于成功。

认证弹窗分别显示等待 PC2 领取、导入会话、重启认证浏览器和确认采集恢复，不在每次状态查询时覆盖当前阶段。连续等待超过 15 分钟会停止自动查询；“已完成挑战”仍可手动查询同一任务，不会重复导出 Cookie，也不会把等待超时当成认证成功。NAS 返回的领取、导入、重启或采集验证超时会显示对应阶段。

以下是旧式桥接脚本的运维说明，不是当前双按钮认证的前置步骤；不得据此未经授权修改线上配置：

当 PC2 无法直连分析提供商时，`start-pc1-analysis-proxy-bridge.ps1` 会动态发现
PC1 当前 Windows 代理，把 PC2 的 `127.0.0.1:42345` 反向转发到 PC1 的 IPv6
回环代理。PC2 的 `OPENAI_PROXY` 只指向这个回环端口；需要开机自启时，使用
`register-pc1-analysis-proxy-bridge-task.ps1`，该操作需要一次管理员权限确认。

人工拖动期间，PC2 不应同时控制同一个标签页。使用共享的 PC1 人工浏览器时，
PC2 host-direct worker 应配置：

```text
FAPAI_CAPTCHA_SOLVER_ENABLED=0
FAPAI_LIST_BROWSER_FALLBACK=0
FAPAI_DETAIL_BROWSER_FALLBACK=0
FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES=0
FAPAI_COOKIE_SNAPSHOT_PREFER=1
FAPAI_CDP_EXTERNAL=1
```

中央暂停期间 seed/detail worker 不运行，analysis worker 可以继续处理已有原始详情；
因此不会在人工拖动时合成鼠标事件、刷新或导航 PC1 页面。需要恢复浏览器 fallback 时，必须先确认人工
认证和 cookie 导出已完成，再把相应 fallback 改回 `1` 并重启 worker；不要在人工
滑块仍显示时恢复。

## 展示范围

- 运行状态：显示 **暂停中 / 运行中 / 待认证 / 已完成**，并提供 **暂停/开始** 与 **认证** 按钮。
  - **开始/暂停** 控制普通采集状态，不强制清除待认证标记。
  - **待认证** 只代表确实需要人工介入（`manual_required` 或 `force_unlock.flag`），不会因为后台 solver 正在运行就误报。
  - **认证** 按钮进入双按钮人工认证流程；挑战在 PC1 外部浏览器中完成，不内嵌淘宝页面，不依赖反向隧道。
- 商品链接采集：总链接数、唯一商品数、逐条商品链接和列表来源。
- 商品详情页采集：已采集详情页、待抓、失败、阻塞，以及详情 HTML/文本文件。
- 商品详情页 AI 分析：已标准化商品列表，点击商品查看数据库标准化字段表、AI 分析次数，并支持：
  - **AI 再分析**：把该商品重新加入详情页 AI 分析队列，由现有 worker 重新分析并更新结果。
  - **手动编辑 / 取消编辑 / 手动更新**：把标准化字段切换为可编辑状态；手动更新会将编辑后的字段写入数据库，取消编辑会丢弃本次未提交修改并恢复数据库当前值。

该应用是 operator 观察台，不会删除任何采集任务或采集数据；写操作仅限上述明确按钮。
