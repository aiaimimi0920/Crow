# Repository operating rules

## Deployment after user-requested updates

- User-requested feature updates and fixes authorize deployment of the verified
  changes to the affected local, PC2, and NAS applications, followed by the
  required application restarts. Complete this flow without asking the user
  for deployment or restart approval again.
- Keep deployment scoped to the affected applications. Do not restart computers,
  unrelated services, or the PC1 human-authentication browser. Preserve runtime
  configuration, credentials, cookies, browser profiles, and database contents.
- Validate the changes before activation, back up replaced artifacts, retain a
  scoped rollback path, and verify installed hashes and actual runtime behavior.
  Never activate a failed build or claim an unverified deployment succeeded.
- Inspect Compose project/service label matches before replacing a container.
  If stopped backups share those labels, do not use service-wide Compose
  recreation. Replace the canonical container by exact ID and retain the old
  container for rollback.
- Read-only audits and ordinary exploration do not authorize unrelated live
  mutations. A specific user instruction to defer deployment takes precedence.
- Read-only inspection must not be presented as a deployment or runtime
  verification.

## Local Crow desktop updates

- After completing and validating Crow changes, automatically apply the latest
  verified desktop build and restart the local Crow application for manual
  testing. The user has authorized this routine local application restart;
  do not ask for the same approval on every completed change.
- Restart Crow, never the computer or the human-authentication browser. PC2/NAS
  updates follow the user-requested deployment workflow above.
- Preserve runtime configuration, credentials, cookies, browser profiles and
  database contents. Back up replaced application files and verify the new
  process executable path and installed hashes before reporting completion.
- Do not activate an unverified or failed build. If activation is blocked,
  report the precise blocker instead of claiming the latest app is running.
- After each successful local update, refresh the user's desktop `Crow.lnk`
  with `scripts/update-collector-desktop-shortcut.ps1` and the verified EXE
  SHA-256. Reuse this stable name, repair missing/stale shortcuts, and verify
  the target, working directory and icon. Do not delete other desktop files.

## Project paths and runtime data

- Derive project paths from the repository root; do not hard-code the checkout
  name, drive letter, UNC share, or developer home directory.
- The default project-local runtime-data root for new installations is `CrowData/`.
  Use the shared read-only root resolvers; existing `FPFData/` runtime data and
  explicit environment/command-line paths must remain in place. Conflicting
  configured roots or two populated roots require explicit selection, never a move.
- `CrowData/` and legacy `FPFData/` may contain credentials, browser profiles, database backups, and
  large generated artifacts. Its runtime contents must remain outside Git;
  only its management documentation and ignore policy are versioned.

## Crow engine boundaries

- Crow is organized into three product engines: collection, data analysis, and
  prediction. Only the collection engine is currently mature enough to be
  treated as an implemented product capability.
- The collection engine has three explicit stages: rough discovery of source
  links, detail-page capture, and evidence-based AI archiving. Source-specific
  field names and completion rules belong in `src/collection/adapters/`, not in
  source-neutral orchestration.
- Storage, multi-machine coordination, unattended operation, and automatic
  challenge solving are cross-cutting collection runtime capabilities. They are
  not separate product engines and must not bypass the live-system rules above.
- Do not present the current analysis or prediction code as complete. Existing
  AVM and analysis modules are migration inputs until their contracts and
  release gates are explicitly completed.

## Effective-code-line and splitting policy

- Effective lines exclude blank lines, comment-only lines, and documentation
  blocks. Inline comments on executable lines still count. The language-aware
  checker is authoritative.
- Target about 150 effective lines per file. 100-250 is preferred; 251-500 is
  acceptable for one cohesive responsibility; 501-700 requires a current,
  independently reviewed exception; 701-1500 is unacceptable for completed
  new or changed work; more than 1500 has no waiver.
- Existing oversized files recorded in the baseline may remain only while
  source-content unchanged; line-ending and UTF-8 BOM normalization do not
  count as code changes. A changed oversized file must be split to at most 700
  effective lines, with a target of at most 500.
- Split by responsibility: domain policy and serialization, parsing and
  validation, business state, I/O and persistence, runtime orchestration, UI,
  and test fixtures. Do not split at arbitrary line numbers or create a giant
  `utils`/`common` dumping ground.
- Never satisfy the checker by deleting useful tests, excluding product source,
  minifying code, or moving logic into generated/runtime-data directories.

## Vertical-closure-first development and test execution

- Work in a vertical slice: choose one user-visible behavior or runtime boundary, implement the smallest complete path, and verify that path before starting another slice. A slice is complete only when its production code, focused regression, and relevant static checks agree on the same behavior.
- Select tests by change impact, not by habit. After a small local edit, run the focused regression and the cheapest applicable import, syntax, formatter, type, or contract check first. Expand to an affected suite only when the focused checks pass or when the change crosses a shared contract, concurrency boundary, security boundary, or persistence boundary.
- Do not run the full historical suite after every small change. Run `fast`, `security`, PostgreSQL, desktop, or release-scale suites at a milestone, before a release/deployment candidate, after a cross-cutting change, or when the user explicitly asks for broad acceptance. A previous fresh result may be reused when the relevant code and test inputs have not changed; record its scope, commit/worktree state, and skipped conditions.
- Before a broad run, state why it is needed, what it covers, its expected time budget, and its data/isolation boundary. If a focused check fails, fix that slice before spending the broad-suite budget. Do not rerun an unchanged broad suite only to refresh a number.
- Keep the longitudinal loop visible in reports: behavior path, focused test, affected-boundary test, then milestone-wide acceptance. Never combine results from different worktree states or different times and describe them as one full pass; report partial, skipped, and unverified gates explicitly.
- This strategy reduces redundant test work; it does not permit weakening security checks, deleting useful tests, changing thresholds, or claiming release/runtime acceptance from focused tests alone.

- Required local gates for relevant changes:
  - `node --test scripts/tests/effective-code-lines.test.mjs`
  - `node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json`
  - focused tests, formatter/type checks, and `git diff`/`git status` review.
- Use `--mode strict` only as a migration report until all grandfathered debt is
  removed. Baseline or policy regeneration requires explicit review of the
  recorded source commit, exclusions, hashes, and oversized-file inventory.
