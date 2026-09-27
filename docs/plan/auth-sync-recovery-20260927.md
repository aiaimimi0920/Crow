# Authentication synchronization recovery: 2026-09-27

The last task in conversation `01a0e287-572e-76f2-a488-48ebd1fa609a` was to fix
`链接采集：认证同步凭据未被 NAS 接受。` The reported credential rejection is fixed
and deployed. The installed desktop now authenticates successfully, and the
real PC2 receiver advertises protocol V2 readiness continuously.

## Cause and deployed changes

The NAS API did not set `FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE`. Its effective
path was `/data/datas/nas-auth-recovery.token`, which did not exist. The
existing credential was at `/data/secrets/nas-auth-recovery.token`.
The installed desktop reproduced `token_rejected` before the change.

NAS now explicitly points to the existing secrets file. Only that environment
entry changed; the image, other environment entries, mounts, ports, networks,
restart policy and credential bytes were checked against the original.
The current API ID is
`6bb278e90bafc042c7509c247b341d37b2b6e83a9e4a03dc57a77b11f8cbc5df`.
Its image remains
`sha256:938c6149779f612ad026f3ce558a2c879929e3d322e2f4bf961ccd738ba30379`.
Activation verification completed at `2026-09-27T13:06:45Z`.

This exposed a second synchronization blocker: the PC2 browser receiver still
used `http://192.168.15.200:8001/api`, which refused connections, and its old
receiver attempted to advertise readiness through a GET query. The current
NAS requires an authenticated POST heartbeat. A read-only request from the
old browser container proved its existing token and CA already worked with
the HTTPS API.

An immutable overlay on the existing browser image now carries exactly three
modules from the verified collection image above:

- `tools/pc2_auth_recovery.py`: protocol V2 POST heartbeat and token validation.
- `tools/internal_api_http.py`: verified HTTPS transport.
- `src/collection_api_credentials.py`: destination-bound credentials and CA.

The receiver now uses `https://192.168.15.200:9520/api` and the existing
`/data/secrets/crow-20260927-ca.pem`. Candidate checks covered imports into
the existing solver, real authenticated HTTPS GET, and an isolated V2
heartbeat contract with no production POST. The image built successfully
before activation. A first receipt-parser attempt encountered import logging
before JSON; parsing the final JSON line completed the preflight without
rebuilding or activating the failed receipt attempt.

The new PC2 browser container is
`18c0cdae5cfedd65597fe0bd963ff7a86e62d4aa68d888de6804784b70b682b2`, image
`sha256:4c4bb1cfeae3d05f008ff38ed51af57d2366adcf08ba802fb763798fad12ad8c`.
Activation passed at `2026-09-27T13:34:46Z`. Installed module hashes matched
all three candidate hashes. Browser profile and other mounts were preserved;
the recovery token and CA bytes were unchanged. Both updated containers use
`unless-stopped`. Compose label matches included stopped backups, so both
cutovers used exact container IDs, with no service-wide Compose recreation.

## Fresh verification

The installed desktop's own Python interpreter, runtime configuration and
`RecoveryClient` returned:

- authorized recovery GET: `ok=true`, `enabled=true`;
- `stage_auth_protocol=2`, `pc2_stage_auth_ready=true`;
- missing token: HTTP 403; invalid token: HTTP 403.

The ready flag was rechecked more than 120 seconds after activation, beyond
its expiry window. It came from the real receiver loop, not a manual test
heartbeat. Final PC2 inspection showed browser and seed worker both healthy
with zero restarts. The seed worker retained its original ID and start time.
The last three minutes of browser logs contained no certificate-verification,
connection-refused, HTTP 403, heartbeat-rejected or recovery-error markers.

Local Crow was restarted as PID `53136`. Its verified C5 EXE and runtime
configuration hashes remain unchanged. The official shortcut script refreshed
`Crow.lnk` and verified target, working directory, icon and EXE hash.
At `2026-09-27T13:41:53Z`, UI Automation invoked the actual installed
window's refresh button. Status, counters and list loaded successfully.
The screenshot was visually inspected and shows 330,786 links, 154,996 detail
captures, 121,084 analyzed records and 175,790 link-stage list items.

Evidence: `artifacts/crow-auth-sync-20260927/verification.json` and
`artifacts/crow-auth-sync-20260927/installed-crow-after-refresh.png`.
Screenshot SHA-256:
`250C1DEA30193302C407C2CB4AD2280F18C0602B904B9F83DBAD4738C618069F`.

Focused tests: 37 passed across `test_pc2_auth_recovery.py`,
`test_internal_api_http.py` and `test_collection_api_credentials.py`.
The first run hung in an existing test whose mocks still targeted the retired
facade after module ownership moved. Its mocks now target the actual loop,
control and probe modules, preserving the exit-code and heartbeat assertions
and avoiding real browser access. The diagnostic timed-out processes were
stopped. The corrected suite completed in 2.45 seconds after formatting.

Ruff 0.16.8 check and format check passed for the changed test. Effective-line
checker tests passed 19/19; the final ratchet passed for 1,379 files, none above
500 effective lines. `git diff --check` passed. No full historical or release
suite was rerun. Product source was not edited locally; the tracked code
change is the test ownership correction and formatting. Earlier README and
deployment-note changes were retained. No commit or push was requested.

## Acceptance boundary

Credential rejection, secure desktop-to-NAS transport, PC2 receiver protocol
readiness and installed-window refresh are verified. No production Cookie
snapshot was submitted as a test, and no human challenge was marked complete.
The UI still reports link collection awaiting authentication and a paused
runtime. The user can reopen link authentication and complete the current
challenge using the normal UI. A fresh real Cookie handoff and successful
Taobao challenge recovery remain user-session acceptance, not established by
these credential/readiness probes. PC1's human-authentication browser was
not restarted. The screenshot also shows an unavailable restart controller;
that separate settings/control path was not exercised by this repair.

## Rollback

NAS private records:
`/volume1/docker/fapaifang/backups/auth-token-path-20260927T130520Z/`.
The retained original API ID is
`495d48822d8b8eef15c00d40a97488052b641d7cb3dabb197a38376537847755`.
The directory contains `before.json`, `candidate.json` and
`verification.json` (private permissions; container specs contain secrets).

PC2 private records:
`/srv/apps/fapaifang-worker/releases/20260927-auth-receiver/`.
This contains the before/candidate specs, original modules, Dockerfile,
build log, preflight receipt and activation receipt. The original browser ID
`4116b7bff53c80d502a93e1c517ef2b5f2546224b7624756c01e11307fa0988c`
is stopped and retained. To roll back either application, stop and rename
only its new exact ID, restore the retained old ID to its canonical name and
start it. Do not recreate the Compose service or restore the database.
Rollback restores the former connection/protocol defects as well.
