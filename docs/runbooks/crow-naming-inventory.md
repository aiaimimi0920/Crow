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

## Deliberate compatibility boundaries

The naming branch implements canonical source names and compatible inputs. It
is not a migration of installed identities, durable records or historical data.
The following old names are intentionally retained:

| Boundary | Retained name or format | Reason |
| --- | --- | --- |
| SQL and old Python callers | `fapai_*` identifiers, migration revisions, five Fapai* aliases | Preserve existing databases and imports; aliases reference the same models |
| Runtime data | populated `FPFData`, configured UNC roots, profile/cache/heartbeat paths | Reuse existing data in place; a new name must not hide it |
| Installed desktop | `fapaifang_collector_desktop.exe`, Tauri identifier/product identity | Preserve upgrades, shortcuts, process detection and AppData; private npm/Rust package/library names are Crow |
| Browser extension | userscript name/namespace/install URL, GM storage keys | Preserve installed update identity and settings |
| Archived evidence | `fapaifang-meta`, source fields and historical export prefixes | Existing evidence and downstream readers remain compatible |
| Host configuration | legacy environment aliases and exported constants | Old configurations remain accepted alongside Crow names |
| HTTP wire | default client X-FAPAI headers | Older server preflight allowlists accept only the legacy names; servers accept both securely |
| Container configuration | env_file/service.environment/build ARG legacy keys | Preserve Docker layer precedence and old images; host aliases are adapted separately |
| Deployment coordination | task/service/mutex/container/volume/image/user identities and release metadata | Avoid duplicate workers, changed mounts or broken rollback |
| Bootstrap labels | historical Python module/loading labels | Preserve dynamic imports and compatibility facades |
| Diagnostic/device identity | virtual-mouse name and existing screenshot/export filenames | Preserve operator/device matching and diagnostic consumers; these are not new data roots |
| History | original listings, reports, logs, migration SQL and prior review records | Historical contents are evidence, not current product wording |

These are compatibility interfaces, not instructions to rename live resources.
Retiring any durable identity requires a separate migration design and review.
This draft is not deployed or merged; the user decides when to merge it.

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

## Environment and entrypoint coverage

`CROW_*` is canonical. Python, PowerShell, native Rust desktop configuration and
supported host Bash inputs accept legacy `FAPAI_*` aliases. Readers are dynamic
where the original reads were dynamic; import-time settings retain their original
lifetime. Injected readers remain isolated from process settings. Explicit empty
values, caller defaults, boolean/numeric conversion and provider-standard OPENAI
precedence retain their original contracts. Conflicts report key names only.

Reads do not rewrite process environments. Explicit writes synchronize aliases;
the Python helper lock covers cooperating helper users, not direct external
`os.environ` writes. Caller-supplied mappings are not generic transactions, and
write failures stop the caller. Public function-global facades explicitly include
the reader in their context. Standalone Python and desktop bundles include the
new dependency closure and have isolated import tests.

Coverage includes API credentials, database/Alembic bootstrap, maintenance and
diagnostic inputs, source discovery/detail/analysis workers, budgets, CDP/cookie
transport, watchdogs, healthchecks, desktop settings and injected Compose models.
Alias conflicts propagate through optional cookie/reconnect fallbacks. Original
credential role, origin, TLS, cookie containment and storage boundaries remain.
Tests use isolated settings and synthetic inputs, not live diagnostic entrypoints.

Management roots use their dedicated read-only path resolver, not generic string
comparison. Desktop path aliases use lexical native path equivalence without
following links. Process configuration overrides saved configuration by logical
alias group; original empty-process fallback remains. Explicit script parameters
still win when conflicting aliases are unused. Existing JSON keys remain readable.
See [data-root compatibility](crow-data-root-compatibility.md) for discovery,
ambiguous roots, symlinks, case variants and rollback.

## Desktop and HTTP behavior

Native API configuration still returns a string on success. Conflicts reject with
key names only; the paired frontend blocks initial, scheduled and shared HTTP
requests until the user explicitly applies an API address. Normal browser fallback
is retained. PR browser tests cover both paths with synthetic responses, including
a ten-minute virtual-time window with zero requests while blocked.

