"""Bounded idle motion, serialized with the PC2 solver loop rather than a thread."""

from __future__ import annotations

import logging
import math
import os
import random
import time
from urllib.parse import urlsplit

from src.project_environment import getenv

logger = logging.getLogger(__name__)


def idle_status_safe(status, *, scoped=False):
    if not isinstance(status, dict) or "error" in status:
        return False
    # The API owns one aggregate running flag; scope snapshots omit that field.
    if (
        status.get("running", False if scoped else None) is not False
        or status.get("paused") is not False
    ):
        return False
    if any(
        status.get(k)
        for k in (
            "manual_required",
            "force_reset_required",
            "manual_only",
            "node_solver_blocked",
        )
    ):
        return False
    for key in ("scopes", "collection_scopes"):
        scopes = status.get(key, {})
        if not isinstance(scopes, dict) or not all(
            idle_status_safe(s, scoped=True) for s in scopes.values()
        ):
            return False
    return True


def idle_mouse_enabled():
    return (
        os.name != "nt"
        and getenv("CROW_SOLVER_OS_MOUSE", "").lower() in {"1", "true", "yes", "on"}
        and getenv("CROW_SOLVER_IDLE_MOUSE", "1").lower() in {"1", "true", "yes", "on"}
        and getenv("CROW_BROWSER_DISPLAY_MODE", "") == "host"
        and bool(os.environ.get("DISPLAY"))
        and os.environ["DISPLAY"] == getenv("CROW_BROWSER_HOST_DISPLAY", "")
    )


class IdlePointer:
    def __init__(
        self, cdp_endpoint, *, backend_factory=None, clock=None, sleep=None, rng=None
    ):
        self.endpoint = cdp_endpoint
        self.factory = backend_factory
        self.clock, self.sleep, self.rng = (
            clock or time.monotonic,
            sleep or time.sleep,
            rng or random.Random(),
        )
        self.expected = None
        self.last_move = None
        self.quiet_since = self.clock()
        self.next_at = self.quiet_since + 15

    def _defer(self):
        self.expected = self.last_move = None
        self.quiet_since = self.clock()
        self.next_at = self.quiet_since + 15

    def _available(self, state):
        if not state or state.get("buttons"):
            return False
        x, y = state["position"]
        left, top, right, bottom = state["bounds"]
        if not left < x < right or not top < y < bottom:
            return False
        if self.expected is not None and math.dist(self.expected, (x, y)) > 1.5:
            return False
        now = self.clock()
        if self.last_move is None:
            return state["idle_seconds"] >= 15
        # XScreenSaver notices keyboard input as well as a moved physical mouse.
        return state["idle_seconds"] >= max(0, now - self.last_move - 0.15)

    def tick(self, status, read_status):
        if not idle_mouse_enabled() or not idle_status_safe(status):
            self._defer()
            return None
        if self.clock() < self.next_at:
            return None
        endpoint = urlsplit(self.endpoint)
        if endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return None
        backend = None
        try:
            if self.factory is None:
                from tools.pc2_solver_idle_x11 import X11IdlePointer

                factory = X11IdlePointer
            else:
                factory = self.factory
            backend = factory(endpoint.port or 9223)
            state = backend.snapshot()
            if not self._available(state) or not idle_status_safe(read_status()):
                self._defer()
                return None
            start_x, start_y = state["position"]
            self.expected = (start_x, start_y)
            left, top, right, bottom = state["bounds"]
            end_x = min(max(start_x + self.rng.uniform(-140, 140), left + 2), right - 2)
            end_y = min(max(start_y + self.rng.uniform(-90, 90), top + 2), bottom - 2)
            duration, steps = self.rng.uniform(0.35, 0.65), self.rng.randint(8, 14)
            bow = self.rng.uniform(-12, 12)
            started, moved = self.clock(), 0
            for step in range(1, steps + 1):
                current = backend.snapshot()
                if (
                    not self._available(current)
                    or current["window"] != state["window"]
                    or self.clock() - started > 1.0
                ):
                    self._defer()
                    return {"kind": "idle_pointer_interrupted", "points": moved}
                if step == steps // 2 and not idle_status_safe(read_status()):
                    self._defer()
                    return {"kind": "idle_pointer_interrupted", "points": moved}
                t = step / steps
                eased = t * t * (3 - 2 * t)
                x = start_x + (end_x - start_x) * eased
                y = min(
                    max(
                        start_y
                        + (end_y - start_y) * eased
                        + math.sin(t * math.pi) * bow,
                        top + 2,
                    ),
                    bottom - 2,
                )
                backend.move(x, y)
                self.expected, self.last_move = (round(x), round(y)), self.clock()
                moved += 1
                self.sleep(duration / steps)
            self.next_at = self.clock() + self.rng.uniform(5, 18)
            return {
                "kind": "idle_pointer_move",
                "points": moved,
                "duration": round(self.clock() - started, 3),
                "next_in": round(self.next_at - self.clock(), 2),
            }
        except Exception as error:  # noqa: BLE001 -- optional motion must never stop collection
            self._defer()
            return {
                "kind": "idle_pointer_unavailable",
                "error_type": type(error).__name__,
            }
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    self._defer()
                    logger.debug("Idle pointer cleanup unavailable", exc_info=True)
