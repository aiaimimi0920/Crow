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
The second cohort covers solver/CDP settings: endpoint, retry/deadline limits,
flags, browser identity and cookie-cache paths. Old/new/same-value dual inputs
are tested without a real browser, network or pointer. Invalid numeric settings
retain their old defaults, but alias conflicts are not swallowed as parse or
transport failures. Connection configuration is validated before socket changes;
cookie discovery/export never retries with another transport after a conflict.

The third cohort covers seed/detail worker configuration and pause ownership,
worker heartbeat paths, live-batch cookie/proxy/browser configuration, and
analysis-module configuration. Public compatibility facades clone function
globals, so the alias reader is explicitly exported through their shared context
rather than being available only in individual implementation modules. Existing
facade names and persisted worker/job identifiers remain unchanged.

The old numeric/default/boolean parsing remains; dual explicit source-template
values now follow the same fail-closed conflict rule. Explicit heartbeat paths
still win. Cookie snapshots are not used to hide configuration conflicts, and
optional page-cache/reconnect fallbacks propagate those errors. Tests exercise
both the public facades and native transport using fake I/O and temporary paths.

The fourth cohort covers PC2 solver startup defaults, auth-report inputs,
retry/fallback/loop flags, watchdog settings and worker healthcheck paths.
Import-time constants keep their original lifetime; function-level reads remain
dynamic. Watchdog direct-script imports are tested from an unrelated temporary
working directory. No watchdog, service or remote process is started by tests.
The existing heartbeat filenames and service/process matching identities remain
compatible; this input-alias batch does not rename runtime files.

The fifth cohort covers injected authentication receipt/cookie readers and
scoped desktop settings. Injected readers never fall back to global process
settings. Desktop CROW/FAPAI path aliases compare lexically without following
links, allowing equivalent trailing separators and native Windows case/UNC
spellings. Two different explicit paths fail closed without values in errors.

Process settings override saved desktop settings as a logical alias group;
original empty-process-value fallback to saved settings is preserved. Saved
relative paths remain relative to the selected bundle, while relative process
paths keep their existing current-directory interpretation. Configuration files
are only read, never rewritten. Old JSON version/keys remain supported and no
origin, TLS, token, browser-profile or cookie containment boundary is relaxed.
The standalone desktop bundle includes the new scoped reader. Linux fixture and
Windows CI coverage verify both namespace spellings and injected isolation.

The sixth cohort closes remaining direct Python environment reads for model
qualification, proxies, community indexes, AVM maintenance, health/location
facades, browser identity configuration and diagnostic entrypoints. Explicit
OPENAI settings retain their original precedence and provider-standard names.
Legacy exported environment-name constants remain aliases; public facades keep
the new reader in their own exported context where function globals are cloned.
Live diagnostic scripts use explicit dual-name defaults only when absent, with
no import/run of those live diagnostics during validation (syntax only).

The seventh cohort covers resolved Compose-model mappings and direct PowerShell
process-environment reads under `scripts/`. Model readers stay scoped to the
provided mapping, and unchanged plans stay byte-for-byte equal as Python data.
Only actual setting changes and newly provisioned worker identity/output values
explicitly synchronize both spellings; service/container identities and mounts
are preserved. `environment_changes` retains its legacy-key mapping as a caller
compatibility API, while writers bridge those keys to both namespaces.

The PowerShell helper is dynamically read-only unless explicitly asked to set a
value. Explicitly supplied script parameters still override environment defaults,
including when the unused aliases conflict. Known local path reads opt into
lexical equivalence without following links. Saved desktop settings accept either
namespace; generated settings and launchers carry matching aliases so older
bundles continue to work. Bundle file manifests include the helper.
Only helper/parameter-binding fixtures and parser checks run on Linux; operational
script bodies are not executed. Windows CI covers copied desktop bundles and
temporary installation-configuration fixtures. Existing static assertions now
look for canonical getter calls while retaining protocol/security assertions.

The eighth cohort adds a read-only Compose environment adapter and completes the
Docker entrypoint's injected mapping reader. It delegates env-file parsing to
Docker's config-only JSON renderer, validates logical alias groups before an
operational command, and passes matching legacy inputs to existing templates.
The templates' volume/service/image names remain compatibility identities, not
rename targets. The required Linux CI integration uses synthetic env files and
only `docker compose config`; local Docker absence is recorded as a skip.
See [Crow Compose compatibility](crow-compose-compatibility.md).

The ninth cohort integrates the three collection-mode PowerShell entrypoints
with the validated Compose adapter and a scoped dual-name env-file writer.
Explicit settings synchronize aliases; defaults preserve any existing alias,
including blanks, and unrelated settings stay intact. Seed/detail configuration
checks precede restart-policy changes. Validation executes only pure writers on
temporary files and source parsing; no operational entrypoint is run.

Remaining scope includes independent Compose/ops entrypoints and bundles,
embedded remote helper interfaces, HTTP headers and safe build/CLI names;
none of the direct-reader counts imply these remaining boundaries are finished.

The tenth cohort covers native desktop process/saved API configuration and the
saved Python interpreter path. Successful native API responses remain strings;
conflicts reject the command with key names only. The paired frontend recognizes
that error, pauses automatic requests and blocks shared HTTP transport until an
explicit API-address application. Non-Tauri browser fallback remains unchanged.
Saved interpreter aliases compare native absolute paths lexically, without
following links; settings execution propagates conflicts before starting Python.
Existing empty process API values still fall back to saved configuration.
