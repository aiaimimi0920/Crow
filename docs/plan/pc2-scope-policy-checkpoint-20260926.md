# PC2 scope policy native-owner checkpoint

Date: 2026-09-26. Base HEAD: f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
Worktree evidence includes inherited uncommitted changes; no commit or push.

## Implemented boundary

tools/pc2_solver_scope_policy.py now owns nine native functions for scope
projection, target identity, request ownership, manual-only eligibility and
execution blocking. The facade and legacy scope module publish the original
functions; their dependencies resolve in the native owner. Scope I/O and the
remaining solver orchestration still use the existing cloning mechanism.

Selection retains preferred challenge identity, oldest positive first-seen
ordering and lexical tie-breaking. Projection copies the selected request.
Malformed timestamps retain their existing exception behavior. URL cleanup,
seed region/sort/page identity, legacy CDP loopback matching and execution block
precedence are preserved. No challenge-solving permission was broadened.

New tests cover native object/global identity, alias scope fallback, tie-breaking,
request copy isolation and malformed timestamps. The native import-isolation
test now includes policy. The fast manifest and CI Ruff/format/strict-mypy checks
include the new owner. The browser overlay wildcard introduced in the previous
checkpoint already includes this new module.

## Failure diagnosis and verification

The first focused boundary passed 46 tests in 5.19 s runner time. The subsequent
orchestration run hit the unchanged 180 s process limit. Three historical loop
fixtures supplied no local CDP ownership, relying on a facade monkeypatch that
also used to affect the cloned execution gate. Native policy correctly rejected
those fixture states and the tests waited indefinitely.

The fixtures now include actual matching CDP endpoints and run the real ownership
policy. An unexpected wait fails immediately. Their three focused checks passed
in 8.56 s. Final combined solver/seed identity/manual handoff/native import/
transport/deployment contract run: 122 passed, pytest 43.17 s, runner 44.56 s.
All runs used the isolated quality runner, with business DB disabled.

Static evidence:

- Native owner, new policy tests, import tests, changed loop fixtures and suite
  manifest: full Ruff check passes (six files).
- Formatter check: eight Python files pass.
- Strict mypy for the native owner: passes.
- Effective-line checker: 19 passed; final ratchet: 1331 files, none above 500.
- Scoped git diff check passes; changed files have no UTF-8 BOM.
- Independent read-only comparison found no implementation regression. It noted
  missing CI coverage, which was then added.

Full Ruff on the legacy scope I/O and dynamic facade CLI is not green: existing
broad-catch/fallback diagnostics and dynamic-name F821 diagnostics remain in
artifacts/pc2-scope-policy-legacy-ruff.log. No blanket suppression was added.
Do not report these results as a clean repository-wide static or release gate.

Evidence logs: artifacts/pc2-scope-policy-focused.log,
artifacts/pc2-scope-policy-orchestration.log (historical timeout),
artifacts/pc2-scope-policy-fixture-focused.log,
artifacts/pc2-scope-policy-affected.log,
artifacts/pc2-scope-policy-native-ruff.log,
artifacts/pc2-scope-policy-format.log, artifacts/pc2-scope-policy-mypy.log,
artifacts/pc2-scope-policy-checker.log, artifacts/pc2-scope-policy-ratchet.log.

## Next cursor

R1-R9 remain open. Continue with explicit PC2 scope I/O ownership/dependencies,
then the fallback/auth-pending/CDP/execution/loop owners. Keep loop admission
replacement seams distinct from internal native policy dependencies. Preserve
legacy exports until their actual callers migrate. Full fast was not rerun for
this bounded change; previous timings describe the previous worktree only.

Deployment, restarts, image builds and business-data changes remain deferred.
