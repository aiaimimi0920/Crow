# PC2 Debian collection and analysis workers

This runbook replaces the retired Windows Scheduled Task deployment on PC2. It does not migrate Windows executables, drive mappings, Edge profiles, or Task Scheduler state.

## Runtime topology

PC2 (`192.168.15.104`) runs one Compose project named `fapaifang-pc2`:

- `pc2-browser-solver`: persistent headed Chromium, Xvfb, Fluxbox, x11vnc/noVNC, CDP, and the automatic slider solver in one display session.
- `pc2-seed-1`: list-page collection.
- `pc2-detail-1..3`: raw detail-page collection.
- `pc2-analysis-1..4`: AI-only analysis of already collected raw records. These services do not depend on browser health, so collection challenges do not stop analysis.

The central API and PostgreSQL remain on NAS (`192.168.15.200`). The LLM gateway runs on `192.168.15.20:4200` (`http://192.168.15.20:4200/v1`); analysis routes by default to qualified non-GPT models (`deepseek-v4.1-flash` with `OPENAI_REASONING_EFFORT=minimal`, or `glm-5-2` when its upstream channel is active) while GPT-family models stay disabled unless `allow_gpt` (`CROW_ANALYSIS_ALLOW_GPT=1`) is explicitly opted in. Re-check `/v1/models` and the qualification pool before changing model IDs.

## Persistent paths

- Releases: `/srv/apps/fapaifang-worker/releases/<release-id>`
- Active release link: `/srv/apps/fapaifang-worker/current`
- Rollback release link: `/srv/apps/fapaifang-worker/previous`
- Runtime environment: `/srv/apps/fapaifang-worker/shared/runtime.env` (mode `0600`)
- noVNC password: `/srv/apps/fapaifang-worker/shared/vnc-password` (mode `0600`)
- Browser profile and worker data: `/srv/data/fapaifang-worker`

PC2 data directories are owned by `mjc:mjc` with group read/write access. The containers keep all Linux capabilities dropped and receive only the host `mjc` data GID through Compose `group_add`; this permits persistent-data access without making cookies or output world-readable.

The deployment script never deletes releases, images, browser state, jobs, cookies, raw pages, or worker output.

## Required deployment inputs

Stage an immutable source tree under the release directory. Create `runtime.env` from the protected NAS environment without displaying credentials. At minimum it must contain:

- `FAPAI_RUNTIME_ENV_FILE=/srv/apps/fapaifang-worker/shared/runtime.env`
- `FAPAI_VNC_PASSWORD_FILE=/srv/apps/fapaifang-worker/shared/vnc-password`
- `FAPAI_DATA_ROOT=/srv/data/fapaifang-worker`
- `FAPAI_HOST_DATA_GID` set to the numeric primary GID of `mjc` on PC2
- `FAPAI_API_BASE_URL` and `FAPAI_CENTRAL_API_BASE_URL` set to the NAS HTTPS `/api` URL
- `FAPAI_API_CA_FILE` pointing to the mounted, verified NAS CA certificate
- `FAPAI_COLLECTION_WORKER_TOKEN_FILE` pointing to the mounted collection credential,
  including in `pc2-browser-solver`; challenge and cooldown reports use this role
- `FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE` pointing to the distinct mounted recovery
  credential; authentication completion and cooldown resume use this role
- `FAPAI_WORKER_DB_URL` with NAS address `192.168.15.200:55432`
- `OPENAI_BASE_URL=http://192.168.15.20:4200/v1`
- `OPENAI_API_KEY`
- `OPENAI_MODEL=glm-5-2`
- `OPENAI_MODEL_CANDIDATES=glm-5-2,zai-glm-5-2`

Copy the preserved inputs before the first start:

- `seed_jobs_all.json` to `/srv/data/fapaifang-worker/jobs/seed_jobs_all.json`
- `taobao-cookies.json` to `/srv/data/fapaifang-worker/secrets/nodes/pc2/taobao-cookies.json`

## Deploy and rollback

Run on PC2 as `mjc`; the script checks the hostname, IP, install profile, passwordless sudo, Docker, and Compose before changing runtime state.

```bash
bash /srv/apps/fapaifang-worker/releases/<release-id>/ops/pc2-linux/deploy.sh \
  --release-dir /srv/apps/fapaifang-worker/releases/<release-id> \
  --release-id <release-id> \
  --dry-run

bash /srv/apps/fapaifang-worker/releases/<release-id>/ops/pc2-linux/deploy.sh \
  --release-dir /srv/apps/fapaifang-worker/releases/<release-id> \
  --release-id <release-id>

# If the exact release images were built on another Linux/amd64 Docker host,
# loaded on PC2, and their tags were verified, skip the slow PC2 network build.
bash /srv/apps/fapaifang-worker/releases/<release-id>/ops/pc2-linux/deploy.sh \
  --release-dir /srv/apps/fapaifang-worker/releases/<release-id> \
  --release-id <release-id> \
  --skip-build

bash /srv/apps/fapaifang-worker/current/ops/pc2-linux/deploy.sh --rollback
```

The active link changes only after all nine containers report healthy. If a new release fails and a previous release exists, the script starts that previous release again. No reboot is required.

## Operator access and checks

