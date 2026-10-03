# Crow security checks

These checks run in GitHub-hosted runners. They do not deploy Crow, start a live
collector, access PC2/NAS data, or require production credentials.

## Coverage

- CodeQL: Python, JavaScript/TypeScript, Rust, and GitHub Actions, with the
  `security-extended` query suite and no-build extraction
- OSV-Scanner 2.6.0: both hashed Python locks, both npm locks, and the desktop
  Cargo lock; scans PRs, `master`, weekly, and on manual dispatch
- Gitleaks 8.30.1: the checked-out, Git-tracked tree, with a checksum-verified
  binary, full finding redaction, and positive/negative canary tests
- Dependabot: weekly GitHub Actions, Python requirements, both npm projects,
  and desktop Cargo updates; compatible version updates are grouped, major
  updates remain separate
- Existing Crow quality suites are preserved; the game gets a clean-checkout
  build gate and tests for its generated local entrypoint

OSV fails on unresolved findings. There are currently no OSV suppressions. A
successful configuration test is not a clean vulnerability scan. CodeQL and
Gitleaks do not prove the absence of every security issue.

Repository settings such as dependency alerts, secret scanning, private
vulnerability reporting, push protection, branch rules, and required checks
are separate from these files. Do not claim those settings are enabled merely
because a workflow or Dependabot configuration exists.

## Python lock maintenance

Dependabot's pip support discovers `.txt` and `.in` requirements; it does not
maintain this project's custom uv-generated `.lock` files automatically. Review
its manifest PRs and regenerate the affected locks before merging. Preserve
Python 3.10 compatibility, universal markers, and package hashes:

```sh
uv pip compile requirements.txt --universal --python-version 3.10 \
  --generate-hashes --no-emit-index-url --output-file requirements.lock
uv pip compile requirements-dev.in --constraint requirements.lock \
  --universal --python-version 3.10 --generate-hashes --no-emit-index-url \
  --output-file requirements-dev.lock
```

Use `--upgrade-package NAME` for a reviewed targeted update. Do not use an
unbounded upgrade merely to clear a vulnerability check. CI installs the
committed development lock with `--require-hashes`, including on Windows.

## Game CLI watcher dependency

`@tailwindcss/cli 4.3.3` pins `@parcel/watcher 2.5.1`, which brings
`micromatch -> braces 3.0.3` and
[GHSA-vfj7-8cjw-p6xm](https://osv.dev/GHSA-vfj7-8cjw-p6xm).
The game manifest narrowly overrides that CLI's watcher to `2.6.0`, whose
upstream implementation uses `picomatch` without the vulnerable chain. The
watcher remains a development dependency; this does not change game data or
the shipped UI. Keep native watcher packages aligned in the lockfile. Remove
the override when the CLI itself adopts a reviewed unaffected watcher; do not
replace it with an OSV exclusion. Reverting the manifest and lockfile together
restores the previous build tooling, but also restores the advisory.

## Reviewed Gitleaks false positives

The default `generic-api-key` rule also matches public identifiers containing
words such as `key`, `auth`, or `tokens`. `.gitleaks.toml` permits only seven exact
non-secret literals, and only for that rule:

- Three public seed job IDs: geographic/category identifiers used as database
  lookup keys, with their generation contract in
  `src/storage/repository_seed_scan_jobs.py::_seed_scan_job_key`
- `pc2_stage_verifying`: a generated UI stage code, defined by the auth recovery
  code contract, not a verification credential
- `pc2-completion-stale`: an artificial completion ID used only in a unit test
- Two SHA-256 asset digests in `docs/design/neuro/source-manifest.json`, for
  design-token JSON/CSS assets, not authentication tokens

No directory, credential format, or whole detector is excluded. The scanner
self-test proves an exact public identifier is accepted and a new synthetic
API-key canary is still rejected; its report must contain only redacted secrets.
New findings require review. Never paste real credentials into an issue, PR,
CI log, or test fixture.

## Remaining upstream dependency findings (2026-09-30)

After compatible fixes for anyhow, plist/quick-xml, game tooling, and the
pytest development dependency, and tauri-utils 2.10.0 / urlpattern 0.6.0,
the desktop framework still brings:

- `glib 0.18.5`: [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html)
  / GHSA-wrw7-89jp-8q8g. The `VariantStrIter` implementation is unsound; upstream
  fixes start at 0.20.0. The current Tauri GTK3 chain uses 0.18. This package is
  absent from the Windows target graph but remains in the Linux graph/lock.
- `proc-macro-error 1.0.4`: [RUSTSEC-2024-0370](https://rustsec.org/advisories/RUSTSEC-2024-0370.html),
  unmaintained, reached through GTK3 macros


Unmaintained advisories are maintenance risk rather than evidence of a specific
exploit, but they remain reported. No compatibility or risk exception has been
approved here. Any proposed exception must name its advisory, package/version,
platform and reachability evidence, owner, expiry, and remediation, and receive
independent review. The all-lockfile scan must not be replaced with a
platform-filtered scan to hide unresolved entries.

The five previously reported UNIC maintenance advisories were removed by the
compatible `tauri-utils 2.10.0 -> urlpattern 0.6.0` update. No Tauri application
major-version migration or local crate patch was made. The remaining GTK chain
cannot be fixed by selecting glib 0.20+ inside GTK 0.18: the parent requires
`glib ^0.18`. The current stable Tauri 2.12.0 still requires `gtk ^0.18`.
The newer GTK 0.19 branch uses glib 0.22, requiring an upstream framework
transition or a separately reviewed backport rather than a lockfile-only fix.

`cargo tree --target x86_64-pc-windows-msvc -i glib` and the corresponding
`proc-macro-error` query are empty. Both appear in `--target all` through the
Linux GTK3 stack. Crow's own Rust source contains no direct `VariantStrIter`
reference, but this is not proof that framework calls are unreachable on
Linux. This baseline therefore leaves those findings visible and blocking.
