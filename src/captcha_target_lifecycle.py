"""HTTP page lifecycle and cleanup of targets owned by one solver."""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from .captcha_budget import SolveStopped

logger = logging.getLogger(__name__)


class CaptchaTargetLifecycleMixin:
    def _close_cdp_target(self, target_id):
        target_id = str(target_id or "").strip()
        if not target_id:
            return False
        timeout = self._bounded_io_timeout(5)
        try:
            response = requests.get(
                f"{self.cdp_endpoint}/json/close/{quote(target_id, safe='')}",
                timeout=timeout,
            )
            status = getattr(response, "status_code", 200)
            if not 200 <= status < 300:
                logger.warning(
                    "[SOLVER] Failed to close CDP target %s: HTTP %s", target_id, status
                )
                return False
            return True
        except (requests.RequestException, OSError, ValueError) as error:
            logger.warning(
                "[SOLVER] Failed to close CDP target %s: %s",
                target_id,
                type(error).__name__,
            )
            return False

    def _open_keepalive_tab(self):
        timeout = self._bounded_io_timeout(5)
        try:
            response = requests.put(
                f"{self.cdp_endpoint}/json/new?about:blank", timeout=timeout
            )
            status = getattr(response, "status_code", 200)
            if not 200 <= status < 300:
                logger.warning("[SOLVER] Failed to open keepalive tab: HTTP %s", status)
                return None
            payload = response.json()
            if isinstance(payload, dict) and payload.get("type", "page") == "page":
                target_id = payload.get("id")
                if isinstance(target_id, str):
                    return target_id.strip() or None
        except (requests.RequestException, OSError, ValueError) as error:
            logger.warning(
                "[SOLVER] Failed to open keepalive tab before page compaction: %s",
                type(error).__name__,
            )
        return None

    def _close_owned_target_tabs(self):
        budget = getattr(self, "_solve_budget", None)
        if budget is not None and budget.stopped(self._cancel_requested):
            # Preserve manual recovery pages instead of extending expired runs.
            return 0
        owned_target_ids = [
            target_id for target_id in self._opened_target_ids if target_id
        ]
        if not owned_target_ids:
            return 0
        self._close_solver_ws()

        closed = 0
        for target_id in owned_target_ids:
            try:
                did_close = self._close_cdp_target(target_id)
            except SolveStopped:
                # An earlier close may finish after cancellation; retain the rest.
                break
            if did_close:
                closed += 1
                self._opened_target_ids.discard(target_id)
                if self.target_id == target_id:
                    self._reset_current_target()
        return closed
