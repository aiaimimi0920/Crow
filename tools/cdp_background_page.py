"""Create collector-owned background pages without touching the foreground target."""

import json
import logging
import time

import websocket


class BackgroundPageCapacityError(RuntimeError):
    """The live browser is reachable but cannot safely accept another page."""


def open_background_page(cdp_endpoint: str, url: str) -> dict:
    from tools import taobao_login_health as health

    targets = health.list_cdp_targets(cdp_endpoint)
    count = sum(target.get("type") == "page" for target in targets)
    if count >= health.cdp_page_target_limit():
        # Never compact another scope's live challenge to make room for a read.
        raise BackgroundPageCapacityError("Background collector page capacity reached")
    version = health.read_cdp_json(cdp_endpoint, "/json/version")
    browser_ws = (
        version.get("webSocketDebuggerUrl") if isinstance(version, dict) else None
    )
    if not browser_ws:
        raise RuntimeError("Browser CDP endpoint unavailable for background page")
    connection = websocket.create_connection(
        browser_ws, suppress_origin=True, timeout=3
    )
    target_id = None
    try:
        # Send once: a lost response must not create duplicate pages on retry.
        connection.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Target.createTarget",
                    "params": {"url": url, "background": True},
                }
            )
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            connection.settimeout(max(0.01, deadline - time.monotonic()))
            reply = json.loads(connection.recv())
            if reply.get("id") != 1:
                continue
            if reply.get("error"):
                raise RuntimeError("Background page creation rejected")
            target_id = (reply.get("result") or {}).get("targetId")
            break
    finally:
        connection.close()
    if not isinstance(target_id, str) or not target_id.strip():
        raise RuntimeError("Background page creation was not acknowledged")
    try:
        for attempt in range(3):
            for target in health.list_cdp_targets(cdp_endpoint):
                if target.get("id") == target_id and target.get("webSocketDebuggerUrl"):
                    return dict(target)
            if attempt < 2:
                time.sleep(0.1)
        raise RuntimeError("Created background page is unavailable")
    except Exception:
        # The returned exact ID is the only target owned by this operation.
        try:
            health.close_cdp_target(cdp_endpoint, target_id)
        except (OSError, RuntimeError, ValueError):
            logging.getLogger(__name__).warning("Owned background page cleanup failed")
        raise
