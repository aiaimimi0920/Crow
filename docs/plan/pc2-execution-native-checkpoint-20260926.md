# PC2 native execution checkpoint (2026-09-26)

Status: this slice and its fast milestone are verified.
Overall R1-R9 remains incomplete. Deployment/restarts remain deferred.
Source: HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus inherited worktree
changes (400 status entries at verification). No commit or push was requested.

## Native execution

Seven existing functions now retain original execution-module identity:
single-attempt solve, child IPC entry, deadline supervision, stale-target close,
failed-target rotation, missing-target rebuild, and post-resume target resolution.
The count includes both run_solver_local and run_solver_local_with_deadline
as separate entrypoints and the child entrypoint.

Explicit imports replace seven wildcard dependencies. A narrow ExecutionSolver
protocol and lazy class loader avoid initializing the solver on module import.
The process entry remains a module-level native function suitable for spawn
lookup; the existing real-spawn unreachable-CDP regression passes.

Attempt limits, terminal human-verification signaling, terminate/kill handling,
keepalive preservation, login-window preservation, regional list identity and
post-resume target cleanup retain their existing contracts. New tests cover
native export identity and child SystemExit reporting with both a connected and
disconnected parent pipe. The pipe closes in both cases.

Tests now replace dependencies in the execution owner. Loop-level replacements
remain at the facade until loop ownership moves. The first focused run found
one remaining nested seam: cooldown resume calls native target resolution, whose
probe dependency no longer reads facade globals. Its test now patches the native
execution probe and still asserts immediate periodic probing is suppressed.

## Results

- Initial solver/seed/manual focused run: 92 passed, 1 failed (the test seam above),
  runner 42.05 s. Repair check: 1 passed, runner 3.14 s.
- New IPC/import checks: 19 passed, runner 4.08 s.
- Final affected PC2 boundary: **170 passed**, runner **45.38 s**.
- Fast milestone: **1437 passed, 2 skipped**, runner **49.74 s**
  (pytest 48.26 s), below the unchanged 60 s threshold.
- Full native Ruff, strict mypy and formatting passed. Formatter covered
  11 relevant files. Effective-line checker: 19 passed; ratchet: 1339 files,
  none above 500 effective lines. Twelve source/test/config files verified
  UTF-8 without BOM; git diff check passed.
- Independent bounded spawn/publication review found no confirmed regression.

Evidence: artifacts/pc2-execution-native-{focused,cooldown-focused,ipc,affected,
fast,ruff,format,mypy,checker,ratchet}.log. Historical failure remains recorded.
The initial broad exploration scout exceeded its useful time budget and was
interrupted; final validation and a bounded review completed independently.

## Milestone verification scope

Pending notifications, CDP and execution ownership have now changed since the
last fast milestone. Run the existing fast manifest once after the affected PC2
suite to verify their combined import/runtime impact and the new test entries.
Expected budget is 60 seconds; process timeout remains 180 seconds.
Use scripts/run_quality_tests.py temporary isolated storage, disabled business
database access, and the existing PostgreSQL skip rules. No live browser or
deployment mutation is part of this check. Do not weaken any threshold.

## Remaining plan

PC2 loop-control and main-loop functions still use cloned facade globals.
The execution module now has explicit ownership, but target lifecycle and child
supervision may be separated further when loop dependency injection is designed.
R1's AVM/source-to-tools work and R2-R9 remain incomplete; the current fast
milestone does not establish PC2/NAS deployment or actual browser acceptance.