- noVNC: `http://192.168.15.104:6080/vnc.html`
- CDP metadata: `http://192.168.15.104:9224/json/version`

Use noVNC only when Taobao requires manual login. The persistent profile keeps the session across container restarts. Do not open a second login window during the five-minute login window.

Routine checks on PC2:

```bash
docker compose -p fapaifang-pc2 \
  --env-file /srv/apps/fapaifang-worker/shared/runtime.env \
  --env-file /srv/apps/fapaifang-worker/current/.release.env \
  -f /srv/apps/fapaifang-worker/current/ops/pc2-linux/compose.yaml ps

curl -fsS http://127.0.0.1:9224/json/version >/dev/null
curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null
```

Healthy containers prove process readiness, not collection success. Final validation must also show a fresh NAS API status response in DB mode, a collection counter or claimed/completed job delta, and an analysis counter or completed AI result delta. A live challenge is needed before claiming that the automatic slider solve itself has succeeded.

The browser health check validates both outgoing credential roles locally, without
sending a challenge report. A recovery heartbeat or successful Cookie handoff does
not validate `/api/report_captcha`. When copying an existing container specification,
compare both credential paths with the rendered Compose environment; an old spec can
omit a role that current Compose already supplies. Preserve existing credential files.
After activation, check real report acknowledgements and cooldown resume events.

### 自动求解连续失败的退避

`collection_resume_confirmed` 仅表示 NAS 接受恢复调度，不表示验证码已通过。
首次达到失败阈值后仍使用配置的冷却时长；未出现真实认证成功时，冷却结束后
仅放行一次求解调用，继续失败则将等待时间翻倍，默认依次为 3、6、12、24、30
分钟，随后保持 30 分钟。若配置的基础冷却超过 30 分钟，不会缩短该配置。
一次调用内部仍受原有拖动、重试和超时预算约束，不等于只拖动一次。

跨轮计数 `solver_cooldown_cycles` 保存于现有 fallback state，重启、挑战换代、
过期 receipt 或恢复调度 ACK 不会清除；当前挑战的认证成功 ACK 才恢复初始额度。
此退避不启用人工接管、不改变 Cookie 或代理，也不保证站点接受自动验证。

### browser-solver Tab 堆积保护

PC2 启动器为独立心跳 watchdog 启用 `--browser-tab-guard`。它不等待 solver
主循环，在正常本地 CDP 响应下每 5 秒检查一次容器内部 `127.0.0.1:9223`；
只计 `type=page` 的 Tab（包括空白页、登录页和参考页），不计 iframe 或 worker。
默认上限设为 `11` 个（低于 `DEFAULT_CDP_PAGE_TARGET_LIMIT = 12` 的后台建页软上限，避免在 `page_count == 12` 时后台建页拒绝而 Tab Guard 不触发恢复的边界死锁；可通过 `CROW_BROWSER_TAB_GUARD_MAX_TABS` 覆盖，至少为 4），兼顾「初始页 + 2 参考页 + seed/detail 双挑战页 + 采集临时页」正常并发且不误触发整容器重启；不超过上限时不处理，超过上限时尝试关闭全部页面，而不是仅关闭超出的页面。

关闭使用 10 秒共享预算和单次最多 2 秒 socket timeout；失败或预算耗尽仍触发
现有 supervisor 退出，再由 Docker `unless-stopped` 重启 browser-solver 全部受管
进程。因而旧 solver 调用和并发新增页面也随本容器退出释放；不是在旧调用仍运行
时直接开新一轮。网络 timeout 不是严格 wall-clock 上限，不能承诺卡死时的恢复时限。

该紧急恢复会关闭本容器的登录/验证码页面，但不访问 PC1 CDP，不删除 profile、
Cookie、凭据或 fallback state，不清除退避预算，也不调整采集 Worker 数。
`browser_tab_overflow` 与 `browser_tab_overflow_restart` 日志记录检测数、关闭 ACK、
失败数和未尝试数，不记录页面 URL。关闭 ACK 不等于浏览器已退出；部署后仍须验证
容器重启、Tab 数和 solver 心跳。CDP 读取失败不猜测 Tab 溢出，既有心跳 watchdog
仍负责停滞检测。回归入口：`tools/test/test_pc2_browser_tab_guard.py`。

### 缺失挑战页恢复不重复分配 Tab

补建页面的导航 ACK 只表示命令被接受，页面之后仍可能重定向。恢复循环按阶段与
挑战 generation 保留已创建页面的 exact ID、请求身份和 CDP endpoint；同一请求的
已知自有页面仍存在但重定向到其他淘宝路由时，复用该页面执行原有 identity-first
导航和超时预算，不再每轮分配新 Tab。页面确实消失后才重新创建。

不导航借用页面，不将首页当作认证成功；自有页面进入登录或外部网站时保留且不再
额外开页。丢失导航 ACK 的同站页面继续等待确认，不重放未知结果。链接与详情交替
调度不会丢失各自的页面身份，其他请求、endpoint 或 challenge generation 不继承
旧权限。恢复日志包含 `target_id` 和 `redirected_target_reused` 原因，便于核对复用。
回归：`test_pc2_redirected_target_recovery.py`、`test_pc2_pending_navigation_loop.py`、
`test_pc2_maintenance_navigation_deferred.py`。
