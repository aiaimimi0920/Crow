#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/env.nas.local"
compose_file="$repo_root/docker-compose.nas-central.yml"
build_mode="full"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --hotfix)
      build_mode="hotfix"
      shift
      ;;
    --auth-recovery-hotfix)
      build_mode="auth-recovery-hotfix"
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cd "$repo_root"
[[ -f "$env_file" ]] || { echo "Missing NAS environment file: $env_file" >&2; exit 1; }
env_file="$(cd "$(dirname "$env_file")" && pwd)/$(basename "$env_file")"
command -v docker >/dev/null
command -v curl >/dev/null
command -v python3 >/dev/null
if ! docker compose version >/dev/null 2>&1; then
  command -v docker-compose >/dev/null
  docker() {
    if [[ "${1:-}" == "compose" ]]; then
      shift
      command docker-compose "$@"
    else
      command docker "$@"
    fi
  }
  export -f docker
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
export FAPAI_NAS_ENV_FILE="${FAPAI_NAS_ENV_FILE:-$env_file}"

: "${FAPAI_NAS_DATA_ROOT:?FAPAI_NAS_DATA_ROOT must be set}"
postgres_container="${FAPAI_POSTGRES_CONTAINER:-fapaifang-postgres}"
postgres_db="${FAPAI_POSTGRES_DB:-fapaifang}"
postgres_user="${FAPAI_POSTGRES_USER:-fapaifang}"
postgres_password="${FAPAI_POSTGRES_PASSWORD:-fapaifang}"
api_container="${FAPAI_API_CONTAINER:-crow-api}"
api_port="${FAPAI_API_HOST_PORT:-8001}"
api_host_bind_address="${FAPAI_API_HOST_BIND_ADDRESS:-127.0.0.1}"
api_tls_cert_file="${FAPAI_API_TLS_CERT_FILE:-}"
api_tls_key_file="${FAPAI_API_TLS_KEY_FILE:-}"
api_health_scheme=http
api_health_host=127.0.0.1
api_health_resolve_address="$api_host_bind_address"
api_health_curl_args=()

if ! api_bind_is_loopback="$(python3 - "$api_host_bind_address" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(2)
if not isinstance(address, ipaddress.IPv4Address):
    raise SystemExit(2)
print(int(address.is_loopback))
PY
)"; then
  echo "FAPAI_API_HOST_BIND_ADDRESS must be a literal IPv4 address." >&2
  exit 1
fi
if [[ "$api_host_bind_address" == "0.0.0.0" ]]; then
  api_health_resolve_address=127.0.0.1
fi

if [[ -n "$api_tls_cert_file" || -n "$api_tls_key_file" ]]; then
  if [[ -z "$api_tls_cert_file" || -z "$api_tls_key_file" ]]; then
    echo "FAPAI_API_TLS_CERT_FILE and FAPAI_API_TLS_KEY_FILE must be set together." >&2
    exit 1
  fi
  api_health_scheme=https
  api_health_host="${FAPAI_API_HEALTH_HOST:-localhost}"
  if [[ -z "$api_health_host" ]]; then
    echo "FAPAI_API_HEALTH_HOST must match a host name in the API certificate." >&2
    exit 1
  fi
  api_health_curl_args=(--resolve "${api_health_host}:${api_port}:${api_health_resolve_address}")
  api_health_ca_file="${FAPAI_API_HEALTH_CA_FILE:-}"
  if [[ -n "$api_health_ca_file" ]]; then
    if [[ ! -r "$api_health_ca_file" ]]; then
      echo "FAPAI_API_HEALTH_CA_FILE is not readable on this host." >&2
      exit 1
    fi
    api_health_curl_args+=(--cacert "$api_health_ca_file")
  fi
fi
if [[ "$api_bind_is_loopback" != 1 && -z "$api_tls_cert_file" ]]; then
  echo "External NAS API binding requires a configured TLS certificate and key." >&2
  exit 1
fi

