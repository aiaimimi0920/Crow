# PC2 native fallback state store checkpoint

Date: 2026-09-26. Base HEAD: f2d735ab20e60c1dce212dd86dd2b15fd22a8c40.
Inherited dirty worktree preserved; no commit, push or live activation.

## Completed boundary

tools/pc2_solver_state_store.py owns the fallback state defaults, load and save
functions plus the existing state path. All three functions publish natively
through the solver and fallback modules. The storage owner imports only config
and logging dependencies; isolated import coverage proves it does not initialize
the solver/context/server/storage runtime.

Persisted fields, legacy slider-attempt fallback, string/number normalization,
missing-file defaults and all-or-default malformed-input recovery are preserved.
Loading damaged bytes does not rewrite them. Saves serialize to a same-directory
PID temporary file before os.replace; serialization or replacement failure keeps
the prior target and attempts temporary cleanup. The established error event and
non-raising save API remain unchanged.

The eleven existing test path replacements now target the native store and use
temporary files. Reset, challenge synchronization and retry state transitions
remain in the old orchestration owner for the next slice. Their facade load/save
replacement seams still work; no new dynamic-global rebinding was introduced.

New tests prove original native object/global identity, fresh defaults, missing
file behavior, damaged input preservation, legacy normalization, complete
serialization before replacement, and preservation/cleanup on serialization and
replace faults. CI and the fast manifest include the new owner/tests.

## Evidence

- Focused store/import/sync/progress checks: 25 passed, runner 3.64 s.
- Affected PC2 boundary plus cooldown recovery: 146 passed, pytest 41.31 s,
  runner 42.00 s, with isolated quality-runner storage and business DB disabled.
- Full Ruff check passes for the new owner and changed tests/manifest (8 files).
- Formatter: 10 Python files pass; strict mypy: one native owner passes.
- Effective-line checker: 19 passed; ratchet: 1334 files, none above 500.
- Scoped git diff check passes. Independent read-only comparison found no field,
  conversion, default-path or atomic replacement semantic regression.

Logs: artifacts/pc2-state-store-{focused,affected,ruff,format,mypy,checker,ratchet,diff-check}.log.
The previous fast result (1401 passed, 2 skipped, 51.34 s) belongs to the scope-I/O
worktree. It was not repeated or reclassified as a full pass of this new state.

## Remaining cursor and limits

R1-R9 remain open. Continue native reset/sync, cooldown and pending-auth/resume
state orchestration, then CDP/execution/loop cloning retirement. Keep persisted
compatibility and admission-time request identity tests throughout that work.

The existing .codex-temp/bridge-control state path is deliberately unchanged.
Migrating to the required FPFData runtime root still needs an explicit precedence
and preservation contract for existing state. No file migration happened here.
Atomic replacement tests do not establish power-loss durability, directory fsync
or concurrent multi-writer safety. Deployment and application restarts remain
deferred under the overall code-first plan.
