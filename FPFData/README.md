# Project-local runtime data

`FPFData/` is the legacy management root and remains supported in place.
New installations default to `CrowData/`; see the
[compatibility guide](../docs/runbooks/crow-data-root-compatibility.md).
There is no need to rename or copy an existing data directory.
Code and local operator scripts should derive this directory from the current
repository root instead of relying on a drive letter, UNC path, checkout name,
or user profile.

The contents are deliberately ignored by Git. This tree can contain browser
profiles, cookies, access tokens, database backups, logs, and large generated
artifacts. Only this README and `.gitignore` are versioned.

## Legacy imports

Use `scripts/import-legacy-fpfdata.ps1` to make a non-destructive, resumable
archive-only copy under the selected management root’s `imports/<source-id>/`
(`FPFData` for an existing installation, `CrowData` for a new one):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\import-legacy-fpfdata.ps1 `
  -SourceRoot '<legacy-data-root>' `
  -SourceId 'legacy-nas'
```

The importer copies only `backups`, `datas`, `jobs`, `output`, and
`postgres/backups`. It excludes the top-level `secrets`, mutable `runtime`,
browser profiles, log trees, and live PostgreSQL data. Common secret-bearing file
names such as environment, cookie, credential, token, and auth files are also
filtered when nested below an allowed archive directory. This is a path/name
filter, not a content scrub, so review unfamiliar archives before sharing them.
The importer does not delete or modify the source and never mirrors deletions
into an existing import.

Existing live services may continue using their configured external data root.
Moving this directory or changing source defaults does not authorize any PC2 or
NAS deployment, restart, synchronization, or configuration update.
