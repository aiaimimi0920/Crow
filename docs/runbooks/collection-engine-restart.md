# Operator-requested PC2 engine restart

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](crow-data-root-compatibility.md).

## Scope and activation boundary

This is an opt-in control channel, separate from authentication recovery.
Source changes and offline tests alone do not activate it. Apply the live-operation
authorization and scoped deployment rules in `AGENTS.md`; ordinary read-only
inspection does not authorize a restart. The button does not invoke deployment.

As of 2026-09-15, the installed desktop uses its native private-CA HTTPS bridge
and existing operator token file. It does not require the user to paste a token.
The button is labelled `重启 PC2 采集`, with confirmation and five-second receipt
polling. A missing HTTP response is not treated as successful execution.

The desktop sends a confirmed restart request to the NAS. A controller running
on the PC2 **host**, outside the worker containers, polls for the request and
restarts only the validated, contiguous active collection containers in Compose project
`fapaifang-pc2`:

- `pc2-seed-1`
- `pc2-detail-1` through `pc2-detail-3`
- `pc2-analysis-1` through `pc2-analysis-4`

The controller validates Docker Compose project/service labels, canonical names and container IDs
before executing. It does not accept commands, shell arguments, container names,
paths or hosts from the NAS. It uses `docker restart --time 30 <validated IDs>`,
not `compose up`, rebuild, redeploy, reboot or Docker daemon restart.
The separate browser solver, PC1 authentication browser, volumes, cookies,
images and stored products are untouched.

Stopped/created release backups with noncanonical names are excluded even when
they retain the same Compose labels. Running noncanonical workers and duplicate
canonical identities fail closed. Never use service-wide Compose recreation when
retained backups share those labels.

## Automatic recovery

Docker `restart: unless-stopped` supervises abnormal container exits. The unified
`crow-engine-controller.service` uses systemd `Restart=on-failure` for its own
crashes. Verify both policies on the installed instances, not just source YAML.

The host controller additionally checks the canonical PC2 collection browser
before polling NAS. If Docker reports it continuously unhealthy for 120 seconds,
the controller rechecks the exact ID/start time/health and restarts only that ID.
This handles a stalled browser inside a still-running container. It does not
operate the PC1 human-authentication browser or solve authentication challenges.

`watchdog.json` records attempts before mutation and enforces a 600-second
cooldown across controller restarts. Deliberately stopped containers are not
revived. The watchdog uses the shared operation lock and yields to unresolved
settings, restart or release journals. A restart call is recorded as readiness
pending; Docker health and actual collection progress must be checked separately.

## Configuration for a separately authorized activation

Provision two different random ASCII tokens of at least 32 characters. Store
them in owner-readable secret files; do not put their contents in Git, command
arguments, logs or documentation. Accepted characters: letters, digits, `_`, `-`.

NAS environment:

| Variable | Meaning |
| --- | --- |
| `FAPAI_ENGINE_OPERATOR_TOKEN_FILE` | File containing the desktop operator token |
| `FAPAI_ENGINE_AGENT_TOKEN_FILE` | File containing the different PC2 controller token |
| `FAPAI_ENGINE_CONTROL_ROOT` | Optional durable runtime root; default is repository-local `CrowData/` |

For a containerized NAS, explicitly point the control root at a persistent
writable data mount. The mailbox is `<root>/control/pc2-engine-restart.sqlite3`.
It contains request IDs, timestamps, claims and fixed outcome codes, not cookies
or arbitrary process output. Back up this database with the runtime data. Do not
delete or restore an older mailbox while a controller may have an active claim.

PC2 requires Python and access to its local Docker daemon. The controller must
use the NAS **agent** token; the desktop receives only the **operator** token.
In browser-only previews, the desktop token is entered in Settings > API connection
and remains only in the current window. Changing the API address clears it. The
installed application reads its existing private token file through the native bridge.
Use HTTPS or a protected tunnel for token-bearing traffic. Plaintext remote HTTP
is rejected by the controller unless the operator explicitly opts into an
isolated trusted LAN with `--allow-insecure-http`.

After live activation has been separately approved, run from the PC2 checkout:

```sh
python tools/pc2_engine_controller.py --api-base "$FAPAI_CENTRAL_API_BASE_URL" \
  --token-file "$FAPAI_ENGINE_AGENT_TOKEN_FILE" --run
```

This command **enables remote restart execution**. It is not a validation
command. Supervision/service registration is intentionally not performed by the
source change or test suite. Until both tokens and a live controller are present,
the button remains unavailable. Docker access is equivalent to host-level power;
keep the helper and its token accessible only to the designated operator.

## Protocol and guarantees

- `POST /api/collection/control/restart`: operator token plus `request_id` only.
- `POST /api/collection/control/restart/poll`: agent token, empty JSON object.
- `POST /api/collection/control/restart/result`: agent token, `request_id`,
  server-issued `claim`, fixed `result` code.
- Header: `X-FAPAI-Control-Token`. Missing, invalid, identical-role or unconfigured
  credentials fail closed. Redirects are not followed by the controller/client.
- Only one pending/executing request exists at a time. Duplicate submissions
  return its receipt. A previously claimed request is never automatically
  claimed again, including after a process restart or HTTP timeout.
- The controller polls every 5 seconds. Availability requires a heartbeat within
  30 seconds. Unclaimed requests expire after 120 seconds; missing execution
  receipts become `unknown` after 600 seconds, never automatic retry.
- A successful receipt requires all targeted original container IDs to be running,
  healthy and to have changed `StartedAt`. This proves **worker restart and
  readiness**, not successful auction capture or challenge resolution.
- Health checks are bounded to 240 seconds after the restart call. Execution
  uncertainty is reported as `unknown`, not success. The user must inspect PC2
  before intentionally submitting a new restart after an uncertain result.
- The installed HTTPS restart endpoint preserves operator pauses and challenge
  state. Use Start separately to release an operator pause. Ordinary Start does
  not clear challenge state or claim authentication; an active challenge still
  requires the PC1 auth workflow. The older data-API restart path resumes an
  operator pause at acceptance, and is not the installed native transport.

## Offline verification

```sh
python -m pytest -q tools/test/test_collection_engine_restart.py tools/test/test_pc2_engine_controller.py
node --experimental-strip-types --test collector-desktop/src/desktop_overview.test.ts
```

These tests use temporary SQLite files, fake Docker responses and synthetic
tokens. They never run the controller against live Docker or call PC2/NAS.
