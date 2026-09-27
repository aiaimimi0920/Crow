# Collection engine deployment and verification: 2026-09-27

Final deployment checks: `2026-09-27 11:52 UTC`. NAS and all eight PC2 workers
run the verified collection candidate. The real-dependency isolated smoke
passed. Production unattended acceptance remains open for the pause and model
cooldown conditions recorded below.

## Scope and candidate

The user authorized deploying the new collection engine to NAS and PC2.
The immutable source is clean commit `42cf73045`, whose production source is
the previously verified C5 candidate. Earlier test evidence remains in
`collection-c5-c6-checkpoint-20260926.md`; those suites were not repeated.

Source archive SHA-256:
`037a6da2b9dfcb648d241ba39fc02dc996a1fab97ff1ef204c8e4a188586a2c1`.

Release roots:

- NAS: `/volume1/docker/fapaifang/releases/20260927-42cf73045`.
- PC2: `/srv/apps/fapaifang-worker/releases/20260927-42cf73045`.

Both received the same verified archive. The candidate uses the full
`Dockerfile`, pinned base images, and hash-locked Python dependencies.
An overlay on the older deployed dependency set was not used.

## Live inventory and configuration differences

The pre-activation NAS API ID was
`eb6f50f57535f96c452924c193e2863357828c074e4834b9f82620dd940eda3f`.
It binds `127.0.0.1:19520` to container port `8001`; the external HTTPS entry
remains `https://192.168.15.200:9520`. Retained historical containers exist.
No service-wide Compose recreation was performed.

The canonical PC2 browser ID is
`4116b7bff53c` (prefix). Existing seed, three detail, and four detail-analysis
workers initially used historical releases. A detail worker was already unhealthy
at the initial read-only inventory. Its database URL currently points at the
NAS database, so migration must not silently invent a different local DB.

Before activation, configure the API data root explicitly as `/data/datas`.
The candidate default is `/app/FPFData/datas`, which is not the existing NAS
persistent mount. PC2 workers need their old HTTP API address replaced by the
verified HTTPS entry, with `FAPAI_API_CA_FILE` and matching worker-token files.
The inspected live workers have neither of these credential/trust variables.
Existing NAS operator/agent and recovery credentials must be preserved.

## Model gate

Fresh NAS model discovery succeeded: HTTP 200, three models, configured
`xopqwen36v35b` present. Actual inference failed twice with HTTP 403:

```
type: permission_error
code: 11200
no valid authorization: the account lacks an active order,
has insufficient quota, or the order is invalid
```

The PC2 detail worker's historical `DeepSeek-V4-Pro-0813` was absent from its
provider's current model list. The PC2 detail-analysis worker's configured
`deepseek-v4-flash` was present and completed a minimal real inference:
HTTP 200, nonempty choices, provider-reported 55 total tokens. This is a model
connectivity check, not evidence of completed collection or AI archiving.
No monetary cost was available from that response.

The continuation adopted the existing PC2 `deepseek-v4-flash` configuration
for the candidate API and workers, retaining the previous specifications in
private rollback directories. No model credentials were copied into Git.

## Rollback preparation

NAS rollback directory:
`/volume1/docker/fapaifang/releases/20260927-42cf73045/rollback`.
It is mode 0700. Saved container specifications and the database dump are
mode 0600 and are not copied into this repository.

PostgreSQL container ID:
`9ea6c8cce67a8d19cf9152ff96abf03691c9b3303da69ce76caecb09c476edd4`.
`pg_dump -Fc` completed; `pg_restore -l` succeeded with 173 listing lines.
Dump size: 327,478,325 bytes. SHA-256:
`1ccee34cceb15130a78296735ccc0a103868830c252ee37a5c80007d8e32c946`.
This verifies a readable dump archive, not a full restore drill.

## Completed image and NAS activation

