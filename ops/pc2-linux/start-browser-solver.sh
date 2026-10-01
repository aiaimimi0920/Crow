#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/process-supervisor.sh"
crow_validate_env

requested_display="${DISPLAY:-:99}"
display_mode="$(crow_env CROW_BROWSER_DISPLAY_MODE "auto")"
host_display="$(crow_env CROW_BROWSER_HOST_DISPLAY ":0")"
display="$requested_display"
screen_geometry="$(crow_env CROW_BROWSER_SCREEN_GEOMETRY "1440x900x24")"
profile_dir="$(crow_env CROW_BROWSER_PROFILE_DIR "/data/browser-profile")"
start_url="$(crow_env CROW_BROWSER_START_URL "https://sf.taobao.com/")"
vnc_password_file="$(crow_env CROW_VNC_PASSWORD_FILE "/run/secrets/pc2_vnc_password")"
cdp_endpoint="$(crow_env CROW_CDP_ENDPOINT "http://127.0.0.1:9223")"
cdp_public_port="$(crow_env CROW_CDP_PUBLIC_PORT "9224")"
cdp_allowed_client_cidrs="$(crow_env CROW_CDP_ALLOWED_CLIENT_CIDRS "127.0.0.0/8,::1/128,172.16.0.0/12,192.168.15.20/32,192.168.15.200/32")"
api_base_url="$(crow_env CROW_API_BASE_URL "http://192.168.15.200:8001/api")"
node_id="$(crow_env CROW_NODE_ID "pc2")"
browser_user_agent="$(crow_env CROW_BROWSER_USER_AGENT "")"
browser_identity_full_version="$(crow_env CROW_BROWSER_IDENTITY_FULL_VERSION "")"
browser_executable="$(crow_env CROW_BROWSER_EXECUTABLE "")"
browser_identity_ready_path="$(crow_env CROW_BROWSER_IDENTITY_READY_PATH "/tmp/fapaifang-browser-identity.ready")"
xauthority="${XAUTHORITY:-/tmp/.Xauthority}"
vnc_auth_file="/tmp/tigervnc.passwd"

if [[ ! -r "$vnc_password_file" || ! -s "$vnc_password_file" ]]; then
  echo "PC2 browser VNC password file is missing, unreadable, or empty: $vnc_password_file" >&2
  exit 1
fi

if ! head -n 1 "$vnc_password_file" | tigervncpasswd -f >"$vnc_auth_file"; then
  echo "Unable to create the TigerVNC authentication file" >&2
  exit 1
fi
chmod 0600 "$vnc_auth_file"

mkdir -p "$profile_dir" /data/output /app/.codex-temp/bridge-control
rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonSocket" "$profile_dir/SingletonCookie"

export DBUS_SESSION_BUS_ADDRESS=/dev/null
pids=()
use_host_display=0
cleanup() {
  trap - EXIT INT TERM
  crow_stop_children
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$display_mode" != "auto" && "$display_mode" != "host" && "$display_mode" != "xvfb" ]]; then
  echo "Unsupported CROW_BROWSER_DISPLAY_MODE" >&2
  exit 1
fi

export XAUTHORITY="$xauthority"
touch "$XAUTHORITY"
chmod 0600 "$XAUTHORITY"

if [[ "$display_mode" != "xvfb" ]]; then
  host_display_number="${host_display#:}"
  host_display_socket="/tmp/.X11-unix/X${host_display_number}"
  if [[ -S "$host_display_socket" ]] \
    && DISPLAY="$host_display" XAUTHORITY="$XAUTHORITY" xdpyinfo >/dev/null 2>&1; then
    use_host_display=1
    display="$host_display"
  elif [[ "$display_mode" == "host" ]]; then
    echo "Requested host browser display is unavailable: $host_display" >&2
    exit 1
  fi
fi

crow_select_xvfb_display() {
  local requested="$1" socket_root="${2:-/tmp}" number offset lock socket_path
  [[ "$requested" =~ ^:([0-9]{1,5})$ ]] || {
    echo "Invalid Xvfb display: expected a local numeric display" >&2
    return 1
  }
  number=$((10#${BASH_REMATCH[1]}))
  # /tmp/.X11-unix may be shared with the host. Never unlink another display's
  # socket or lock, even when its PID is invisible inside this container.
  for ((offset=0; offset<64; offset++)); do
    lock="$socket_root/.X$((number + offset))-lock"
    socket_path="$socket_root/.X11-unix/X$((number + offset))"
    if [[ ! -e "$lock" && ! -L "$lock" && ! -e "$socket_path" && ! -L "$socket_path" ]]; then
      printf ':%s\n' "$((number + offset))"
      return 0
    fi
  done
  echo "No unused Xvfb display in the bounded startup range" >&2
  return 1
}

if [[ "$use_host_display" == "0" ]]; then
  display="$(crow_select_xvfb_display "$display")"
  Xvfb "$display" -screen 0 "$screen_geometry" -nolisten tcp -ac &
  pids+=("$!")
fi
export DISPLAY="$display"

for _ in $(seq 1 40); do
  if xdotool getmouselocation >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
xdotool getmouselocation >/dev/null 2>&1 || {
  echo "X display did not become ready on $display" >&2
  exit 1
}

if [[ "$use_host_display" == "0" ]]; then
  fluxbox >/tmp/fluxbox.log 2>&1 &
  pids+=("$!")
  echo "Browser display mode: xvfb ($display)"
else
  echo "Browser display mode: host ($display)"
fi
x0tigervncserver \
  -display "$display" \
  -rfbport 5900 \
  -SecurityTypes VncAuth \
  -PasswordFile "$vnc_auth_file" \
  -AlwaysShared \
  -fg >/tmp/tigervnc.log 2>&1 &
pids+=("$!")
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
pids+=("$!")

if [[ -z "$browser_executable" ]]; then
  for candidate in /usr/bin/google-chrome-stable /usr/bin/google-chrome; do
    if [[ -x "$candidate" ]]; then
      browser_executable="$candidate"
      break
    fi
  done
fi

if [[ -z "$browser_executable" ]]; then
  browser_executable="$({
    python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    print(playwright.chromium.executable_path)
PY
  } | tail -n 1)"
fi

if [[ ! -x "$browser_executable" ]]; then
  echo "Browser executable not found: $browser_executable" >&2
  exit 1
fi

runtime_browser_version="$(
  "$browser_executable" --version \
    | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
    | head -n 1 \
    || true
)"
if [[ -z "$runtime_browser_version" ]]; then
  echo "Unable to determine browser version: $browser_executable" >&2
  exit 1
