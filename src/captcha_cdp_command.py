"""Single-send CDP commands with shared deadlines and cooperative stop checks."""

import json
import logging
import time

import websocket

from .captcha_budget import SolveStopped
from .captcha_navigation_flow import (
    invalidate_navigation_trace,
    observe_navigation_event,
)

logger = logging.getLogger(__name__)


def cdp_connection_is_closed(solver):
    """Unknown state is not closure; a replacement socket starts independently."""
    sock = getattr(solver, "ws", None)
    return sock is not None and (
        getattr(sock, "connected", None) is False
        or sock is getattr(solver, "_closed_cdp_socket", None)
    )


class CaptchaCDPCommandMixin:
    def _send_cdp(self, method, params=None, *, deadline=None):
        if not self.ws:
            return None
        if self._stop_if_cancelled():
            return None
        if cdp_connection_is_closed(self):
            return None

        sock = self.ws
        budgeted = getattr(self, "_solve_budget", None) is not None
        navigation_wait = budgeted and method == "Page.navigate"
        timeout_seconds = (
            15 if navigation_wait else (12 if "captureScreenshot" in method else 5)
        )
        receive_limit = 5 if navigation_wait else timeout_seconds
        command_deadline = time.monotonic() + timeout_seconds
        deadline = (
            command_deadline if deadline is None else min(command_deadline, deadline)
        )
        receive_timeouts = 0
        unknown_timeout = object()
        previous_timeout = unknown_timeout
        settimeout = getattr(sock, "settimeout", None)

        def prepare_io(limit):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise websocket.WebSocketTimeoutException("CDP command deadline")
            timeout = self._bounded_io_timeout(min(limit, remaining))
            if not budgeted and type(previous_timeout) in (int, float):
                timeout = min(timeout, previous_timeout)
            if callable(settimeout):
                settimeout(timeout)

        msg = {"id": self.message_id, "method": method, "params": params or {}}

        try:
            gettimeout = getattr(sock, "gettimeout", None)
            if callable(gettimeout):
                previous_timeout = gettimeout()
            payload = json.dumps(msg)
            prepare_io(5)
            # A failed send may already have written the request to the peer.
            self.message_id += 1
            sock.send(payload)
            while True:
                if self._stop_if_cancelled():
                    return None
                try:
                    prepare_io(receive_limit)
                    res = sock.recv()
                    if self._stop_if_cancelled():
                        return None
                    if time.monotonic() >= deadline:
                        raise websocket.WebSocketTimeoutException("Late CDP response")
                    res_json = json.loads(res)
                    if "id" not in res_json:
                        observe_navigation_event(self, sock, res_json)
                    if res_json.get("id") == msg["id"]:
                        if "error" in res_json:
                            invalidate_navigation_trace(self, sock)
                            logger.error(
                                "[SOLVER] CDP Error method=%s error=%s",
                                method,
                                res_json["error"],
                            )
                            return None
                        return res_json.get("result")
                except websocket.WebSocketTimeoutException:
                    if self._stop_if_cancelled():
                        return None
                    receive_timeouts += 1
                    # Keep waiting for this single navigation request, never resend.
                    # Five-second slices preserve cooperative cancellation checks.
                    if (
                        navigation_wait
                        and receive_timeouts < 3
                        and time.monotonic() < deadline
                    ):
                        continue
                    logger.warning("[SOLVER] Timeout waiting for %s", method)
                    invalidate_navigation_trace(self, sock)
                    return None
                except SolveStopped:
                    self._stop_if_cancelled()
                    return None
                except Exception as e:
                    if isinstance(e, websocket.WebSocketConnectionClosedException):
                        self._closed_cdp_socket = sock
                    invalidate_navigation_trace(self, sock)
                    logger.warning(
                        "[SOLVER] Error receiving response method=%s: %s", method, e
                    )
                    return None
        except SolveStopped:
            self._stop_if_cancelled()
            return None
        except Exception as e:
            if isinstance(e, websocket.WebSocketConnectionClosedException):
                self._closed_cdp_socket = sock
            invalidate_navigation_trace(self, sock)
            logger.error("[SOLVER] CDP Send Error method=%s: %s", method, e)
            return None
        finally:
            if (
                self.ws is sock
                and previous_timeout is not unknown_timeout
                and callable(settimeout)
            ):
                try:
                    settimeout(previous_timeout)
                except (OSError, ValueError, websocket.WebSocketException) as error:
                    logger.warning(
                        "[SOLVER] Socket timeout restore failed: %s",
                        type(error).__name__,
                    )
