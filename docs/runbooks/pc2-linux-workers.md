# PC2 Debian collection and analysis workers

This runbook replaces the retired Windows Scheduled Task deployment on PC2. It does not migrate Windows executables, drive mappings, Edge profiles, or Task Scheduler state.

## Runtime topology

PC2 (`192.168.15.104`) runs one Compose project named `fapaifang-pc2`:

- `pc2-browser-solver`: persistent headed Chromium, Xvfb, Fluxbox, x11vnc/noVNC, CDP, and the automatic slider solver in one display session.
- `pc2-seed-1`: list-page collection.
- `pc2-detail-1..3`: raw detail-page collection.
- `pc2-analysis-1..4`: AI-only analysis of already collected raw records. These services do not depend on browser health, so collection challenges do not stop analysis.

The central API and PostgreSQL remain on NAS (`192.168.15.200`). The LLM gateway remains on `192.168.15.20:8317`; analysis routes to the gateway's current concrete DeepSeek V4 Flash model first and DeepSeek V4 Pro model second. Re-check `/v1/models` before changing these IDs because the unversioned aliases are not guaranteed to exist.

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
- `OPENAI_BASE_URL=http://192.168.15.20:8317/v1`
- `OPENAI_API_KEY`
- `OPENAI_MODEL=deepseek-v4-flash-0731`
- `OPENAI_MODEL_CANDIDATES=deepseek-v4-flash-0731,deepseek-v4-pro-0813`

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
