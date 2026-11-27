#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/project-environment.sh"
env_file="${CROW_NAS_ENV_FILE:-$repo_root/env.nas.local}"
keep_recent_days=""
keep_daily_days=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --keep-recent-days)
      keep_recent_days="$2"
      shift 2
      ;;
    --keep-daily-days)
      keep_daily_days="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -r "$env_file" ]]; then
  crow_source_env_file "$env_file" "$repo_root/tools/shell_environment_file.py" --legacy-container-env
elif [[ -z "${CROW_NAS_DATA_ROOT:-}" ]]; then
  echo "Missing or unreadable NAS environment file: $env_file (and CROW_NAS_DATA_ROOT is unset)" >&2
  exit 1
fi

: "${CROW_NAS_DATA_ROOT:?CROW_NAS_DATA_ROOT must be set}"
keep_recent_days="${keep_recent_days:-${CROW_BACKUP_KEEP_RECENT_DAYS:-7}}"
keep_daily_days="${keep_daily_days:-${CROW_BACKUP_KEEP_DAILY_DAYS:-30}}"
[[ "$keep_recent_days" =~ ^[1-9][0-9]{0,3}$ && "$keep_daily_days" =~ ^[1-9][0-9]{0,3}$ ]] || {
  echo "Retention must be a positive number of days (at most 9999)." >&2; exit 2;
}
postgres_container="${CROW_POSTGRES_CONTAINER:-fapaifang-postgres}"
postgres_host="${CROW_POSTGRES_HOST:-127.0.0.1}"
postgres_port="${CROW_POSTGRES_HOST_PORT:-55432}"
postgres_db="${CROW_POSTGRES_DB:-fapaifang}"
postgres_user="${CROW_POSTGRES_USER:-fapaifang}"
postgres_password="${CROW_POSTGRES_PASSWORD:-fapaifang}"

# Deployment rollback dumps live in the parent and are not owned by this job.
backup_dir="$CROW_NAS_DATA_ROOT/backups/postgres/scheduled"
status_dir="$CROW_NAS_DATA_ROOT/datas"
status_file="$status_dir/postgres-backup-status.json"
mkdir -p "$backup_dir" "$status_dir"

lock_file="$backup_dir/.backup.lock"
exec 9<>"$lock_file"
flock -n 9 || { echo "PostgreSQL backup lock unavailable." >&2; exit 1; }

stamp="$(date -u +%Y%m%d-%H%M%S)"
container_dump="/tmp/fapaifang-scheduled-$stamp.dump"
host_tmp="$backup_dir/.fapaifang-$stamp.dump.tmp"
host_dump="$backup_dir/fapaifang-$stamp.dump"
[[ ! -e "$host_dump" ]] || { echo "Backup name already published." >&2; exit 1; }
use_docker=0
if command -v docker >/dev/null 2>&1 && docker inspect --format '{{.State.Running}}' "$postgres_container" 2>/dev/null | grep -qx 'true'; then
  use_docker=1
fi

cleanup() {
  rm -f "$host_tmp" >/dev/null 2>&1 || true
  if [[ "$use_docker" -eq 1 ]]; then
    docker exec "$postgres_container" rm -f "$container_dump" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$use_docker" -eq 1 ]]; then
  docker exec \
    -e "PGPASSWORD=$postgres_password" \
    "$postgres_container" \
    pg_dump -U "$postgres_user" -d "$postgres_db" -Fc -f "$container_dump"

  docker cp "$postgres_container:$container_dump" "$host_tmp" >/dev/null
  toc_entries="$(docker exec -i "$postgres_container" pg_restore -l < "$host_tmp" | grep -cvE '^[[:space:]]*(;|$)')"
elif command -v pg_dump >/dev/null 2>&1 && command -v pg_restore >/dev/null 2>&1; then
  PGPASSWORD="$postgres_password" pg_dump \
    -h "$postgres_host" \
    -p "$postgres_port" \
    -U "$postgres_user" \
    -d "$postgres_db" \
    -Fc -f "$host_tmp"
  toc_entries="$(
    PGPASSWORD="$postgres_password" pg_restore -l "$host_tmp" | grep -cvE '^[[:space:]]*(;|$)'
  )"
else
  echo "Neither accessible Docker container '$postgres_container' nor host pg_dump/pg_restore is available." >&2
  exit 1
fi

[[ "$toc_entries" -ge 5 ]] || {
  echo "pg_restore TOC check failed ($toc_entries entries)." >&2
  exit 1
}

size_bytes="$(wc -c < "$host_tmp" | tr -d '[:space:]')"
[[ "$size_bytes" -ge 1024 ]] || {
  echo "PostgreSQL dump is unexpectedly small (${size_bytes} bytes)." >&2
  exit 1
}
chmod 0600 "$host_tmp"
mv -f "$host_tmp" "$host_dump"

python3 - "$backup_dir" "$status_file" "$host_dump" "$size_bytes" "$toc_entries" "$keep_recent_days" "$keep_daily_days" <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

backup_dir = Path(sys.argv[1])
status_file = Path(sys.argv[2])
latest_dump = Path(sys.argv[3])
size_bytes = int(sys.argv[4])
toc_entries = int(sys.argv[5])
keep_recent_days = max(1, int(sys.argv[6]))
keep_daily_days = max(keep_recent_days, int(sys.argv[7]))

now = dt.datetime.now(dt.timezone.utc)
recent_cutoff = now - dt.timedelta(days=keep_recent_days)
daily_cutoff = now - dt.timedelta(days=keep_daily_days)
stamp_re = re.compile(r"fapaifang-(\d{8})-(\d{6})\.dump$")

dumps = sorted(
    (p for p in backup_dir.glob("fapaifang-*.dump") if stamp_re.fullmatch(p.name) and not p.is_symlink() and p.is_file() and p.stat().st_size >= 1024),
    key=lambda p: p.name,
    reverse=True,
)

kept: list[Path] = []
seen_days: set[str] = set()
pruned = 0
for idx, dump in enumerate(dumps):
    if idx < 4 or dump == latest_dump:
        kept.append(dump)
        m = stamp_re.search(dump.name)
        if m:
            seen_days.add(m.group(1))
        continue
    m = stamp_re.search(dump.name)
    if m:
        ts = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=dt.timezone.utc
        )
        day_key = m.group(1)
    else:
        ts = dt.datetime.fromtimestamp(dump.stat().st_mtime, tz=dt.timezone.utc)
        day_key = ts.strftime("%Y%m%d")
    if ts >= recent_cutoff:
        kept.append(dump)
        seen_days.add(day_key)
    elif ts >= daily_cutoff and day_key not in seen_days:
        kept.append(dump)
        seen_days.add(day_key)
    else:
        try:
            dump.unlink(missing_ok=True)
            pruned += 1
        except PermissionError:
            kept.append(dump)

payload = {
    "ok": True,
    "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "latest_backup_file": latest_dump.name,
    "size_bytes": size_bytes,
    "toc_entries": toc_entries,
    "retained_backups": len(kept),
    "pruned_backups": pruned,
    "keep_recent_days": keep_recent_days,
    "keep_daily_days": keep_daily_days,
}
tmp_status = status_file.with_name(f".{status_file.name}.{os.getpid()}.tmp")
tmp_status.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.chmod(tmp_status, 0o644)
os.replace(tmp_status, status_file)
PY

echo "Verified NAS PostgreSQL backup: $host_dump (${size_bytes} bytes, ${toc_entries} TOC entries)"
