# Crow naming and compatibility inventory

This is a staged source change on the independent naming branch. It does not
activate deployments or rename live data. The data-root phase is documented in
[crow-data-root-compatibility.md](crow-data-root-compatibility.md).

## Canonical Python collection names

The five historically prefixed ORM types represent source-neutral collection
queues, not necessarily judicial-auction property. They now use:

| Canonical code name | Legacy import alias retained |
| --- | --- |
| CollectionSeedScanJob | FapaiSeedScanJob |
| CollectionSeedScanProgress | FapaiSeedScanProgress |
| CollectionSeedItem | FapaiSeedItem |
| CollectionAnalysisRun | FapaiAnalysisRun |
| CollectionSeedOccurrence | FapaiSeedOccurrence |

Old/new imports point to the same mapped class and table. Internal production
references use canonical English names. Existing SQL table, column, constraint,
index and foreign-key names remain byte-for-byte identical, as do migration
revision files (`alembic/versions`). PostgreSQL and SQLite DDL signatures are checked against the pre-rename
baseline. Existing legacy class/instance pickle references remain readable;
production storage has no identified ORM-pickle persistence flow.

PropertyListing, PropertyRiskFlags and PropertyLegalContext already use English.
Taobao's judicial-auction adapter retains that specific domain meaning. Do not
rename generic catalog collection records to JudicialAuctionProperty, or change
source evidence/Chinese upstream field keys merely to remove an old prefix.

## Product wording

Crow is the display name in the collection console, desktop window/HTML title,
Rust errors/descriptions, capability description, current desktop README and
seed-generation help. Userscript human-readable description/log prefixes use
Crow; structured fields are unchanged.

## Deliberate compatibility boundaries and remaining batches

- DB identifiers `fapai_*`: durable schema and migration contract; no SQL rename
- Five Fapai* class aliases: old callers and serialized references; no extra model
- `FPFData`: existing populated data remains in place; both path markers read
- Tauri `com.fapaifang.collector`, installed AppData/profile paths, NSIS product
  identity, existing binary/library/package names: next build/installation batch
  must add compatible discovery/entry points before any old identifier retires
- Userscript `@name` + `@namespace`, old installed URL/filename and GM storage keys:
  update identity and persisted state; keep until a tested update/alias path exists
- Browser archive DOM markers (`fapaifang-meta`) and evidence-source strings:
  historical artifacts must remain readable; add a dual reader before new writes
- `FAPAI_*` environment keys and X-FAPAI/X-Fapai HTTP headers: next configuration
  batch requires dynamic dual-name readers and old-server/new-client handling;
  no global environment monkeypatch and no secret values in conflict messages
- Scheduled-task/service/container/image/mutex identities: existing coordination
  and deployment contracts, not cosmetic labels; prevent duplicate workers
- Export filename prefixes and Python bootstrap module labels: inventory/readers
  need compatible aliases before new names become defaults
- Historical run reports, original listing evidence, logs and migration SQL:
  retain historical contents; do not rewrite them to appear renamed

The remaining legacy names are not a declaration that the full naming request
is finished. Each next batch gets focused compatibility tests, an exact tree
review and CI on this same draft branch. Merging remains a separate user decision.

## Userscript generated revision review (2026-09-30)

The generated install-file delta was reviewed as exactly three display-text
changes: the description identifies Crow and two console prefixes become Crow.
`@name`, namespace, version, credentials, headers, DOM/storage keys, endpoints
and authenticated request behavior are unchanged. The install file remains
deterministically generated from its maintained fragments.

- Previous normalized SHA-256: `775624987431dbee86ba43c07d4a624327853d74496c27314ee87e72c44c45e4`
- Reviewed naming revision SHA-256: `42f73cfb5cf5b2de3f051641fb9458df69a11ab4a9baa985da09040b3db972fe`

The fixed-digest assertion is updated to this reviewed content. Existing
[authenticated-client review](../plan/userscript-generated-artifact-review-20260921.md)
remains historical evidence. The generated-artifact policy, exclusions,
handwritten-source limits and authenticated-request test assertions are not relaxed.

## Environment namespace rollout

The first Python cohort uses a small dynamic alias reader for API credentials,
runtime flags, database configuration and isolated/maintenance entry points.
`CROW_*` is canonical, while existing `FAPAI_*` inputs and exported legacy
credential constants remain supported. Conflicting explicitly set values fail
closed, reporting names only. Empty strings are preserved; each caller keeps
its existing default and boolean conversion rules.

Reads do not rewrite `os.environ`. An injected reader stays isolated from global
process settings. Explicit writes through the helper update both aliases for
old/new consumers; the private lock covers cooperating helper users, not direct
external writes to `os.environ`. Caller-supplied mappings are not generic
transactions and any write failure must stop the caller.

Management-root aliases continue through the dedicated path resolver, including
lexical path equivalence. Generic string-value comparison does not replace that
path contract. Alembic's bootstrap accepts the new DB environment name; migration
revision files, schema metadata and SQL identifiers are unchanged.

Quality runs clear canonical counterparts of their forced isolated settings,
then run the original legacy-environment suites plus explicit new-name mirrors.
This prevents inherited Crow settings from redirecting tests to real data.
Worker/captcha readers, injected desktop settings, PowerShell/Compose and HTTP
header aliases remain later cohorts until their own compatibility tests pass.
