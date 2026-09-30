# PC2 collection progress recovery - 2026-09-28

## Result

Added and activated a progress watchdog for the PC2 collection browser. It detects a
healthy container with pending collection work but no progress for 900 seconds.
This closes the gap in the existing watchdog, which only handled Docker-unhealthy
browsers. The earlier change removed unconditional browser restart after Cookie
import; it did not remove the unhealthy-container watchdog.

CAPTCHA solving algorithms were not changed. The latest read-only investigation
at 04:29 UTC found 24 solver executions since the browser deployment: 23 returned
challenge_retry_exhausted and one succeeded. These are execution outcomes, not a
per-drag success rate. The observed failures included explicit site rejection
while coordinates and browser processes remained available. No improvement in
CAPTCHA pass rate is claimed, and no challenge-bypass optimization was performed.

## Recovery behavior

- Observe fresh NAS collection statistics every 60 seconds through the installed
  browser's existing API credentials and private CA.
- Require pending detail or discovery work, a healthy running canonical browser,
  and at least one running discovery/detail worker.
- Track captured details, discovered link occurrences, completed discovery jobs,
  and exhausted discovery ranges. Movement resets the no-progress timer. Progress
  in either collection stage prevents disruption of the shared browser.
- After 900 seconds of continuously observed stagnation, preserve session Cookies,
  recheck browser identity, startup time and current collection/authentication
  state, and restart only that exact browser container.
- Restore the preserved session using the existing importer and verify its receipt.
  Keep private checkpoint files for diagnosis. Never delete the profile or database.
- Do not trigger during operator pause, CAPTCHA/manual-authentication handling,
  Cookie recovery, empty queues, invalid/stale statistics or unavailable observations.
  Authentication waits must not be treated as browser hangs.
- Keep a durable attempt cap of two; retry spacing grows to 1,800 seconds after the
  first attempt. Real progress resets the cap. Corrupt state, interrupted restart
  and failed session restoration require reconciliation instead of replay.
- Reuse the controller's operation lock and skip unresolved release/settings/restart
  operations. The existing unhealthy-browser watchdog retains its separate grace,
  cooldown and three-attempt cap.

## Implementation

- tools/pc2_collection_progress.py: read-only status probe and eligibility policy.
- tools/pc2_collection_progress_watchdog.py: observation window and durable recovery.
- tools/pc2_browser_session.py: private session checkpoint and verified restoration.
- tools/pc2_collection_controller.py: integrate progress recovery under the existing lock.
- tools/test/test_pc2_collection_progress_watchdog.py and test_pc2_browser_session.py:
  offline regression coverage with fake Docker, NAS and session operations.

## Verification

The final focused batch passed 38 tests in 4.48 seconds, covering the two new suites,
test_pc2_collection_watchdog.py and test_watchdog_state_preservation.py. This includes
actual restart decisions against fake Docker, exact targeting, session restoration,
no-restart states, observation gaps, persisted limits, new challenges appearing just
before restart, invalid receipts and controller operation guards.

Ruff formatting and the repository's selected I/F/E/B lint rules passed. The effective
code-line checker tests passed 19 tests; ratchet passed 1,394 files with none above
500 effective lines. No full historical/security/PostgreSQL suite was rerun.
An independent read-only review found no confirmed serious correctness issue; its
own test attempt used the wrong interpreter and was unavailable. The 38-test result
above is the primary agent's run using the repository venv.

## Installed PC2 verification

Private release and rollback files:
/srv/apps/fapaifang-worker/releases/20260928-progress-watchdog/

Only crow-engine-controller.service was restarted. No PC2 collection container or
NAS container was replaced or restarted during activation. The installed controller
was older than the checkout, so its unrelated receipt handling was preserved and
only the progress-watchdog integration and early return after liveness restart were
patched. The tested current liveness watchdog was installed as a required dependency.

Candidate compilation/import and a real read-only progress probe passed before
activation. All five installed source hashes matched the candidate manifest.
active.json, runtime.env, the agent credential and the CA retained their hashes.
The first activation attempt hit the owner-only lock guard because the deployment
process was root while the service belongs to mjc. It restored the old service
without changing source. The successful activation acquired the lock as the actual
service owner; directory permissions were not relaxed.

At 2026-09-28T04:58:57Z:

- Controller: active; progress state fresh and result=progress.
- Captured details: 157,060 at activation -> 157,065 at the subsequent observation.
- Link occurrences: 1,245,940 -> 1,245,969.
- Automatic progress-restart attempts: 0.
- Browser: healthy, ID 72d56087024eff11dd7dfc26d7d94f05bbb92a81adcd448563570bf2c62fba14.
- Browser start time unchanged at 2026-09-28T03:16:52.077633431Z; restart count 0.

This proves deployment, real observation and non-disruption while collection advances.
A natural 15-minute eligible stall has not occurred during acceptance, so a production
restart and post-restart recovery are not claimed. That path has offline regression
coverage. The existing challenge-handling system also logged a confirmed blocked
report at 04:10:23 UTC and cooldown recovery at 04:13:16 UTC; it was not changed here.

The runtime manifest, activation.json and verification.json are in the private release
folder. Revert only the five manifest-listed source files from backup (remove only
new files whose prior hash is null), under the same operation lock with the controller
stopped, then restart that controller. Preserve watchdog state and all runtime data;
do not use Compose recreation or delete pending operation journals.

## Local desktop and remaining scope

The previously verified installed desktop EXE was reused unchanged, SHA-256:
B6375A7D994FB5F08D56C0F8F5498B7A84C612C903CAF64EBD8A69AB9058613B.
Crow was restarted as PID 56780 from the installed directory. Its runtime config hash
was unchanged. scripts/update-collector-desktop-shortcut.ps1 refreshed Crow.lnk and
verified target, working directory and icon. This turn verified the process and
shortcut, not a new browser/UI acceptance run or a new desktop build.

The user's request to increase third-party CAPTCHA bypass success is not implemented.
The delivered change improves recovery from collection stagnation outside active
access challenges. Website rejection and normal authentication waits remain possible.
Previous unrelated dirty changes were preserved. No commit or push was requested or made.
