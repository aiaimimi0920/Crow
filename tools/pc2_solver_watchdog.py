from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv


def heartbeat_age_seconds(path: Path, *, now: float | None = None) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(payload.get("updated_at_epoch") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if updated_at <= 0:
        return None
    current_time = time.time() if now is None else float(now)
    return max(0.0, current_time - updated_at)


def watchdog_iteration(
    heartbeat_path: Path,
    *,
    started_at: float,
    stale_seconds: float,
    startup_grace_seconds: float,
    parent_pid: int,
    now: float | None = None,
    terminate: Callable[[int, int], None] = os.kill,
) -> dict[str, object]:
    current_time = time.time() if now is None else float(now)
    age = heartbeat_age_seconds(heartbeat_path, now=current_time)
    startup_age = max(0.0, current_time - float(started_at))
    if age is None and startup_age <= max(0.0, startup_grace_seconds):
        return {"status": "startup_grace", "heartbeat_age_seconds": None}
    if age is not None and age <= max(1.0, stale_seconds):
        return {"status": "healthy", "heartbeat_age_seconds": age}

    terminate(parent_pid, signal.SIGTERM)
    return {
        "status": "restart_requested",
        "heartbeat_age_seconds": age,
        "parent_pid": parent_pid,
    }


def run_watchdog(
    heartbeat_path: Path,
    *,
    stale_seconds: float,
    startup_grace_seconds: float,
    poll_seconds: float,
    parent_pid: int,
) -> int:
    started_at = time.time()
    while True:
        result = watchdog_iteration(
            heartbeat_path,
            started_at=started_at,
            stale_seconds=stale_seconds,
            startup_grace_seconds=startup_grace_seconds,
            parent_pid=parent_pid,
        )
        if result["status"] == "restart_requested":
            print(json.dumps({"kind": "local_solver_watchdog_restart", **result}), flush=True)
            return 0
        time.sleep(max(1.0, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart the PC2 browser container when its solver loop stalls.")
    parser.add_argument(
        "--heartbeat-path",
        default=project_getenv(
            "CROW_LOCAL_SOLVER_HEARTBEAT_PATH",
            "/tmp/fapaifang-local-solver-heartbeat.json",
        ),
    )
    parser.add_argument(
        "--stale-seconds",
        type=float,
        default=float(project_getenv("CROW_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS", "300")),
    )
    parser.add_argument(
        "--startup-grace-seconds",
        type=float,
        default=float(project_getenv("CROW_LOCAL_SOLVER_WATCHDOG_STARTUP_GRACE_SECONDS", "180")),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(project_getenv("CROW_LOCAL_SOLVER_WATCHDOG_POLL_SECONDS", "30")),
    )
    parser.add_argument("--parent-pid", type=int, default=os.getppid())
    args = parser.parse_args()
    return run_watchdog(
        Path(args.heartbeat_path),
        stale_seconds=args.stale_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        poll_seconds=args.poll_seconds,
        parent_pid=args.parent_pid,
    )


if __name__ == "__main__":
    raise SystemExit(main())
