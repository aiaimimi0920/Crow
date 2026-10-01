# Collection runtime settings

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](crow-data-root-compatibility.md).

Status: activated on NAS and PC2 on 2026-09-07 (Asia/Shanghai), with an installed
desktop/native HTTPS probe and a successful no-op apply receipt. See
`docs/design/neuro/HTTPS-CONTROL-ACTIVATION-20260907.md` for exact runtime evidence.
This runbook is not authorization for subsequent deployment, restart or SSH changes.

## Scope

The desktop settings page edits the collection engine only:

- Link, detail and AI-archiving worker counts, bounded to 2/8/8 and 16 total.
- Active-batch and idle-poll intervals for each stage.
- Detail success/failure pacing and per-item/per-batch attempt limits.
- AI base URL, model route, timeout, request retries and optional replacement key.

Blank AI key means preserve the current key. Keys are never returned to the editor.
Changing the model selects that explicit route for subsequent AI requests; leaving it
unchanged preserves existing candidate routes. Applying parameters and container health
checks does not prove successful AI inference.

The challenge-failure threshold for PC1 escalation is NOT exposed in this slice.
Existing visible manual-auth policy remains unchanged. Analysis here means collection
AI archiving, not the unfinished analysis or prediction product engines.

## Components and API

- `src/collection_settings_schema.py`: closed settings schema and environment mapping.
- `src/collection_settings_store.py`: separate SQLite revisioned control mailbox.
- `tools/collection_control_https.py`: independent, authenticated HTTPS control service.
- `src/server_collection_settings.py`: optional boundary for integration into the API server.
- `tools/pc2_settings_model.py`: pure inventory and Compose plan generation.
- `tools/pc2_settings_runtime.py`: bounded worker reconciliation and rollback.
- `tools/pc2_settings_controller.py`: settings client and durable apply receipts.
- `tools/pc2_collection_controller.py`: unified, opt-in settings/restart host controller.
- `tools/collection_control_lock.py`: shared operation and controller-instance locks.
- `tools/pc2_settings_release.py`: settings-preserving release/rollback integration.
- `tools/desktop_settings_client.py`: installed-bundle, app-CA HTTPS transport.
- `collector-desktop/src-tauri/src/settings_bridge.rs`: bounded native stdin bridge.
- `collector-desktop/src/desktop_settings.ts`: editor and app-managed confirmation.

Routes under `/api/collection/settings`:

| Route | Role | Contract |
| --- | --- | --- |
| `GET /` (without trailing slash in implementation) | operator | Effective/desired settings, revision, key-presence boolean and latest status |
| `POST /apply` | operator | Unique request ID, expected revision, closed config, optional key |
| `POST /poll` | agent | Observed inventory; claims one command at most once |
| `POST /result` | agent | Claim-bound applied/rolled-back/rejected/interrupted receipt |

Operator and agent tokens use the existing distinct engine-control token files.
They are not AI credentials. Request bodies are bounded to 16 KiB.
The controller and editor reject remote plaintext HTTP for settings. Use trusted HTTPS
or an authorized loopback-only SSH tunnel; never disable certificate verification.
The ordinary read-only desktop API may still use the configured NAS HTTP address.
The deployed native desktop reads its control origin, application CA path, operator
token path and absolute Python path from its installation configuration. It never
passes credentials or an AI key on a command line. No system trust store or SSH
forwarding policy was modified. This is server-authenticated TLS plus role tokens,
not mutual TLS; a normal browser does not automatically trust the private CA.

## Apply and recovery semantics

1. Editing and non-secret local drafts remain available before PC2 connects. A draft is
   explicitly not live configuration. Save-and-apply first fetches actual inventory,
   checks the draft baseline and confirms replacement; no default is presented as live.
   External inventory changes advance the revision. Drafts are scoped to the NAS API
   origin, survive app reload and exclude the AI key. Reading live values over a draft
   requires confirmation. A missing route/offline controller saves but does not apply.
2. NAS checks revision, fresh controller heartbeat and single-flight status. Reusing
   one request ID with different settings is rejected; identical retries are idempotent.
3. Unclaimed requests expire after 120 seconds. Claims are not replayed. A claim without
   a confirmed result becomes `unknown` after 900 seconds and blocks further applies.
4. PC2 writes an interrupted receipt before any Docker mutation. On controller restart,
   it retries receipt delivery, not the container operation.
