# C5/C6: delivery and acceptance checkpoint

Date: 2026-09-26. C5 source preparation is verified. Local desktop activation is
verified. C6 remains open for real AI/browser acceptance and remote activation.

## Candidate and source scope

This continues session `01a0e099-0169-7621-aea5-087ea7f71c85` from
`8a4e75529` on `quality-review-fixes`. C4 and C5 changes were tested together in
the working tree before checkpoint commits. Intermediate commits are recovery
boundaries, not separate full acceptance claims.

Recovery commits: `f376afcf5` (C4 maintenance and native route ownership),
`0cc97c435` (isolated crash-probe scheduling). This document is committed with
the C5 entrypoint/CI checkpoint. No push or remote release is claimed.

`auto/main.bat` launches `tools/run_collection_api.py`, which delegates to the
production collection server with its existing port/TLS configuration. The
isolated API tool remains a separate test entrypoint. Shared native location
handlers keep the collection route set independent of evaluation imports.

The full NAS source digest includes Python runtime owners under `src/` instead
of identifying new collection code only through the old server facade. Full
Docker build contexts already include these modules. Desktop is a remote API
client; the new backend modules are not unnecessarily copied into its helper
payload. Existing paths, roles, HTTPS and browser sandbox policy are retained.

## Verification

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| C4 maintenance | 71 passed; 7.59 s runner | Temporary runtime; no business DB |
| Windows delivery | 100 passed; 7.77 s runner | Includes all eight real CMD tests |
| Auth crash matrix | 90 passed; 47.22 s runner | Fresh process and directory per crash; four concurrent workers |
| fast | 1,473 passed, 2 skipped; 56.91 s runner | `artifacts/c4c5-fast-verified-timing.json`; unchanged 60 s limit |
| security | 750 passed, 4 skipped; 128.64 s runner | `artifacts/c4c5-security-verified-timing.json`; unchanged 180 s limit |
| Dedicated PostGIS | 42 passed; 39.91 s runner | Loopback port 25433, database `crow_quality`, unique test schemas |
| Linux delivery | 92 passed, 8 skipped; 10.75 s runner | Read-only repository mount; CMD tests explicitly Windows-only |
| NAS shell syntax | Passed | `bash -n scripts/deploy-nas-central-api.sh` in Linux container |
| Workflow validation | Passed | actionlint; shellcheck/pyflakes disabled for this structural check |
| Desktop TS/lint | Passed | Existing project commands |
| Desktop unit/browser | 43 unit and 3 Playwright smoke passed | Browser fixtures; no production collection requests |
| Rust | 9 passed, 1 explicit live probe ignored offline; fmt passed | `cargo test --locked`, `cargo fmt --check` |
| Desktop release | EXE, MSI and NSIS build succeeded | `npm run tauri:build` |
| Installed settings bridge | 1 explicit read-only probe passed | Installed helper/config; real configured settings endpoint |
| Static/size | Affected CI Ruff/mypy passed; 19 checker tests passed | Ratchet: 1,379 files, none over 500 effective lines |

The broad suites preceded only the later Windows platform marker/CI wiring and
documentation changes; no production Python source changed after those runs.
Windows delivery and Linux delivery were rerun for that platform change. Skips
are not counted as passes. Fast has only about three seconds of timing headroom;
one passing run does not establish stable performance across machine load.

The first PostgreSQL attempt used a plain PostgreSQL image and failed three
PostGIS-dependent migrations. It was replaced by a separate isolated PostGIS
container, where the complete PostgreSQL suite passed. Both containers created
by this session are stopped; no unrelated database/container was changed.

Linux first exposed eight CMD execution failures. The tests now declare their
actual Windows platform requirement, and the Windows CI job explicitly executes
them. Assertions, test matrices and runner deadlines were retained.

## Local installation

The verified EXE was applied using `update-collector-desktop-exe-only.ps1`.

- Installed path: `C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`.
- SHA-256: `B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B`.
- Previous EXE backup: `backup\exe-only-20260926-224313-fcfed479\fapaifang_collector_desktop.exe` under the installation.
- Started process: PID 47492; executable path and installed hash verified; native window handle observed.
- Adjacent `crow-desktop.runtime.json` hash was unchanged.
- Stable `C:\Users\vmjcv\Desktop\Crow.lnk` target, working directory and icon were verified by the shortcut script.

This proves local client installation and read-only settings integration. It
does not prove that the NAS API or PC2 worker is running this candidate.

## Remaining C6 boundaries

NAS and PC2 were not deployed or restarted. The checkout has no `env.nas.local`
or PC2 Linux `runtime.env`, and no confirmed current Linux SSH user/key mapping.
The old `Admin@192.168.15.104` batch SSH probe failed public-key authentication.
An asynchronous request asks for existing deployment configuration locations;
no passwords, private keys or tokens are requested.

Local `docker.local.env` has nonempty model configuration, and the documented
PC2 CDP endpoint answers version discovery and a read-only `Browser.getVersion`
command. These connectivity facts alone do not establish live collection
acceptance. No existing business records are used for these probes.

The isolated probe reached real browser capture of `https://example.com/`,
authenticated collection HTTP seed/detail submission and an actual AI request.
It did not complete: `COLLECTION_DETAIL_EXTRACTION_FAILED`, stage `extraction`,
`HTTPError`, two attempts, exhausted. The record remains `is_processed=false`,
and its input HTML is retained in `artifacts/c6-live-b57f96b52b/` with a separate
SQLite database and failure sidecar. The harness timed out during shutdown;
no matching Python probe process remained afterward. This is failed acceptance,
not a success or a completed lifecycle proof.

Read-only model discovery returned HTTP 200 with 24 models. Configured model
`grok-4.6` was absent; `OPENAI_MODEL_CANDIDATES` contained only `grok-4.6`.
No substitute model was guessed and no deployed configuration was changed.
An earlier PowerShell-inherited proxy environment also caused CDP 400/502 and
connection timeouts; the clean subprocess path reached capture. The native CDP
WebSocket handshake and read-only `Browser.getVersion` both succeeded.

The temporary probe is `artifacts/c6_live_probe.py`, outside version control.
It uses a new browser context and closes only that context. It does not navigate
existing tabs or close/restart the PC2 browser. Actual model cost was not
available from the failed run and is not reported as zero.

Before remote activation: identify the actual release/config roots and exact
canonical containers, inspect Compose labels for retained backups, back up
replaced artifacts, activate only the verified candidate, and verify installed
hashes plus collection behavior. Do not service-wide recreate backup-labelled
containers or restart the human-authentication browser.
