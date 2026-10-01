#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts" && pwd)/project-environment.sh"
crow_sync_env

app_root="/srv/apps/fapaifang-worker"
data_root="/srv/data/fapaifang-worker"
shared_root="$app_root/shared"
runtime_env="$shared_root/runtime.env"
control_root="$(crow_env CROW_COLLECTION_CONTROL_ROOT "$shared_root/collection-control")"
vnc_password_file="$shared_root/vnc-password"
project_name="fapaifang-pc2"
expected_ip="192.168.15.104"
release_dir=""
release_id=""
mode="deploy"
dry_run=0
skip_build=0
browser_only=0

# Capacity checks are intentionally read-only.  Crow retains historical
# evidence and release metadata, so deployment must stop before exhaustion
# instead of pruning data or Docker state automatically.
min_free_space_percent="$(crow_env CROW_MIN_FREE_SPACE_PERCENT 10)"
min_free_inodes_percent="$(crow_env CROW_MIN_FREE_INODES_PERCENT 5)"

usage() {
  cat <<'EOF'
Usage:
  deploy.sh --release-dir PATH --release-id ID [--dry-run] [--skip-build] [--browser-only]
  deploy.sh --rollback

The runtime environment and VNC password must already exist at:
  /srv/apps/fapaifang-worker/shared/runtime.env
  /srv/apps/fapaifang-worker/shared/vnc-password
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-dir)
      release_dir="${2:-}"
      shift 2
      ;;
    --release-id)
      release_id="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    --browser-only)
      browser_only=1
      shift
      ;;
    --rollback)
      mode="rollback"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

verify_identity() {
  [[ "$(hostname -s)" == "pc2" ]] || {
    echo "Refusing deployment: hostname is not pc2." >&2
    return 1
  }
  ip -o -4 addr show scope global | awk '{print $4}' | grep -Eq '^192\.168\.15\.104/' || {
    echo "Refusing deployment: expected PC2 address $expected_ip is missing." >&2
    return 1
  }
  [[ -r /etc/pc2-install-profile ]] || {
    echo "Refusing deployment: /etc/pc2-install-profile is missing." >&2
    return 1
  }
  grep -Eq '^PROFILE=pc2$' /etc/pc2-install-profile || {
    echo "Refusing deployment: install profile is not pc2." >&2
    return 1
  }
  grep -Eq '^EXPECTED_BOOT_MODE=uefi$' /etc/pc2-install-profile || {
    echo "Refusing deployment: PC2 boot-mode contract is not uefi." >&2
    return 1
  }
  sudo -n true
  docker version >/dev/null
  docker compose version >/dev/null
}

verify_runtime_inputs() {
  [[ -f "$runtime_env" && -s "$runtime_env" ]] || {
    echo "Runtime environment is missing: $runtime_env" >&2
    return 1
  }
  [[ -f "$vnc_password_file" && -s "$vnc_password_file" ]] || {
    echo "VNC password file is missing: $vnc_password_file" >&2
    return 1
  }
  local key
  for key in FAPAI_WORKER_DB_URL OPENAI_API_KEY; do
    grep -Eq "^${key}=.+" "$runtime_env" || {
      echo "Runtime environment is missing required key: $key" >&2
      return 1
    }
  done
  if grep -Eq '(^|=)(replace-me|changeme)([[:space:]]|$)' "$runtime_env"; then
    echo "Runtime environment still contains a placeholder value." >&2
    return 1
  fi
}

validate_capacity_threshold() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ && "$value" -lt 100 ]] || {
    echo "${name} must be an integer between 0 and 99." >&2
    return 1
  }
}

