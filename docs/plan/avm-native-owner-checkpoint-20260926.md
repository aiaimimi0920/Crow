# AVM service dependency ownership (2026-09-26)

Status: the AVM service module-patch facade is removed and verified.
Overall R1-R9 is incomplete; AVM remains a migration input, not a completed
analysis/prediction product. Deployment and restarts remain deferred.
Source is HEAD f2d735ab20e60c1dce212dd86dd2b15fd22a8c40 plus inherited dirty worktree.

## Removed global mutation

Assigning one of five attributes on src.avm.service previously propagated the
assignment into five other modules via a custom ModuleType.__setattr__. Repository
search found five test patch sites relying on this and no production assignment
to those dependency names. The custom module class, patch registry, sys.modules
class replacement and obsolete function exports are removed.

Data, prediction and health mixins now import dependencies directly from their
actual mapper, feature, engine, quality and configuration owners. service_context
contains only its four shared constants and an explicit export list. AVMService,
its constructor/methods, model version and documented constant exports remain.
No new forwarding or rebinding adapter was introduced.

The existing tests patch the module that reads the dependency. A runtime
regression verifies that assigning a service-namespace attribute cannot replace
the health provider or change the active weighting returned by health_snapshot.
The test also requires an ordinary module type and the same public model version.

## Verification

- Before extraction: engine/service contract suite **48 passed**, runner **0.98 s**.
- After extraction plus ownership regression: **49 passed**, runner **1.03 s**.
- Affected engine/service, HTTP, evaluation/screening jobs, pipeline/UTC, quality,
  config and data loader boundary: **456 passed, 1278 subtests passed**, runner
  **30.99 s** (pytest 29.18 s).
- Relevant selective Ruff gate passed (imports, undefined names, exception syntax,
  bugbear); formatter passed for 9 files after normalizing manifest line endings.
  Five affected production modules passed compileall. Existing mixin Any/self
  contracts are still R7 typing work; no full strict-mypy acceptance is claimed.
- Effective-line checker **19 passed**; ratchet **1345 files**, none above 500
  effective lines. Policy and baseline unchanged. Ten source/test/config files
  verified UTF-8 without BOM; git diff check passed.
- Current src search found no FunctionType, _ServiceFacadeModule,
  _PATCHABLE_GLOBALS or module __class__ replacement references.

Evidence: artifacts/avm-native-owner-{before,focused,affected,ruff,format,checker,
ratchet}.log. Tests used the isolated quality runner with business DB disabled.
The ownership regression is added to fast; fast was not rerun at this narrow
boundary. The prior PC2 milestone (1446 passed, 2 skipped, 38.49 s) predates these
changes and is not current AVM acceptance. No deployment acceptance is claimed.

## Next R1 boundary

Source-to-tools imports remain in manual-review/analysis planning, AVM calibration
and pipeline, report jobs, collection detail maintenance and CDP browser identity.
The scout located four detail-maintenance operations forwarded from
src/collection/detail_service.py into tools; their implementation/CLI/test
contracts need inspection before moving ownership into src. Keep existing CLI
entrypoints delegating to production implementations when that move is made.
R2-R9 retain their original completion conditions.
