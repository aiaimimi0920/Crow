from __future__ import annotations

import logging

from .captcha_challenge_binding import input_target_matches
from .captcha_navigation_flow import retain_navigation_connection

logger = logging.getLogger(__name__)


class CaptchaOrchestrationPreflightMixin:
    def _run_solve_preflight_and_fallbacks(self, finish):
        """Return (terminal_outcome, connected_for_first_attempt, local_mock_target)."""
        if self._stop_if_cancelled():
            return finish(False), False, False

        preflight = self._preflight_current_challenge()
        if self._stop_if_cancelled():
            return finish(False), False, False
        local_mock_target = self._is_local_mock_slider_target()
        if preflight.get("manual_required"):
            self.last_failure_reason = "manual_required"
            return finish(False), False, local_mock_target
        if preflight.get("already_authenticated"):
            return finish(True), False, local_mock_target
        if preflight.get("retryable_failure"):
            return finish(False), False, local_mock_target
        if preflight.get("connected"):
            if preflight.get("has_slider"):
                logger.info(
                    "[SOLVER] Active slider challenge detected; using CDP method first."
                )
            else:
                logger.info(
                    "[SOLVER] Challenge target is connected; waiting for its slider over CDP."
                )
            return None, True, local_mock_target

        if not local_mock_target and self._headed_playwright_enabled():
            if self._stop_if_cancelled():
                return finish(False), False, local_mock_target
            try:
                logger.info("[SOLVER] Attempting ddddocr AI识别...")
                if self._solve_with_ddddocr():
                    return finish(True), False, local_mock_target
            except Exception:
                logger.exception("[SOLVER] ddddocr error")

            if self._stop_if_cancelled():
                return finish(False), False, local_mock_target
            try:
                logger.info("[SOLVER] Attempting Playwright Stealth...")
                if self._solve_with_playwright_stealth():
                    return finish(True), False, local_mock_target
            except Exception:
                logger.exception("[SOLVER] Playwright Stealth error")
        else:
            if local_mock_target:
                logger.info(
                    "[SOLVER] Local mock target detected; skipping headed solver fallbacks."
                )
            else:
                logger.info(
                    "[SOLVER] Skipping headed Playwright solvers because no DISPLAY/WAYLAND_DISPLAY is available."
                )

        if local_mock_target:
            logger.info(
                "[SOLVER] Local mock target detected; using CDP solve path directly."
            )
        else:
            logger.info(
                "[SOLVER] Skipping userscript fallback on live targets; using CDP drag."
            )
        return None, False, local_mock_target

    def _recover_explicit_nc_failure(
        self,
        *,
        challenge_summary,
        local_mock_target,
        nc_retry_replays,
        nc_retry_replay_limit,
        attempt,
        finish,
    ):
        """Handle explicit NC failure after drag; returns (action, result, replays, attempt, connected)."""
        if nc_retry_replays < nc_retry_replay_limit:
            restored = self._reset_failed_nc_challenge()
            if not restored and not local_mock_target:
                if self._stop_if_cancelled():
                    return ("return", finish(False), nc_retry_replays, attempt, False)
                challenge_summary = self._refresh_challenge_summary(challenge_summary)
                challenge_summary = self._wait_for_loading_document(challenge_summary)
                if challenge_summary.get("probeFailed"):
                    self._preflight_retryable_failure()
                    return (
                        "return",
                        finish(False, preserve_target=True),
                        nc_retry_replays,
                        attempt,
                        False,
                    )
                if challenge_summary.get("authenticatedPage"):
                    self._preflight_already_authenticated()
                    return ("return", finish(True), nc_retry_replays, attempt, False)
                if challenge_summary.get(
                    "readyState"
                ) == "loading" and not challenge_summary.get("hasSlider"):
                    self._preflight_retryable_failure("challenge_loading")
                    return (
                        "return",
                        finish(False, preserve_target=True),
                        nc_retry_replays,
                        attempt,
                        False,
                    )
                if not challenge_summary.get("explicitFailure"):
                    restored = bool(
                        challenge_summary.get("hasSlider")
                        and input_target_matches(self, challenge_summary)
                    )
                    if not restored:
                        self._preflight_retryable_failure("slider_not_found")
                        return (
                            "return",
                            finish(False, preserve_target=True),
                            nc_retry_replays,
                            attempt,
                            False,
                        )
            if restored:
                nc_retry_replays += 1
                logger.info(
                    "[SOLVER] Challenge asked to retry; "
                    f"replaying drag without spending a main attempt "
                    f"({nc_retry_replays}/{nc_retry_replay_limit})."
                )
                if local_mock_target:
                    self._close_solver_ws()
                    connected = False
                else:
                    connected = retain_navigation_connection(self, local_mock_target)
                return (
                    "continue",
                    None,
                    nc_retry_replays,
                    max(attempt - 1, 0),
                    connected,
                )
        if not local_mock_target and challenge_summary.get("retryableFailure"):
            logger.warning(
                "[SOLVER] Retryable challenge attempts exhausted; "
                "returning to the bounded retry/cooldown policy."
            )
            self.last_failure_reason = "challenge_retry_exhausted"
            self._close_solver_ws()
            return ("return", finish(False), nc_retry_replays, attempt, False)
        logger.warning(
            "[SOLVER] Official challenge rejected the automated drag; manual verification required."
        )
        self.last_failure_reason = "manual_required"
        self._close_solver_ws()
        return ("return", finish(False), nc_retry_replays, attempt, False)


__all__ = ["CaptchaOrchestrationPreflightMixin"]
