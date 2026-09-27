# Local Crow scheduled-task repair - 2026-09-27

## Outcome

The local task \FapaiFang\FapaiFangNasAuthRecovery has been repaired and remains enabled, with one-minute polling and IgnoreNew concurrency. Fresh scheduled executions at 09:21 and 09:27 local time returned LastTaskResult=0. Its previous execution returned 1.

## Cause

The action still referenced the 20260912-seed-auth-pending-072208 release and http://192.168.15.200:8001/api. That endpoint was unreachable in a fresh bounded request (HTTP 000). Current Crow uses https://192.168.15.200:9520 with an explicit trusted CA. The old scheduled action had not followed that migration.

A second deployment defect was found: the installed current watcher was missing collection-api-origin.ps1, pc1-recovery-http.ps1, pc1-auth-recovery-policy.ps1 and tools/pc1_recovery_request.py. Updating only the task address or redirecting it to that incomplete installation would not suffice.

## Repair

- Re-registered the task using the installed current watcher, verified HTTPS origin, CA and existing Python.
- Preserved its UNC data root, token, snapshot location, port 9225 and existing human-authentication browser profile. The UNC token and desktop configured token were verified identical without printing values.
- Installed the four missing helpers and the updated task registrar, verifying source/installed hashes.
- Added those dependencies to scripts/deploy-collector-desktop-local.ps1 for future installations.
- Set -WindowStyle Hidden in scripts/register-pc1-nas-auth-recovery-task.ps1, keeping normal authentication browser presentation intact.
- Backed up the task XML and replaced registrar under %LOCALAPPDATA%/FapaiFangCollectorDesktop/backups/recovery-task-20260927-092007/. Existing configuration hash remained unchanged.

## Verification and remaining boundary

The installed production HTTP helper successfully authenticated to NAS before task registration. Actual scheduled runs subsequently returned 0 and updated the recovery state, with target_lookup_failed=false.

The nested authentication check currently returns pending (exit 2). Direct read-only examination explained it: the selected page is a healthy list page, while the full recovery check requires a healthy detail page and reports No healthy open Taobao detail page is available in the PC1 browser. The watcher handles this pending state with task exit 0 and does not publish an unverified snapshot. This repair does not establish that PC2 collection or the site's authentication challenge has recovered.

Relevant recovery transport/handoff tests: 27 passed in 19.54 seconds. PowerShell syntax checks passed. Effective-code-line checker tests: 19 passed. Ratchet: 1380 files and no files above 500 effective lines. git diff --check passed. No broad historical suite was run.

The unchanged verified desktop EXE was gracefully restarted and its stable Crow.lnk refreshed. Its SHA-256 remained B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B. No human-authentication browser, computer, NAS or PC2 service was restarted for this local task repair. Existing unrelated changes were retained; no commit or push was performed.
