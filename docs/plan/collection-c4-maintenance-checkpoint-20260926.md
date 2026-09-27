# C4: collection maintenance checkpoint

Date: 2026-09-26. Source and focused acceptance complete; remote activation is
tracked separately in the C5/C6 checkpoint.

## Delivered behavior

The collection service owns archive fetch, archived-detail backfill and replay.
The existing leaf CLIs delegate to these owners. The mixed legacy maintenance
tool remains available to its analysis callers; collection maintenance does not
run readiness, valuation recommendations or calibration.

Authenticated maintenance routes submit durable jobs. Location inference uses a
native shared handler so opening the collection route set does not import the
evaluation owner. Generic and Taobao fresh-process probes reject postprocessing
imports while exercising HTTP admission, real SQLite storage and shutdown.

Nonempty dry-run leaves business JSON, database rows, evidence and queues
unchanged. Fetch returns before network/AI calls. Backfill previews artifacts
without sidecar writes or paid risk extraction. Receipts and CLI preview reports
are permitted outputs. CLI defaults use repository-local `FPFData/datas`, accept
`FAPAI_DATA_ROOT` and explicit arguments, and derive reports under `maintenance/`.

JSON publication precedes DB publication. A failed DB write can leave evidence
and JSON ahead of the database; subsequent fetch/backfill/replay reconciles this
state. Revision-specific sidecars preserve evidence referenced by earlier rows.
No cross-file transaction or rollback of partially completed work is claimed.

Shutdown requests cooperative cancellation even if writing a receipt fails.
Active work remains cancelling until it exits; `close()` reports actual thread
termination, and the HTTP server waits outside its manager lock.

## Evidence and boundaries

- Windows `collection-maintenance`: 71 passed, runner 7.59 seconds, isolated
  storage and business DB disabled. Includes nonempty dry-run, JSON/DB failure
  retry, existing evidence preservation, cancellation and failed receipt writes.
- Windows `collection-delivery`: 100 passed, runner 7.77 seconds after the
  Windows-only batch-test platform marker was added.
- Independent read-only review found no concrete correctness defects in archive
  publication, backfill, replay, maintenance and job shutdown; this is supplementary
  evidence, not a test run.
- Required line-checker tests: 19 passed. Ratchet: 1,379 source files, no file over
  500 effective lines. Baseline and limits were not changed.
- Affected CI Ruff and mypy commands passed. The local venv was supplied with
  locked-version mypy 2.3.1 and types-requests 2.33.0.20260906; import-untyped was
  not disabled for these final CI checks.

The full candidate includes the adjacent C5 entrypoint edits. Broad acceptance
belongs to that combined source state, not an independently tested intermediate
commit. See `collection-c5-c6-checkpoint-20260926.md` for timing, platform,
database and installation evidence.
