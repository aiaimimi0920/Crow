# Crow code-quality remaining work (2026-09-25)

Status: **incomplete**. This inventory reconciles the original
[58 findings and three implementation batches](code-quality-review-20260920.md)
with the current source and the
[longitudinal verification record](code-quality-progress-20260921.md).
It is not a new product roadmap or a claim that every historical test was rerun.

The checkpoint is HEAD `f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` plus the inherited
dirty worktree and this continuation. The original findings overlap structural
tasks and deployment gates; a single completed-item percentage would be misleading.
Deployment, application restarts, and business-database changes remain deferred
until the code tasks are complete. Analysis and prediction remain migration inputs.

## Completed in this continuation

The auth-completion preparation path could validate an old challenge, then capture
a concurrently published challenge ID for the cookie worker. A healthy snapshot
could consequently confirm and clear the newer challenge.

[server_collection_console.py](../../src/server_collection_console.py#L61) now
captures target validation, scope, retained request, confirmation state, and the
expected challenge ID under the shared runtime lock. Before publishing the async
manual-required state, it checks that the same challenge is still current.
Snapshot scheduling and finalization remain outside this lock, preserving the
existing finalizer lock order.

The regression in
[test_solver_scope_runtime.py](../../tools/test/test_solver_scope_runtime.py#L499)
uses a real competing thread and isolated receipt files. PC2, seed-probe, and
operator cases all failed before the fix by returning `auth_state_confirmed=True`.
They now preserve the new challenge's exact receipt bytes, paused state, solver
outcome, and lack of an old completion confirmation.

The resumed cleanup slice also closes scoped receipt deletion failures in
[server_solver_state.py](../../src/server_solver_state.py#L110). Matching legacy
receipts are removed before the authoritative scoped receipt; a legacy deletion
failure leaves the scoped latch intact, and a scoped deletion failure leaves the
runtime challenge ID unchanged. Compatibility receipts owned by another scope
remain untouched. The 10 cases in
[test_auth_completion_cleanup.py](../../tools/test/test_auth_completion_cleanup.py)
cover seed/detail, finalization/cooldown, both deletion faults, restart, retry,
and preservation of the other scope. These cases are in both fast and security.

If scoped deletion fails after legacy deletion succeeds, startup restores the
remaining scoped receipts through `_restore_solver_scope_states()`. This does
not promise atomic rollback of every file or preservation of the legacy singleton
selection order across restart; scoped challenge identity and pause state are
the recovery evidence. The wider R3 completion condition below remains open.

The subsequent cooldown-confirmation slice preserves the original scoped
challenge when cleanup succeeds but confirmation publication fails. It snapshots
the scope and recovery metadata before cleanup, restores them on publication
failure, and returns a separate `recovery_error` if scoped restoration fails.
That failure path attempts a durable global manual-required flag to keep workers
blocked after restart. Four new fault-injection cases cover seed/detail and
successful/failed restoration; normal restoration permits replay with the original
challenge ID. See
[server_collection_control.py](../../src/server_collection_control.py#L350) and
[test_auth_completion_cleanup.py](../../tools/test/test_auth_completion_cleanup.py#L125).
This covers returned I/O errors for scoped cooldowns. It does not close the
process-crash window between cleanup and confirmation, legacy-only requests,
or failure of every available persistence mechanism.

The cookie-finalizer follow-up now preserves the original scoped challenge on
confirmation-publication failure too. Previously its compensation created a new
challenge ID, while the cookie retry chain retained the old expected ID; restoration
errors could also be logged without appearing in the response. Four new failing
cases reproduced both issues. Both entrypoints now use
[auth_cleanup_recovery.py](../../src/auth_cleanup_recovery.py), a native owner with
explicit runtime and persistence callbacks. It retains the current facade injection
contract without adding function cloning. The original cooldown behavior was
checked before and after extraction. All 18 cleanup/confirmation cases now pass.
Scoped cookie-finalizer I/O recovery is covered. The checkpoints below add scoped
process-interruption recovery and legacy returned-I/O-error compensation.

The scoped cleanup transaction now writes a per-scope intent before clearing the
challenge and retires it only after completion publication. Pending intents block
receipt replay from reporting success and are recovered before startup workers.
Cookie finalization (including anonymous completion), cooldown and direct operator
completion share this protocol. Explicit reset/resume retires unprotected intents
so an old challenge cannot reappear. Startup preserves newer challenge generations
and newer paused metadata for the same ID. Corrupt intents and failed restoration
block startup until repaired/retried. See
[auth_cleanup_journal.py](../../src/auth_cleanup_journal.py) and the 29 cases in
[test_auth_cleanup_crash_recovery.py](../../tools/test/test_auth_cleanup_crash_recovery.py),
including 16 actual subprocess exits across two scopes and two commit windows.
These cases run in security, not the time-bounded fast manifest. This is process-exit
coverage, not a power-loss/fsync guarantee or closure of legacy-only transactions.

The finalizer scope-selection follow-up now includes request scope inference,
challenge-ID lookup and legacy fallback under the existing finalizer/runtime lock
order. Previously a native scoped publication could occur after the empty-scope
read but before cleanup; the stale legacy fallback then deleted the new receipt.
Four real-thread cases reproduced the loss for seed/detail and explicit/inferred
scope. All eight before/during-publication cases now pass and preserve the exact
new receipt bytes and manual pause. See
[test_auth_finalizer_scope_selection.py](../../tools/test/test_auth_finalizer_scope_selection.py).
This proves the independently callable scoped persistence boundary, not a loss
claim for the combined `_begin_solver_challenge` path that also updates singleton ID.

Legacy completion now fails before destructive cleanup when an active scoped
challenge or pending scoped cleanup intent exists. The response requires a
scope-specific completion; legacy/global operator reset remains a separate action.
When unambiguous legacy cleanup succeeds but completion publication returns an
error, all three completion entrypoints restore the original legacy ID, request,
resume/manual metadata and durable manual flag. A failed rollback is reported as
`recovery_error`; a surviving receipt or manual flag keeps restart paused, but
failure of all persistence mechanisms is not claimed recoverable. The 21 cases in
[test_auth_legacy_completion_recovery.py](../../tools/test/test_auth_legacy_completion_recovery.py)
cover active/pending scoped preservation, receipt/rollback/flag errors and retry.
The following checkpoint adds legacy process-exit recovery to this returned-error
path.

Legacy completion now writes `auth-cleanup-intent-legacy.json` before removing
flags or challenges and deletes it only after completion publication. Startup
restores its challenge, request, recovery epochs and manual flag before workers;
pending completion receipts cannot report success. New legacy/scoped ownership
supersedes old intents, same-ID request updates are retained, and explicit global
reset or cleanup of a newer scoped challenge retires obsolete legacy recovery.
Corruption and failed restoration block startup until retry. The 38 cases in
[test_auth_legacy_crash_recovery.py](../../tools/test/test_auth_legacy_crash_recovery.py)
include 16 real process exits, partial cleanup/commit faults, reset and supersession.
The captured manual-only mode includes the durable flag, since a prior restart
may leave that mode absent from the in-memory recovery snapshot. This checkpoint
covers process termination, not power-loss/directory-fsync guarantees or exact
preservation of republished compatibility-receipt timestamps.

## Remaining code and structural work

| ID | Original scope | Current evidence | Completion condition |
| --- | --- | --- | --- |
| R1 | Batch 3.2; structural 1, 3, 4 | [server.py](../../src/server.py#L43) has no core or handler cloning sources. Core exports, solver execution and all registered handlers now publish native owners. [server_module_exports.py](../../src/server_module_exports.py#L14) now only publishes native objects; its `FunctionType` rebind and empty legacy module registries are removed. [pc2_local_solver.py](../../tools/pc2_local_solver.py) now publishes original native objects too; PC2 cloning and default rebinding have been removed. The AVM service module patch facade is removed; its mixins now import native dependency owners directly. Source-to-tools imports remain. | Finish explicit ownership and dependency injection, remove the remaining active cloning/patch facades, and verify public entrypoints, import isolation, runtime replacement, and route coverage at each boundary. |
| R2 | Batch 3.4; structural 5, 8 | [repository_search.py](../../src/storage/repository_search.py#L25) still builds Taobao URLs and uses a default Taobao policy. Seed jobs/pages/items retain default policies; storage imports collection policies and AVM templates. Detail processing still receives a long per-operation callback bundle. | Supply source policies/adapters explicitly, move source semantics behind collection contracts, remove storage-to-implementation imports, and consolidate the callback ownership without losing archive/DB/runtime commit ordering. |
| R3 | Batch 3.5; structural 6; auth persistence follow-up | Generated auth codes exist, but scoped and legacy state remain in [server_solver_state.py](../../src/server_solver_state.py#L175). Finalizer scope selection shares its transaction lock in [auth_cleanup_completion.py](../../src/auth_cleanup_completion.py#L86). Scoped and legacy completions now have write-ahead intents, process-exit/returned-error recovery and explicit-reset retirement. Global legacy completion refuses active/pending scoped ownership. | Manual/automated scoped cleanup and mixed-state process-exit startup preserve independent legacy pause ownership; startup, receipts, creation, manual transitions, state and dispatch now have native owners; their legacy persisted-state and caller contracts still require migration. Complete caller/persisted-state migration before retiring legacy compatibility, and define the supported multi-file durability contract. Existing process-exit coverage does not establish power-loss or deployment acceptance. |
| R4 | Finding 17; batch 3.3 | The threaded server and durable job manager are implemented. However, [evaluation_handlers.py](../../src/evaluation_handlers.py#L72) defaults evaluation and inference to synchronous execution; evaluation still calls the service in the request thread at line 129. Inference, screening, and seed-batch compatibility paths also remain. Manual-review async compatibility returns HTTP 200. | Complete the remaining client/job-contract transitions and error-envelope consistency. Preserve required compatibility until the actual callers are migrated; do not reclassify all asynchronous work as missing. |
| R5 | Finding 55, remaining desktop security/interaction pieces | [desktop_collection_views.ts](../../collector-desktop/src/desktop_collection_views.ts#L217) filters URL schemes but still uses a plain `_blank` link. Auth uses `window.open`; no native opener integration was found in desktop source, Cargo dependencies, or capabilities. [tauri.conf.json](../../collector-desktop/src-tauri/tauri.conf.json#L25) still permits unrestricted `https:` in `connect-src`. | Implement and exercise a constrained native external-link path, and derive an appropriate CSP/origin boundary from supported runtime configuration. Verify both packaged Tauri and browser-preview behavior. |
| R6 | Batch 3.7; structural 9, 10; finding 57 remainder | The unified controller composes settings/restart controllers, and terminal receipt delivery is shared. Separate persistence and polling loops remain in [pc2_collection_controller.py](../../tools/pc2_collection_controller.py#L17), [pc2_settings_controller.py](../../tools/pc2_settings_controller.py#L40), and the engine controller. Compose/start scripts still contain independent machine-address and HTTP API defaults. Both host and Linux deployment stacks remain. | Consolidate controller lifecycle/journal policy and topology configuration; reconcile HTTPS/role-token wiring and defaults; decide and implement the supported status of the old host stack. Audit its retained PowerShell wrappers and their failure propagation. |
| R7 | Batch 3.10; test/gate observations | `tools/test/` still contains 189 numbered `_part_NN.py` files and 203 files with wildcard imports. Shared-context and script-text assertions remain. Explicit fast/security manifests, fixtures, and CI already exist. Strict backend typing covers selected native modules, not the whole backend. | Reorganize remaining slices by behavior with shared fixtures and meaningful runtime assertions, retaining test coverage and the current effective-line policy. Expand strict checks as ownership becomes native; keep the fast gate below 60 seconds. |
| R8 | Findings 33, 40, 46, retention portions | Cookie publishing is atomic, controller terminal receipts are archived, logs rotate, and DB indexes exist. The reviewed snapshot helpers, release script, and task-event repository do not provide a complete lifecycle/capacity policy for old credential snapshots, retained releases/images, and ingest-event history. | Implement bounded retention/capacity management consistent with the user's prohibition on deleting organized data. Define archival, capacity reporting, and failure behavior before activating any cleanup. Do not silently restore the original destructive cleanup suggestions. |
| R9 | Finding 43; batch 3.11; structural 12 | Bare `except:` is gone from `src/`, and logging is widely used. Server startup still prints active AVM configuration and exceptions in [server.py](../../src/server.py#L585); broad exception/fallback handling remains in legacy modules. Some remaining stdout is intentional CLI output. | Finish boundary-specific exception and diagnostic/redaction review, remove obsolete code, and preserve intentional CLI contracts. Text-match counts alone do not establish defects or justify blanket rewrites. |

The remaining server cloning sources are:

```text
core:
  (none)
handlers:
  (none)
```

Missing detail archive fetching now has a native collection owner. The service
and maintenance call it directly, while the CLI preserves its original function,
flags and report contract. Focused checks: 10 passed; affected fetch/maintenance/
HTTP boundary: 411 passed and 1280 subtests passed (30.14 s). Strict typing,
selective lint, formatting, 19 checker tests and the 1347-file ratchet pass.
Only requests dev stubs were added; previous lock pins and hashes were retained.
Backfill/replay/maintenance source-to-tools edges remain. Positive-candidate
dry-run artifact writes are pre-existing and remain an explicit next fix.
See [detail fetch checkpoint](detail-fetch-native-checkpoint-20260926.md).
Full-fast and deployment acceptance were not rerun or claimed for this slice.

AVM's module-patch facade is now removed: ordinary service exports and direct
dependency imports replace ModuleType assignment broadcasting. Five existing
test seams target their real owners; a runtime regression proves a service
namespace assignment cannot replace the health provider. Before/after focused:
48/49 passed. Affected AVM/HTTP/job/pipeline boundary: 456 passed and 1278 subtests
passed (30.99 s). Selective lint, format, syntax and the 1345-file ratchet pass.
Full AVM typing and product contracts remain open. R1 now proceeds to the actual
source-to-tools import boundaries. See [AVM ownership checkpoint](avm-native-owner-checkpoint-20260926.md).

PC2 facade cloning is now removed completely: native loop/control ownership,
explicit reset signals and original-object publication replace function cloning
and default rebinding. Discovery and failed-attempt handling have separate native
owners, keeping every changed file below 500 effective lines. Two failing cadence
regressions reproduced overly frequent probing and cross-invocation counter reuse;
both now pass. Final affected checks: 179 passed (44.73 s); fast: 1446 passed,
2 skipped (38.49 s). Native typing, Ruff/format, 19 checker tests and the 1344-file
ratchet pass. R1 now continues with AVM and source-to-tools ownership; R2-R9 remain
open. See [native loop checkpoint](pc2-loop-native-checkpoint-20260926.md).

PC2 execution and target lifecycle now retain their original module identity,
including the spawn child entrypoint. Seven functions exit cloning; lazy solver
loading and explicit dependencies replace wildcard imports. Final affected
boundary: 170 passed (45.38 s). The combined native-owner milestone fast passed
1437 tests with 2 skips in 49.74 s, under the unchanged 60 s threshold.
Strict typing, Ruff/format, 19 checker tests and the 1339-file ratchet pass.
Loop-control/main-loop cloning remains open. See
[execution checkpoint](pc2-execution-native-checkpoint-20260926.md).

PC2 CDP probes now publish six original native functions with explicit HTTP,
policy and logging dependencies and lazy solver/socket loading. Focused checks:
32 passed; repaired seed mock boundary: 12 passed; final affected PC2 suite:
166 passed (46.94 s). Native strict typing, Ruff/format, 19 checker tests and the
1338-file ratchet pass. Execution/loop-control/main-loop cloning remains open.
See [CDP checkpoint](pc2-cdp-native-checkpoint-20260926.md). Full-fast and live
browser/deployment acceptance were not rerun or claimed for this slice.

PC2 pending auth/resume and fallback notifications now publish native owners;
fourteen more functions exit cloning, including their shared backoff helper.
Focused checks passed 32 tests (9.92 s); affected PC2 checks passed 159 (46.12 s).
Strict native typing, Ruff/format, 19 checker tests and the 1337-file ratchet
passed. The prior fast result below predates this slice; it was not rerun or
claimed current. CDP/execution/loop ownership remains open. See
[pending notification checkpoint](pc2-pending-native-checkpoint-20260926.md).

PC2 challenge/reset/attempt/cooldown transitions now have a native retry-state
owner: eight further functions exit cloning. PC2 tests isolate the state path
per test. Focused 33 passed; affected 153 passed (44.12 s). An initial fast run
failed timing at 67.05 s despite all tests passing. Transport now delays HTTP
imports until status I/O, and pure native imports assert HTTP libraries remain
unloaded. Follow-up focused 29 passed; final fast 1420 passed, 2 skipped, runner
45.98 s under the unchanged 60 s gate. See
[retry-state checkpoint](pc2-retry-state-checkpoint-20260926.md). Pending auth and
resume notifications, CDP, execution and loop ownership remain open.

PC2 fallback serialization and file replacement now have a native owner in
tools/pc2_solver_state_store.py. Three more functions exit cloning; reset/sync
and retry orchestration remain for the next state-lifecycle slice. Existing
fields, conversion/fallback rules and atomic-replace behavior are preserved.
Focused 25 passed; affected boundary including cooldown recovery 146 passed
(runner 42.00 s); strict typing, native Ruff, formatter and 1334-file ratchet pass.
See [state store checkpoint](pc2-state-store-checkpoint-20260926.md). The legacy
state path remains unchanged pending a data-preserving runtime-root migration.

PC2 scope I/O is now native as well: six notification/health/tab-cleanup functions
use explicit HTTP and lazy solver dependencies. Two target selectors moved into
the cycle-free policy owner. The affected boundary passed 130 tests (41.44 s),
and its fast milestone passed 1401 tests with 2 PostgreSQL skips in 51.34 s
(60 s threshold unchanged). Native strict typing, Ruff/format and the 1332-file
ratchet pass. Fallback/auth-pending/CDP/execution/loop cloning and CDP lint debt
remain. See [scope I/O checkpoint](pc2-scope-io-checkpoint-20260926.md).

PC2 scope projection, target identity and executor eligibility now have a native
owner in tools/pc2_solver_scope_policy.py: nine functions no longer use cloned
facade globals. Three loop fixtures now carry actual local CDP ownership instead
of replacing an internal policy dependency. Focused 46 passed, repaired fixture
checks 3 passed, final affected boundary 122 passed (runner 44.56 s). Native-owner
Ruff/strict typing and the 1331-file ratchet pass. Existing facade/I/O lint debt and
the remaining PC2 I/O/state/orchestration cloning remain open. See
[scope policy checkpoint](pc2-scope-policy-checkpoint-20260926.md).

PC2 native-auth validation now closes the four pre-existing focused failures:
the tests patch the native auth owner while invoking the public facade. No
production caller was found assigning those facade dependencies. Both browser
overlay Dockerfiles now copy the split pc2_solver modules, with two packaging
regressions. The affected boundary passed 118 tests in 42.17 s runner time;
after extracting freshness cases to stay below 500 effective lines, their three
preserved node IDs passed again. R1 PC2 cloning remains open. See
[PC2 auth checkpoint](pc2-auth-owner-checkpoint-20260926.md). No image build or
deployment acceptance is claimed.

The earlier runner-recovery milestone passed on its recorded worktree: 1389 passed, 2 skipped,
runner 40.77 s, with collection 3.99 s and test loop 35.31 s. The 60 s gate,
180 s process timeout, isolation environment and all original tests remain.
The runner now collects the suite directory once using quality_selection.py to
exclude unselected paths before collector creation and enforce exact node selectors.
Collection node comparison retained all 1384 previous nodes and added 7 selector
regressions. The prior failed timings below remain historical evidence, not current
acceptance. R7's wider test organization/typing work remains open.

Diagnosis: cProfile of collection-only execution exposed repeated directory
collection for separate file arguments in the installed pytest: 14524 directory
collect calls, 54456 ignore checks and 34812 stat calls. A real subprocess regression
now requires one suite-directory collection and blocks unselected sibling collectors.
Focused runner/selection checks: 13 passed, runner 5.17 s. Strict mypy, Ruff/format/
syntax, 19 checker tests and 1328-file ratchet pass; independent review found no
confirmed issue within current relative-path manifests. Evidence:
artifacts/quality-selection-fast.log and quality-selection-fast-timing.json.

The unused server FunctionType rebind implementation, its callsites and three empty
legacy registries are removed. ModuleExports only publishes original objects.
Publication tests now verify native identity/aliases/globals/metadata and repeated
publication; all runtime replacement tests remain. Focused before/after: 127 passed,
runner 6.49 / 6.98 s. No FunctionType/rebind/legacy-registry references remain in src.
Strict typing, Ruff/format/syntax, 19 checker tests and 1326-file ratchet pass.

The native migration milestone fast run had 1382 passed and 2 skipped, but runner
67.91 s exceeded the unchanged 60 s gate. A diagnostic run of the same worktree with
existing phase timing had the same outcomes but took 122.88 s: collection 52.80 s,
test loop 67.60 s, and native-import test phases 11.16 s. These are two separate
failed timing gates, not a combined pass or proof of an environmental cause.
R7 remains open; investigate collection/import and execution timing before choosing
an optimization. Evidence: artifacts/rebind-retirement-fast{,-profile}.log and
artifacts/rebind-retirement-fast-timing.json. No deployment acceptance is claimed.

All server handler cloning sources have now exited. LocationCatalogHandlers preserves
locked catalog read/merge/write and existing names; SeedTaskHandlers now owns seed
batch admission with legacy mode semantics and current execution-time callback lookup.
Analysis is native composition only. Baseline: 52 passed plus 2 subtests; focused:
66 passed plus 2 subtests; affected owner/HTTP/job/import/lifecycle: 317 passed,
runner 23.28 s. Import fixtures were then extracted to keep the changed test below
500 effective lines; final import checks: 131 passed, runner 11.14 s. Final ratchet:
1326 files, none above 500; typing, Ruff/format, syntax and 19 checker tests pass.
R1 still includes removing obsolete cloning machinery and the PC2/service facades.

Manual-review receipt admission/work now use ReviewWriteHandlers with explicit
contracts. Read-only advisory previews, deep payload copy, captured dependencies,
checkpoint/write/maintenance/log/summary ordering, stage failure codes and async
HTTP 200 compatibility remain. Added 10 native cases; baseline 73 passed plus
22 subtests; focused 83 passed plus 22 subtests, runner 8.89 s; affected persistence/
HTTP/access/job/import boundaries 214 passed, runner 14.78 s. Strict typing,
Ruff/format/syntax and 19 checker tests pass; that checkpoint's ratchet had 1322
files. Independent review found no drift. Both slices kept business data isolated.

Evaluation, inference and their shared execution-mode reader now use EvaluationHandlers.
Queued evaluation retains the admitted service and shallow payload; inference retains
the admitted service and LLM callbacks. Existing sync/async envelopes and different
queue/response exception boundaries remain. Baseline: 48 passed plus 4 subtests;
focused: 63 passed plus 4 subtests, runner 8.30 s; affected screen/jobs/import/lifecycle:
201 passed, runner 18.80 s. Strict typing, Ruff/format/syntax, 19 checker tests and
1319-file ratchet pass; independent review found no drift. R4 caller migration remains
open. Manual-review writes, location saving and seed submission still need native owners.

Pipeline and maintenance admission now use PipelineSubmissionHandlers. Control-plane
and body ordering, root confinement, numeric validation, default configuration,
maintenance delegation and live facade replacement remain. Baseline HTTP: 35 passed;
baseline source contracts: 18 passed; focused: 65 passed, runner 6.25 s; affected
imports/lifecycle/jobs/source: 201 passed, runner 16.78 s. Strict typing, Ruff/format,
syntax, 19 checker tests and 1317-file ratchet pass. Independent review found no
behavior drift. Analysis remains the only server cloning module; R1-R9 remain open.

Area-result and manual-approval POSTs now share the existing DetailIngestHandlers
owner. Their current body-before-index order, string ID conversion, processed/done
flags, exact successful result and non-ok 404 mappings remain. Baseline 33 passed;
focused 53 passed; affected archive/DB/runtime/concurrency/HTTP contracts 132 passed,
runner 11.42 s. Strict typing, Ruff/format/syntax, 19 checker tests and 1315-file
ratchet pass. The per-operation service callback contract and analysis handler's
remaining entrypoints are still open work; only one server cloning module remains.

Legacy screen execution/admission now use ScreenHandlers. Threshold fallback,
cache/DB lookup, inline precedence, prediction degradation, risk blocking, margin
ordering, UTC alerts and sync/async response behavior remain. Queued work still uses
the current screen callback with its admitted shallow payload copy. Ingest is now
native composition only, leaving server_handler_analysis as the sole server cloning
source. Baseline 16 passed; focused 35 passed; affected ingest/job/HTTP/import
contracts 306 passed, runner 21.92 s. Strict typing, Ruff/format/syntax, 19 checker
tests and 1314-file ratchet pass; independent review found no drift. Analysis and
prediction remain migration inputs; R4 compatibility and fast-budget gates stay open.

Client logging and unknown POST fallback now use native HandlerCompatibility
adapters. Literal log formatting, 4000-character cap, log level, API JSON 404 and
ordinary non-API 404 behavior are preserved. The source checker now attributes
nested bare-404 calls to their actual function without dropping nested or outer
calls; its allowed-owner set is unchanged. Baseline 57 passed; final focused 77
passed; affected HTTP/access/import/lifecycle contracts 228 passed, runner 16.98 s.
Strict typing, Ruff/format/syntax, 19 checker tests and 1312-file ratchet pass.
Only screening bodies remain in ingest; the two-module cloning inventory is unchanged.

The next-visit POST now joins the existing DetailDispatchHandlers owner. Body
admission precedes the snapshot; legacy index copies remain lock-protected, database
mode omits legacy entries, and the service receives the current lock/cooldown/optional
dispatch callbacks. Baseline 16 passed; focused 33 passed; affected concurrency,
retention, UTC, DB-read and HTTP contracts 95 passed, runner 8.70 s. Strict typing,
Ruff/format/syntax, 19 checker tests and 1311-file ratchet pass. Remaining ingest
bodies are screening, client logging and POST fallback; cloning modules remain two.

Detail item-update and HTML-submission POSTs now use DetailIngestHandlers. Current
service/archive/database/runtime callbacks, body limits, response projections and
exception boundaries are preserved. Baseline 51 passed; focused 70 passed; affected
archive/DB faults, dispatch locking, lazy DB loading, HTTP access and native imports
309 passed, runner 18.61 s. Strict typing, Ruff/format/syntax, 19 checker tests and
1311-file ratchet pass. The service still accepts its existing per-operation callback
bundle; R2 consolidation remains open. Ingest still owns screening, client logging,
next-visit dispatch and POST fallback bodies; two handler cloning modules remain.

Binary uploads now use UploadHandlers, including native path resolution. Positive
bounded Content-Length, Transfer-Encoding rejection, short-read closure, invalid
target body drain, resolved path containment and exclusive creation are preserved.
Current root, size limit, resolver, filesystem and optional facade open injection
remain live. Baseline 64 passed; focused 82 passed; affected HTTP/security/import/
archive contracts 260 passed, runner 23.14 s. Strict typing, Ruff/format/syntax,
19 checker tests and 1309-file ratchet pass; independent review found no regression.
This ownership move does not add filesystem race or power-loss guarantees. Two
handler cloning modules remain; deployment and broad fast acceptance remain open.

Captcha reports now use CaptchaReportHandlers with live runtime/clock/callback
dependencies. Stale challenge/auth reports, reset/auth grace, blocked/manual
handoff, force-retry lock clearing, queued/running protection, timeout manual
fallback and remote node-local deferral retain their ordering and response shapes.
Baseline 33 passed; focused 51 passed; final affected auth/scope/solver/HTTP/import
contracts 397 passed, runner 20.62 s. Strict typing, Ruff/format/syntax, 19 checker
tests and 1307-file ratchet pass; independent review found no behavior defect.
server_handler_ingest still owns other cloned handlers, so the two-module cloning
inventory remains unchanged. This does not retire persisted auth compatibility.

The /api/status adapter now uses CollectionStatusHandler with live typed host
dependencies. Database/runtime counts, file capture union, cooldown preview,
100-candidate/10-result bounds, independent repository/read-mode gates and the
existing exception boundary remain unchanged. server_handler_get_collection is
now native composition only; two handler cloning sources remain. Baseline 40
passed; final focused 62 passed; affected import/routing/status/HTTP/access/lifecycle
contracts 273 passed, runner 14.59 s. Strict typing, Ruff/format/syntax, 19 checker
tests and 1305-file ratchet pass. Independent review found no behavior defect.
The fast-budget failure and R1-R9 remain open; deployment remains deferred.

Drift, release-gate and recent-gap report POSTs now use ReportJobHandlers.
Admission still captures generators, root paths and release summary callbacks;
invalid/negative numeric defaults, zero values, body rejection, async polling,
summary-stage errors and atomic report publication are preserved. Before 22
passed; focused with source contracts 42 passed; affected job lifecycle/access/
import contracts 233 passed, runner 21.98 s. Strict typing, Ruff/format/syntax,
19 checker tests and 1303-file ratchet pass. Only _get_status still has a cloned
body in get_collection. Report generators still depend on tools and remain
migration inputs; this move does not complete their product or dependency gates.

Legacy analysis prediction/health and collection-template GETs now use native
AnalysisReadHandlers. Prediction validation/logging, template lazy loading and
callback replacement, uptime clamping and DB-count degradation are preserved.
Eight real HTTP cases plus health characterization/descriptors pass: 12 before,
15 after. Affected lifecycle/status/routing/import contracts: 266 passed, runner
17.50 s. Strict typing, Ruff/format/syntax, 19 checker tests and 1301-file ratchet
pass. Only status and three report-job POST bodies remain in get_collection;
analysis/prediction are still migration inputs, not completed product engines.

All six manual-review GETs now use ReviewReadHandlers: receipts, jobs, operations,
control status, backup repairs and integrity history. Current roots/repositories,
runtime/context ordering, response fields, error codes, default/clamped limits and
newest-first history are preserved. Baseline/focused 20/32 passed; after keeping
limit validation visible to existing route contracts, final affected tests report
211 passed and 12 subtests, runner 18.80 s. Strict typing, Ruff/format/syntax,
19 checker tests and 1299-file ratchet pass. Remaining get_collection functions
are status, prediction/health/template and three report-job POSTs; three handler
cloning sources and the earlier full-fast timing failure remain open.

Manual snapshot path validation and RecoveryError now live in the I/O-free
auth_snapshot_contract module shared by NAS reads and PC1 publishing. Existing
tools exports preserve exception identity; NAS manual download succeeds with
tools imports actively blocked. The desktop installer includes the new contract
and five previously missing native browser/cookie dependencies. Isolated actual
payload imports and the PowerShell auth launcher now pass. Focused 60 passed;
affected 179 passed/1 failed on an outdated standalone-settings fixture, then its
updated dependency closure passed separately (1 passed). Strict typing, relevant
Ruff/format/syntax, PowerShell parse, 19 checker tests and 1297-file ratchet pass.
This closes this snapshot-path src-to-tools edge, not all such dependencies or
desktop deployment acceptance. Three handler cloning sources and R1-R9 stay open.

Recovery snapshot downloads now read at most 5 MiB plus one byte before rejecting
oversized files, so the HTTP limit also bounds file-read allocation. A regression
failed on the original unbounded read(-1), then passed with the capped read and
closed stream. Exact-limit success, digest/base64 delivery, HTTP validation and
immutable manual snapshots remain covered: 45 passed, runner 7.30 s. Strict typing,
Ruff/format/syntax, 19 checker tests and 1295-file ratchet pass. This closes the
whole-file-read concern below; src-to-tools manual-path dependency remains open.

Recovery state and snapshot GETs now use RecoveryReadHandlers with live coordinator,
authorization and path callbacks. Auth-before-state/file access, active ID/status,
immutable manual snapshot path, 5 MiB boundary, digest and base64 contract are
preserved. Four characterization cases plus native descriptors supplement real
HTTP validation and manual-handoff tests: focused 60/61 passed before/after;
affected auth/security/import contracts 257 passed, runner 22.66 s. Strict typing,
Ruff/format/syntax, 19 checker tests and 1295-file ratchet pass. The pre-existing
whole-file read before size validation and src-to-tools manual-path dependency
remain explicit follow-up concerns; this extraction does not close either.

Six collection console GET handlers now use CollectionReadHandlers: HTML, static
assets, overview, item list, regions and item detail. Raw bytes/MIME/length,
decoded path-ID precedence without query mutation, current repository/callbacks
and original 400/404/503/500 boundaries remain intact. Focused before/after:
60/61 passed; affected observer/status, static resources, access and import/source
contracts: 343 passed, runner 22.88 s. Strict typing, Ruff/format/syntax, 19 checker
tests and 1293-file ratchet pass. Manual-review reads, recovery snapshot transport
and collection status/visit routes remain in get_collection; three cloning sources
remain. No full-fast timing or deployment closure is claimed.

The task-control module has now exited function cloning. TaskReadHandlers owns
item and pipeline reads, API/non-API fallbacks and recent-detail replay delegation;
the legacy module retains explicit composition and exports. DB-first reads,
locked runtime fallback, 400/404/503 responses, pipeline errors and late facade
replacement are preserved. Baseline 43 passed; final focused 61 passed; affected
all task-control native owners plus real item/merge HTTP, access and import/source
contracts 269 passed, runner 19.48 s. Strict typing, Ruff/format/syntax, 19 checker
tests and 1291-file ratchet pass. Three handler cloning sources remain. The prior
fast timing failure and R1-R9 remain open; no deployment acceptance is inferred.

Auth force reset, completion and cooldown-resume HTTP commands now use native
AuthCommandHandlers. Node authorization precedes parsing; current CDP/cookie trust
policies precede completion; stale results, rejection statuses and original
exception boundaries remain intact. Focused before/after: 65/68 passed; affected
auth, scoped cleanup, access and import contracts: 273 passed, runner 20.80 s.
Strict typing, Ruff/format/syntax, 19 checker tests and 1289-file ratchet pass.
Independent extraction review found no behavior/binding regression. Remaining
task-control ownership includes item/pipeline reads, fallback and maintenance.

Operator region reset, item reanalysis, manual update and pause/resume now use
ObserverCommandHandlers with ordinary bound HTTP functions and current-host
callbacks. Authorization-before-body, rejection/error envelopes and path-only
pause selection are preserved. Focused before/after: 75/79 passed; affected
operator, persistence/error, access and import contracts: 268 passed, runner
13.14 s. Strict typing, Ruff/format/syntax, 19 checker tests and 1287-file ratchet
pass. Independent extraction review found no behavior/binding regression.
Four handler cloning sources and the earlier fast timing failure remain open.

The five recovery POST transitions now share a native RecoveryTransitionHandlers
owner. Authorization still precedes body parsing; heartbeat protocol/node checks,
required recovery IDs, normalized claim identities, snapshot numeric conversion,
stale 409 responses and result callback forwarding are unchanged. Fourteen focused
cases now cover mutation prevention and native/coordinator replacement; this file
is included in fast and security. Focused before/after 22/24 passed; affected auth,
scope, access and import contracts 243 passed, runner 22.34 s. Strict typing,
Ruff/format/syntax, 19 checker tests and 1285-file ratchet pass. Full security and
cross-device deployment remain unverified for this state.

Seed task claim and progress-report routes now use SeedTaskHandlers. Session
validation/defaults, seed-scope pause, generic task_key forwarding, response/error
codes, legacy URL aliases and worker access rules remain intact. Seven new native/
late-callback cases supplement ten selected HTTP contract cases and write-access
coverage: focused 25 passed; affected seed/service/status/access/import contracts
193 passed and 2 skipped, runner 16.42 s. Strict typing, Ruff/format/syntax,
19 checker tests and 1283-file ratchet pass. No PostgreSQL acceptance is inferred.
Seed batch/async job handling remains in the analysis handler for later migration.

Both detail POST task-dispatch routes now use DetailDispatchHandlers, covering
single/batch claims through DB service callbacks or the runtime queue. The native
handler functions retain names, binding, cooldown/UTC rules, paused batch behavior,
error envelopes and current-host lookup. Existing parallel dispatch/retention and
retired-GET security tests remain active. Seven new cases characterize validation,
pause, failures, callback publication and method ownership. Focused 39 and affected
297 passed, runner 16.52 s; strict typing, Ruff/format/syntax, 19 checker tests and
1281-file ratchet pass. The route inventory now inspects registered handler source,
including native closures, instead of silently dropping relocated functions.
Four legacy handler sources remain; fast latency and whole-plan acceptance stay open.

The complete solver run lifecycle now has explicit SolverRunHost dependencies and
a native SolverRunLifecycle owner. Ordinary function adapters retain DataHandler
method binding and executor request/token arguments. File-update and quiet HTTP-log
adapters are native too, so server_handler_core exits cloning. The direct core
module still requires full host injection for standalone solver execution, as before.
Baseline 122 passed; native descriptor/file callback cases brought the matching
group to 124. After replacing one location-dependent logging assertion with a real
preflight-failure/logging/token-release check, focused 130 and affected 336 passed.
Independent review found no lifecycle/lock regression. Strict typing, Ruff/format,
syntax, 19 checker tests and 1279-file ratchet pass; the unchanged ratchet needed
one retry after git returned an empty baseline-tree value. Fast latency remains open.

Solver execution identity, resume/cancel checks and manual polling now publish
four native SolverExecutionGuard methods. A separate late handler composition
phase prevents handler exports from overwriting the facade-bound owner. The
real-thread run replacement/resume coverage remains intact, and 14 new direct/
facade cases cover saved callbacks, runtime/clock replacement and cancellation
sources. Focused 38 passed; affected solver/status/import contracts 277 passed,
runner 20.30 s. Strict typing, Ruff/format/syntax, 19 checker tests and 1275-file
ratchet pass. run_solver and HTTP compatibility functions still clone; all five
handler sources remain. The prior fast performance failure remains open.

ScreenResultSummary and ScreenAlertStore now own confidence/summary and alert
persistence callbacks. server_collection_operations has exited the cloning list;
its direct-module DB preference helper remains a local function, and the facade's
equivalent remains owned by CollectionStatusReaders. Focused before/after: 36/38
passed. Affected HTTP/import/export/runtime: 527 tests and 1207 subtests passed,
runner 64.47 s. Strict mypy, Ruff/format/syntax, 19 checker tests and 1273-file
ratchet pass; independent review found no slice defect. Legacy unreadable-alert
fallback and non-atomic writes remain unchanged.

The core-exit fast milestone has 1063 passed and 2 skipped, but its runner took
99.14 s and failed the unchanged 60-second gate. This is not fast acceptance.
Import probes and runner subprocess tests approximately doubled versus the prior
checkpoint; a later CPU sample was 96%, which does not prove test-time contention.
Performance diagnosis remains open; do not weaken gates or remove test isolation.

Auction risk payload/alias/signal and result callbacks now publish five native
AuctionRiskPolicy methods from collection/adapters/auction_risks.py. Direct and
server/context entrypoints retain live callback and constant replacement, exact
boolean tests, top-level value precedence and existing response fields. Twelve
behavior cases passed before extraction; two native ownership cases were added
afterward. Focused before/after totals: 16/18 passed; affected detail, screening,
ingest and import/export/source checks: 214 passed, runner 17.56 s. Strict mypy,
Ruff/format/syntax, 19 checker tests and 1270-file ratchet pass. Summary/confidence
and alert persistence still clone; the direct DB preference helper remains local.
No full fast/security or deployment acceptance is inferred from this slice.

Auction field override and structured reset now publish native AuctionRecordPatch
methods from collection/adapters, with the public alias table retained. All 44 alias
entries and their order were compared before removal from the old owner. Seven new
cases cover conflict precedence, empty/zero/false values, retained fields, live table
replacement and detail rebuild/archive/DB/runtime publication order. Focused before/
after 26 passed; affected persistence/HTTP/import/export/source 193 passed, runner
20.31 s. Strict typing, 19 checker tests and 1268-file ratchet pass. The remaining
operations implementation covers risk/result/summary helpers and alert persistence.

Five auction numeric callbacks now publish native AuctionPricePolicy methods from
collection/adapters/auction_prices.py. Preserved unit parsing, legacy string cleanup,
numeric zero/negative behavior, field precedence/zero fallback, margin and integer
conversion semantics; saved composite methods still use the current parser. Existing
AVM normalization is intentionally not substituted because its contracts differ.
Thirty-four characterization/native cases pass on both hosts, with 53 focused cases
before/after and 193 affected seed/AVM/import/export/source cases, runner 20.59 s.
Strict typing, 19 checker tests and 1266-file ratchet pass. Remaining operations
cloning includes record overrides, risk/result/summary helpers and alert persistence.

Service factories, seed-stub building and batch intake now publish four native
CollectionServiceOperations methods. Constructor/root/repository/adapter and saved
service callbacks remain live; batch intake retains the collection lock and existing
archive/DB/queue ordering. Four native replacement cases plus an import probe were
added. Baseline 50 passed; focused 54 passed; affected seed/HTTP jobs/startup/import/
export/source group 231 passed, runner 19.27 s. Two files pass strict typing; 19
checker tests and 1264-file ratchet pass. Source-policy defaults and long per-operation
callback contracts are unchanged and remain R2 work; operations cloning still remains.

Working-item index access, eviction and cache/DB lookup now publish three native
CollectionWorkingItems methods. Cache identity/precedence, sync-before-processed
filtering, missing/error returns and eviction scope are preserved. Removed the
overwritten duplicate runtime-index function from server.py. A direct-module DB
lookup without auction_date reproduced AttributeError from a datetime class/module
mismatch; its import is corrected and tested. Ten direct/facade cases plus an
import probe were added. Final focused 34 passed; affected DB/detail/runtime/HTTP/
import/export/source group 205 passed, runner 21.58 s. Strict typing, 19 checker
tests and 1262-file ratchet pass. The facade DB-read preference remains owned by
CollectionStatusReaders; the legacy operations preference helper remains pending.

Task submission and the retry polling loop now also use native owners. submit_task
belongs to CollectionFileRuntime and keeps the processing registry captured at claim
time for completion/cancellation/rejection release. SolverRetryLoop preserves live
retry-policy and poll-interval dependencies. Ten new native/replacement/loop cases
and an import probe were added. Baseline 25 passed; focused 44 passed; affected
concurrency/startup/import/export/source group 179 passed, runner 12.48 s. Three
files pass strict typing; 19 checker tests and 1260-file ratchet pass. The operations
module still clones its remaining source-policy, working-item and service helpers.
This latest state has focused/affected evidence, not a new full fast/security pass.

server_data_runtime has fully exited function cloning. File processing/scanning now
publish native CollectionFileRuntime methods; all existing runtime exports, including
load_json_file, remain available through native publication and live facade bindings.
Nine new cases cover full export identity, saved service/model/queue dependencies,
scan order, processing skip, idle cadence and error backoff. Baseline 40 passed;
focused 49 passed. Formal fast: 942 passed, 2 skipped, runner 58.97 s, exit 0 under
the unchanged 60-second gate. Two files pass strict typing; 19 checker tests and
1258-file ratchet pass. The fast gate has only 1.03 s margin in this run; timing
evidence is retained. One core and five handler cloning sources remain.

Index loading and interrupted-file recovery now publish native CollectionIndexBootstrap
methods. Saved direct/facade entrypoints follow root/runtime/repository replacements;
index containers, DB preference/fallback and per-file recovery error handling are
unchanged. Six new cases cover live dependencies, recovered evidence, retained old
markers and sibling recovery after a rename failure. Baseline 17 passed; focused
23 passed; affected index/startup/import/export/source group 151 passed, runner
12.75 s. Two files pass strict typing; 19 checker tests and 1256-file ratchet pass.
The remaining processing/scanner functions subsequently migrated as recorded above.

Startup initialization now publishes a native CollectionStartup method through an
explicit live host protocol. Initialization/runtime lock order, journal recovery
before workers, index failure retry, optional DB/seed/sample failure behavior and
worker selection are unchanged. Four lifecycle regressions and one import probe
were added. Baseline 46 passed; focused 50 passed; affected startup, real scoped/
legacy/mixed process-exit recovery and import/export/source contracts 230 passed,
runner 89.50 s. Strict typing, 19 checker tests and 1254-file ratchet pass. Index
loading and orphan recovery were subsequently migrated as recorded above;
processing/scanner remain in the cloning module.

Collection DB upsert/deletion callbacks now publish native CollectionDatabaseWrites
methods for both direct-module and facade callers. Saved callbacks follow repository
replacement; payload identity, string deletion IDs, disabled-DB no-ops and original
exceptions are preserved. Six native regression cases and an import probe were
added. Baseline 37 passed; focused 43 passed; affected HTTP/archive failure, dual-write,
seed/import/export/source group 185 passed, runner 10.06 s. Two files pass strict
typing; 19 checker tests and 1253-file ratchet pass. Database transaction/storage
contracts are unchanged; initialization was subsequently migrated as recorded above.

Eight archive exports now use native CollectionArchivePaths/CollectionArchiveRecords
with explicit date/filesystem/root/reader/artifact dependencies. Direct data-module
callers and server facade callers each bind the same native implementations to their
own live host. An initial fast run exposed 34 missing-direct-entrypoint failures;
the scoped binding fix passed 73 focused consumer/preservation cases. After replacing
dynamic export publication with explicit native aliases, final focused: 73 passed,
runner 4.19 s; final formal fast: 913 passed, 2 skipped, runner 41.56 s, exit 0 under
the unchanged limit. The earlier 35.42 s fast pass predates the explicit-alias fix.
server_native_bindings now centralizes native owner publication order. Five typed
native/I/O/composition files, 19 checker tests and the 1251-file ratchet pass. Data
runtime initialization, DB writes, processing/scanner and remaining cloning stay
open; this checkpoint does not close full security or deployment acceptance.

The remaining observer wrappers and pause/resume orchestration now publish native
CollectionObserver and CollectionRuntimeControl methods. server_collection_control
has fully exited cloning; repository/runtime/filesystem/clock/status dependencies
remain live. Failed flag or challenge cleanup retains pause and does not advance
resume state. Five native/replacement/fallback cases and two import probes were
added. Baseline 125 passed; final focused 132 passed; affected collection API,
HTTP routes, source/import/export suite 296 passed (runner 11.83 s). Two native
files pass strict typing; 19 checker tests and the 1246-file ratchet pass.
Two core and five handler cloning sources remain; full R1-R9 completion is open.

The console authentication-completion entrypoint now has a native AuthCompletion
owner and explicit live dependency bindings. It has left the cloning inventory;
server/context publish the same bound method. Generation validation, journal
prepare/clear/receipt/finish ordering, rollback and cookie two-phase confirmation
are unchanged. Five new native ownership/replacement/invalid-target cases and two
fresh-process import probes were added. Baseline 41 tests passed before/after;
final focused group 46 passed; affected concurrency/persistence/HTTP/import/source
group 304 passed (runner 105.86 s). Three native files pass strict mypy and full
Ruff/format; checker tests 19 passed; ratchet 1240 files with no above-500 tier.
This affected-group evidence does not replace full security or release acceptance.

The six confirmation-receipt helpers also now publish native bound methods from
AuthCompletionReceipts. Path/runtime/recovery/clock dependencies remain live;
pending cleanup intents still block cached/durable receipt replay under the
runtime lock. Existing store/journal and retention/error semantics are unchanged.
Baseline 52 cases pass before/after, final focused group 57 passed, affected
receipt/cleanup/crash/import/source group 295 passed (runner 100.84 s). Two native
files pass strict typing; 19 checker tests and the 1242-file ratchet pass with
unchanged baseline. Other control functions and R1-R9 work remain incomplete.

Authentication finalization, confirmation-state validation, node challenge matching
and cooldown resume now publish four native AuthCleanupCompletion methods too.
Finalizer scope selection still holds finalize_lock then runtime.lock; journal and
rollback order and cooldown no-solve semantics are unchanged. Focused group 70
passed; affected real-exit/receipt/generation/HTTP/import/source group 306 passed
(runner 79.59 s). Two native files pass strict typing; 19 checker tests and the
1244-file ratchet pass. Remaining control cloning covers observer wrappers and
pause/resume, not these auth transactions. Full release acceptance remains open.

The manual completion mixed-state boundary is now covered by the native
solver_pause_cleanup owner: finalizer, cooldown and direct completion preserve an
independent legacy receipt, flag, recovery identity/manual epochs and global pause.
Identity comparison also preserves independent IDs whose request names the same
scope. Scoped receipt publication failure restores the target without deleting
the legacy flag. Explicit global reset retains its deliberate clearing behavior.

Automated solver success now uses the same native ownership policy. An independent
legacy owner retains its full recovery/solver/pause snapshots and durable bytes;
the completed scope is cleared without publishing success or grace metadata into
that legacy owner. Scoped flag/receipt deletion failures retain a retryable target.
Own-mirror cleanup, inferred scope and operator pause behavior remain covered.

Mixed-state process termination is now covered at scoped flag removal, cleanup
and completion publication, through two startups and same-request retry. Startup
hydrates a matching valid legacy flag's manual mode and required epoch without
rewriting its bytes. Opaque/invalid/nonmatching legacy flags retain the existing
existence-based pause behavior; their metadata is not assigned to another owner.

Legacy/scoped restore orchestration now lives in solver_startup_recovery with
explicit runtime, receipt-reader and pause dependencies. Facade wrappers preserve
current runtime replacement and monkeypatch entrypoints; the native owner imports
without bootstrapping server/context and keeps separate runtime instances isolated.

Challenge receipt publication/clearing now lives in solver_challenge_receipts,
with explicit runtime, path, reader and clock dependencies. Facade entrypoints
retain current bindings and the locked-clear override. Intent retirement still
precedes receipt deletion under the same lock; matching legacy mirrors are removed
before scoped latches, and recovery reassignment uses exact challenge IDs.

Challenge creation/reuse now uses the native ChallengeCreation owner with explicit
request policies, receipt I/O, runtime, clocks and pause dependencies. The public
entrypoint still owns the runtime lock and resolves current facade dependencies.
Scoped/legacy reuse, first-seen times, publication order and logged persistence
failures remain unchanged; direct native import does not bootstrap the server.

Manual-required transitions and flag publication now use solver_manual_pause,
with explicit runtime, clock, cancellation, persistence and pause dependencies.
Facade entrypoints remain replaceable. Running-solver cancellation, scoped flag
before legacy mirror, both-write attempts and first-error precedence are preserved.

Flag reading and manual-retry eligibility now live in solver_manual_retry with
explicit runtime, path, normalization, status and configuration callbacks. Legacy
opaque/non-object/missing flags, string manual-only values, file replacement and
scope/global precedence are covered through both native and facade entrypoints.

SolverDispatch now owns all 28 dispatch exports as native bound methods, including
retry request routing/timing, CDP probes and submission reservation/activation.
solver_dispatch_binding supplies explicit live facade callbacks; retained methods
observe runtime, policy and executor replacement. The dispatch module is removed
from the active cloning list. Both native modules import without server bootstrap.
SolverState also publishes all 23 state entrypoints as native bound methods,
composing the existing challenge creation/receipt/startup/pause owners. Its live
binding observes replacement runtime, clocks, I/O and cleanup callbacks; source
classification is supplied at composition. State and dispatch no longer bootstrap
server_context when imported. AuthRecovery, SolverAuthHistory and SolverStatusReader
now publish the 18 former server_auth_recovery exports without cloning. The native
owners receive live facade dependencies through auth_recovery_binding, including
coordinator/repository replacement, current grace settings, token reader and
source target policy. Cookie ownership has also exited cloning; the remaining R1
server owners are listed above. General adapter selection remains R2 work.
Flag publication remains direct-write; atomic flag publication and full facade
retirement are not claimed.
Legacy schema/caller retirement and the broader durability contract remain open:
these tests establish process-exit retry, not atomic multi-file power-loss recovery,
cross-process coordination or challenge-ID binding in the old manual-flag schema.

Current cookie exit checkpoint: all 19 remaining cookie/report/path exports are
native bound methods, composed by auth_cookie_binding. server_auth_cookie has
left _CORE_MODULES/function cloning. Paths, blocked-report ordering and healthy-only
refresh writes preserve their existing behavior and live facade dependencies.
Final focused group: 201 passed; separate source/import group: 96 passed. Four
native modules pass strict typing and Ruff/format. Checker tests: 19 passed;
ratchet: 1236 files, no above-500 tier, baseline unchanged. The initial 501-line
server facade failure was fixed by sharing the native-owner publication loop.

Latest R7 timing checkpoint: source-contract profiling found repeated full-source
splits, AST parsing and traversals. Indexed UTF-8 source slicing, source-keyed AST
caching and one-pass assertion scanning preserve the assertions; three Unicode/
CRLF equivalence cases were added. Native import probes retain all 22 fresh
interpreters and all four bootstrap path combinations, now in bounded groups of
four with distinct working directories and unchanged per-process timeouts.
Focused source/import group: 96 passed; final source group: 17 passed. Under the
same cProfile invocation, the 14-test source group went from 18.19 s to 7.01 s;
instrumented timings are diagnostic only, not acceptance measurements.

Earlier formal fast at the profiling state: 877 passed, 2 skipped, pytest 88.65 s,
runner 92.00 s; FAILED the unchanged 60-second gate. The local profile improvement
does not prove a full-suite speedup. Next R7 step is phase-level collection/startup/
test timing attribution before another broad run. Full security remains open.

The subsequent runner now supports optional --timing-report JSON checkpoints.
Six isolated success/failure/abrupt-exit integration cases pass with diagnostics
enabled and disabled. The initial diagnostic attempt has only an incomplete
500-test report and no recovered terminal status; it is not acceptance evidence.
The completed diagnostic run on the final timing implementation passed fast:
881 passed, 2 skipped, pytest 29.89 s, runner 31.20 s, exit 0, with unchanged
60-second gate. Collection was 5.36 s and test loop 24.47 s. Reports contain phase
and file aggregates without captured payloads; parent elapsed includes diagnostic
overhead. The earlier timing variability remains unexplained, and this does not
establish a performance fix or close R7. Full security and release gates remain
open. Ruff/format, 19 checker tests and the 1237-file ratchet passed.

Earlier milestone fast after the composition change: 874 passed, 2 skipped,
pytest 68.60 s, runner 70.77 s. The command FAILED its unchanged 60-second gate.
R7 timing remained open; diagnose elapsed-time sources before another
full run. Full security still lacks completion after its earlier 180-second timeout.
Deployment/restarts remain deferred. R1-R9 are not complete.

The following checkpoints describe earlier worktree states; their outstanding
cookie items are superseded by the current checkpoint above.

Retry-monitor checkpoint: SolverRetryMonitor and solver_retry_monitor_binding
now publish the three manual-retry entrypoints as native bound methods. The old
definitions and exports are removed from server_auth_cookie. Live runtime,
callback replacement, retry lock, post-probe snapshot checks, delegated PC2
ownership and submit failure/False behavior are preserved. Final affected tests:
165 passed; strict typing, Ruff/format, checker self-tests and ratchet pass.
server_auth_cookie still has 19 cloned exports for reports, paths and refresh/state
operations. Its full retirement and the rest of R1-R9 remain open.

Cookie health checkpoint: src/auth_cookie_health.py now aggregates native
collection/adapters/taobao_health.py and taobao_list_probe.py. Classification,
list parsing, cookie sessions/navigation headers and credential redaction no
longer depend on tool facades; tools re-export native owners and shared constants.
server_auth_cookie has no remaining tools imports, but still belongs to the
server cloning inventory. Final affected tests: 257 passed; three native modules
pass strict typing, Ruff/format and import isolation; checker self-tests and
ratchet pass (1229 files, no above-500 tier). Native retry/report/path/state owners
are still required before server_auth_cookie can leave cloning. R1-R9 stay open.

CDP cookie transport checkpoint: src/cdp_cookie_transport.py now owns websocket
export, lazy Playwright fallback, bounded reconnects, health/user-agent probes,
endpoint discovery and cache handling. Runtime export no longer imports tools.
All 14 transport exports bypass function cloning; two tool entrypoints use explicit
live dependency bindings to preserve later facade replacements. The 218-test
transport/browserless/API/health/handoff/retry/scheduler group passed, alongside
strict typing for owner/binding, Ruff/format, checker self-tests and ratchet.
Native import isolation proves no tools/server/bootstrap or eager Playwright load.
Cookie health orchestration and server_auth_cookie cloning remain R1 work; this
does not complete the broader facade inventory or R2-R9.

Cookie metadata checkpoint: src/cookie_snapshot_metadata.py now owns summaries,
expiry normalization, shape/value fingerprints and snapshot comparisons. Runtime
summary calls no longer import tools; all eight cookie-slice exports now reference
native functions without cloning. Local datetime formatting and safe output fields
are preserved. A 203-test metadata/browserless/API/health group passed; after
lint-only cleanup, the 43-test metadata/browserless group passed again. Native
strict typing, Ruff/format, 19 checker tests and ratchet (1223 files, no above-500
tier) pass. CDP export, health probing and server_auth_cookie cloning remain open.

Cookie snapshot storage checkpoint: runtime writes and tool read/write exports
now share src/cookie_snapshot_storage.py directly, without cloning those two
functions or importing tools from the runtime write path. Atomic staging,
fsync, replacement, cleanup and list-only loader validation are preserved.
The 155-test focused storage/browserless/API/retry/scheduler group passes;
native strict typing, Ruff/format, 19 checker tests and ratchet (1221 files,
no above-500 tier) pass. Cookie summaries, CDP export, health probing and the
server_auth_cookie cloning boundary remain open. No broad suite or deployment
was repeated at this checkpoint.

Latest authentication-recovery exit: 179 focused tests and a separate 96-test
source-route/bootstrap group passed. Four native modules pass strict typing;
Ruff/formatting, checker tests and ratchet pass (1219 files, no above-500 tier).
The full security milestone failed the unchanged 180-second runner limit, with
no completed suite result. Full fast was not repeated. This leaves broad security
acceptance open; focused passes do not replace it. See the progress log's
"Authentication recovery exits function cloning" section.

Previous state-exit checkpoint: 171 entrypoint/runtime tests passed. Separate scoped,
legacy and mixed process-exit groups passed 29 / 38 / 23 tests; concurrency passed
4 tests. The initial combined crash run exceeded an outer observation limit and
is not a pass. Native typing, Ruff/formatting, checker self-tests and the ratchet
passed (1216 files, no above-500 tier). Full fast/security were not rerun after
the state migration; the prior dispatch fast result is historical for this state.
See the progress log's "Solver state exits function cloning" section.

## Older entries that must not be reopened as wholly unimplemented

Previous dispatch-exit checkpoint: 147 focused tests passed; fast passed with
871 passed / 2 skipped in 53.30 s under the unchanged 60-second gate. The earlier
pre-binding-extraction fast attempt failed timing at 74.78 s despite passing test
assertions. These are separate runs, not evidence of a measured optimization.
Both native modules pass strict typing; the ratchet covers 1215 files with no
above-500 tier. Full security and deployed runtime acceptance remain unverified
for this final state; see the progress log's "Solver dispatch exits function
cloning" section for scope and intermediate failures.

- Source wildcard imports and source bare exceptions are both zero in the current
  scan. Data-fixer and captcha function cloning have been removed. The recent
  status, cookie-scheduler, and manual-review owners use native bindings.
- Auth recovery codes have one Python registry, generated TypeScript, and a CI
  consistency check. Legacy retirement remains R3.
- Threaded HTTP, request guards, bounded/durable collection jobs, archive failure
  propagation, and runtime-state ownership have implementation and focused proof.
  The remaining sync compatibility paths are identified in R4.
- HTTPS/private-CA and role-token guards, negative HTTP security tests, atomic
  cookie writes, LLM evidence/response budgets, cancellation deadlines, pinned
  dependencies/images, UTC migration, and Alembic parity have code and recorded
  verification. Machine configuration and release acceptance remain separate.
- Desktop product source has no remaining `.js` files. Strict TypeScript,
  shared DOM/native/HTTP helpers, npm checks, Rust checks, and Playwright smoke are
  integrated. This does not close R5 or packaged-app acceptance.
- PC2 worker heartbeats, watchdog retry limits, log rotation, child supervision,
  graceful-stop configuration, and a non-root browser exist. Real PC2 acceptance
  is still required.
- The decision is to retain the current effective-line policy and baseline.
  The original suggestion to relax it is not an outstanding implementation task.

## Verification and release gates

Latest flag-reader/retry-policy checkpoint (2026-09-25):

- Added 20 native/facade contract cases for flag replacement/legacy fallbacks and
  retry precedence, plus native import isolation. Final affected group: 191 passed,
  pytest 21.35 s, runner 23.50 s; isolated storage, business DB disabled.
- Native module/tests/manifest Ruff, strict native mypy with imports skipped,
  full owner/test formatting and edited dispatch-range formatting pass. Selected
  facade syntax/bug checks excluding F821 and 19 checker tests pass.
- Static batch timed out before reporting its ratchet result; standalone ratchet
  then passed for 1214 files, no above-500 tier or baseline change. This was not
  a completed static batch pass. Only a formatter-added blank line followed tests.
- Full fast/security, real retry-worker scheduling and deployed-runtime acceptance
  were not run in this structural slice; earlier broad results remain historical.

Earlier manual-pause owner checkpoint (2026-09-25):

- Added six real open-failure cases covering scoped/legacy/both flag failures,
  running-solver cancellation, both-write ordering, pause preservation and retry.
- Focused API/manual/mixed/returned-error group: 162 passed, runner 32.06 s.
  Final import/legacy/mixed crash group: 66 passed, runner 88.88 s. These are
  separate serial isolated runs with business DB disabled and unchanged limits.
- Native module/tests/manifest Ruff and strict native mypy (imports skipped)
  pass. Full formatting passes for the new owner, state facade and tests;
  dispatch formatting is checked only for the edited function range.
- Selected facade syntax/bug checks excluding F821, 19 checker tests and ratchet
  pass: 1212 files, no above-500 tier or baseline change.
- Subagent exploration was unavailable due to a service authentication failure;
  the main thread checked the extraction and test contracts. No independent-review
  pass is claimed. Full fast/security and deployment were not run for this slice.

Earlier creation-owner extraction checkpoint (2026-09-25):

- Focused request/durability/import/concurrency/API/scope group: 163 passed,
  runner 34.88 s. Separate legacy/mixed crash recovery group: 61 passed, runner
  96.86 s. Serial isolated runs, business DB disabled, execution limits unchanged.
- Native module and regression Ruff, strict native mypy (imports skipped),
  formatting, selected facade syntax/import checks excluding F821, 19 checker
  tests and ratchet pass: 1210 files, no above-500 tier or baseline change.
- Independent review found no introduced behavioral regression. Full fast/security
  were not repeated for the structural slice; earlier broad results are historical.
  Deployment/restarts and remaining R1-R9 closure are still deferred/open.

Earlier receipt-owner extraction checkpoint (2026-09-25):

- Focused durability/import/cleanup/mixed-ownership/scope group: 104 passed,
  runner 28.75 s. Native writer now shares the fsync/replace fault regression;
  native receipt import is checked without server/context bootstrap.
- Separate scoped/mixed crash group: 52 passed, runner 117.03 s. Separate legacy
  crash/returned-error group: 59 passed, runner 55.95 s. Serial isolated storage,
  business DB disabled, execution limits unchanged; no combined-suite claim.
- Native owner/tests Ruff and strict native mypy (imports skipped), formatter,
  selected facade syntax/import checks excluding F821, 19 checker tests and ratchet
  pass: 1209 files, no above-500 tier or baseline change. Independent review found
  no confirmed extraction regression.
- Full fast/security were not rerun for this behavior-preserving extraction.
  Earlier broad checkpoints are historical. Deployment/restarts remain deferred.

Earlier startup-owner extraction checkpoint (2026-09-25):

- Native owner/regression/manifest Ruff and strict native mypy (imports skipped)
  pass. Public wrappers preserve behavior; no new server cloning source added.
- Original combined affected attempts did not complete: first tool timeout at
  180 s, then runner execution gate at 180 s without reported assertion failure.
  Host CPU sampled at 100%; this does not establish the sole timeout cause.
- Separate isolated groups passed: mixed/legacy-completion 86 cases, runner
  74.19 s; scoped/legacy crash/import 149 cases, runner 128.39 s. These precede
  only removal of unused os/Path facade imports. Final-source owner/runtime group:
  15 passed, runner 4.70 s. Do not label these as one combined-suite pass.
- Formatting, selected facade syntax/import checks excluding inherited F821,
  19 checker tests and ratchet pass: 1208 files, no above-500 tier or baseline change.
- Full fast/security were not rerun for this behavior-preserving extraction;
  earlier numbers below belong to the previous source. No release/deployment claim.

Earlier mixed-state startup checkpoint (2026-09-25):

- First actual crash probe failed: startup restored legacy ID/request but lost
  runtime manual-only and its required epoch. Native legacy-flag hydration fixes it.
- Added 23 security-only cases: 18 real child exits (three manual entrypoints,
  seed/unscoped legacy and detail/same-scope legacy, three interruption points)
  plus five matching/retryable/other-owner/opaque/invalid metadata cases.
- Final affected auth/crash/startup/import group: 235 passed, runner 90.44 s.
- Final fast: 867 passed, 2 skipped, runner 46.88 s; security: 604 passed,
  4 skipped, runner 145.95 s. Both exit 0; serial isolated runs, business DB
  disabled. Fast limit remains 60 seconds; earlier timing failure remains historical.
- Native module/regression/manifest Ruff, native strict mypy (imports skipped),
  selected facade syntax/bug checks excluding F821, formatting, 19 checker tests
  and ratchet pass: 1206 files, no above-500 tier or baseline change.
- Independent review found no confirmed new defect. Fake startup workers verify
  initialization state and launch registration, not actual thread scheduling.
  PostgreSQL/POSIX skips, power-loss and deployed-runtime gates remain unverified.
  No deployment, restart or business-data changes.

Earlier automated mixed-state checkpoint (2026-09-25):

- Four new cases reproduced legacy flag deletion before the fix. Added 18 cases:
  independent legacy ownership, scoped flag/receipt deletion failure and retry,
  own compatibility-mirror cleanup, inferred scope and operator pause.
- Affected group: 91 passed, runner 13.62 s. Independent review found no new
  ownership/locking regression in the changed boundary.
- Final-source fast first passed all 867 cases (2 skips) but FAILED its time gate
  at 71.59 s. An unchanged, separate rerun passed in 54.27 s (867 passed, 2 skipped).
  The intermittent timing cause is not established; the 60-second gate is unchanged.
- Security: 581 passed, 4 skipped, runner 142.80 s, exit 0. All broad runs were
  serial, used isolated storage and disabled business DB access.
- Native owner/regression Ruff, owner strict mypy (imports skipped), selected
  facade syntax/bug checks excluding F821, formatter, 19 checker tests and ratchet
  pass. 1205 files; no above-500 tier or baseline change.
- Mixed-state process exits, PostgreSQL/POSIX skips and full backend typing remain
  unverified. No deployment or restart; remaining R1-R9 work is not complete.

Earlier manual mixed-state checkpoint (2026-09-25):

- Twelve success cases reproduced legacy flag deletion before the fix. The final
  new file contains 24 cases, including confirmation-publication failure, across
  seed/detail and three entrypoints, with legacy requests unscoped or same-scope.
- Affected auth/scope/crash group: 150 passed, runner 67.61 s. This precedes only
  an exception-local variable rename, lint annotations and manifest formatting.
- Final fast: 867 passed, 2 skipped, runner 50.73 s; final security: 563 passed,
  4 skipped, runner 131.41 s. Both exit 0, serial, isolated storage, business DB
  disabled. New cases are security-only; the 60-second fast limit is unchanged.
- Native owner and regression/manifest Ruff, owner strict mypy (imports skipped),
  selected facade syntax/bug checks excluding F821, formatting, 19 checker tests
  and ratchet pass. 1205 files; no above-500 tier or baseline change.
- Automated-success mixed-state handling remains open. PostgreSQL/POSIX skips,
  mixed-state process exits and full backend typing are not covered by this
  checkpoint. Deployment/restarts remain deferred.

Earlier legacy process-exit checkpoint (2026-09-25):

- Initial three finalizer crash probes failed: manual-only was lost after flag
  removal; challenge ID was lost after cleanup/receipt publication. Initial
  implementation passed 296 affected cases, runner 86.19 s, but those results
  precede the subsequent cold-start manual-mode fix.
- Seven further cold-start crash/returned-error cases failed before that fix.
  Final focused group: 77 passed, runner 29.47 s, including all 38 legacy cases.
- Final fast: 867 passed, 2 skipped, runner 55.36 s, exit 0. Final security:
  539 passed, 4 skipped, runner 131.67 s, exit 0. New process-exit cases are
  security-only. Serial runs, isolated storage, no business DB; fast limit unchanged.
- Native journal/recovery Ruff and strict mypy (imports skipped), regression and
  manifest lint, selected legacy syntax/bug checks excluding F821, formatting,
  19 checker tests and ratchet for 1203 files pass. No above-500 tier or baseline
  change. Diff/UTF-8 checks pass. Full backend type closure is not claimed.
- Platform/DB skips remain unverified. Final security emitted an HTTP handler
  exception header without a traceback; no test failed. Deployment remains deferred.

Earlier legacy returned-error and scoped-preservation checkpoint (2026-09-25):

- Initial regression: 15 failed, covering six incorrect global completions and
  nine lost/rotated legacy identities. Final legacy regression adds six pending
  scoped-intent cases: 21 passed. Affected group: 265 passed, runner 47.97 s.
- Official fast: 867 passed, 2 skipped, runner 41.66 s, exit 0. Official security:
  501 passed, 4 skipped, runner 97.75 s, exit 0. Serial, isolated storage, business
  DB disabled; the fast limit remains 60 seconds.
- Both native auth cleanup modules pass Ruff and strict mypy with imports skipped.
  Regression/manifest lint, selected legacy syntax/bug checks excluding F821 and
  official formatting pass. Checker: 19 passed; ratchet: 1202 files, no above-500
  tier or baseline change. Diff/UTF-8 checks pass; full backend typing not claimed.
- Platform/DB skips remain unverified. Security emitted an HTTP handler exception
  header without a traceback. Deployment/restarts remain deferred.

Earlier finalizer scope-selection checkpoint (2026-09-25):

- Regression before fix: 4 failed (new scoped receipts erased), 4 passed. After
  fix: 8 passed, runner 2.56 s; affected auth/persistence/startup/contract group:
  244 passed, runner 57.66 s.
- Official fast: 846 passed, 2 skipped, runner 47.19 s, exit 0 under the unchanged
  60-second gate. Official security: 480 passed, 4 skipped, runner 106.03 s, exit 0.
  Broad runs were serial and used isolated storage with business DB disabled.
- New regression/manifest Ruff lint, selected source syntax/bug checks excluding
  legacy F821, official formatting, 19 checker tests and ratchet for 1201 files
  pass. No above-500 tier or baseline change. No full legacy-module type claim.
- Independent review found no new lock-order defect in the changed path. Database
  and POSIX skips remain unverified; security again emitted an HTTP handler
  exception header without a traceback. No deployment/runtime acceptance claimed.

Earlier scoped process-exit recovery checkpoint (2026-09-25):

- Same-ID metadata overwrite reproduced before the fix; focused group: 51 passed.
- Before the final scope-lookup extraction: affected group 236 passed, runner
  77.62 s. After extraction: focused cleanup/startup/scope group 71 passed, runner
  29.94 s. These are distinct worktree checkpoints.
- Final official fast: 838 passed, 2 skipped, runner 57.14 s; security: 472 passed,
  4 skipped, runner 118.39 s. Both exit 0; broad runs were serial.
- Journal/regression/manifest Ruff lint, journal strict mypy (imports skipped),
  selected source syntax/bug checks, formatting, 19 checker tests, ratchet for
  1200 files and diff whitespace checks pass. No above-500 tier or baseline change.
- The scope-ID lookup moved into the existing native scope module to retain the
  line policy. That module still has 5 preexisting Ruff findings and 5 strict-mypy
  errors under skipped imports; its full lint/type closure is not claimed.
- Platform/DB skips remain unverified. Security emitted an HTTP handler exception
  header without a traceback; no test failed. All tests used isolated storage
  with business DB disabled. Deployment/restarts remain deferred.

Earlier cookie-finalizer/native-recovery checkpoint (2026-09-25):

- New finalizer fault cases: 4 failed before the fix (2 ID rotations, 2 missing
  recovery errors). Native extraction preserved the previous 14 passing cases.
- Final affected auth/persistence/HTTP group: 199 passed, pytest 21.03 s, runner
  22.06 s, including all 18 cleanup/confirmation cases.
- Official fast: 838 passed, 2 skipped, pytest 55.00 s, runner 56.69 s, exit 0.
- Official security: 443 passed, 4 skipped, pytest 92.90 s, runner 94.33 s, exit 0.
- New native module and regression Ruff lint, native-module strict mypy with
  imports skipped, selected legacy source syntax/bug checks excluding F821,
  formatting, AST parsing, 19 checker tests, ratchet for 1198 files and
  `git diff --check` passed. No new above-500 tier or baseline change.
- Dedicated PostgreSQL/POSIX skips remain unverified. Security stderr emitted
  one request-handler exception header without a traceback; no test failed.
  All tests used isolated storage with business DB disabled. No deployment,
  restart, business-data mutation, commit or push occurred.

The checkpoint sections below are historical and must not be combined into one
current full-release result.

Preparation-race checkpoint, before the later cleanup fix (historical results):

| Gate | Result | Scope |
| --- | --- | --- |
| New race regression | 3 failing cases before the fix, then all 3 pass | Real thread contention; isolated files; fake cookie scheduler |
| Affected auth/HTTP group | 145 passed; pytest 11.97 s, runner 13.31 s | Scope runtime, collection status, seed target binding, cookie retry/scheduler, source contracts |
| Official fast | 820 passed, 2 skipped; pytest 42.48 s, runner 43.61 s; exit 0 | Unchanged 60-second gate |
| Official security | 425 passed, 4 skipped; pytest 76.61 s, runner 77.70 s; exit 0 | Authentication, request, transport, persistence, and platform-conditional cases |
| Static checks | Passed | Regression lint, legacy source syntax/bug rules, Ruff format, Python compilation |
| Effective lines | 19 checker tests pass; ratchet passes for 1196 files | No handwritten above-500 tier; edited console 253 and regression file 480 effective lines |

The legacy console is not fully lint/type clean: it still has 21 unique facade
names reported by F821, unchanged from the pre-edit snapshot. No new unresolved
name was introduced. Its full native/type closure remains R1/R7.

The fast skips are two PostgreSQL seed-job status refresh cases. Security skips
are two POSIX child-signaling cases and two PostgreSQL UTC migration cases.
They are not passing platform evidence. No business DB was used.

Fresh cleanup-slice verification after resuming session
`01a0d840-68b9-7c53-991a-0e06c68d29ce`, on the inherited dirty worktree at the
same HEAD (2026-09-25):

- Focused cleanup regression: 10 passed, pytest 1.77 s, runner 2.51 s.
- Official fast: 830 passed, 2 skipped, pytest 37.15 s, runner 38.20 s, exit 0.
- Official security: 435 passed, 4 skipped, pytest 73.40 s, runner 74.66 s, exit 0.
- Regression/manifest Ruff lint, source syntax/bug rules excluding legacy F821,
  and Ruff format checks: passed. Full-module strict typing is not claimed.
- Effective-line checker: 19 passed; ratchet: 1197 files, no above-500 tier.
  `git diff --check` passed.

The conditional skips are unchanged. Security stderr also emitted one HTTP
request-handler exception header without a traceback; the runner exited 0 with
no failed tests. These results do not establish deployment/runtime acceptance.
The earlier session's 191-test affected-group pass remains historical evidence
and is not represented as another fresh run here.

Latest scoped cooldown-confirmation checkpoint (2026-09-25), superseding the
cleanup checkpoint for the changed production file:

- Before the fix, both new seed/detail cases failed because the challenge ID was
  lost after confirmation publication failed. After the fix: 14 focused tests
  passed, including two additional restoration-failure cases; affected group:
  195 passed, pytest 16.34 s, runner 17.48 s.
- First fast attempt: 834 passed, 2 skipped, but runner 62.33 s, exit 1 for the
  unchanged 60-second threshold. Static checks overlapped that run. A serial retry
  on unchanged source passed: 834 passed, 2 skipped, runner 56.02 s, exit 0.
  This is observed timing variability, not proof of its sole cause.
- Security: 439 passed, 4 skipped, runner 93.92 s, exit 0.
- Regression lint, selected source syntax/bug rules excluding facade F821, Ruff
  formatting, AST parsing, 19 checker tests, ratchet for 1197 files, and
  `git diff --check` passed. No full-module strict typing is claimed.
- The PostgreSQL and POSIX skips remain unverified. Tests used isolated storage
  with business DB access disabled; deployment and application restarts remain
  deferred. No release or installed-runtime acceptance is claimed.

The following acceptance work remains for the final candidate:

1. The dedicated PostGIS suite and migration/data-preservation checks. An earlier
   38-test PostgreSQL pass is recorded in the progress section "Close the PostgreSQL
   milestone and include seed insert counts"; it is a historical checkpoint, not
   a fresh result for this continuation.
2. Linux/PC2 shutdown within the configured grace period, lease release,
   heartbeat/watchdog recovery, sandbox, and actual multi-machine collection.
3. Desktop type/lint/unit/Rust/build/smoke plus packaged native interaction for the
   final worktree. Older passing desktop runs do not validate later backend/client
   combinations or R5's unfinished functionality.
4. Hosted CI and scoped installation/activation on local desktop, NAS, and PC2:
   retained backups, configuration/data preservation, exact container identity
   where backup labels collide, installed hashes, executable paths, restart/health
   and functional checks, rollback evidence, and the stable desktop shortcut.

No deployment, restart, business migration, commit, or push was performed in this
continuation. Fresh results above must not be combined with earlier runs and
presented as one complete release acceptance.
