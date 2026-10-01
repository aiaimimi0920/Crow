# Crow data-root compatibility (stage 1)

This is a source-only compatibility change on an isolated branch. It does not
rename, copy, delete or scan the contents of real PC2/NAS data, deploy, restart,
or modify a database. Existing data does not need to move.

## Selection contract

Python `src/project_data_paths.py` and PowerShell `scripts/project-data-root.ps1`
share the following read-only management-root selection contract:

1. An explicit management-root CLI argument wins, even if its target does not
   exist. Resolving it does not create it. Existing callers may create their
   normal runtime subdirectories later when explicitly run.
2. Process `CROW_DATA_ROOT_HOST` or legacy `FAPAI_DATA_ROOT_HOST` wins over the
   local file and discovery. If both are set to different normalized paths,
   fail with a conflict rather than silently changing the data location.
3. If neither process variable is set, inspect only those two keys in
   `docker.local.env`. Conflicting aliases or duplicate values fail closed.
   Keys may have surrounding whitespace and an optional `export` prefix.
   Single/double-quoted paths (including spaces and Unicode) and trailing
   comments are supported. Malformed quotes and unexpanded `$VAR` / `${...}` / `$(...)`
   values are rejected instead of becoming accidental directory names.
   Other settings and secrets are neither printed nor modified.
4. Inspect immediate repository children matching CrowData/FPFData
   case-insensitively. A directory containing only regular `README.md` and
   `.gitignore` files is a checkout shell, not an installation. Any other
   entry, even an empty subdirectory, counts conservatively as runtime content.
5. One populated root wins, preserving its actual spelling and location.
   Two populated roots, duplicate case variants, non-directory roots or
   unreadable inspection fail closed. Select the intended root explicitly.
6. With no populated roots, select the existing CrowData spelling or default
   to `CrowData`. No directory or marker is created by selection.

Path identity is normalized lexically, without collapsing symbolic links or
Windows junctions to their targets. A legacy root that is a link remains that
link. Two aliases specifying the link and its target are ambiguous and fail
closed; select one explicitly. No links or targets are changed. Dotenv variable
expansion/escaping is not performed; use an already-literal process environment
or CLI value when a path must contain dollar-prefixed variable-like text.

Relative management-root overrides are relative to the repository, independent
of the current working directory. Existing absolute local/UNC paths remain
valid on their host OS. A Linux process must use its mounted host path, not a
Windows UNC string as an environment path. Persisted Windows/UNC artifact
references containing either `/FPFData/` or `/CrowData/` are read compatibly
and traversal is rejected; their stored database values are not rewritten.

IMPORTANT: `FAPAI_DATA_ROOT` keeps its existing meaning: the collection's
`datas` directory itself, not its parent management root. The collection
`--data-root` argument keeps the same meaning. Do not replace either with the
management-root setting. Specific existing overrides (model-pool file,
controller root, cookie-snapshot root, browser-profile path) keep priority.
Desktop runtime JSON accepts either management-root key; process settings
override saved settings as a group. Deployment helpers preserve an installed
desktop's explicit stored root and reject conflicting saved aliases.

## Existing installations and rollback

Leave populated `FPFData` where it is. No import command is needed. If both roots
contain runtime entries, choose the correct root using the existing explicit
argument or management-root variable; do not delete either to clear the error.
When pinning for rollback to an older version, use `FAPAI_DATA_ROOT_HOST` (the
old version does not understand the new alias). A new installation that has
used CrowData can pin that exact CrowData path in the old variable before an
older binary is run. The resolver never rewrites configuration automatically.
Old scheduled-task entry-point filenames and persisted runtime identifiers
remain available. Docker build contexts and Git ignore both roots, including
case variants. Only management README/ignore files are versioned.

## Naming inventory and next stages

At base `07921151ca70f4916407876936cfde0a12b8d25d`, exact FPFData references
appeared 146 times across 87 tracked files; FAPAI environment names 3380 times
across 317 files, and FapaiFangCollectorDesktop 60 times across 30 files.
These are reference counts, not a mechanical replacement list.

- Stage 1 (this branch): local management-root defaults, Python/PowerShell
  shared selectors, path-translation dual reads, Git/Docker protection and
  entry-point regression tests. Existing PC2 host-specific installation paths
  in `ops/pc2-host` and remote-browser scripts stay as explicit compatibility
  deployment configuration. Historical reports stay historically accurate.
- Stage 2: generic application identity becomes Crow. Audit Fapai/FaPai/fapai,
  FPF and FAPAI uses in process/config/env/CLI names, AppData install paths,
  desktop runtime bundles, scheduled tasks, container/service/image names,
  log names and scripts. Add Crow aliases and deprecation guidance before
  retiring old names. Changing deployed persistent identities requires a
  separate activation/rollback plan; do not start duplicate workers or empty
  profiles under a new name.
- Stage 3: genuine auction-business code should also use English, not pinyin.
  Use `judicial_auction_property` / `JudicialAuctionProperty` for judicial
  auction real estate; use a broader auction asset term where the domain is
  broader. Keep the business meaning intact. For example, Taobao judicial
  auction source adapters remain judicial-auction adapters rather than being
  renamed to a generic Crow concept. Translate display/product wording as
  appropriate, but do not alter original listing evidence or historical data.
- Durable compatibility boundaries: database schema/table/column names,
  serialized keys, external HTTP headers/routes, browser storage keys,
  upstream filenames/identifiers and signed/persisted formats must be inventoried
  separately. Keep dual readers/aliases; no bulk SQL rename or raw-data rewrite
  is authorized by a terminology change.

The branch must be reviewed with its tests and remaining risks before merge.
No deployment acceptance is implied by repository-only or CI checks.
