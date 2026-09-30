#!/usr/bin/env bash
# Positive/negative canaries prevent the reviewed false-positive rules hiding new secrets.
set -euo pipefail
scanner=$1
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
cat > "$fixture/public-identifiers.txt" <<'PUBLIC'
job_key = "shanghai-shanghai-fengxian-50025969"
AUTH_STAGE_VERIFY_CODE = "pc2_stage_verifying"
PUBLIC
"$scanner" dir "$fixture" --config="$root/.gitleaks.toml" --no-banner --redact=100 --log-level=error
# This deliberately synthetic canary is assembled at runtime so it is not a repository finding.
printf 'api_key = "%s%s"\n' 'crow_canary_' 'Vg9R6s2N4m8Q1w7E3x5K0z' > "$fixture/canary.txt"
set +e
"$scanner" dir "$fixture" --config="$root/.gitleaks.toml" --no-banner --redact=100 \
  --log-level=error --report-format=json --report-path="$fixture/report.json"
status=$?
set -e
if [[ "$status" != 1 ]]; then
  echo "Secret-scanner positive canary failed (exit $status)." >&2
  exit 2
fi
python3 - "$fixture/report.json" <<'PY'
import json
import sys
findings = json.load(open(sys.argv[1], encoding="utf-8"))
assert findings and any(item["RuleID"] == "generic-api-key" for item in findings)
assert all(item["Secret"] == "REDACTED" for item in findings)
assert all("Vg9R6s2N4m8Q1w7E3x5K0z" not in item["Match"] for item in findings)
PY
