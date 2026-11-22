"""Emergency tab recovery for the private browser-solver container only."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv

# Never use the configurable worker/PC1 CDP endpoint for destructive recovery.
ENDPOINT = "http://127.0.0.1:9223"
# Must exceed normal steady state (initial + 2 reference + seed + detail + attached captures),
# aligning with DEFAULT_CDP_PAGE_TARGET_LIMIT (12) so cooperative capacity checks run first.
MAX_TABS = 12
CLOSE_BUDGET_SECONDS = 10.0
POLL_SECONDS = 5.0


def configured_max_tabs() -> int:
    raw = str(
        project_getenv("CROW_BROWSER_TAB_GUARD_MAX_TABS")
        or project_getenv("CROW_CDP_MAX_PAGE_TARGETS")
        or MAX_TABS
    ).strip()
    try:
        parsed = int(raw)
    except ValueError:
        return MAX_TABS
    return max(4, parsed) if parsed > 0 else MAX_TABS


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
    limit = configured_max_tabs()
    if len(ids) <= limit:
        return {"status": "within_limit", "page_count": len(ids)}

    log({"kind": "browser_tab_overflow", "page_count": len(ids), "limit": limit})
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
