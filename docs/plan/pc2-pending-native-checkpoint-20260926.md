# PC2 pending notification native ownership (2026-09-26)

Status: this slice is verified; the overall R1-R9 plan remains incomplete.
Source: HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus inherited dirty worktree.
Before this checkpoint document, git status contained 394 entries; unrelated
changes were preserved. No commit, push, deployment, restart, or business-data
change was performed.

## Behavior path

Fallback reporting and pending auth/resume notification now publish their
original native functions through pc2_local_solver. Fourteen further functions
exit cloning: seven fallback functions, six auth-pending functions, and the
shared retry-delay helper moved into pc2_solver_retry_state.

The success path keeps the same owned-target challenge rotation rule, persists
the pending completion identity before notification, clears obsolete resume
metadata, and retains slider attempt history. A failed notification retains
the same identity and persisted retry/backoff. Resume and auth only clear state
on explicit confirmation or a stale-challenge response. Manual report endpoint,
payload and failure envelopes remain unchanged.

Explicit imports replace wildcard dependencies in both native owners.
Tests patch dependencies in the owner that reads them; facade entrypoints and
loop-level orchestration seams remain available. There is no new facade-global
lookup or rebinding bridge. Strict CI typing, Ruff and formatting include both
owners. Import isolation includes them while allowing their intentional HTTP
dependencies; pure retry/state/policy/transport imports remain HTTP-free.

## Verification on this slice

- Focused lifecycle, persisted ID, blocked-report, timeout, resume and import
  checks: **32 passed**, runner **9.92 s**.
- Affected PC2 solver, scope, storage, retry, seed identity, manual handoff,
  cooldown recovery and deployment packaging contracts: **159 passed**,
  runner **46.12 s** (pytest 45.18 s).
- Native Ruff passed; strict mypy passed for all three changed native owners.
  Formatter check passed for 11 relevant files.
- Effective-line checker: **19 passed**. Ratchet: **1337 files**, none above
  500 effective lines; baseline and thresholds unchanged.
- Git diff check passed with CR treated as a line terminator; 12 affected
  source/test/config files were valid UTF-8 without BOM.
- Independent read-only review found no confirmed introduced defect.

Evidence logs are artifacts/pc2-pending-native-{focused,affected,ruff,format,
mypy,checker,ratchet}.log. Tests used run_quality_tests.py temporary isolated
storage with business DB access disabled.

The prior fast milestone was 1420 passed, 2 skipped, runner 45.98 s, recorded
in pc2-retry-state-checkpoint-20260926.md. It predates this slice and is not
presented as acceptance of the current source. The fast manifest now includes
the four new lifecycle cases. No unchanged broad suite was rerun at this
non-release slice boundary; current evidence is the focused and affected suite.

## Remaining boundary

PC2 CDP, execution, loop-control and loop functions still use cloning.
R1 also retains AVM patch-facade and source-to-tools work. R2-R9 remain open,
including data-preserving migration of the legacy fallback-state path.
Deployment and application restarts remain deferred by the overall plan.

The reviewer noted a pre-existing malformed-state edge case: an already-pending
resume record without a request ID can send an empty ID. This was not changed
as part of the behavior-preserving ownership extraction and is not claimed fixed.