fi
runtime_browser_major="${runtime_browser_version%%.*}"
if [[ -n "$browser_identity_full_version" && "$browser_identity_full_version" != "$runtime_browser_version" ]]; then
  echo "Configured browser identity version does not match the browser executable" >&2
  exit 1
fi
if [[ -n "$browser_user_agent" ]]; then
  configured_browser_major="$(
    printf '%s\n' "$browser_user_agent" \
      | grep -Eo '(Chrome|Chromium)/[0-9]+' \
      | head -n 1 \
      | cut -d/ -f2 \
      || true
  )"
  if [[ -z "$configured_browser_major" || "$configured_browser_major" != "$runtime_browser_major" ]]; then
    echo "Configured browser user agent does not match the browser executable" >&2
    exit 1
  fi
fi
echo "Browser executable: $browser_executable (version $runtime_browser_version)"

if [[ "$(id -u)" == "0" ]]; then
  echo "PC2 browser must run as the non-root fapaifang user" >&2
  exit 1
fi
if [[ -r /proc/sys/kernel/unprivileged_userns_clone ]] \
  && [[ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" != "1" ]]; then
  echo "Chromium user-namespace sandbox is unavailable; refusing an unsandboxed browser" >&2
  exit 1
fi

# Keep launch-time UA, CDP UA-CH metadata, and the HTTP-cookie workers on one
# identity when an explicit Windows user agent is configured.
browser_identity_args=()
if [[ -n "$browser_user_agent" ]]; then
  browser_identity_args+=(--user-agent="$browser_user_agent")
fi

browser_graphics_args=(
  --ignore-gpu-blocklist
  --enable-webgl
)
if [[ "$use_host_display" == "0" ]]; then
  # Xvfb has no DRI device, so keep its software-WebGL compatibility fallback.
  browser_graphics_args+=(
    --enable-unsafe-swiftshader
    --use-gl=angle
    --use-angle=swiftshader
  )
else
  browser_graphics_args+=(--ozone-platform=x11)
fi

"$browser_executable" \
  --disable-dev-shm-usage \
  --disable-blink-features=AutomationControlled \
  "${browser_graphics_args[@]}" \
  --disable-background-networking \
  --disable-default-apps \
  --disable-features=Translate,OptimizationHints,MediaRouter \
  --disable-session-crashed-bubble \
  --no-default-browser-check \
  --no-first-run \
  "${browser_identity_args[@]}" \
  --remote-allow-origins='*' \
  --remote-debugging-address=0.0.0.0 \
  --remote-debugging-port=9223 \
  --user-data-dir="$profile_dir" \
  --window-position=0,0 \
  --window-size=1440,900 \
  about:blank >/tmp/chromium.log 2>&1 &
pids+=("$!")

python - <<'PY'
import json
import time
from urllib.request import urlopen

for _ in range(120):
    try:
        with urlopen("http://127.0.0.1:9223/json/version", timeout=2) as response:
            payload = json.load(response)
        if payload.get("webSocketDebuggerUrl"):
            raise SystemExit(0)
    except Exception:
        time.sleep(1)
raise SystemExit("Chromium CDP did not become ready on port 9223")
PY

rm -f "$browser_identity_ready_path"
python tools/cdp_browser_identity.py \
  --cdp-endpoint "$cdp_endpoint" \
  --ready-path "$browser_identity_ready_path" >/tmp/browser-identity.log 2>&1 &
pids+=("$!")
for _ in $(seq 1 40); do
  [[ -s "$browser_identity_ready_path" ]] && break
  sleep 0.25
done
if [[ ! -s "$browser_identity_ready_path" ]]; then
  echo "PC2 browser identity controller did not become ready" >&2
  exit 1
fi

# The first Taobao navigation must happen only after the stable blank target has
# received UA/UA-CH and document identity overrides from the controller.
python - "$start_url" <<'PY'
import json
import sys
from urllib.request import urlopen

import websocket

start_url = sys.argv[1]
with urlopen("http://127.0.0.1:9223/json/list", timeout=5) as response:
    targets = json.load(response)
target = next(
    (
        item
        for item in targets
        if item.get("type") == "page"
        and item.get("url") == "about:blank"
        and item.get("webSocketDebuggerUrl")
    ),
    None,
)
if target is None:
    raise SystemExit("Identity-prepared blank browser target is missing")
connection = websocket.create_connection(
    target["webSocketDebuggerUrl"],
    suppress_origin=True,
    timeout=5,
)
try:
    connection.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": start_url}}))
    while True:
        try:
            message = json.loads(connection.recv())
        except websocket.WebSocketTimeoutException:
            # A slow site must not terminate the healthy browser and its supervisor.
            print(json.dumps({"kind": "initial_navigation_pending", "reason": "cdp_response_timeout"}))
            break
        if message.get("id") != 1:
            continue
        if message.get("error"):
            raise SystemExit("Identity-prepared initial navigation failed")
        break
finally:
    connection.close()
PY

# Chromium binds its DevTools HTTP server to loopback even when
# --remote-debugging-address=0.0.0.0 is supplied. Keep that endpoint private
# and normalize the Host header while relaying HTTP and WebSocket traffic.
relay_allow_args=()
IFS=',' read -r -a configured_cdp_cidrs <<<"$cdp_allowed_client_cidrs"
for cidr in "${configured_cdp_cidrs[@]}"; do
  [[ -n "$cidr" ]] && relay_allow_args+=(--allow-cidr "$cidr")
done
if (( ${#relay_allow_args[@]} == 0 )); then
  echo "CROW_CDP_ALLOWED_CLIENT_CIDRS must contain at least one CIDR" >&2
  exit 1
fi
python tools/cdp_host_relay.py \
  --listen-port "$cdp_public_port" \
  --upstream-host 127.0.0.1 \
  --upstream-port 9223 \
  "${relay_allow_args[@]}" &
pids+=("$!")

python - "$cdp_public_port" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

endpoint = f"http://127.0.0.1:{int(sys.argv[1])}/json/version"
for _ in range(40):
    try:
        with urlopen(endpoint, timeout=2) as response:
            payload = json.load(response)
        if payload.get("webSocketDebuggerUrl"):
            raise SystemExit(0)
    except Exception:
        time.sleep(0.25)
raise SystemExit(f"public Chromium CDP relay did not become ready: {endpoint}")
PY

solver_heartbeat_path="$(crow_env CROW_LOCAL_SOLVER_HEARTBEAT_PATH "/tmp/fapaifang-local-solver-heartbeat.json")"
rm -f "$solver_heartbeat_path"
python tools/pc2_solver_watchdog.py \
  --heartbeat-path "$solver_heartbeat_path" \
  --stale-seconds "$(crow_env CROW_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS "300")" \
  --startup-grace-seconds "$(crow_env CROW_LOCAL_SOLVER_WATCHDOG_STARTUP_GRACE_SECONDS "180")" \
  --poll-seconds "$(crow_env CROW_LOCAL_SOLVER_WATCHDOG_POLL_SECONDS "30")" \
  --parent-pid "$$" &
pids+=("$!")

python tools/pc2_local_solver.py \
  --api-base-url "$api_base_url" \
  --cdp-endpoint "$cdp_endpoint" \
  --poll-seconds "$(crow_env CROW_LOCAL_SOLVER_POLL_SECONDS "5")" \
  --max-attempts "$(crow_env CROW_LOCAL_SOLVER_MAX_ATTEMPTS "10")" \
  --node-id "$node_id" &
solver_pid="$!"
pids+=("$solver_pid")
crow_wait_children