5. Runtime requires exact provisioned image/environment/bind-mount identity, contiguous
   bounded workers and homogeneous exposed settings within a stage. Unsupported services
   and named-volume layouts fail closed; they are not silently reconciled.
6. Worker images are pinned to the current image IDs. Only affected workers are recreated
   with `--no-deps --no-build`; downsized workers are stopped, not deleted. The browser,
   PostgreSQL, persistent mounts and unrelated services are not changed.
7. A 300-second health/configuration check precedes success. Failure attempts a scoped
   rollback to the previous model and verifies it before reporting `rolled_back`.
8. A valid late receipt can settle an unknown operation. A lost command response or failed
   rollback requires operator inspection. Do not delete the mailbox to unlock it, replay
   an old command, or claim completion without matching actual containers.
9. The desktop polls requested/applying receipts every three seconds, including after
   losing a POST response. Five consecutive status-query failures stop automatic polling;
   manual refresh remains available. Changing credentials does not unlock an in-flight
   HTTP request or replay the POST. Pending/unknown operations block apply, not draft edits.

NAS state defaults to `<runtime-root>/control/collection-settings/`; PC2 state defaults
to the repository-derived `CrowData/settings-controller/`, with a CLI override supported.
State directories are owner-only on Linux; secret/Compose files are mode 0600. Keys are
not encrypted at rest: host filesystem permissions and backup access remain essential.
Unclaimed NAS keys are removed after claim/expiry on a subsequent mailbox transaction;
private PC2 before/after models retain rollback credentials. Do not publish these files.

## Deployed transport and persistence

1. NAS control uses `https://192.168.15.200:18443` in an independent container. Its only
   writable mount is the existing control mailbox root; it has no business database
   credentials, database volume or Docker socket. Port 8001 remains the ordinary API.
2. PC2 state is provisioned in the persistent shared `collection-control` directory,
   outside worker releases. The resolved Compose baseline was reconciled against actual
   container environment values before activation; model/candidate/reasoning drift was
   preserved rather than overwritten. Private `active.json` is authoritative thereafter.
3. One systemd service owns settings and restart polling. Both operations and the normal
   deploy/rollback entry point use `operation.lock`. Restart targets are the validated,
   contiguous active worker set, not a fixed eight-container list. Durable restart receipts
   prevent a process crash from replaying Docker restarts.
4. The deploy script invokes the stable settings-aware helper whenever `active.json`
   exists. The helper rebases exposed settings and the AI key onto release images, refuses
   mount changes, pins locally available images, and commits active state only after health
   validation. Missing helper/state or an unresolved `release-operation.json` fails closed.
   Do not bypass this seam with an old deployment script or raw Compose invocation.
5. A controller restart must retain `active.json`, receipt journals and request directories.
   An interrupted release requires inspection of before/after models and actual containers;
   never simply delete the release marker to unlock writes. Protect all rollback artifacts
   because resolved models contain credentials.
6. Provision NAS settings storage with verified owner-only permissions. Synology inherited
   ACLs may override the mode requested by `mkdir`; check the resulting mode explicitly.
   Generate CA extensions from an explicit configuration to avoid duplicate extensions;
   include SKI/AKI and validate the chain in strict mode for Python 3.13 clients.

The unified CLI requires explicit `--run`, `--api-base`, `--ca-file`, `--token-file`,
`--compose-file`, ordered `--env-file` arguments and a private `--runtime-root`.
Ordinary tests remain offline. The ignored Rust installed-bundle probe additionally
requires explicit `CROW_LIVE_CONTROL_READ_ONLY=1` and issues only configuration/GET calls.

The PC1 challenge-escalation threshold remains a separately scoped, unimplemented setting;
it does not block the already activated worker/interval/retry/AI settings. Actual worker
recreation/rollback was tested with offline Docker fixtures; the live acceptance used
unchanged parameters and did not restart workers just to demonstrate a settings change.

## Offline verification

```text
python -m pytest tools/test/test_collection_settings.py tools/test/test_pc2_settings_runtime.py -q
npm --prefix collector-desktop run build
python tools/test/collector_ui_preview.py --port 1436
```

Use `collector_settings_ui_smoke.mjs` and `collector_settings_apply_race_smoke.mjs`
through the existing Playwright CLI run-code flow, with separate browser sessions.
It intercepts settings calls with synthetic inventory and blocks external requests.
The preview does not forward requests to NAS, read production credentials, or run Docker.
