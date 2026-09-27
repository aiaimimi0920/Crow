# PC2 native-auth verification and overlay checkpoint

Date: 2026-09-26. Base HEAD: f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
The worktree contains inherited uncommitted changes; no commit or push was made.

## Boundary and diagnosis

The PC2 scope migration baseline reported four failures, 89 passes, and a
45.30 s runner time. Authentication had already become a native module, but
the tests still replaced facade globals. The native function's HTTP dependency
and freshness constants therefore did not receive those replacements.

Read-only caller inspection found no production assignments relying on this
facade patch seam. Tests now patch tools.pc2_solver_auth while continuing to
invoke the public tools.pc2_local_solver entrypoints. Production authentication
semantics and retry/confirmation policy are unchanged.

The browser and auth-recovery Dockerfiles previously overlaid only the facade
and selected helpers. They now also COPY tools/pc2_solver_*.py, ensuring the
split solver owners and configuration are updated with their facade. Two
parameterized packaging cases check both overlays against the implementation
module inventory. This is source packaging evidence, not an image/runtime test.

Ruff formatting pushed part_04 above 500 effective lines. Its three cohesive
freshness-policy tests now live in pc2_auth_freshness_cases.py, with explicit
imports retaining their original pytest node IDs. No tests were deleted and
no effective-line baseline or exception was added.

## Verification sequence

- Initial focused boundary: 30 passed, runner 3.22 s.
- Affected solver, seed identity, manual handoff, isolated import/transport and
  Linux deployment contracts: 118 passed, runner 42.17 s (pytest 40.62 s).
- After the freshness-only test extraction, the three preserved node IDs were
  rerun successfully. The unchanged affected tests were not rerun.
- Ruff and format checks pass on all five changed Python test files.
- Effective-line checker: 19 passed; final ratchet: 1329 files, none above 500.
- Changed files are UTF-8 without BOM. Git diff check found no whitespace
  errors; Git emitted existing LF/CRLF normalization warnings.

Logs: artifacts/pc2-scope-policy-before.log,
artifacts/pc2-auth-owner-focused.log, artifacts/pc2-auth-owner-affected.log,
artifacts/pc2-auth-owner-split-focused.log, artifacts/pc2-auth-owner-ruff.log,
artifacts/pc2-auth-owner-format.log, artifacts/pc2-auth-owner-checker.log,
artifacts/pc2-auth-owner-ratchet.log.

## Remaining work

R1-R9 remain open. Resume R1 with PC2 scope/target identity policy ownership,
then retire its remaining function cloning without introducing dynamic global
rebinding. The current PC2 baseline is healthy for that next slice.

Deployment, application restarts, image builds and business-data mutations
remain deferred under the overall code-first plan. Full fast was not repeated:
its prior 1389-pass/2-skip, 40.77 s milestone belongs to the earlier worktree.