check_capacity() {
  validate_capacity_threshold CROW_MIN_FREE_SPACE_PERCENT "$min_free_space_percent"
  validate_capacity_threshold CROW_MIN_FREE_INODES_PERCENT "$min_free_inodes_percent"

  local path probe space_line inode_line used_pct free_pct free_inodes_pct
  local -a paths=("$app_root" "$data_root" "$control_root")
  for path in "${paths[@]}"; do
    probe="$path"
    while [[ ! -e "$probe" && "$probe" != "/" ]]; do
      probe="$(dirname "$probe")"
    done
    used_pct="$(df -Pk "$probe" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
    free_inodes_pct="$(df -Pi "$probe" | awk 'NR==2 {gsub(/%/, "", $5); print 100 - $5}')"
    [[ -n "$used_pct" && -n "$free_inodes_pct" && "$used_pct" =~ ^[0-9]+$ && "$free_inodes_pct" =~ ^[0-9]+$ ]] || {
      echo "Unable to read filesystem capacity for $path." >&2
      return 1
    }
    free_pct=$((100 - used_pct))
    echo "Capacity $path: free=${free_pct}% inodes=${free_inodes_pct}% (probe=$probe)"
    if (( free_pct < min_free_space_percent )); then
      echo "Refusing deployment: $path has only ${free_pct}% free space (minimum ${min_free_space_percent}%)." >&2
      return 1
    fi
    if (( free_inodes_pct < min_free_inodes_percent )); then
      echo "Refusing deployment: $path has only ${free_inodes_pct}% free inodes (minimum ${min_free_inodes_percent}%)." >&2
      return 1
    fi
  done
}

browser_apparmor_name() {
  printf 'crow-browser-sandbox-%s' "$(sha256sum "$1/ops/pc2-linux/crow-browser.apparmor" | cut -c1-12)"
}

prepare_browser_security() {
  local target_release="$1"
  local profile="$target_release/ops/pc2-linux/crow-browser.apparmor"
  local name generated installed
  name="$(browser_apparmor_name "$target_release")"
  generated="$target_release/crow-browser.apparmor.generated"
  installed="/etc/apparmor.d/$name"
  [[ "$(uname -m)" == "x86_64" ]] || {
    echo "The Crow browser seccomp policy requires an amd64 PC2 host." >&2
    return 1
  }
  python3 "$target_release/tools/pc2_browser_security.py" \
    --output "$target_release/ops/pc2-linux/seccomp-browser.json"
  sed "s/crow-browser-sandbox/$name/g" "$profile" >"$generated"
  sudo -n apparmor_parser -Q "$generated"
  if [[ -f "$installed" ]]; then
    sudo -n cmp -s "$generated" "$installed" || {
      echo "Existing content-addressed AppArmor policy differs; refusing overwrite." >&2
      return 1
    }
  else
    sudo -n install -m 0644 "$generated" "$installed"
  fi
  sudo -n apparmor_parser -r "$installed"
}

prepare_host_display_access() {
  local display_mode host_display display_number display_socket runtime_dir host_xauthority host_user
  display_mode="$(sed -n 's/^FAPAI_BROWSER_DISPLAY_MODE=//p' "$runtime_env" | tail -n 1)"
  display_mode="${display_mode:-auto}"
  [[ "$display_mode" != "xvfb" ]] || return 0

  host_display="$(sed -n 's/^FAPAI_BROWSER_HOST_DISPLAY=//p' "$runtime_env" | tail -n 1)"
  host_display="${host_display:-:0}"
  display_number="${host_display#:}"
  display_socket="/tmp/.X11-unix/X${display_number}"
  runtime_dir="/run/user/$(id -u)"
  host_xauthority="$(find "$runtime_dir" -maxdepth 1 -type f -name '.mutter-Xwaylandauth.*' -readable -print -quit 2>/dev/null || true)"

  host_user="$(crow_env CROW_BROWSER_XHOST_USER)"
  if [[ -S "$display_socket" && -n "$host_xauthority" ]] \
    && DISPLAY="$host_display" XAUTHORITY="$host_xauthority" \
      xhost +SI:localuser:"${host_user:-$(id -un)}" >/dev/null 2>&1; then
    echo "Prepared logged-in host display for the browser solver: $host_display"
    return 0
  fi
  if [[ "$display_mode" == "host" ]]; then
    echo "Requested host browser display is unavailable: $host_display" >&2
    return 1
  fi
  echo "Logged-in host display is unavailable; browser solver will use Xvfb." >&2
}

compose_for() {
  local target_release="$1"
  shift
  if [[ -f "$control_root/active.json" ]]; then
    PYTHONPATH="$control_root/runtime" python3 -m tools.pc2_settings_release \
      --runtime-root "$control_root" --env-file "$runtime_env" \
      --env-file "$target_release/.release.env" \
      --compose-file "$target_release/ops/pc2-linux/compose.yaml" compose "$@"
    return
  fi
  docker compose \
    --project-name "$project_name" \
    --env-file "$runtime_env" \
    --env-file "$target_release/.release.env" \
    --file "$target_release/ops/pc2-linux/compose.yaml" \
    "$@"
}

