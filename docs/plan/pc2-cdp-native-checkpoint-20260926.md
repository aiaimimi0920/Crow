# PC2 CDP native probes (2026-09-26)

Status: this ownership slice is verified; the overall R1-R9 plan remains open.
Source is HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus inherited changes.
No deployment, restart, business-data operation, commit or push was performed.

## Implemented boundary

Six CDP functions now publish their original native objects through
pc2_local_solver, without cloned facade globals. Explicit HTTP, policy and
logging dependencies replace six wildcard imports. ProbeSolver documents only
the required solver methods; its factory imports CaptchaSolver lazily. Websocket
loading also remains lazy. A small socket protocol binds the synchronous command
sender to its current connection.

Existing selection rules are retained: requested route and seed query identity,
metadata before DOM evidence, inconclusive failure results, authentication
rejection when a matching page is challenged, and best-effort socket cleanup.
New regressions check native identity, page/fallback URL selection, same-request
route revalidation, connection close before continuing after an error, and
error-type-only logging. Existing slider success cleanup tests remain intact.

Native CI Ruff, formatting and strict typing cover this owner. Import-isolation
tests confirm importing the owner does not initialize the solver/server/storage.
Its HTTP dependency is intentional; pure-owner HTTP isolation remains unchanged.
The six new test cases are registered in the fast manifest.

## Evidence and repair

- Focused CDP/import checks: **32 passed**, runner **13.30 s**.
- First affected run: **165 passed, 1 failed**, runner **53.61 s**. The seed
  identity test still patched facade fetch_json after native ownership moved.
  That mock and an adjacent negative test's mock now target the CDP owner;
  the negative test must exercise its fixture rather than return inconclusive
  from unpatched I/O.
- Repaired seed boundary: **12 passed**, runner **2.78 s**.
- Final affected PC2 suite: **166 passed**, runner **46.94 s**
  (pytest **45.73 s**), including loop, execution, seed identity, cooldown,
  scope, state, pending notifications and packaging contracts.
- Native Ruff and strict mypy passed. Relevant formatter checks passed, including
  the suite manifest after normalizing mixed line endings with the formatter.
- Effective-line checker: **19 passed**; ratchet: **1338 files**, none above
  500 effective lines. Policy and baseline unchanged.
- Independent review found no confirmed introduced defect. No live CDP/browser
  acceptance is claimed by these isolated fake-I/O and contract tests.

Logs: artifacts/pc2-cdp-native-focused.log,
pc2-cdp-native-seed-focused.log, pc2-cdp-native-affected.log (historical failure),
pc2-cdp-native-affected-final.log, and the matching Ruff/format/mypy/checker/ratchet
logs. All pytest runs used the isolated quality runner with business DB disabled.
The prior fast milestone remains historical evidence only; no current full-fast
result is claimed, and no unchanged broad suite was rerun at this slice boundary.

## Next work

PC2 execution, loop-control and main-loop owners still use cloning. Their
orchestration tests retain facade-level replacement seams until those callers
move. R1 also retains AVM/source-to-tools work; R2-R9 and deferred deployment
acceptance remain open.
