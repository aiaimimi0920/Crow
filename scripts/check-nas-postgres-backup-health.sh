#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/project-environment.sh"
env_file="${CROW_NAS_ENV_FILE:-$repo_root/env.nas.local}"
max_age_hours=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --max-age-hours)
      max_age_hours="$2"
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
max_age_hours="${max_age_hours:-${CROW_BACKUP_MAX_AGE_HOURS:-12}}"

exec python3 "$repo_root/src/postgres_backup_status.py" "$CROW_NAS_DATA_ROOT" "$max_age_hours"