wait_for_health() {
  if [[ -f "$control_root/active.json" ]]; then
    PYTHONPATH="$control_root/runtime" python3 -m tools.pc2_settings_release --runtime-root "$control_root" finish
    return
  fi
  local deadline=$((SECONDS + 600))
  local containers=(
    fapaifang-pc2-browser-solver
    fapaifang-pc2-seed-1
    fapaifang-pc2-detail-1
    fapaifang-pc2-detail-2
    fapaifang-pc2-detail-3
    fapaifang-pc2-analysis-1
    fapaifang-pc2-analysis-2
    fapaifang-pc2-analysis-3
    fapaifang-pc2-analysis-4
  )
  local name state
  while (( SECONDS < deadline )); do
    local all_healthy=1
    for name in "${containers[@]}"; do
      state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || true)"
      if [[ "$state" != "running healthy" ]]; then
        all_healthy=0
        break
      fi
    done
    if (( all_healthy )); then
      return 0
    fi
    sleep 5
  done
  echo "PC2 services did not all become healthy within 600 seconds." >&2
  return 1
}

wait_for_browser_health() {
  if [[ -f "$control_root/active.json" ]]; then
    wait_for_health
    return
  fi
  local deadline=$((SECONDS + 600))
  local state
  while (( SECONDS < deadline )); do
    state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' fapaifang-pc2-browser-solver 2>/dev/null || true)"
    if [[ "$state" == "running healthy" ]]; then
      return 0
    fi
    sleep 5
  done
  echo "PC2 browser solver did not become healthy within 600 seconds." >&2
  return 1
}

validate_release_tree() {
  local target_release="$1"
  [[ -f "$target_release/Dockerfile" ]]
  [[ -f "$target_release/ops/pc2-linux/Dockerfile.browser" ]]
  [[ -f "$target_release/ops/pc2-linux/compose.yaml" ]]
  [[ -f "$target_release/tools/pc2_linux_healthcheck.py" ]]
  [[ -f "$target_release/requirements.lock" ]]
  [[ -f "$target_release/ops/pc2-linux/process-supervisor.sh" ]]
  if [[ -f "$target_release/scripts/project-environment.sh" ]]; then
    bash -n "$target_release/scripts/project-environment.sh"
  elif grep -q 'project-environment\.sh' \
    "$target_release/ops/pc2-linux/process-supervisor.sh" \
    "$target_release/ops/pc2-linux/start-browser-solver.sh"; then
    echo "Release requires missing project-environment.sh helper." >&2
    return 1
  fi
  bash -n "$target_release/ops/pc2-linux/process-supervisor.sh"
  bash -n "$target_release/ops/pc2-linux/start-browser-solver.sh"
  compose_for "$target_release" config --quiet
}

write_release_metadata() {
  local target_release="$1"
  local app_image="$2"
  local browser_image="$3"
  local app_image_id browser_image_id
  app_image_id="$(docker image inspect --format '{{.Id}}' "$app_image")"
  browser_image_id="$(docker image inspect --format '{{.Id}}' "$browser_image")"
  umask 022
  cat >"$target_release/.release.env" <<EOF
FAPAI_IMAGE=$app_image
FAPAI_BROWSER_IMAGE=$browser_image
FAPAI_BROWSER_SECCOMP_PROFILE=$target_release/ops/pc2-linux/seccomp-browser.json
FAPAI_BROWSER_APPARMOR_PROFILE=$(browser_apparmor_name "$target_release")
EOF
  cat >"$target_release/release-manifest.txt" <<EOF
release_id=$release_id
app_image=$app_image
app_image_id=$app_image_id
browser_image=$browser_image
browser_image_id=$browser_image_id
compose_project=$project_name
compose_services=9
EOF
}

restore_release() {
  local prior_release="$1"
  if [[ -n "$prior_release" && -d "$prior_release" && -f "$prior_release/.release.env" ]]; then
    echo "Restoring previous PC2 release: $prior_release" >&2
    compose_for "$prior_release" up -d --remove-orphans
    wait_for_health
    sudo -n ln -sfn "$prior_release" "$app_root/current"
    return 0
  fi
  return 1
}