NAS built the complete candidate. PC2's duplicate build was cancelled after
sustained low download speed, and the verified NAS image was transferred to
PC2. Both hosts have the exact image ID:

`sha256:938c6149779f612ad026f3ce558a2c879929e3d322e2f4bf961ccd738ba30379`.

Candidate dependency, entrypoint, schema and isolated API checks passed before
activation. NAS initially rolled back because Nginx still used an HTTP backend
while the new API listened with TLS. The verified proxy candidate now uses the
HTTPS backend. The API also joins PostgreSQL's Docker network. Synology's
`HostConfig.Env` override was handled and the created container's actual
environment was compared against the candidate before activation.

The active NAS API is
`495d48822d8b8eef15c00d40a97488052b641d7cb3dabb197a38376537847755`,
started at `2026-09-27T10:36:15.501490896Z`. At `11:36 UTC`, it was running with
zero restarts, the expected image, `unless-stopped` restart policy, preserved
mounts and matching candidate environment. The proxy configuration matched
its verified candidate. The old API container remains stopped for rollback.

`/api/status` and `/api/collection/overview` returned HTTP 200 over verified
HTTPS. Status identified commit `42cf73045` and `db_mode=true`.
Final NAS receipt, including normalized source-hash assertions:
`/volume1/docker/fapaifang/backups/collection-20260927-42cf73045/runtime-verification-20260927T115206Z.json`.

## PC2 activation recovery

The interrupted second attempt rolled back all eight workers. The missing
`FAPAI_WORKER_HEARTBEAT_PATH` was identified from actual Docker health logs
and added to the staged specifications. The module entrypoint is
`python -m tools.docker_entrypoint`.

The third attempt passed the heartbeat-file check but rolled back when the
next health condition detected a missing output directory. Historical
`FAPAI_OUTPUT_DIR` values did not include the node scope that the command
builder actually used. The staged values now come from the candidate image's
own `build_command()` output, including each worker's distinct directory.

All eight exact output directories were verified using the real mounted
paths and official `check_worker()`. The heartbeat writer and health checker
agreed, and the output path matched the generated worker command. These
configuration probes did not start collection loops or write business data.
The earlier, narrower probe used `/tmp` for its output check and did not
establish this mounted-directory condition.

The fourth activation succeeded. At `11:52 UTC`, all eight containers were
Docker `healthy`, with zero restarts and official worker health-check exit 0.
Their actual environments matched the candidates, mounts matched the original
containers, restart policies were `unless-stopped`, and old containers were
stopped and retained. Earlier failed containers and their logs remain
available; no service-wide Compose recreation was used.

The worker-to-NAS check verified CA-validated HTTPS, source commit `42cf73045`,
HTTP 400 for an authenticated malformed seed payload, and HTTP 403 for the
same unauthenticated payload. Neither request created a business record.
The PC2 browser retained ID `4116b7bff53c` and its original start time
`2026-09-25T08:30:09.734341586Z`.

Current container ID prefixes:

| Worker | Container |
| --- | --- |
| seed-1 | `03b4e5b56469` |
| detail-1 | `1055bf192593` |
| detail-2 | `f83739a63f94` |
| detail-3 | `4a81ff4352ef` |
| analysis-1 | `af9b3a1150b4` |
| analysis-2 | `9e148f09866e` |
| analysis-3 | `f6949fad58c3` |
| analysis-4 | `912293f39ae1` |

Final PC2 receipt:
`/srv/apps/fapaifang-worker/backups/collection-20260927-42cf73045/runtime-verification-20260927T115214Z.json`.

Private PC2 rollback/configuration records:
`/srv/apps/fapaifang-worker/backups/collection-20260927-42cf73045/`.
This includes `worker-activation-attempt-2.json`,
`worker-activation-attempt-3.json`, original container specifications,
pre-change candidate copies, and `output-preflight.json`.

## Isolated acceptance with real dependencies: passed