version="$(date -u +%Y%m%d-%H%M%S)"
commit="$(git rev-parse --short=12 HEAD 2>/dev/null || printf unknown)"
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [[ "$build_mode" == "auth-recovery-hotfix" ]]; then
  digest_files=(
    Dockerfile.nas-auth-recovery
    docker-compose.nas-central.yml
    src/server.py
    src/nas_auth_recovery.py
  )
else
  digest_files=(
    Dockerfile
    Dockerfile.nas-hotfix
    docker-compose.nas-central.yml
    src/server.py
    src/nas_auth_recovery.py
    src/storage/repository.py
    src/captcha_solver.py
    collector-desktop/index.html
    collector-desktop/dist/index.html
    tools/browserless_seed_probe.py
    tools/taobao_login_health.py
  )
  # Include transitive runtime owners, not only the historical server facade.
  while IFS= read -r source_file; do
    digest_files+=("$source_file")
  done < <(find src -type f -name '*.py' -print | LC_ALL=C sort)
fi
source_digest="$(sha256sum "${digest_files[@]}" | sha256sum | awk '{print $1}')"

export FAPAI_BUILD_VERSION="$version"
export FAPAI_BUILD_COMMIT="$commit"
export FAPAI_BUILD_TIME="$built_at"
export FAPAI_SOURCE_DIGEST="$source_digest"
export FAPAI_DOCKERFILE="Dockerfile"

docker inspect "$postgres_container" >/dev/null
docker inspect "$api_container" >/dev/null
previous_image="$(docker inspect --format '{{.Config.Image}}' "$api_container")"
if [[ -z "$previous_image" || "$previous_image" == "<no value>" ]]; then
  previous_image="$(docker inspect --format '{{.Image}}' "$api_container")"
fi
compose_project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$api_container")"
if [[ -z "$compose_project" || "$compose_project" == "<no value>" ]]; then
  compose_project="$(basename "$repo_root")"
fi
candidate_image="fapaifang-collector:nas-$version"
export FAPAI_IMAGE="$candidate_image"
rollback_tag="fapaifang-collector:rollback-$version"

echo "Deployment identity: version=$version commit=$commit source_digest=$source_digest"
echo "Build mode: $build_mode"
echo "Compose project: $compose_project"
echo "Candidate image: $candidate_image"
echo "Rollback image tag: $rollback_tag"

if [[ "$dry_run" -eq 1 ]]; then
  echo "Dry run complete; no backup, build, or restart was performed."
  exit 0
fi

auth_recovery_token_file="$FAPAI_NAS_DATA_ROOT/secrets/nas-auth-recovery.token"
if [[ ! -s "$auth_recovery_token_file" ]]; then
  mkdir -p "$(dirname "$auth_recovery_token_file")"
  umask 077
  python3 - "$auth_recovery_token_file" <<'PY'
import secrets
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
PY
fi
chmod 0600 "$auth_recovery_token_file"

# PC1 and PC2 mount the shared artifact root, while the NAS API keeps its
# private secrets mount. Publish the same token atomically into the shared
# secrets directory so all three nodes authenticate with one value without
# putting it in an environment file or command line.
if [[ -n "${FAPAI_SHARED_ARTIFACT_ROOT:-}" ]]; then
  shared_auth_recovery_token_file="$FAPAI_SHARED_ARTIFACT_ROOT/secrets/nas-auth-recovery.token"
  if [[ "$shared_auth_recovery_token_file" != "$auth_recovery_token_file" ]]; then
    mkdir -p "$(dirname "$shared_auth_recovery_token_file")"
    python3 - "$auth_recovery_token_file" "$shared_auth_recovery_token_file" <<'PY'
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
try:
    temporary.write_bytes(source.read_bytes())
    temporary.chmod(0o600)
    os.replace(temporary, target)
finally:
    temporary.unlink(missing_ok=True)
PY
    if [[ "$(id -u)" -eq 0 ]]; then
      chown --reference="$(dirname "$shared_auth_recovery_token_file")" \
        "$shared_auth_recovery_token_file"
    fi
    chmod 0600 "$shared_auth_recovery_token_file"
  fi
