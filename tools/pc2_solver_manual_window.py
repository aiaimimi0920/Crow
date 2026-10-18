"""Bounded operator window, acknowledged only between complete solver iterations."""

from __future__ import annotations

import json
import math
import os
import re
import time

from tools.pc2_solver_state_store import FALLBACK_STATE_PATH
from tools.pc2_solver_transport import log_event, write_solver_heartbeat

REQUEST_PATH = FALLBACK_STATE_PATH.with_name("solver-manual-window.json")
ACK_PATH = FALLBACK_STATE_PATH.with_name("solver-manual-window-ack.json")
MAX_WINDOW_SECONDS = 600


def active_manual_window(now: float | None = None) -> dict[str, object] | None:
    """No URL, account, browser operation or NAS manual-auth side effect."""
    current = time.time() if now is None else now
    try:
        with REQUEST_PATH.open(encoding="utf-8") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict):
            return None
        request_id = value.get("request_id")
        start, end = value.get("requested_at"), value.get("expires_at")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            return None
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)):
            return None
        if not start <= current < end or not 0 < end - start <= MAX_WINDOW_SECONDS:
            return None
        return {"request_id": request_id, "expires_at": end}
    except (OSError, ValueError, UnicodeError):
        return None


def hold_manual_window(poll_seconds: float) -> bool:
    """Caller must have joined its input child before ACK; never interrupt a press."""
    window = active_manual_window()
    if window is None:
        return False
    write_solver_heartbeat("manual_window")
    ack = {**window, "status": "active", "solver_pid": os.getpid()}
    try:
        previous = json.loads(ACK_PATH.read_text(encoding="utf-8")) if ACK_PATH.exists() else None
        if previous != ack:
            staged = ACK_PATH.with_suffix(".tmp")
            with staged.open("w", encoding="utf-8") as stream:
                os.chmod(staged, 0o600)
                json.dump(ack, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, ACK_PATH)
            log_event({"kind": "manual_window_acquired", **ack})
    except (OSError, ValueError, UnicodeError):
        # Stay quiet even when the operator cannot obtain an ACK.
        log_event({"kind": "manual_window_ack_unavailable"})
    remaining = max(0.0, float(window["expires_at"]) - time.time())
    time.sleep(min(remaining, max(0.1, min(float(poll_seconds), 2.0))))
    return True