The first resumed browser attempt exposed Docker hairpin connectivity:
`192.168.15.104:9224` timed out inside PC2 containers, while
`pc2-browser-solver:9224` answered successfully on the existing Docker network.
The probe now uses that internal endpoint. No browser, firewall or Chromium
sandbox setting was changed.

The next probe reached HTML submission but failed extraction because its new
isolated model-pool store had not been qualified. The final probe uses the
production qualification gate before submitting detail work. It retains pool
validation and uses a separate model-pool SQLite file.

The final probe completed all of these steps:

1. `deepseek-v4-flash` passed all five production qualification cases.
2. A new context in the existing PC2 browser captured `https://example.com/`.
3. Authenticated collection HTTP requests stored the seed and queued its HTML.
4. The real AI extraction path committed `is_processed=true` to isolated SQLite.
5. The archived HTML matched the captured bytes, and application shutdown
   completed. The probe container exited 0.
6. No analysis/prediction postprocessing import was attempted.

Evidence root:
`/srv/data/fapaifang-worker/acceptance/20260927-42cf73045-qualified/live-8c841988cd/`.
The root contains `acceptance.json`, `collection.sqlite3`, qualification state,
and the source archive under
`html_archive/2026/2026-09-27/capture-57cfc6c85dca4bf4b779d2029b83f4a7/`.
`acceptance.json` SHA-256:
`502146936ac9bec9764f58ab32d21cc8a314bbc79f86fbb952dafc96f08087dd`.

This is a real dependency smoke test with a public example page and isolated
data. It does not prove long-running Taobao collection, challenge recovery or
business-record quality. The legacy API metrics returned zero counters for
this qualified-pool route; those counters do not establish zero requests or
zero cost. No monetary cost is claimed.

## Local client and source verification

The local desktop still matched the previously verified C5 executable:
`B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B`.
After remote activation, Crow was restarted using that verified executable.
The new process was PID `30860`, with a native window handle and the expected
installed executable path. The adjacent `crow-desktop.runtime.json` hash was
unchanged. `scripts/update-collector-desktop-shortcut.ps1` refreshed and
verified the stable `Crow.lnk` target, working directory and icon using the
verified EXE SHA-256. No new desktop binary was required for this backend
deployment, and the existing EXE rollback copy remains available.

Those initial desktop checks did not exercise status retrieval in WebView2.
The user subsequently reported that the installed window could not read runtime
status. The client-level recovery and its evidence are recorded below.

No product source changed in this continuation. The source archive has CRLF
line endings in the inspected Python files; after line-ending normalization,
the installed application, detail processor and worker lifecycle sources
match commit `42cf73045`. This is separate from the exact image-ID comparison.

Fresh local gates: 19 effective-line checker tests passed; the ratchet passed
for 1,379 files, with none above 500 effective lines. Eight deployment scripts
passed Python AST and UTF-8/no-BOM checks. The unchanged C5 broad-suite evidence
was reused with its original scope and skip conditions, not rerun or combined
with this runtime smoke as a new full-suite result.

## Remaining production acceptance boundary

The final NAS status returned `paused=true`, with 330,786 records, 154,996
captures and 121,083 AI-finalized records. Recent seed-worker cycles reported
`seed_collection_paused / captcha_solver_running`. Recent analysis-worker
cycles reported `detail_worker_llm_unavailable`, with no items attempted in
those cycles. Container health therefore does not prove active collection.

A read-only check of the actual analysis worker's shared qualification store
confirmed `deepseek-v4-flash` has score 5, but its per-model
`blocked_until` was `2026-09-27T12:05:52.614202Z`. The configured production
timeout was 180 seconds. Account cooldown was zero; the per-model temporary
block made the production preflight return 503. No cooldown, qualification
result, challenge state or production pause was manually reset to force a
passing result.

Remote activation, restart persistence configuration, authenticated transport,
source identity and the isolated real-dependency collection lifecycle are
verified. C6's full unattended production collection/challenge-recovery gate
remains open. This deployment makes no completion claim for the separate data
analysis or prediction product engines.

