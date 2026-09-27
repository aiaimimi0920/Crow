# PC2 native loop and probe cadence (2026-09-26)

Status: this slice and its fast milestone are verified. PC2 function cloning is removed.
Overall R1-R9 remains incomplete. Deployment, restarts and business-data changes
remain deferred. Work continues in the inherited dirty worktree without a commit.
HEAD remains f2d735ab20e60c1dce212dd86dd2b15fd22a8c40; git status contained 409
entries at final verification. Unrelated worktree changes were preserved.

## Behavior and native ownership

Two cadence regressions failed against the old source: a six-poll idle loop
probed on polls 3, 4, 5 and 6 instead of 3 and 6; a second loop invocation inherited
the first invocation's counter and probed immediately. The counter is now local
to each invocation and resets when the periodic probe runs. Confirmation and
target-rebuild paths return an explicit reset signal through ControlResult.

The facade now publishes original objects only. FunctionType cloning, wrapper
metadata copying, default/keyword-default rebinding and the native/legacy module
partition have been removed. Public entrypoints retain their original owners.
The existing context export module remains an API export source; native runtime
owners do not import it or look back into facade globals.

Responsibilities were split before completing the changed oversized loop:
loop_control owns pending acknowledgements, scope reset and stale-pause recovery;
loop_probe owns browser readiness and prioritized target discovery; loop_failure
owns failed-attempt persistence and optional manual escalation. The loop coordinates
them with explicit imports. All affected files pass the unchanged effective-line
policy without exceptions, baseline regeneration or removed tests.

Existing loop tests replace shared dependencies at the explicit native call sites
using a test-only helper. Production code has no new rebinding adapter. Auth-grace
constant mocks now target the auth owner. Identity assertions require every public
implementation function to be the original object. New control tests cover
acknowledgement reset signals, cleanup order and foreign-node scope preservation.

## Verification

- Cadence baseline: 2 failures reproducing both bugs above.
- Initial migrated loop boundary: 86 passed, 1 failed because an auth-grace test
  still patched a retired facade constant. The test now patches its native owner.
- Cadence plus repaired grace check: 3 passed, runner 3.69 s.
- Control, cadence and isolated imports: 25 passed, runner 5.34 s.
- Final affected PC2 suite: **179 passed**, runner **44.73 s**.
- Fast milestone: **1446 passed, 2 skipped**, runner **38.49 s**
  (pytest 37.24 s), below the unchanged 60 s threshold.
- Full native Ruff and strict mypy passed for all four loop owners. Formatter
  passed for 17 relevant files; 18 source/test/config files were valid UTF-8
  without BOM. Git diff check passed.
- Effective-line checker: **19 passed**. Ratchet: **1344 files**, none above
  500 effective lines. Initial oversized intermediate states were split before
  acceptance; no exception or baseline change was made.
- Independent bounded review found no confirmed state propagation, reset,
  sleep-ordering or ownership defect. PC2 runtime source search found no remaining
  FunctionType, _clone_function or _NATIVE_MODULES references.

Logs: artifacts/pc2-loop-native-{before,focused,cadence-final,control-focused,
affected,fast,ruff,format,mypy,checker,ratchet}.log. Historical intermediate
failures remain recorded; they are not combined with final acceptance counts.

## Acceptance scope before the milestone run

PC2 facade function cloning and shared function-attribute probe state have been
removed. Native loop/control/probe/failure ownership changes the cross-module
runtime boundary, so run fast once after affected PC2 checks to verify combined
imports, test selection and adjacent behavior. Expected budget: 60 seconds;
process timeout: 180 seconds. Use the existing isolated quality runner and
temporary storage with business DB disabled. Retain all thresholds and skip
rules. No live browser or deployment acceptance is implied.

## Remaining overall work

This closes the PC2 cloning boundary within R1. AVM's module patch facade and
source-to-tools imports remain; R2-R9 still require their recorded completion
conditions. No current analysis/prediction product completion or deployment
acceptance is claimed. Continue with AVM ownership and actual caller contracts.
