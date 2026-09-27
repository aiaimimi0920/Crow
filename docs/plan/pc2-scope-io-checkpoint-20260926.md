# PC2 native scope I/O checkpoint

Date: 2026-09-26. Base HEAD: f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
Inherited uncommitted changes remain; no commit or push was requested.

## Completed boundary

tools/pc2_solver_scope.py is now a native owner. The six exported notification,
CDP health and tab-cleanup functions no longer use FunctionType cloning or
wildcard context imports. HTTP dependencies are explicit, and a narrow solver
protocol with a lazy factory avoids loading the solver/browser runtime at import.

solver_request_target_url and solver_request_target_urls moved from the CDP
module into scope policy, breaking the old scope-to-later-CDP dependency. Their
field priority, deduplication and facade/CDP exports remain intact. Existing
scope policy and these selectors publish their original function objects.

Behavior tests still invoke the facade; their HTTP and solver replacements now
target the native I/O owner. Orchestration replacements of exported operations
remain available. New tests cover public function identity, force-reset payloads,
non-dictionary responses, health fallback, failed-target cleanup continuation,
tab-refresh failure and report rejection/error envelopes.

The established broad exception boundaries are retained and explained with
line-specific lint annotations. No global lint rule, test threshold or line-count
baseline was weakened. Broader legacy CDP/facade lint debt remains open.

## Verification

- Focused existing/native-import/identity coverage: 33 passed, runner 3.94 s.
- New I/O fault cases: 7 passed, runner 0.91 s.
- Complete affected PC2 boundary: 130 passed, pytest 40.74 s, runner 41.44 s.
- Fast milestone: 1401 passed, 2 skipped, pytest 49.68 s, runner 51.34 s.
  Collection 5.06 s; test loop 44.52 s. The two PostgreSQL variants remain skipped
  because fast intentionally clears CROW_TEST_POSTGRES_URL. No PostgreSQL or
  release acceptance is inferred from this run.
- Full Ruff check passes for both native owners, their changed tests and suite
  manifest (nine files). Formatter check passes for eleven Python files.
- Strict mypy passes for scope I/O and policy (two files).
- Effective-line checker: 19 passed; ratchet: 1332 files, none above 500.
- Scoped git diff check and UTF-8/no-BOM inspection pass.
- Independent static review found no concrete regression, export break or cycle.

After the fast run, the official formatter normalized two mixed-line-ending
manifest entries; suite contents did not change and the broad test was not rerun.
The final formatter check passed. CI now enforces scope I/O Ruff/format/typing,
and the fast suite includes the new I/O cases. Browser overlay wildcard coverage
already includes the changed owners; no image was built or activated.

Evidence: artifacts/pc2-scope-io-{focused,faults,affected,fast}.log,
artifacts/pc2-scope-io-fast-timing.json,
artifacts/pc2-scope-io-{native-ruff,format,mypy,checker,ratchet,diff-check}.log.

## Remaining cursor

R1-R9 remain open. Continue with PC2 fallback/auth-pending state ownership,
CDP operations, execution and loop orchestration; then retire the remaining
cloning mechanism. Review legacy CDP closures and diagnostic handling at that
boundary rather than mixing unrelated changes into this completed scope slice.

Deployment, restarts, business-DB mutations and release activation remain
deferred under the code-first plan.
