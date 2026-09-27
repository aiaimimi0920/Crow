# Detail archive fetch native ownership (2026-09-26)

Status: this R1 boundary is complete; the overall R1-R9 plan remains incomplete.
Evidence belongs to HEAD `f2d735ab20e60c1dce212dd86dd2b15fd22a8c40` plus the
inherited dirty worktree. Final status review found 424 entries; unrelated work
was retained. Deployment, restarts and business-data changes remain deferred.

## Behavior and ownership

`src/collection/detail_archive_fetch.py` now owns missing detail archive fetching.
`DetailCollectionService.fetch_missing_archives()` and recent enrichment
maintenance import that owner directly. The CLI retains its root bootstrap,
original function re-export, flags, defaults, JSON report file and stdout contract.
Existing fetch, checkpoint, bounded timeout, gate detection, optional risk
extraction and archive/JSON/database publication semantics are retained.

Existing tests now patch the native owner. New entrypoint regressions prove that
the service operates with the CLI module blocked and that CLI function identity,
arguments and output remain intact. The empty-repository entrypoint test does not
establish positive-candidate dry-run safety. Independent read-only review found
no confirmed introduced defect; it did not rerun tests.

Selective lint, formatter and strict mypy gates include the native owner and CLI.
The missing requests stubs required adding `types-requests>=2.32.0` to the dev
input and locking `types-requests==2.33.0.20260906`. Lock comparison retained every
pre-existing version and hash set, with no removed packages. Runtime requirements
were unchanged. The prior dirty dev lock is preserved in
`artifacts/detail-fetch-native-dev-lock-before.txt`.

## Verification

All pytest checks used `scripts/run_quality_tests.py`, isolated temporary storage
and disabled business DB access. Execution and fast thresholds were unchanged.

- Baseline: 8 passed, runner 2.67 s; migrated existing tests: 8 passed, 3.09 s.
- Entrypoint and focused regression group: 10 passed, runner 2.73 s.
- Affected fetch, stop, maintenance, collection job HTTP and AVM HTTP group:
  411 passed and 1280 subtests passed, pytest 29.01 s, runner 30.14 s.
- Strict mypy with the exact locked requests stubs: 2 source files passed.
- Selective Ruff (`I,F401,F403,F405,F821,E9,E722,F63,F7,B`) passed;
  formatter reported 6 files already formatted. This is not full Ruff acceptance.
- Relevant Python compilation and actual CLI `--help` passed.
- Effective-line checker: 19 passed; ratchet: 1347 files, none above 500 effective
  lines, without changing the baseline or exception policy.
- Final changed-file inspection confirmed UTF-8 without BOM. Diff whitespace
  check passed with the repository's CRLF handling retained.

Logs: `artifacts/detail-fetch-native-{before,focused,entrypoints,affected,mypy,ruff,format,checker,ratchet,cli-help}.log`.
The latest full-fast result predates the AVM and fetch ownership slices; it is not
current full-suite acceptance. No full suite was rerun just to refresh a count.

## Open follow-up

The other DetailService imports for backfill, replay and maintenance still depend
on tools. Their transitive loaders, audit and analysis dependencies need actual
ownership review before migration. The CLI's legacy `datas` default remains
pending the data-preserving runtime-root transition.

The existing positive-candidate dry-run path calls `get_detail_archive_path`
(which creates directories) and `extract_detail_artifacts` (which writes files)
before the `not dry_run` publication guard. This pre-existing behavior was not
changed by extraction. A follow-up must prove a positive-candidate no-write
contract with isolated filesystem/database evidence and fake HTTP/risk extraction
before changing that boundary. Broad fetch exception handling, local timestamps
and session cleanup were also not changed or claimed fixed here.

No installed application, live collection, PC2/NAS deployment, packaged desktop,
PostgreSQL or full security acceptance is inferred from these focused results.
