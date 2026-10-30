"""Deployment-side ownership and admission for the existing bounded solver gate.

The caller holds the collection operation lock and binds the canonical container
and its installed gate sources. This module never navigates or edits solver state.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from pathlib import Path


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("Oversized maintenance request")
    return raw


def manual_window_admission(
    expected: dict[str, object],
    request: object,
    ack: object,
    heartbeat: object,
    state: object,
    status: object,
    solver_pids: list[int],
    *,
    child_busy: bool,
    now: float,
    minimum_remaining: float,
) -> dict[str, bool]:
    """A fresh complete-iteration ACK is distinct from a natural idle snapshot."""
    request = request if isinstance(request, dict) else {}
    ack = ack if isinstance(ack, dict) else {}
    heartbeat = heartbeat if isinstance(heartbeat, dict) else {}
    state = state if isinstance(state, dict) else {}
    status = status if isinstance(status, dict) else {}
    start, end = expected.get("requested_at"), expected.get("expires_at")
    token = expected.get("request_id")
    bounded = (
        isinstance(token, str)
        and re.fullmatch(r"[a-f0-9]{32}", token) is not None
        and all(_finite(v) for v in (start, end, now, minimum_remaining))
        and 0 < end - start <= 600
        and start <= now < end
        and 0 < minimum_remaining <= end - now
    )
    owner = bounded and request == expected
    pid = solver_pids[0] if len(solver_pids) == 1 else None
    live = type(pid) is int and pid > 0
    acknowledged = (
        owner
        and live
        and ack.get("request_id") == token
        and type(ack.get("expires_at")) in (int, float)
        and ack.get("expires_at") == end
        and ack.get("status") == "active"
        and type(ack.get("solver_pid")) is int
        and ack.get("solver_pid") == pid
    )
    stamp = heartbeat.get("updated_at_epoch")
    fresh = (
        live
        and heartbeat.get("phase") == "manual_window"
        and type(heartbeat.get("pid")) is int
        and heartbeat.get("pid") == pid
        and _finite(stamp)
        and bounded
        and start <= stamp <= now
        and now - stamp < 10
    )
    no_pending = (
        all(
            state.get(k) is False
            for k in (
                "auth_complete_pending",
                "collection_resume_pending",
                "terminal_manual_pending",
            )
        )
        and state.get("slider_attempt_started_at") is None
    )
    control_quiet = (
        bool(status)
        and not status.get("error")
        and status.get("running") is False
        and status.get("global_manual_pause_active") is False
        and all(
            status.get(k, False) is False
            for k in ("queued", "nas_solver_active", "operator_paused")
        )
    )
    proof = {
        "request_owned_and_bounded": bool(owner),
        "acknowledged_by_live_solver": bool(acknowledged),
        "fresh_manual_window_heartbeat": bool(fresh),
        "no_input_child": child_busy is False,
        "no_pending_control": no_pending,
        "control_quiet": bool(control_quiet),
    }
    return {"eligible": all(proof.values()), **proof}


class CutoverWindow:
    """Publish once, never renew, and expire only our exact request on exit.

    Do not overwrite malformed, future or active requests. Expired prior bytes
    remain available to the caller for its private deployment backup.
    """

    def __init__(self, path: Path):
        self.path = path
        self.request: dict[str, object] = {}
        self.raw: bytes | None = None
        self.previous: bytes | None = None
        self.released = False

    def _publish(self, raw: bytes, expected: bytes | None) -> None:
        temporary = self.path.with_name(
            self.path.name + "." + str(self.request["request_id"])
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if hasattr(os, "chown"):
            owner = self.path.parent.stat()
            os.chown(temporary, owner.st_uid, owner.st_gid)
        if self.path.is_symlink():
            raise RuntimeError("Maintenance request is a symlink")
        current = _read(self.path) if self.path.exists() else None
        if current != expected:
            raise RuntimeError("Maintenance request owner changed")
        os.replace(temporary, self.path)

    def begin(self, now: float | None = None) -> dict[str, object]:
        if self.raw is not None or self.path.is_symlink():
            raise RuntimeError("Maintenance window cannot be reacquired")
        current = time.time() if now is None else now
        if not _finite(current) or current <= 0:
            raise ValueError("Invalid maintenance start")
        previous = _read(self.path) if self.path.exists() else None
        if previous is not None:
            value = json.loads(previous)
            end = value.get("expires_at") if isinstance(value, dict) else None
            if not _finite(end) or end > current:
                raise RuntimeError("Another maintenance request may be active")
        self.previous = previous
        self.request = {
            "request_id": secrets.token_hex(16),
            "requested_at": current,
            "expires_at": current + 600,
        }
        raw = (json.dumps(self.request) + "\n").encode("utf-8")
        self._publish(raw, previous)
        self.raw = raw
        return dict(self.request)

    def release(self, now: float | None = None) -> bool:
        if self.raw is None or self.released or self.path.is_symlink():
            return False
        if not self.path.exists() or _read(self.path) != self.raw:
            return False
        current = time.time() if now is None else now
        if not _finite(current):
            raise ValueError("Invalid maintenance end")
        value = {
            **self.request,
            "expires_at": min(current, float(self.request["expires_at"])),
        }
        self._publish((json.dumps(value) + "\n").encode("utf-8"), self.raw)
        self.released = True
        return True