deploy_release() {
  [[ -n "$release_dir" && -n "$release_id" ]] || {
    echo "--release-dir and --release-id are required." >&2
    usage >&2
    return 2
  }
  release_dir="$(readlink -f "$release_dir")"
  [[ -d "$release_dir" ]] || {
    echo "Release directory does not exist: $release_dir" >&2
    return 1
  }
  [[ "$release_id" =~ ^[0-9A-Za-z._-]+$ ]] || {
    echo "Release ID contains unsupported characters." >&2
    return 1
  }

  local expected_release="$app_root/releases/$release_id"
  [[ "$release_dir" == "$expected_release" ]] || {
    echo "Release must be staged at $expected_release" >&2
    return 1
  }

  if (( dry_run )); then
    echo "Dry run passed identity and path checks for $expected_release."
    return 0
  fi

  check_capacity
  verify_runtime_inputs
  local prior_release=""
  if [[ -L "$app_root/current" ]]; then
    prior_release="$(readlink -f "$app_root/current")"
  fi

  local app_image="fapaifang-worker:$release_id"
  local browser_image="fapaifang-browser:$release_id"
  local browser_base_image=""
  local source_digest build_time build_commit
  source_digest="$(find "$release_dir" -type f ! -name '.release.env' ! -name 'release-manifest.txt' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  build_time="$(date --iso-8601=seconds)"
  build_commit="$(git -C "$release_dir" rev-parse HEAD 2>/dev/null || printf 'working-tree')"

  if (( browser_only )); then
    [[ -n "$prior_release" && -f "$prior_release/.release.env" ]] || {
      echo "Browser-only deployment requires a current release with image metadata." >&2
      return 1
    }
    [[ -f "$release_dir/ops/pc2-linux/Dockerfile.auth-recovery" ]] || {
      echo "Browser auth recovery Dockerfile is missing from the release." >&2
      return 1
    }
    app_image="$(sed -n 's/^FAPAI_IMAGE=//p' "$prior_release/.release.env" | tail -1)"
    browser_base_image="$(sed -n 's/^FAPAI_BROWSER_IMAGE=//p' "$prior_release/.release.env" | tail -1)"
    [[ -n "$app_image" && -n "$browser_base_image" ]] || {
      echo "Current release image metadata is incomplete." >&2
      return 1
    }
  fi

  if (( skip_build )); then
    docker image inspect "$app_image" >/dev/null
    docker image inspect "$browser_image" >/dev/null
    echo "Using preloaded PC2 release images for $release_id."
  elif (( browser_only )); then
    docker image inspect "$app_image" >/dev/null
    docker image inspect "$browser_base_image" >/dev/null
    docker run --rm --entrypoint python "$browser_base_image" -c 'import evdev'
    if ! docker build \
      --build-arg "FAPAI_BASE_IMAGE=$browser_base_image" \
      --build-arg "FAPAI_BUILD_VERSION=$release_id" \
      --build-arg "FAPAI_BUILD_COMMIT=$build_commit" \
      --build-arg "FAPAI_BUILD_TIME=$build_time" \
      --build-arg "FAPAI_SOURCE_DIGEST=$source_digest" \
      --tag "$browser_image" \
      --file "$release_dir/ops/pc2-linux/Dockerfile.auth-recovery" \
      "$release_dir"; then
      echo "Browser hotfix layer build failed; rebuilding from the worker image to collapse the layer chain." >&2
      docker build \
        --build-arg "FAPAI_BASE_IMAGE=$app_image" \
        --tag "$browser_image" \
        --file "$release_dir/ops/pc2-linux/Dockerfile.browser" \
        "$release_dir"
    fi
  else
    docker build \
      --build-arg "FAPAI_BUILD_VERSION=$release_id" \
      --build-arg "FAPAI_BUILD_COMMIT=$build_commit" \
      --build-arg "FAPAI_BUILD_TIME=$build_time" \
      --build-arg "FAPAI_SOURCE_DIGEST=$source_digest" \
      --tag "$app_image" \
      --file "$release_dir/Dockerfile" \
      "$release_dir"
    docker build \
      --build-arg "FAPAI_BASE_IMAGE=$app_image" \
      --tag "$browser_image" \
      --file "$release_dir/ops/pc2-linux/Dockerfile.browser" \
      "$release_dir"
  fi
  write_release_metadata "$release_dir" "$app_image" "$browser_image"
  validate_release_tree "$release_dir"
  prepare_browser_security "$release_dir"
  prepare_host_display_access

  if (( browser_only )); then
    if compose_for "$release_dir" up -d --no-deps pc2-browser-solver && wait_for_browser_health; then
      if [[ "$prior_release" != "$release_dir" ]]; then
        sudo -n ln -sfn "$prior_release" "$app_root/previous"
      fi
      sudo -n ln -sfn "$release_dir" "$app_root/current"
      compose_for "$release_dir" ps pc2-browser-solver
      echo "PC2 browser auth recovery release is healthy: $release_id"
      return 0
    fi

    echo "PC2 browser auth recovery release failed health validation." >&2
    compose_for "$release_dir" ps pc2-browser-solver >&2 || true
    if compose_for "$prior_release" up -d --no-deps pc2-browser-solver && wait_for_browser_health; then
      echo "Previous PC2 browser solver restored after failed deployment." >&2
    else
      echo "Previous PC2 browser solver could not be restored automatically." >&2
    fi
    return 1
  fi

  if compose_for "$release_dir" up -d --remove-orphans && wait_for_health; then
    if [[ -n "$prior_release" && "$prior_release" != "$release_dir" ]]; then
      sudo -n ln -sfn "$prior_release" "$app_root/previous"
    fi
    sudo -n ln -sfn "$release_dir" "$app_root/current"
    compose_for "$release_dir" ps
    echo "PC2 release is healthy: $release_id"
    return 0
  fi

  echo "PC2 release failed health validation." >&2
  compose_for "$release_dir" ps >&2 || true
  if restore_release "$prior_release"; then
    echo "Previous release restored after failed deployment." >&2
  else
    echo "No healthy previous release was available; failed containers were left for diagnosis." >&2
  fi
  return 1
}

