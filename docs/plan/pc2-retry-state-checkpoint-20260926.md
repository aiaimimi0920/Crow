# PC2 native retry-state checkpoint

Date: 2026-09-26. Base HEAD: f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
The inherited dirty worktree remains uncommitted; no deployment or restart.

## State transition boundary

tools/pc2_solver_retry_state.py owns eight native functions: reset, challenge
sync, cooldown active/resume eligibility/start, retry due, attempt start and
attempt failure. The three related environment constants retain their original
names and defaults. Facade/fallback exports retain the original native objects.

Challenge rotation creates a new default state without mutating the old snapshot;
same-ID scope updates preserve counters. Attempt start persists immediately;
failure updates counters/cooldown in memory and still leaves commit to the caller.
Tests pin this ordering and the exact cooldown deadline. No thresholds changed.

The conditional root fixture now gives test_pc2_* cases a temporary state path
through the native store. Existing per-test path overrides take precedence and
restore normally. Non-PC2 tests do not request a temporary directory through
this fixture. Production state paths and persisted files were not migrated.

## Fast-budget diagnosis and import fix

The first fast attempt had 1420 passed and 2 skipped but failed its timing gate:
pytest 65.48 s, runner 67.05 s. Collection was 6.46 s and test loop 58.88 s.
Comparison with the previous scope-I/O run showed about 3.69 s additional PC2
test-phase time, with larger combined growth in unchanged non-PC2 tests. The
new fixture alone did not explain the overall difference.

A targeted import diagnostic passed 143 cases in 21.12 s. PC2 transport/import
cases consumed 4.95 s and server imports 14.18 s. Inspection found that pure
PC2 state/policy imports unnecessarily loaded internal_api_http and requests via
transport. read_solver_status now imports its HTTP dependency only when called.
Pure native-import cases additionally assert those HTTP modules stay unloaded;
status-call tests replace the actual HTTP dependency and preserve response shapes.

After this change, 29 focused cases passed in 3.12 s and the PC2 transport test
phases took 1.96 s. Final fast: 1420 passed, 2 PostgreSQL variants skipped,
pytest 43.31 s, runner 45.98 s, collection 4.80 s and test loop 38.40 s. The
60 s threshold, 180 s process limit, suite membership and isolation remain.
The total timing improvement is not attributed solely to the lazy import change;
the measured targeted reduction is about 2.99 s and other timings also varied.

## Verification scopes

- Initial state/import/cooldown focused run: 33 passed, runner 8.05 s.
- Affected PC2 boundary before lazy HTTP import: 153 passed, runner 44.12 s.
- Post-import-change focused run and final fast results are recorded above.
- Native retry owner, tests, fixture and manifest: full Ruff passes (six files).
- Transport and its tests pass the existing CI Ruff rule selection.
- Strict mypy: retry-state and transport pass (two files).
- Formatter: nine Python files pass; checker: 19 tests pass; ratchet: 1336 files,
  none above 500. Scoped git diff check and UTF-8/no-BOM inspection pass.
- Independent static review found no transition, default, persistence-order or
  test-path isolation regression. CI and fast include the new retry-state cases.

Evidence: artifacts/pc2-retry-state-{focused,affected,ruff,format,mypy,checker,ratchet,diff-check}.log;
artifacts/pc2-retry-state-fast.log (failed historical timing);
artifacts/pc2-retry-state-import-diagnostic.log;
artifacts/pc2-retry-state-lazy-import.log;
artifacts/pc2-retry-state-fast-final.log and its corresponding timing JSON.

## Remaining cursor

R1-R9 remain open. Fallback still defines seven local functions for manual
fallback/reporting and collection-resume notification/retry; auth_pending defines
seven functions. Resolve their shared retry-delay dependency explicitly when
making them native. CDP, execution, loop control and loop ownership also remain.
Do not add a new dynamic-global bridge to retain old internal test seams.

Deployment and data migration remain deferred. This checkpoint does not prove
release acceptance, power-loss durability or concurrent-writer safety.