fi

backup_dir="$FAPAI_NAS_DATA_ROOT/backups/postgres"
mkdir -p "$backup_dir"
container_dump="/tmp/fapaifang-$version.dump"
host_dump="$backup_dir/fapaifang-$version.dump"

cleanup_dump() {
  docker exec "$postgres_container" rm -f "$container_dump" >/dev/null 2>&1 || true
}
trap cleanup_dump EXIT

docker exec \
  -e "PGPASSWORD=$postgres_password" \
  "$postgres_container" \
  pg_dump -U "$postgres_user" -d "$postgres_db" -Fc -f "$container_dump"
docker exec \
  -e "PGPASSWORD=$postgres_password" \
  "$postgres_container" \
  pg_restore -l "$container_dump" >/dev/null
docker cp "$postgres_container:$container_dump" "$host_dump" >/dev/null
[[ "$(wc -c < "$host_dump")" -ge 1024 ]] || { echo "Database backup is unexpectedly small." >&2; exit 1; }
echo "Verified database backup: $host_dump"

docker image tag "$previous_image" "$rollback_tag"
if [[ "$build_mode" == "hotfix" ]]; then
  export FAPAI_DOCKERFILE="Dockerfile.nas-hotfix"
  export FAPAI_BASE_IMAGE="$previous_image"
elif [[ "$build_mode" == "auth-recovery-hotfix" ]]; then
  export FAPAI_DOCKERFILE="Dockerfile.nas-auth-recovery"
  export FAPAI_BASE_IMAGE="$previous_image"
fi

rollback() {
  echo "Health gate failed; restoring $rollback_tag" >&2
  FAPAI_IMAGE="$rollback_tag" docker compose --project-name "$compose_project" \
    --env-file "$env_file" \
    -f "$compose_file" \
    up -d --no-deps --no-build crow-api
}

if ! docker compose --project-name "$compose_project" \
  --env-file "$env_file" -f "$compose_file" build crow-api; then
  echo "Candidate image build failed; the running API was not replaced." >&2
  exit 1
fi
if ! docker compose --project-name "$compose_project" \
  --env-file "$env_file" -f "$compose_file" up -d --no-deps crow-api; then
  rollback
  exit 1
fi

health_url="${api_health_scheme}://${api_health_host}:${api_port}/api/status"
healthy=0
for _ in $(seq 1 60); do
  if payload="$(curl -fsS --max-time 5 "${api_health_curl_args[@]}" "$health_url" 2>/dev/null)"; then
    if EXPECTED_VERSION="$version" EXPECTED_DIGEST="$source_digest" PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["PAYLOAD"])
if not (payload.get("auth_recovery") or {}).get("enabled"):
    raise SystemExit(1)
build = payload.get("build_info") or {}
if build.get("version") != os.environ["EXPECTED_VERSION"]:
    raise SystemExit(1)
if build.get("source_digest") != os.environ["EXPECTED_DIGEST"]:
    raise SystemExit(1)
if not payload.get("db_mode"):
    raise SystemExit(1)
PY
    then
      healthy=1
      break
    fi
  fi
  sleep 2
done

if [[ "$healthy" -ne 1 ]]; then
  echo "Candidate container state before rollback:" >&2
  docker inspect \
    --format 'status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} restart={{.RestartCount}} oom={{.State.OOMKilled}} error={{.State.Error}}' \
    "$api_container" >&2 || true
  echo "Candidate container logs before rollback:" >&2
  docker logs --tail 200 --timestamps "$api_container" >&2 || true
  rollback
  exit 1
fi

docker exec "$postgres_container" pg_isready -U "$postgres_user" -d "$postgres_db" >/dev/null
curl -fsS --max-time 10 "${api_health_curl_args[@]}" \
  "${api_health_scheme}://${api_health_host}:${api_port}/api/collection/overview" >/dev/null
echo "NAS API deployment passed build identity, database, and collection overview health gates."
