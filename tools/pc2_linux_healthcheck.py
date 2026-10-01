from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv
from tools.pc2_solver_watchdog import heartbeat_age_seconds


def _read_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected an object from {url}")
    return payload


def _process_exists(fragment: str) -> bool:
    proc_root = Path("/proc")
    for command_line_path in proc_root.glob("[0-9]*/cmdline"):
        try:
            command_line = (
                command_line_path.read_bytes()
                .replace(b"\x00", b" ")
                .decode("utf-8", errors="replace")
            )
        except OSError:
            continue
        if fragment in command_line:
            return True
    return False


def _check_rfb_listener(
    port: int = 5900,
    *,
    proc_net_paths: tuple[Path, ...] | None = None,
) -> None:
    # Opening RFB without authenticating counts as a security failure in
    # TigerVNC. Repeated health checks can therefore blacklist websockify's
    # loopback source and lock every noVNC user out.
    expected_port = f"{port:04X}"
    paths = proc_net_paths or (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
    for path in paths:
        try:
            rows = path.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 4:
                continue
            local_port = fields[1].rsplit(":", 1)[-1].upper()
            state = fields[3].upper()
            if local_port == expected_port and state == "0A":
                return
    raise RuntimeError(f"RFB server is not listening on port {port}")


def _check_solver_heartbeat(
    heartbeat_path: Path | None = None,
    *,
    stale_seconds: float | None = None,
    now: float | None = None,
) -> None:
    path = heartbeat_path or Path(
        project_getenv(
            "CROW_LOCAL_SOLVER_HEARTBEAT_PATH",
            "/tmp/fapaifang-local-solver-heartbeat.json",
        )
    )
    maximum_age = (
        float(project_getenv("CROW_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS", "300"))
        if stale_seconds is None
        else float(stale_seconds)
    )
    heartbeat_age = heartbeat_age_seconds(path, now=now)
    if heartbeat_age is None:
        raise RuntimeError("PC2 local solver heartbeat is missing or invalid")
    if heartbeat_age > max(1.0, maximum_age):
        raise RuntimeError(
            f"PC2 local solver heartbeat is stale: {heartbeat_age:.1f}s > {maximum_age:.1f}s"
        )


def _check_solver_api_credentials() -> None:
    from src.collection_api_credentials import (
        RECOVERY_TOKEN_HEADER,
        WORKER_TOKEN_HEADER,
        configured_api_base,
        request_headers,
    )

    try:
        base = configured_api_base()
        for route, header in (
            ("/report_captcha", WORKER_TOKEN_HEADER),
            ("/collection/auth/complete", RECOVERY_TOKEN_HEADER),
        ):
            if not request_headers(base + route, method="POST").get(header):
                raise RuntimeError(f"PC2 solver API credential missing for {route}")
    except (OSError, ValueError) as error:
        raise RuntimeError("PC2 solver API credential check failed") from error


def check_browser() -> None:
    cdp_endpoint = str(
        project_getenv("CROW_CDP_ENDPOINT") or "http://127.0.0.1:9223"
    ).rstrip("/")
    version = _read_json(f"{cdp_endpoint}/json/version")
    if not version.get("webSocketDebuggerUrl"):
        raise RuntimeError("CDP websocket endpoint is missing")
    public_port = int(str(project_getenv("CROW_CDP_PUBLIC_PORT") or "9224"))
    public_version = _read_json(f"http://127.0.0.1:{public_port}/json/version")
    if not public_version.get("webSocketDebuggerUrl"):
        raise RuntimeError("public CDP relay websocket endpoint is missing")
    with socket.create_connection(("127.0.0.1", 6080), timeout=5):
        pass
    _check_rfb_listener()
    if not _process_exists("x0tigervncserver"):
        raise RuntimeError("TigerVNC server process is missing")
    if not _process_exists("websockify"):
        raise RuntimeError("noVNC WebSocket relay process is missing")
    if not _process_exists("tools/pc2_local_solver.py"):
        raise RuntimeError("PC2 local solver process is missing")
    if not _process_exists("tools/pc2_solver_watchdog.py"):
        raise RuntimeError("PC2 local solver watchdog process is missing")
    if not _process_exists("tools/cdp_browser_identity.py"):
        raise RuntimeError("PC2 browser identity controller process is missing")
    _check_solver_heartbeat()
    _check_solver_api_credentials()


def check_worker() -> None:
    path = Path(
        project_getenv(
            "CROW_WORKER_HEARTBEAT_PATH", "/tmp/fapaifang-worker-heartbeat.json"
        )
    )
    try:
        heartbeat = json.loads(path.read_text(encoding="utf-8"))
        updated = float(heartbeat["updated_at_epoch"])
        pid = int(heartbeat["pid"])
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RuntimeError("worker progress heartbeat is missing or invalid") from error
    age = time.time() - updated
    maximum = max(
        1, float(project_getenv("CROW_WORKER_HEARTBEAT_STALE_SECONDS", "900"))
    )
    if not 0 <= age <= maximum or pid < 1 or heartbeat.get("stage") == "stopped":
        raise RuntimeError("worker progress heartbeat is stale or stopped")
    os.kill(pid, 0)
    output_root = Path(project_getenv("CROW_OUTPUT_DIR", "/data/output"))
    if not output_root.is_dir() or not os.access(output_root, os.W_OK):
        raise RuntimeError("worker output root is not writable")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Health check for the Debian PC2 browser and collection workers."
    )
    parser.add_argument("--mode", choices=("browser", "worker"), required=True)
    args = parser.parse_args()
    if args.mode == "browser":
        check_browser()
    else:
        check_worker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
