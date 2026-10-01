# Crow（乌鸦引擎）

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](docs/runbooks/crow-data-root-compatibility.md).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Storage](https://img.shields.io/badge/Storage-JSON%20%2B%20PostgreSQL-green)
![Control%20Plane](https://img.shields.io/badge/Control%20Plane-Receipt%20Aware-orange)
![Status](https://img.shields.io/badge/Status-Active-yellow)

## 项目简介

Crow 是一套面向任意商品来源的采集、分析与预测引擎。法拍房是当前首个且最完整的领域适配器，不是采集引擎本身的边界。

三个产品级模块的当前状态：

- **采集引擎**：当前核心，覆盖粗采集（链接发现）、细采集（详情页抓取）和 AI 联合决策归档。
- **数据分析引擎**：尚未完成；已有 AVM/分析代码作为迁移输入保留。
- **预测引擎**：尚未完成；现阶段不宣称具备完整产品契约。

模块边界、通用适配器和扩展方式见 [`docs/architecture/crow-engines.md`](docs/architecture/crow-engines.md)。

当前实现重点包括：

- **采集主链路**：浏览器侧脚本抓取 + Python 后端接收、调度、归档。
- **DB-first / dual-write**：保留 JSON 归档，同时支持 PostgreSQL 作为主索引与分析落盘方向。
- **analysis-ready / AVM**：围绕 Canonical / feature / alert / gate 的分析侧工具链。
- **maintenance & recovery**：围绕 recent gap、replay、coordinate backfill、analysis reconcile 的维护闭环。
- **manual review control-plane**：围绕 receipt、async maintenance job、operation audit、status/gate surface 的人工回执与自动恢复链路。

如果你是第一次进入这个仓库，可以把它理解为：

> **以通用商品采集为当前核心，逐步建设数据分析与预测能力的 Crow 引擎。**

---

## 常用 operator 入口

### 后端本地入口

- 启动主服务：
  - `auto/main.bat`
- 启动数据修复：
  - `auto/data_fixer.bat`
- 启动 hybrid 种子采集执行器（browserless fast path + 浏览器 fallback）：
  - `auto/seed_hybrid_collector.bat`

这两个 batch 入口现在都支持外部覆盖 `PYTHON_CMD`，因此在 smoke / 包装脚本 / 定制 Python 环境下可以直接注入解释器路径，而不是只能依赖仓库内 `venv` 或系统 `python`。

其中 `auto/seed_hybrid_collector.bat` 额外支持：

- `HYBRID_API_BASE`
- `HYBRID_SESSION_ID`
- `HYBRID_CDP_ENDPOINT`
- `HYBRID_RUN_MODE`
- `TAOBAO_AUTH_PROFILE_DIR`
- `HYBRID_EXTRA_ARGS`

运行模式说明：

- `HYBRID_RUN_MODE=hybrid`
  - 默认模式
  - 先走 browserless fast path
  - 命中 login / challenge / punish / missing payload 时按现有 fallback 逻辑切回浏览器 worker
- `HYBRID_RUN_MODE=browserless`
  - 只跑 browserless
  - 即使命中 fallback 条件，也只返回结果，不自动打开浏览器
- `HYBRID_RUN_MODE=browser`
  - 跳过 browserless 探测
  - 直接把真实 task URL 改写为 `uni_mode=SNIFF_WORKER` 并打开浏览器 worker

`HYBRID_EXTRA_ARGS` 可继续补 runner 级控制，例如：

- `--max-runs 1`
- `--stop-on-fallback`
- `--max-consecutive-fallbacks 3`

例如，可以安全做一次单轮 bounded run：

```powershell
$env:HYBRID_API_BASE = "http://127.0.0.1:8011/api"
$env:HYBRID_EXTRA_ARGS = "--max-runs 1 --stop-on-fallback"
cmd /c auto\seed_hybrid_collector.bat
```

### 前端本地入口

- 从当前工作区稳定构建前端：
  - `python tools/build_web_app.py`
- 从当前工作区稳定启动前端静态预览：
  - `python tools/preview_web_app.py`
- 从当前工作区稳定启动前端 dev server：
  - `python tools/dev_web_app.py`

这些 helper 会优先处理当前 Windows + UNC 工作目录下的本地盘映射问题，避免直接 `npm run build` / `npm run dev` 时踩 `CMD.EXE` 的 UNC cwd 限制。

### Userscript smoke 入口

- 启动本地 userscript harness 预览：
  - `python tools/preview_userscript_harness.py`

它会暴露：

- `http://127.0.0.1:43180/tools/userscript_harness.html`

用于对：

- `tampermonkey_scripts/fapaifang_unified.user.js`

做本地 load-time smoke，而不需要直接碰真实站点。

可维护源码位于 `tampermonkey_scripts/src/fapaifang_unified/`。Tampermonkey
安装入口仍保持为一个共享 IIFE 的单文件产物，避免 `@require` 改变授权、加载
时序和闭包状态。修改分源后执行：

```powershell
node scripts/build-userscript.mjs --write
node scripts/build-userscript.mjs --check
node --check tampermonkey_scripts/fapaifang_unified.user.js
```

### 本地 mock 滑块回归入口

这组入口只访问仓库内的 `file://.../tools/mock_slider.html`，用于稳定回归：

- 本地 mock challenge 识别
- solver repeated-run 稳定性
- 成功 / 失败语义
- 主流程边界在 mock 语义下的可重复验证

推荐的一键入口：

- 跑 targeted pytest + mock matrix：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-local-mock-slider-regression.ps1`
- 跑更高压力的 matrix：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-local-mock-slider-regression.ps1 -Runs 5 -Workers 4`
- 只跑 matrix：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-local-mock-slider-regression.ps1 -SkipPytest`
- 只跑单场景：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-local-mock-slider-regression.ps1 -Scenario near_miss`

如果只想直接跑 Python 入口，也可以使用：

- `python -m pytest tools/test/test_mock_slider_drag_check.py tools/test/test_mock_solver_probe.py tools/test/test_mock_solver_matrix.py tools/test/test_captcha_solver.py tools/test/test_taobao_login_health.py tools/test/test_detail_worker.py -q`
- `python tools/mock_solver_matrix.py --runs 3 --workers 4`
- `python tools/mock_solver_matrix.py --scenario near_miss --runs 3 --workers 1`

### 真实采集 live smoke 入口

已登录淘宝/阿里资产的 Chrome 需要先以 remote debugging 暴露 CDP，例如 `http://127.0.0.1:9223`。

#### Taobao 登录恢复与 CDP 浏览器辅助脚本

如需启动专用的可见 CDP 浏览器，并让 Docker worker 复用同一登录态，优先使用：

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-taobao-cdp-browser.ps1 -Port 9223`

默认会复用：

- `.\CrowData\edge-cdp-profile`

如需把 Taobao 采集会话与日常浏览器/扩展环境隔离，推荐改用：

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-taobao-cdp-browser.ps1 -Port 9225 -ForceNew -IsolatedProfile -DisableExtensions -StartUrl "https://sf.taobao.com/?__captcha_worker_master=1"`

该模式会改用隔离 profile：

- `.\CrowData\edge-cdp-profile-isolated`

并尽量减少扩展污染，适合：

- `验证失败，点击框体重试(error:XXXXXX)` 排障
- `manual_verification_required` 后的人工恢复
- 怀疑现有 `edge-cdp-profile` 被 MetaMask / 下载扩展 / 侧边栏状态污染时

脚本会在宿主校验：

- `http://127.0.0.1:9223/json/version`

并提示容器侧应访问：

- `http://192.168.65.254:9223`

如果真实采集进入 `login_recovery`、`punish`、验证码、或淘宝官方安全校验状态，可使用：

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-taobao-login-health.ps1 -Port 9223 -CheckUrl "https://sf.taobao.com/list/50025969__2.htm"`
- 如需走隔离浏览器排障：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-taobao-login-health.ps1 -Port 9225 -CheckUrl "https://sf.taobao.com/list/50025969__2.htm" -IsolatedProfile -DisableExtensions`

该脚本会调用：

- `tools\taobao_login_health.py`

并在 `http://127.0.0.1:9223` 上检查 CDP 与登录健康度；必要时会打开登录页、触发验证码求解上报，并要求你在可见浏览器窗口中完成官方验证。

如需导出隔离浏览器的 cookie 快照用于后续 browserless / health probe 复核，可使用：

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export-taobao-cookie-snapshot.ps1 -Port 9225 -IsolatedProfile -DisableExtensions`

- 运行 3-5 个真实法拍详情页的 batch smoke：
  - `python tools/live_batch_smoke.py --target-success 5 --max-attempts 15 --output-dir output/live_batch_smoke`
- 默认会启用断点续采状态文件：
  - `output/live_batch_smoke/resume_state.json`
  - 已标记为 `completed` 的 item_id 后续会被跳过，因此中断后重跑会继续处理后面的候选，而不是重新采集已经成功落盘的标的。
  - 如果状态文件丢失，但 `output/live_batch_smoke/<item_id>/final.json` 与 `selected.json` 仍存在，下一轮会自动把该 item 补回 `completed` 状态并跳过。
  - 如需显式指定状态文件：`python tools/live_batch_smoke.py --target-success 5 --max-attempts 50 --resume-state output/live_batch_smoke/resume_state.json`
  - 如需关闭续采去重：追加 `--no-resume`
- 长驻循环采集入口：
  - `python tools/live_batch_smoke.py --loop --loop-interval-seconds 300 --target-success 5 --max-attempts 50 --output-dir output/live_batch_smoke --resume-state output/live_batch_smoke/resume_state.json`
- 如果已经有一轮 `summary.json`，只生成面积缺失二级补全队列、不重新访问真实站点：
  - `python tools/live_batch_smoke.py --from-summary output/live_batch_smoke/summary.json --write-followup-only --output-dir output/live_batch_smoke`

输出产物：

- `output/live_batch_smoke/summary.json`
- `output/live_batch_smoke/<item_id>/detail.html`
- `output/live_batch_smoke/<item_id>/seed.json`
- `output/live_batch_smoke/<item_id>/extracted.json`
- `output/live_batch_smoke/<item_id>/final.json`
- `output/live_batch_smoke/<item_id>/selected.json`
- `output/live_batch_smoke/area_followup_queue.json`
- `output/live_batch_smoke/resume_state.json`

其中 `area_followup_queue.json` 会把详情页与异步描述均未解析出建筑面积的成交标的列入二级补全队列，后续可接公告附件、评估报告附件、页面图片 OCR、外部小区/产权索引等补全路线。

- 处理面积缺失二级补全队列：
  - 只解析本地已归档详情页/文本/附件 manifest：
    - `python tools/area_followup_runner.py --queue output/live_batch_smoke/area_followup_queue.json --output-dir output/live_batch_smoke`
  - 如果需要继续回源抓取阿里司法拍卖公告详情页，传入已登录 Chrome 的 CDP：
    - `python tools/area_followup_runner.py --queue output/live_batch_smoke/area_followup_queue.json --output-dir output/live_batch_smoke --cdp-endpoint http://127.0.0.1:9223`

二级补全成功时会写出：

- `output/live_batch_smoke/<item_id>/notice_detail_*.html`
- `output/live_batch_smoke/<item_id>/notice_detail_*.txt`
- `output/live_batch_smoke/<item_id>/area_followup_patch.json`
- `output/live_batch_smoke/area_followup_result.json`

确认 patch 后，可离线安全应用到对应 `final.json`：

- `python tools/area_followup_runner.py --queue output/live_batch_smoke/area_followup_queue.json --output-dir output/live_batch_smoke --apply-patches`

应用器只会处理 `status=resolved` 的 `area_followup_patch.json`，会先写出 `final.json.area-followup.bak` 备份，再合并 `建筑面积`、`产权建筑面积`、`单价`、`property.area_sqm`、`property.gross_area_sqm`、`property.unit_price` 及补全证据字段。

如需把 resolved patch 投递到正在运行的采集服务，可复用现有面积回写 API：

- `python tools/area_followup_runner.py --queue output/live_batch_smoke/area_followup_queue.json --output-dir output/live_batch_smoke --push-area-result http://127.0.0.1:8000/api/collection/details/area_result`

该模式会 POST `id`、`建筑面积`、`产权建筑面积`、`单价`、`property.*`、`archive.*`、`legal_context.*`、`area_followup_source`、`area_followup_evidence` 到现有服务，由服务端继续执行 `sync_collection_record()`、JSON/DB 持久化和 runtime cache evict。

---

## Docker 长驻运行与断点续采

正式长驻采集入口已经切到 **DB-backed 三段式任务池模型**，不再依赖旧的单体
`live_batch_smoke --loop` 作为主采集器：

1. `fapaifang-seed-collector`
   - 运行 `tools/seed_collector.py --loop`。
   - 只扫描列表页，只写入商品 URL / seed 队列。
   - 支持 `FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json` 一次展开
     全地区、全品类、全排序组合的 seed jobs。
   - 支持 `FAPAI_SEED_PARALLEL_SORTS=1`，多个 seed worker 可以同时 claim
     不同地区/排序的列表页，先把商品链接池铺开，不被后续详情或 AI 阶段卡住。
   - 每个排序组合的断点写入 PostgreSQL 表 `fapai_seed_scan_progress`。

2. `fapaifang-detail-worker`
   - 运行 `tools/detail_worker.py --loop`。
   - 只从 PostgreSQL 表 `fapai_seed_item` 中 claim `pending_detail`
     商品 URL。
   - 默认 `FAPAI_DETAIL_RAW_ONLY=1`，只抓详情页 HTML/全文文本并写入 raw artifacts。
   - 成功后标记 `raw_detail_captured`；失败后保留 `detail_failed`，后续可重试。

3. `fapaifang-detail-analysis-worker` / `fapaifang-detail-analysis-worker-2` / `fapaifang-detail-analysis-worker-3`
   - 运行 `tools/detail_worker.py --loop --analysis-only`。
   - 只从 DB claim `raw_detail_captured` 的商品。
   - 每个 analysis worker 使用独立输出目录，例如 `/data/output/detail_analysis_worker_2`，
     claim 后会把 DB 中记录的 raw artifact staging 到自己的工作目录，再执行 AI 解析。
   - 根据已缓存的详情页全文调用 LLM，写 `final.json` / `selected.json`，
     并同步写入 canonical property tables。
   - 成功后标记 `detail_completed`；失败后保留 `analysis_failed`，后续可重试。

这意味着断点续采的主状态在 PostgreSQL，不在容器本地临时文件：

- 列表扫描断点：`fapai_seed_scan_job`、`fapai_seed_scan_progress`
- 去重后的商品 URL 队列：`fapai_seed_item`
- 某个商品来自哪些区域 / 排序 / 页码：`fapai_seed_occurrence`
- 结构化详情结果：`property_listing`、`property_audit` 等 canonical 表
- 文件产物：`/data/output/seed_collector`、`/data/output/detail_worker`

容器中断后重启时：

1. seed collector 会从未完成的 `progress.next_page` 继续扫，不会重头扫同一排序。
2. raw detail worker 会跳过已抓取 raw detail 的 item，只消费 pending/failed 可重试项。
3. analysis worker 会跳过 `detail_completed` 的 item，只消费 `raw_detail_captured`
   或 analysis failed 的可重试项。
4. 同一个 `item_id` 在不同排序或不同页重复出现时，只会在 `fapai_seed_item`
   中保留一个详情任务；重复来源记录在 `fapai_seed_occurrence`。

`tools/live_batch_smoke.py` 仍保留为 **真实 smoke / 调试工具**，旧 `fapaifang-collector`
服务也保留在 compose 的 `legacy` profile 下，但它不是默认长驻采集入口。

### 连续采集 operator 脚本

Windows 宿主机上的常用入口集中在 `scripts/`：

- `scripts\start-continuous-collection.ps1`：生成全量 seed jobs、检查 Taobao 登录健康度，并启动 seed collector pool、raw detail worker pool、detail analysis worker pool。
- `scripts\generate-all-seed-jobs.ps1`：生成 `/data/jobs/seed_jobs_all.json`，容器内通过 `FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json` 读取。
- `scripts\taobao-login-watchdog.ps1`：multi-sample 登录健康门，默认同时抽检 `50025969` 和 `200782003` 两类法拍列表；失败时打开可见浏览器供人工完成官方验证。
- `scripts\trigger-taobao-login-recovery-if-needed.ps1`：事件触发式人工验证恢复器，根据 DB 中连续 `list_payload_missing` / challenge 信号触发 watchdog 任务。
- `scripts\register-taobao-login-watchdog-task.ps1`：注册可见用户态 Taobao 登录恢复计划任务。
- `scripts\register-taobao-login-recovery-monitor-task.ps1`：注册高频恢复监控计划任务。
- `scripts\register-continuous-collection-task.ps1`：注册连续采集计划任务。
- `scripts\start-seed-scan-only.ps1`：只启动 seed collector pool，停止 raw detail / analysis worker，适合先恢复列表采集。
- `scripts\start-detail-analysis-only.ps1`：只启动 raw detail worker pool 和 detail analysis worker pool，停止 seed collector，适合专注详情抓取与 AI 分析补齐。
- `scripts\backup-postgres-to-host.ps1`：把 PostgreSQL 做成 host 侧 custom-format dump，并用 `pg_restore -l` 做恢复列表探针。
- `scripts\register-postgres-backup-task.ps1`：注册独立的 `FapaiFangPostgresBackup` 周期备份任务。
- `scripts\check-postgres-backup-health.ps1`：检查最近 dump 是否缺失、过期、过小或无法列出恢复清单。
- `scripts\register-postgres-backup-health-task.ps1`：注册独立的 `FapaiFangPostgresBackupHealth` 备份健康检查任务。

这些脚本会把关键运行参数写入 `docker.local.env`，常用值包括：

```env
FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json
FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json
FAPAI_SEED_PAGES_PER_RUN=20
FAPAI_SEED_LOOP_INTERVAL_SECONDS=60
FAPAI_SEED_PARALLEL_SORTS=1
FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900
FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=1800
FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800
FAPAI_DETAIL_ANALYSIS_WORKER_RESTART=unless-stopped
FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART=unless-stopped
FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART=unless-stopped
```

### 持久化目录

本地开发默认使用仓库内、但不进入 Git 的数据根：

```text
.\CrowData
```

该路径由脚本相对于当前仓库根目录解析，因此移动或重命名项目目录后不需要改代码。
现有安装仍可通过 `FAPAI_DATA_ROOT_HOST` 或脚本的 `-DataRoot` 参数覆盖默认值。
`CrowData/.gitignore` 会阻止凭据、浏览器 profile、数据库备份和生成数据进入 Git。

历史数据只通过 `scripts\import-legacy-fpfdata.ps1` 做非破坏、可重试的归档导入。
导入结果放在 `CrowData\imports\<source-id>`，默认排除 secrets、runtime、浏览器
profile、日志和 live PostgreSQL data。导入不会修改源目录，也不会触发部署。

当前默认 compose 使用 **Docker named volume** 持久化运行状态：

- `fapaifang_fapaifang-output` -> `/data/output`
- `fapaifang_fapaifang-datas` -> `/data/datas`
- `fapaifang_fapaifang-jobs` -> `/data/jobs`
- `fapaifang_postgres_data` -> PostgreSQL `/var/lib/postgresql/data`

这样可以保证容器重启后采集断点和 PostgreSQL 数据不丢。仓库内的
`.\CrowData` 只作为本地开发、离线归档和显式同步目标，不是默认 live bind mount。

原因是当前这台机器实测：

- `C:\...` 本地盘 bind mount 正常，容器写入后宿主可见。
- 历史网络盘或 UNC 目录直 bind mount 曾出现“容器内写入成功，但宿主目录看不到
  文件”的假成功。
- Docker local CIFS volume 指向 `//192.168.15.200/home` 当前报 `no route to host`。

因此不要把网络盘/UNC 直挂当作已经可用的持久化方案。正式运行时使用 Docker volumes，
再用同步脚本把 collector artifacts 和 PostgreSQL dump 落到 `CrowData`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-docker-data-to-host.ps1
```

如果 `docker.local.env`、当前 shell 或命令行设置了 `FAPAI_DATA_ROOT_HOST` / `-DataRoot`，
该显式值优先于仓库相对默认值：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-docker-data-to-host.ps1
```

如需让外部目录持续跟随 Docker volumes，可注册 Windows 计划任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-fpfdata-sync-task.ps1 -IntervalMinutes 15
```

该任务名为 `\FapaiFang\FapaiFangDataSync`。默认只同步 collector artifacts；
如果确实需要周期性数据库 dump，可追加 `-IncludePostgres`，但 dump 文件会持续增长。

PostgreSQL 建议使用独立 dump 脚本维护可恢复备份，默认数据根为：

```text
.\CrowData
```

手动备份并验证 restore list：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup-postgres-to-host.ps1
```

注册周期备份与健康检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-postgres-backup-task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-postgres-backup-health-task.ps1
```

任务名分别是 `FapaiFangPostgresBackup` 和 `FapaiFangPostgresBackupHealth`。临时排查时可运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-postgres-backup-health.ps1
```

如果未来 Docker daemon 已修通对该目录的真实 bind mount 能力，可以显式叠加
host-bind override：

```powershell
docker compose --env-file docker.local.env `
  -f docker-compose.postgres.yml `
  -f docker-compose.postgres.host-bind.yml `
  up -d

docker compose --env-file docker.local.env `
  -f docker-compose.collection.yml `
  -f docker-compose.collection.host-bind.yml `
  up -d --build `
  fapaifang-seed-collector `
  fapaifang-detail-worker `
  fapaifang-detail-analysis-worker `
  fapaifang-detail-analysis-worker-2 `
  fapaifang-detail-analysis-worker-3
```

启用 override 前必须先做 bind smoke：容器写入 `${FAPAI_DATA_ROOT_HOST}` 后，
宿主同一路径必须能看到同一个文件。否则不要启用 override。

host-bind override 会把运行数据挂载到：

- `${FAPAI_DATA_ROOT_HOST}\output` -> `/data/output`
- `${FAPAI_DATA_ROOT_HOST}\datas` -> `/data/datas`
- `${FAPAI_DATA_ROOT_HOST}\jobs` -> `/data/jobs`
- `${FAPAI_DATA_ROOT_HOST}\postgres` -> PostgreSQL `/var/lib/postgresql/data`

不要把 live 采集产物加入 Git。仓库内 `CrowData` 的内容已被忽略；如需在
`docker.local.env` 中显式设置，可使用相对当前项目的路径：

```env
FAPAI_DATA_ROOT_HOST=.\CrowData
```

### 1. 准备环境变量

不要把 API key 写入仓库。`docker-compose.collection.yml` 会自动读取本地 `docker.local.env`，该文件已被 `.gitignore` / `.dockerignore` 忽略，适合本机开发明文保存运行配置：

```env
OPENAI_BASE_URL=https://your-openai-compatible-base-url/v1
OPENAI_API_KEY=<your-key>
OPENAI_MODEL=<optional-model-name>
CROW_COLLECTION_ADAPTER=taobao_judicial
# CROW_COLLECTION_SOURCE_PLATFORM is required only for the generic adapter.
# CROW_COLLECTION_SOURCE_PLATFORM=catalog_x
FAPAI_CDP_ENDPOINT=http://host.docker.internal:9223
FAPAI_DB_URL=postgresql+psycopg://fapaifang:fapaifang@host.docker.internal:55432/fapaifang
FAPAI_DB_AUTO_CREATE=1
FAPAI_DB_ENABLE_POSTGIS=1
FAPAI_DATA_ROOT_HOST=.\CrowData
FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json
FAPAI_SEED_JOB_KEY=guangdong-guangzhou-nansha-50025969
FAPAI_SEED_PROVINCE=广东省
FAPAI_SEED_CITY=广州市
FAPAI_SEED_DISTRICT=南沙区
FAPAI_SEED_LOCATION_CODE=440115
FAPAI_SEED_CATEGORY=50025969
FAPAI_SEED_SORTS=sort_0:0:默认排序,sort_3:3:价格由高到低,bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远,sort_4:4:排序4,sort_5:5:排序5
FAPAI_SEED_MAX_PAGE=83
FAPAI_SEED_PAGES_PER_RUN=20
FAPAI_SEED_LOOP_INTERVAL_SECONDS=60
FAPAI_SEED_PARALLEL_SORTS=1
FAPAI_DETAIL_TARGET_SUCCESS=10
FAPAI_DETAIL_MAX_ATTEMPTS=30
FAPAI_DETAIL_LOOP_INTERVAL_SECONDS=900
FAPAI_DETAIL_RAW_ONLY=1
FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS=10
FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=60
FAPAI_HTTP_PROXY=http://http.docker.internal:3128
FAPAI_HTTPS_PROXY=http://http.docker.internal:3128
FAPAI_LLM_PREFLIGHT=1
PYTHON_BASE_IMAGE=ghcr.io/aiaimimi0920/easy-protocol-python:providers-20260531-001
```

也可以不写文件，直接在本机临时设置环境变量：

```powershell
$env:OPENAI_BASE_URL = "https://your-openai-compatible-base-url/v1"
$env:OPENAI_API_KEY = "<your-key>"
$env:OPENAI_MODEL = "<optional-model-name>"
$env:FAPAI_CDP_ENDPOINT = "http://host.docker.internal:9223"
$env:FAPAI_DATA_ROOT_HOST = (Join-Path $PWD "CrowData")
```

其中 `FAPAI_CDP_ENDPOINT` 指向已登录淘宝/阿里资产的 Chrome remote debugging endpoint。Docker Desktop 场景下容器访问宿主机通常使用 `host.docker.internal`；如果宿主 Chrome 只监听 `127.0.0.1` 且容器连不上，需要把 remote debugging endpoint 暴露到容器可访问的地址。

### 2. 启动 PostgreSQL/PostGIS

```powershell
docker compose --env-file docker.local.env -f docker-compose.postgres.yml up -d
```

### 3. 构建并长驻运行三段式采集器

默认 Dockerfile 会从 `python:3.10-slim` 安装 `requirements.txt`。如果当前宿主机/daemon 的 PyPI 或 Docker Hub 网络不稳定，可以预先准备离线 wheelhouse：

```powershell
New-Item -ItemType Directory -Force vendor\wheels | Out-Null
python -m pip download --index-url https://pypi.org/simple --dest vendor\wheels --platform manylinux2014_x86_64 --implementation cp --python-version 310 --abi cp310 --only-binary=:all: -r requirements.txt
docker compose --env-file docker.local.env -f docker-compose.collection.yml build fapaifang-seed-collector fapaifang-detail-worker fapaifang-detail-analysis-worker fapaifang-detail-analysis-worker-2 fapaifang-detail-analysis-worker-3
```

如果本机已有可用 Python base image，也可以覆盖构建参数：

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml build fapaifang-seed-collector fapaifang-detail-worker fapaifang-detail-analysis-worker fapaifang-detail-analysis-worker-2 fapaifang-detail-analysis-worker-3
```

长驻启动：

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml up -d --build fapaifang-seed-collector fapaifang-detail-worker fapaifang-detail-analysis-worker fapaifang-detail-analysis-worker-2 fapaifang-detail-analysis-worker-3
```

默认 seed collector 参数等价于：

```powershell
python tools/seed_collector.py `
  --loop `
  --loop-interval-seconds 60 `
  --jobs-file /data/jobs/seed_jobs_all.json `
  --parallel-sorts `
  --job-key guangdong-guangzhou-nansha-50025969 `
  --province 广东省 `
  --city 广州市 `
  --district 南沙区 `
  --location-code 440115 `
  --category 50025969 `
  --sorts sort_0:0:默认排序,sort_3:3:价格由高到低,bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远,sort_4:4:排序4,sort_5:5:排序5 `
  --max-page 83 `
  --pages-per-run 20 `
  --output-dir /data/output/seed_collector
```

默认 raw detail worker 参数等价于：

```powershell
python tools/detail_worker.py `
  --loop `
  --loop-interval-seconds 900 `
  --target-success 10 `
  --max-attempts 30 `
  --raw-only `
  --output-dir /data/output/detail_worker
```

默认 detail analysis worker pool 参数等价于：

```powershell
python tools/detail_worker.py `
  --loop `
  --analysis-only `
  --loop-interval-seconds 60 `
  --target-success 10 `
  --max-attempts 5 `
  --llm-preflight `
  --output-dir /data/output/detail_analysis_worker
```

第二、第三个 analysis worker 使用相同参数，但分别设置：

```env
FAPAI_OUTPUT_DIR=/data/output/detail_analysis_worker_2
FAPAI_DETAIL_WORKER_ID=analysis-2
FAPAI_OUTPUT_DIR=/data/output/detail_analysis_worker_3
FAPAI_DETAIL_WORKER_ID=analysis-3
```

LLM 解析使用 OpenAI-compatible HTTP 接口。为避免通用宿主机代理污染采集链路，代码不会读取
`http_proxy` / `https_proxy` 这类泛用环境变量；如果 LLM endpoint 需要代理，应显式设置
`OPENAI_HTTP_PROXY` / `OPENAI_HTTPS_PROXY`，或采集器专用的
`FAPAI_LLM_HTTP_PROXY` / `FAPAI_LLM_HTTPS_PROXY`。未设置专用 LLM 代理时，会回落使用
`FAPAI_HTTP_PROXY` / `FAPAI_HTTPS_PROXY`。Docker 入口默认只在 analysis worker 上启用
`FAPAI_LLM_PREFLIGHT=1`：每轮有候选 raw detail 时会先访问 `${OPENAI_BASE_URL}/models`
做 TLS/代理连通性预检；如果预检在连接、TLS、代理层失败，本轮会直接中止并等待下一轮，
而不会把一批候选 item 全部写成 AI 解析错误。

### 4. 常用运行参数

可通过环境变量调整：

```powershell
# 在 docker.local.env 中调整：
# FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json
# FAPAI_SEED_LOCATION_CODE=440115
# FAPAI_SEED_SORTS=sort_0:0:默认排序,sort_3:3:价格由高到低,bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远
# FAPAI_SEED_MAX_PAGE=83
# FAPAI_SEED_PAGES_PER_RUN=20
# FAPAI_SEED_LOOP_INTERVAL_SECONDS=60
# FAPAI_SEED_PARALLEL_SORTS=1
# FAPAI_DETAIL_TARGET_SUCCESS=10
# FAPAI_DETAIL_MAX_ATTEMPTS=30
# FAPAI_DETAIL_LOOP_INTERVAL_SECONDS=900
# FAPAI_DETAIL_RAW_ONLY=1
# FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS=10
# FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=60
# FAPAI_HTTP_PROXY=http://http.docker.internal:3128
# FAPAI_HTTPS_PROXY=http://http.docker.internal:3128
# FAPAI_LLM_PREFLIGHT=1
# FAPAI_LLM_PREFLIGHT_TIMEOUT_SECONDS=15
docker compose --env-file docker.local.env -f docker-compose.collection.yml up -d --build fapaifang-seed-collector fapaifang-detail-worker fapaifang-detail-analysis-worker fapaifang-detail-analysis-worker-2 fapaifang-detail-analysis-worker-3
```

如果只想各跑一次 batch：

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml run --rm -e FAPAI_RUN_MODE=seed-batch fapaifang-seed-collector
docker compose --env-file docker.local.env -f docker-compose.collection.yml run --rm -e FAPAI_RUN_MODE=detail-batch fapaifang-detail-worker
docker compose --env-file docker.local.env -f docker-compose.collection.yml run --rm -e FAPAI_RUN_MODE=detail-analysis-batch fapaifang-detail-analysis-worker
```

旧单体 live smoke 入口仍可手动运行：

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml --profile legacy run --rm fapaifang-collector
```

### 5. API 与面积补全辅助容器

采集 API 可按需启动，不是长驻三段式 worker 的必需项：

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml --profile api up -d crow-api
```

面积二级补全可作为一次性 profile 运行：

```powershell
# 在 docker.local.env 中设置：
# FAPAI_AREA_APPLY_PATCHES=1
docker compose --env-file docker.local.env -f docker-compose.collection.yml --profile area-followup run --rm fapaifang-area-followup
```

如需把 resolved patch 推给 API：

```powershell
# 在 docker.local.env 中设置：
# FAPAI_AREA_PUSH_URL=http://crow-api:8001/api/collection/details/area_result
docker compose --env-file docker.local.env -f docker-compose.collection.yml --profile area-followup run --rm fapaifang-area-followup
```

---

## 当前系统实际在做什么

### 1. 数据采集

- 后端主入口：`src/server.py`
- 浏览器脚本安装入口：`tampermonkey_scripts/fapaifang_unified.user.js`
- 浏览器脚本可维护分源：`tampermonkey_scripts/src/fapaifang_unified/`
- 采集服务实现：
  - `src/collection/seed_service.py`
  - `src/collection/detail_service.py`

当前支持：

- 搜索/种子采集
- 详情任务分发
- HTML / payload / 详情归档
- DB-first pending task 读取

### 2. 数据存储与索引

当前是 **JSON + PostgreSQL dual-write** 模式：

- JSON 仍负责：
  - 历史归档
  - HTML / payload / 附件路径
  - 本地离线调试与回放
- PostgreSQL 负责：
  - 主索引
  - pending / stage / readiness 统计
  - 后续 analysis-ready 主落盘方向

关键实现：

- `src/storage/repository.py`
- `src/storage/models.py`

### 3. AVM 与分析侧工具链

在线能力：

- `src/avm/service.py`
- `src/avm/engine.py`
- `src/avm/pipeline.py`

离线 / 构建 / 门禁工具：

- `tools/build_canonical_dataset.py`
- `tools/check_feature_drift.py`
- `tools/evaluate_avm.py`
- `tools/generate_avm_alerts.py`
- `tools/avm_release_gate.py`

### 4. recent enrich maintenance 与自动恢复

当前维护闭环已经不是单纯“补详情”，而是面向 collection-stage / analysis-stage 的系统化修复：

- `tools/run_recent_enrich_maintenance.py`
- `tools/run_analysis_stage_reconcile.py`
- `tools/run_data_supply_optimization_loop.py`
- `tools/analysis_stage_planner.py`

支持：

- detail archive fetch
- archived detail backfill
- recent coordinate backfill
- detail replay preparation
- analysis ready recheck
- stage state reconcile

### 5. manual review control-plane

当前已经有正式的 receipt control-plane：

- snapshot store：
  - `tools/manual_review_receipt_store.py`
- async maintenance jobs：
  - `tools/manual_review_receipt_jobs.py`
- append-only audit log：
  - `tools/manual_review_receipt_audit.py`

对外接口位于：

- `GET/POST/DELETE /api/avm/manual_review_receipts`
- `GET /api/avm/manual_review_receipt_jobs`
- `GET /api/avm/manual_review_receipt_operations`

并且 status / health / release gate 已经可见：

- `manual_review_receipt_summary`
- `manual_review_reentry_application_summary`
- `manual_review_receipt_jobs_summary`
- `manual_review_receipt_operations_summary`

---

## 快速开始

### 环境要求

- Python 3.10+
- Chrome + Tampermonkey
- 可选：Docker（本地 PostgreSQL）

### 1. 安装依赖

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动后端

最小启动：

```powershell
python src/server.py
```

### 3. 可选：启用 PostgreSQL 主索引

```powershell
docker compose -f docker-compose.postgres.yml up -d
$env:FAPAI_DB_URL="postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
$env:FAPAI_DB_PREFER_RUNTIME_INDEX="1"
python src/server.py
```

说明：

- 不配置 `FAPAI_DB_URL` 时，系统仍可在 JSON 模式下运行。
- 配置后，运行时 pending / stage / readiness 统计会优先走 DB-first。

### 4. 安装浏览器脚本

将以下脚本导入 Tampermonkey：

- `tampermonkey_scripts/fapaifang_unified.user.js`

### 5. 常用维护命令

#### recent enrich maintenance

```powershell
python tools/run_recent_enrich_maintenance.py --dry-run
```

#### data supply optimization loop

```powershell
python tools/run_data_supply_optimization_loop.py --dry-run --max-rounds 2
```

#### release gate

```powershell
python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report
```

#### offline pytest shards

The repository-wide test runner collects the suite once, assigns complete test
files to deterministic shards, and executes each file in an isolated process.
It permits loopback traffic only and refuses the live-network override.

```powershell
0..3 | ForEach-Object {
    python scripts/run_pytest_shards.py --shard-count 4 --shard-index $_
}
```

Detailed logs, JUnit XML, and shard summaries are written below
`artifacts/pytest-shards/`.

#### historical seed collision audit

Run the audit only against an offline local SQLite copy. The default action is
read-only and reports collisions that require manual review as well as the
small subset eligible for a conservative automatic split.

```powershell
python scripts/repair_seed_collisions.py `
    --database-url "sqlite:///CrowData/offline/crow-copy.db" `
    --item-id "<historical-item-id>"
```

Applying a repair requires an explicit durable receipt. The same receipt is
required to roll the batch back:

```powershell
python scripts/repair_seed_collisions.py `
    --database-url "sqlite:///CrowData/offline/crow-copy.db" `
    --item-id "<historical-item-id>" `
    --apply `
    --receipt "artifacts/seed-collision-repair.json"

python scripts/repair_seed_collisions.py `
    --database-url "sqlite:///CrowData/offline/crow-copy.db" `
    --rollback "artifacts/seed-collision-repair.json"
```

The command rejects non-SQLite databases. Never point it at a PC2 or NAS live
database; copy the database locally, stop all writers to that copy, and review
the dry-run report before using `--apply`.

---

## 常用接口

### 采集 / 状态

- `GET /api/status`
- `GET /api/avm/health`
- `GET /api/analysis/health`

### AVM

- `GET /api/avm/predict?id=<item_id>`
- `POST /api/avm/screen`
- `POST /api/avm/evaluate`

### maintenance / pipeline

- `POST /api/avm/recent_enrich_maintenance`
- `POST /api/avm/run`

### manual review control-plane

- `GET/POST/DELETE /api/avm/manual_review_receipts`
- `GET /api/avm/manual_review_receipt_jobs`
- `GET /api/avm/manual_review_receipt_operations`

详细契约见：

- `docs/AVM_API.md`
- `docs/AVM_Runbook.md`

---

## 文档索引

建议按下面顺序阅读：

1. `README.md`
2. `architecture.md`
3. `docs/AVM_API.md`
4. `docs/AVM_Runbook.md`
5. `docs/AVM_Architecture_Overview.md`
6. `docs/analysis/final-collection-contract.md`

其中：

- `architecture.md`：当前实现视角的工程架构
- `docs/AVM_Architecture_Overview.md`：AVM 目标蓝图 / 规划视角

---

## 目录结构

```text
fapaifang/
├── src/
│   ├── server.py                 # 主 HTTP 服务
│   ├── collection/               # seed/detail collection services
│   ├── storage/                  # DB-first repository and models
│   └── avm/                      # AVM online service / pipeline / schema
├── tools/
│   ├── run_recent_enrich_maintenance.py
│   ├── run_data_supply_optimization_loop.py
│   ├── run_analysis_stage_reconcile.py
│   ├── avm_release_gate.py
│   ├── analysis_stage_planner.py
│   ├── manual_review_receipt_store.py
│   ├── manual_review_receipt_jobs.py
│   └── manual_review_receipt_audit.py
├── datas/                        # JSON 归档、AVM 报告、receipt/job/audit 状态
├── docs/                         # API、Runbook、架构文档
├── tampermonkey_scripts/         # 浏览器采集脚本
├── jobs/                         # 搜索/调度任务文件
└── auto/                         # Windows 本地脚本入口
```

---

## 当前边界

当前仓库仍有这些明确边界：

- manual review control-plane 当前已支持 **DB-backed first phase**，但在 repository disabled 场景下仍会回退到 JSON persistence
- live DB migration / alembic 不是默认可执行路径，仍依赖环境显式配置
- `docs/AVM_Architecture_Overview.md` 是目标蓝图，不应误读为“所有能力都已上线”
- 游戏 / 可视化内容仍存在，但已经不是仓库主叙事中心

---

## 许可证与使用说明

1. 本项目仅供技术研究、学习与内部工程实践使用。
2. 数据源来自公开网页，使用时需遵守目标站点协议与相关法律法规。
3. 仓库内的自动化、抓取、分析与估值能力都应在合规边界内使用。