Servers accept X-Crow-Control-Token, X-Crow-Recovery-Token and
X-Crow-Collection-Token alongside the legacy names. Matching is case-insensitive;
repeated fields, comma-merged values and conflicting aliases fail closed across
roles. Existing origin/TLS/role gates remain, including CORS. Both namespaces are
classified as sensitive before client transport checks. Clients retain the old
wire default for older servers; there is no token probe or negotiation protocol.

Private npm and Rust package/library names are Crow. Cargo's explicit binary and
default-run retain the installed executable name. Dependency versions/checksums
are unchanged by this source-naming step; Windows CI builds the existing NSIS
identity. Building a package does not install or activate it.

## PowerShell and operator bundles

The three collection-mode entrypoints use the validated Crow Compose adapter and
scoped env-file writer. Explicit writes synchronize aliases; defaults preserve
any existing spelling, including blanks, and unrelated lines remain intact.
Seed/detail configuration checks precede restart-policy changes.

PC2 operator helpers load from repository scripts/ or a flat runtime/ bundle.
Installer validation, backup, copy and rollback manifests include the full helper
closure. Rollback restores files with backups; newly introduced files without
backups may remain. This change adds no deletion or installation migration.
Operator env-file loading validates all alias groups before process writes and
preserves file-over-process priority and existing literal parsing rules.

Analysis import adds aliases only for the three approved proxy settings. Conflicts
fail before backup/write; unrelated keys remain excluded. Batch defaults fill both
spellings only when both are absent. Solver CMD explicit settings are paired, and
console output no longer echoes the database URL. Paired remote-auth temporary
variables use Crow; tests evaluate only environment assignments, never SSH calls.

PowerShell regression fixtures reuse one host per module for speed, with a fresh
runspace for each case and restoration of process environment and directory.
Tests prove same-process reuse cannot leak added/changed/deleted environment
values, global variables or functions, including after a failed case. Temporary
files remain isolated. Operational script bodies are not executed by these tests.

## Compose and Linux boundaries

The Crow Compose adapter validates a strict supported global-argument grammar,
uses Docker config-only rendering for env parsing, and preserves the exact chosen
files/project directory. Before forwarding an operation it validates the final
service environment model using the same selectors. Captured values are neither
printed nor written to disk. Container alias conflicts use conservative text
comparison and key/service-only guidance, not host-path equivalence.
Synthetic Docker integration tests issue only config commands and verify a
conflicting service model prevents any subsequent operation.
See [Compose compatibility](crow-compose-compatibility.md).

Container env_file, service.environment and build ARG keys remain legacy wire
interfaces. New host inputs do not imply equivalence across Docker layers; use
the documented legacy container keys where indicated in env examples. NAS/PC2
legacy runners retain their existing commands, Compose v1 fallback and metadata.

Host Bash helpers validate aliases before browser/profile/child work. Declared
shell env files permit plain UTF-8 LF, optional export, quoting, comments and
simple variable references. BOM, CR, NUL, conditional/dynamic assignment, command
substitution, unset, multiline values and compound commands are rejected before
source. File alias groups retain priority even when equal to preexisting values.
NAS container-wire files reject Crow-prefixed declarations with key-only guidance.
Derived build/image values explicitly synchronize aliases; rollback image values
remain scoped to the original Docker command. Supervisor startup validates first;
cleanup keeps the preexisting safe grace fallback when exit-time parsing fails.

Browser image source-copy lists include shared helpers, but no Linux image is
built or released by this branch. Tests use synthetic shell files, extracted pure
blocks and fake child/Docker commands. No PC2/NAS deployment, data migration,
service restart, real browser-profile operation or installation has been performed.

## Acceptance evidence and limits

Focused tests cover old/new/equal/conflicting aliases, explicit precedence,
empty values, bundle closure, unchanged schema, path discovery and rollback
compatibility. Hosted CI checks real Windows Python/PowerShell and Cargo/NSIS,
Docker config rendering and browser DOM behavior, in addition to ordinary quality
and security checks. Exact-head results belong in the PR report; this document
must not imply that results from an older tree cover later changes.

The existing glib 0.18.5 and proc-macro-error 1.0.4 OSV findings remain visible.
There are no new ignore rules or relaxed test/time limits. Full historical
platform/live-operation tests are not implied by focused or ordinary CI success.
