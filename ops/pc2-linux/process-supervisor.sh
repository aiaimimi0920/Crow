#!/usr/bin/env bash
# All PIDs must be direct children started by this launcher.
_crow_helpers="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/project-environment.sh"
if [[ ! -f "$_crow_helpers" ]]; then
  _crow_helpers="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts" && pwd)/project-environment.sh"
fi
source "$_crow_helpers"
crow_stop_children() {
  local pid deadline grace
  grace="$(crow_env CROW_BROWSER_SHUTDOWN_GRACE_SECONDS 30)" || grace=30
  [[ "$grace" =~ ^[0-9]+$ ]] || grace=30
  deadline=$((SECONDS + grace))
  for pid in "${pids[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
  done
  pids=()
}

crow_wait_children() {
  local result=0
  # A display/Chrome/relay exit is just as fatal as a solver exit.
  wait -n "${pids[@]}" || result=$?
  if (( result == 0 )); then
    result=1
  fi
  return "$result"
}