To roll back, use the exact old/new IDs in each private activation manifest.
Stop and rename only the new canonical containers, restore the retained old
containers to their canonical names, and start them. NAS rollback also restores
`nginx-before.conf` to the existing Crow Nginx configuration and reloads that
verified Nginx PID. Do not run service-wide Compose recreation while retained
containers share Compose labels. Database restoration is not part of a normal
application rollback; the readable PostgreSQL dump is retained separately.

## Installed desktop connection recovery: 2026-09-27 12:18 UTC

The installed Crow window reproduced the user's exact status-read failure.
Its configured API was already `https://192.168.15.200:9520`. A Windows HTTPS
request failed with a certificate trust error, while a Python request from the
same PC, explicitly using the configured CA file, returned HTTP 200 for
`/api/collection/overview` (11,315 response bytes).

The configured `Crow Local API CA` was absent from both the current user's
and local machine's trusted root stores. `desktop_http.ts` uses WebView2
`fetch()` for overview, regions and items; the configured `FAPAI_API_CA_FILE`
does not configure WebView2's trust store. Thus the earlier backend-only HTTPS
checks and correct desktop EXE hash did not establish desktop connectivity.

After verifying the configured CA against the actual API, the existing public
CA certificate was imported into `Cert:\CurrentUser\Root` only. Its SHA-1
certificate-store thumbprint is
`41DE6E3881BFC4617EFE97E309EC568400EC6B32`. No certificate validation was
disabled. The CA file, API address, runtime configuration and installed EXE
were not replaced. No NAS/PC2 service or authentication browser was restarted.
Only the local Crow application was restarted, as PID `52576`.

At `2026-09-27T12:18:01Z`, Windows UI Automation invoked the installed window's
actual `refresh` button and verified successful completion. The rendered
window showed runtime state `paused`, authentication required, 330,786 links,
154,996 detail captures, 121,083 analyzed records, loaded region controls,
and the link-stage list `175790` items with rows `1-10`. The original
status-read failure was absent. A native `PrintWindow` capture was visually
inspected; it contains the actual installed Crow window and populated cards
and rows. The first screen-copy attempt captured the desktop background and
was discarded as invalid evidence.

Local evidence (ignored runtime artifacts):

- `artifacts/crow-desktop-connection-20260927/verification.json`.
- `artifacts/crow-desktop-connection-20260927/installed-crow-after-refresh.png`.
- Screenshot SHA-256:
  `2C763196080C186ABA2A9345E8BDBABB5770132C8E1C9F29055F709F5478710C`.
- The EXE SHA-256 remains the C5 value recorded above. Runtime configuration
  SHA-256 remains
  `FFCF989F497033B96D51A37731D2AC2D30BE19CC69DF93ACF4AB1CB7A4A5F5A9`.
- The official shortcut script refreshed `Crow.lnk` and reverified its EXE
  hash, target, working directory and icon.

The scoped rollback for this trust-store addition is removal of that exact
thumbprint from the current user's Root store, followed by a Crow restart;
the pre-fix state had no such entry. No pre-existing certificate was replaced.

This fixes desktop status/list connectivity. Production pause and challenge
states were preserved. No pause/resume, authentication or worker-restart action
was exercised, and the screenshot's restart-controller hint is not evidence
of controller availability. The production acceptance gates above remain open.
Product source is unchanged; the previous C5 and effective-line gate evidence
is reused, with this real installed-client check as the focused verification.

## Authentication synchronization follow-up

The later credential rejection and PC2 receiver readiness defects were fixed
and deployed separately. See [auth-sync-recovery-20260927.md](auth-sync-recovery-20260927.md)
for current NAS/browser container IDs, exact changes, focused tests, installed
desktop evidence, rollback records and the remaining real Cookie-handoff gate.
