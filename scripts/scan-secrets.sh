#!/usr/bin/env bash
# Scan the checked-out tree, not installed application data or Git history.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mode=${1:-strict}
if [[ "$mode" != strict && "$mode" != advisory ]]; then exit 2; fi
version=8.30.1
sha256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'This pinned scanner bootstrap requires Linux x86_64.' >&2
  exit 2
fi
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
asset="gitleaks_${version}_linux_x64.tar.gz"
curl --fail --silent --show-error --location --retry 3 \
  "https://github.com/gitleaks/gitleaks/releases/download/v${version}/${asset}" \
  --output "$work/$asset"
printf '%s  %s\n' "$sha256" "$work/$asset" | sha256sum --check --status
tar -xzf "$work/$asset" -C "$work" gitleaks
bash "$root/scripts/test-secret-scan.sh" "$work/gitleaks"
# Exclude untracked runtime files by scanning an exact tracked-tree snapshot.
git -C "$root" ls-files -z | tar -C "$root" --null --files-from=- -cf "$work/tree.tar"
mkdir "$work/tree"
tar -xf "$work/tree.tar" -C "$work/tree"
set +e
"$work/gitleaks" dir "$work/tree" --config="$root/.gitleaks.toml" --redact=100 --no-banner --exit-code=1 \
  --report-format=json --report-path="$work/redacted.json" --log-level=error >/dev/null 2>&1
status=$?
set -e
python3 "$root/scripts/report_secret_scan.py" "$work/redacted.json" "$status" "$mode" "$work/tree"
