"""Emergency tab recovery for the private browser-solver container only."""

from __future__ import annotations

import json
import os
import signal
import time
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

# Never use the configurable worker/PC1 CDP endpoint for destructive recovery.
ENDPOINT = "http://127.0.0.1:9223"
MAX_TABS = 4
CLOSE_BUDGET_SECONDS = 10.0
POLL_SECONDS = 5.0


def read_cdp(path: str, timeout: float) -> bytes:
    opener = build_opener(ProxyHandler({}))
    with opener.open(ENDPOINT + path, timeout=timeout) as response:
        return response.read(1024 * 1024 + 1)


def page_ids(payload: bytes) -> list[str]:
    if len(payload) > 1024 * 1024:
        raise ValueError("CDP inventory exceeds limit")
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise TypeError("Invalid CDP inventory")
    ids = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Invalid CDP target")
        if row.get("type") != "page":
            continue
        target_id = row.get("id")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Invalid page target identity")
        ids.append(target_id)
    return list(dict.fromkeys(ids))


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def guard_iteration(
    parent_pid: int,
    *,
    request=read_cdp,
    terminate=os.kill,
    clock=time.monotonic,
    log=emit,
) -> dict[str, object]:
    """Close all pages on overflow, then restart through the existing supervisor.

    A stalled solver must not block this independent watchdog. Closing pages is
    best effort under one deadline; supervisor shutdown also releases pages that
    hang or are created concurrently. Profile, cookies and retry state stay intact.
    """
    try:
        ids = page_ids(request("/json/list", 2.0))
    except (OSError, ValueError, TypeError) as error:
        event = {
            "kind": "browser_tab_guard_unavailable",
            "error_type": type(error).__name__,
        }
        log(event)
        return {"status": "unavailable"}
    if len(ids) <= MAX_TABS:
        return {"status": "within_limit", "page_count": len(ids)}

    log({"kind": "browser_tab_overflow", "page_count": len(ids), "limit": MAX_TABS})
    deadline = clock() + CLOSE_BUDGET_SECONDS
    acknowledged = 0
    failures = 0
    for target_id in ids:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        try:
            response = request(
                "/json/close/" + quote(target_id, safe=""), min(2.0, remaining)
            )
            if response.strip() == b"Target is closing":
                acknowledged += 1
            else:
                failures += 1
        except (OSError, ValueError):
            failures += 1
    result = {
        "status": "restart_requested",
        "page_count": len(ids),
        "close_acknowledged": acknowledged,
        "close_failed": failures,
        "close_unattempted": len(ids) - acknowledged - failures,
    }
    # Emit before SIGTERM: the parent tears down this watchdog with its children.
    log({"kind": "browser_tab_overflow_restart", **result})
    terminate(parent_pid, signal.SIGTERM)
    return result