rollback_release() {
  verify_runtime_inputs
  [[ -L "$app_root/current" && -L "$app_root/previous" ]] || {
    echo "Rollback requires both current and previous release links." >&2
    return 1
  }
  local current_release previous_release
  current_release="$(readlink -f "$app_root/current")"
  previous_release="$(readlink -f "$app_root/previous")"
  [[ -d "$previous_release" && -f "$previous_release/.release.env" ]] || {
    echo "Previous release is not deployable: $previous_release" >&2
    return 1
  }
  validate_release_tree "$previous_release"
  compose_for "$previous_release" up -d --remove-orphans
  wait_for_health
  sudo -n ln -sfn "$previous_release" "$app_root/current"
  sudo -n ln -sfn "$current_release" "$app_root/previous"
  compose_for "$previous_release" ps
  echo "Rollback completed: $(basename "$previous_release")"
}

verify_identity

# Serialize the entire release, including rollback, against settings and restarts.
if (( ! dry_run )) && [[ -d "$control_root" ]]; then
  [[ ! -L "$control_root" && "$(stat -c '%u:%a' "$control_root")" == "$(id -u):700" ]] || { echo "Unsafe controller state directory" >&2; exit 1; }
  umask 077
  [[ ! -L "$control_root/operation.lock" ]] || { echo "Unsafe operation lock" >&2; exit 1; }
  exec 9<>"$control_root/operation.lock"
  flock -n 9 || { echo "A collection operation is already running" >&2; exit 1; }
  [[ ! -e "$control_root/release-operation.json" ]] || { echo "Previous release needs reconciliation" >&2; exit 1; }
  if [[ -f "$control_root/active.json" ]]; then
    [[ -f "$control_root/runtime/tools/pc2_settings_release.py" ]] || { echo "Settings-aware release helper is missing" >&2; exit 1; }
  fi
fi

if (( dry_run )) && [[ "$mode" == "rollback" ]]; then
  echo "--dry-run cannot be combined with --rollback." >&2
  exit 2
fi

if [[ "$mode" == "rollback" ]]; then
  rollback_release
else
  deploy_release
fi
