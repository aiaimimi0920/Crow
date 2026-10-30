from __future__ import annotations

import logging
import random

from .captcha_deferral import TargetNavigationUnconfirmed, preserve_unconfirmed_target
from .captcha_nc_retry import NCRetryDeferred
from .captcha_slider_geometry import SliderEndpointReached
from .captcha_target_diagnostics import log_missing_slider, log_target_binding
from .captcha_verification import ready_target_matches

logger = logging.getLogger(__name__)


class CaptchaOrchestrationMixin:
    def solve(
        self, max_attempts=50, nc_retry_replay_limit=None,
        slider_find_max_retries=None, drag_profile_offset=0, *,
        deadline=None, cancel_event=None,
    ):
        from .captcha_budget import SolveBudget, SolveStopped
        budget = SolveBudget(
            deadline=deadline if deadline is not None else getattr(self, "solve_deadline", None),
            cancel_event=cancel_event,
        )
        try:
            return self._solve_attempts(
                max_attempts, nc_retry_replay_limit, slider_find_max_retries, drag_profile_offset,
                _budget=budget,
            )
        except SolveStopped:
            return False
        except (NCRetryDeferred, TargetNavigationUnconfirmed):
            # Deferred state and socket cleanup already finished under the lock.
            return False

    def _solve_attempts(
        self,
        max_attempts=50,
        nc_retry_replay_limit=None,
        slider_find_max_retries=None,
        drag_profile_offset=0,
        *, _budget,
    ):
        """Main solve method - tries all methods in priority order."""
        with _budget.scope(self), preserve_unconfirmed_target(self, _budget):
            self.last_failure_reason = None

            def finish(result, *, preserve_target=False):
                if self._stop_if_cancelled():
                    result = False
                if not result and self.last_failure_reason == "manual_required":
                    if self.ws:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
                    self._opened_target_ids.clear()
                    return result
                if not preserve_target:
                    self._close_owned_target_tabs()
                if self._stop_if_cancelled():
                    return False
                return result

            connected_for_first_attempt = False
            if self._stop_if_cancelled():
                return finish(False)

            preflight = self._preflight_current_challenge()
            if self._stop_if_cancelled():
                return finish(False)
            local_mock_target = self._is_local_mock_slider_target()
            if preflight.get("manual_required"):
                self.last_failure_reason = "manual_required"
                return finish(False)
            if preflight.get("already_authenticated"):
                return finish(True)
            if preflight.get("retryable_failure"):
                return finish(False)
            if preflight.get("connected"):
                connected_for_first_attempt = True
                if preflight.get("has_slider"):
                    logger.info("[SOLVER] Active slider challenge detected; using CDP method first.")
                else:
                    logger.info("[SOLVER] Challenge target is connected; waiting for its slider over CDP.")
            else:
                if not local_mock_target and self._headed_playwright_enabled():
                    if self._stop_if_cancelled():
                        return finish(False)
                    # Try ddddocr AI FIRST
                    try:
                        logger.info("[SOLVER] Attempting ddddocr AI识别...")
                        if self._solve_with_ddddocr():
                            return finish(True)
                    except Exception as e:
                        logger.exception("[SOLVER] ddddocr error")

                    # Try Playwright Stealth
                    if self._stop_if_cancelled():
                        return finish(False)
                    try:
                        logger.info("[SOLVER] Attempting Playwright Stealth...")
                        if self._solve_with_playwright_stealth():
                            return finish(True)
                    except Exception as e:
                        logger.exception("[SOLVER] Playwright Stealth error")
                else:
                    if local_mock_target:
                        logger.info("[SOLVER] Local mock target detected; skipping headed solver fallbacks.")
                    else:
                        logger.info("[SOLVER] Skipping headed Playwright solvers because no DISPLAY/WAYLAND_DISPLAY is available.")

                if local_mock_target:
                    logger.info("[SOLVER] Local mock target detected; using CDP solve path directly.")
                else:
                    # Userscript DOM events are isTrusted=false and burn the NC challenge.
                    logger.info("[SOLVER] Skipping userscript fallback on live targets; using CDP drag.")

            # CDP mouse drag (buttons bitmask + slow human path)
            logger.info("[SOLVER] Using CDP method...")
            attempt = 0
            nc_retry_replays = 0
            if nc_retry_replay_limit is None:
                nc_retry_replay_limit = self._nc_retry_replay_limit()
            else:
                nc_retry_replay_limit = max(0, int(nc_retry_replay_limit))
            try:
                drag_profile_offset = int(drag_profile_offset or 0) % max(len(self._os_drag_profiles()), 1)
            except (TypeError, ValueError):
                drag_profile_offset = 0

            while attempt < max_attempts:
                attempt += 1
                if self._stop_if_cancelled():
                    return finish(False)
                logger.info("[SOLVER] Attempt %s/%s", attempt, max_attempts)

                # 每一轮都重新连接目标页签，避免 ws 失效后卡死
                if connected_for_first_attempt:
                    connected_for_first_attempt = False
                elif not self.connect_tab():
                    if self.last_failure_reason == "manual_required":
                        return finish(False)
                    if attempt < max_attempts:
                        logger.warning("[SOLVER] connect_tab failed; retrying in 5 seconds")
                        self._wait_interruptibly(5)
                    else:
                        logger.warning("[SOLVER] connect_tab failed on the final attempt.")
                    continue

                logger.info("[SOLVER] Connected to browser. Starting solve loop...")
                self._bring_to_front()

                try:
                    # Step 1: Find Slider
                    if slider_find_max_retries is None:
                        slider_info = self._find_slider()
                    else:
                        slider_info = self._find_slider(
                            max_retries=max(1, int(slider_find_max_retries)),
                            retry_delay=0,
                        )
                    if not slider_info:
                        challenge_summary = self._refresh_challenge_summary({})
                        if not local_mock_target:
                            slider_info, challenge_summary = (
                                self._confirm_missing_slider(challenge_summary)
                            )
                    if not slider_info:
                        log_missing_slider(logger, challenge_summary, self.target_url)
                        if challenge_summary.get("probeFailed"):
                            self._preflight_retryable_failure()
                            return finish(False)
                        if challenge_summary.get("readyState") == "loading" and not challenge_summary.get("hasSlider"):
                            self._preflight_retryable_failure("challenge_loading")
                            return finish(False)
                        if challenge_summary.get("authenticatedPage"):
                            logger.info("[SOLVER] Auction page became accessible; captcha is already resolved.")
                            self.last_failure_reason = None
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(True)
                        if not local_mock_target and challenge_summary.get("hasSlider"):
                            self._preflight_retryable_failure("slider_not_found")
                            return finish(False, preserve_target=True)
                        if challenge_summary.get("hardBlock") and not challenge_summary.get("hasSlider"):
                            if (
                                not local_mock_target
                                and nc_retry_replays >= nc_retry_replay_limit
                            ):
                                self.last_failure_reason = "challenge_retry_exhausted"
                                self._close_solver_ws()
                                return finish(False)
                            logger.info("[SOLVER] Hard block without slider; trying NC retry-click to restore slider.")
                            restored = self._reset_failed_nc_challenge()
                            if self._stop_if_cancelled():
                                return finish(False)
                            if restored and local_mock_target:
                                logger.info("[SOLVER] NC slider restored after retry-click; continuing loop...")
                                if self.ws:
                                    try:
                                        self.ws.close()
                                    except Exception:
                                        pass
                                    self.ws = None
                                continue
                            challenge_summary = self._refresh_challenge_summary(challenge_summary)
                            if not local_mock_target:
                                challenge_summary = self._wait_for_loading_document(
                                    challenge_summary
                                )
                            if challenge_summary.get("probeFailed"):
                                self._preflight_retryable_failure()
                                return finish(
                                    False, preserve_target=not local_mock_target
                                )
                            if challenge_summary.get("readyState") == "loading" and not challenge_summary.get("hasSlider"):
                                self._preflight_retryable_failure("challenge_loading")
                                return finish(
                                    False, preserve_target=not local_mock_target
                                )
                            if challenge_summary.get("authenticatedPage"):
                                self._preflight_already_authenticated()
                                return finish(True)
                            if challenge_summary.get("hasSlider"):
                                if not local_mock_target:
                                    if not ready_target_matches(
                                        challenge_summary, self.target_url
                                    ):
                                        self._preflight_retryable_failure("slider_not_found")
                                        return finish(False, preserve_target=True)
                                    # Recovery spent no drag attempt. Reuse it only
                                    # within the existing bounded NC replay budget.
                                    nc_retry_replays += 1
                                    attempt = max(attempt - 1, 0)
                                self._close_solver_ws()
                                continue
                            if challenge_summary.get("hardBlock"):
                                logger.warning("[SOLVER] Unsupported hard block detected; manual verification required.")
                                self._preflight_manual_required()
                                return finish(False)
                        if challenge_summary.get("loginRequired"):
                            logger.warning("[SOLVER] Login page detected; manual login is required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        logger.info("[SOLVER] Slider not found after retries; reloading and continuing")
                        self._reload_page()
                        self._wait_interruptibly(0.2 if local_mock_target else random.uniform(1, 2))
                        self._close_solver_ws()
                        continue

                    start_x = slider_info["x"] + (slider_info["width"] / 2)
                    start_y = slider_info["y"] + (slider_info["height"] / 2)

                    # Sanity check
                    if start_x < 10 or start_y < 10:
                        logger.warning("[SOLVER] Invalid coordinates: (%s, %s); reloading and continuing", start_x, start_y)
                        self._reload_page()
                        self._wait_interruptibly(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                        continue

                    # Human hesitation before action (NC needs time to bind listeners)
                    self._wait_interruptibly(0.05 if local_mock_target else random.uniform(1.5, 2.4))

                    logger.info(
                        "[SOLVER] Slider found at (%.0f, %.0f) selector=%s context=%s",
                        start_x,
                        start_y,
                        slider_info.get("selector"),
                        slider_info.get("context"),
                    )

                    # Step 2: Get Track Width (dynamic)
                    track_width, track_rect = self._slider_track_geometry(slider_info)
                    slider_info["track_width"] = track_width

                    # Calculate actual drag distance
                    # NC captcha needs slider to reach nearly the end (95-100%)
                    if local_mock_target:
                        distance = max(1, track_width - slider_info["width"] - 8)
                    else:
                        # The challenge can leave the handle part-way across the
                        # track after a rejected attempt. Calculate the remaining
                        # distance from the live rectangles instead of assuming the
                        # handle is always at the left edge.
                        distance = self._remaining_drag_distance(slider_info, track_rect, track_width)
                        if distance == 0:
                            raise SliderEndpointReached
                    logger.info(
                        "[SOLVER] Drag distance: %.0fpx (track: %.0fpx, slider: %.0fpx)",
                        distance,
                        track_width,
                        slider_info["width"],
                    )

                    # Step 3: Execute drag
                    self._bring_to_front()
                    self._wait_interruptibly(0.05 if local_mock_target else random.uniform(0.2, 0.5))
                    if local_mock_target:
                        drag_result = self._do_drag_local_mock(start_x, start_y, distance)
                    elif self._os_mouse_enabled():
                        logger.info("[SOLVER] Using OS-level mouse drag for live NC challenge.")
                        drag_profile_variant = (
                            drag_profile_offset
                            + min(nc_retry_replays, len(self._os_drag_profiles()) - 1)
                        ) % len(self._os_drag_profiles())
                        drag_result = self._do_drag_os(
                            start_x,
                            start_y,
                            distance,
                            slider_info=slider_info,
                            profile_variant_index=drag_profile_variant,
                        )
                        if drag_result is None:
                            os_drag_failure = str(self.last_failure_reason or "")
                            unsafe_os_failure = (
                                os_drag_failure == "window_focus_failed"
                                or os_drag_failure == "mouse_drag_exception"
                                or os_drag_failure.startswith("screen_mapping_")
                                or os_drag_failure in {"os_cursor_position_unverified", "os_button_state_unverified"}
                            )
                            if unsafe_os_failure:
                                # OS input may already have reached the page; its old
                                # coordinates cannot authorize a second CDP gesture.
                                logger.warning(
                                    "[SOLVER] OS drag input or target was not verified; "
                                    "skipping unsafe CDP drag fallback."
                                )
                                self._preflight_retryable_failure(
                                    "execution_unavailable"
                                )
                                return finish(False, preserve_target=True)
                            else:
                                logger.info("[SOLVER] OS mouse unavailable; falling back to CDP drag.")
                                drag_result = self._do_drag(start_x, start_y, distance)
                    else:
                        drag_result = self._do_drag(start_x, start_y, distance)
                    if drag_result is None:
                        if self.last_failure_reason in {"manual_required", "cancelled", "deadline_exceeded"}:
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        if (
                            not local_mock_target
                            and self.last_failure_reason == "cdp_unavailable"
                        ):
                            # Input may have reached the page despite a missing ACK.
                            logger.warning(
                                "[SOLVER] CDP drag input was not confirmed; "
                                "preserving page for bounded retry."
                            )
                            self._preflight_retryable_failure("cdp_unavailable")
                            return finish(False, preserve_target=True)
                        logger.warning("[SOLVER] Drag did not complete; reloading and continuing")
                        self._reload_page()
                        self._bring_to_front()
                        self._wait_interruptibly(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        continue
                    if self.last_failure_reason == "manual_required":
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        return finish(False)
                    logger.info("[SOLVER] Drag complete. Verifying...")

                    # Step 4: Verify Success
                    if local_mock_target:
                        self._wait_interruptibly(0.15)

                    if self._wait_for_verification_success():
                        logger.info("[SOLVER] Verified: Captcha solved")
                        self.last_failure_reason = None

                        # Phase 3.1: We DO NOT close the page anymore.
                        # The userscript handles redirecting it back to standby.
                        logger.info("[SOLVER] Leaving worker tab alive for userscript redirect.")

                        self._close_solver_ws()
                        return finish(True)

                    if self.last_failure_reason == "manual_required":
                        return finish(False)

                    logger.warning("[SOLVER] Verification unconfirmed; inspecting challenge state")
                    challenge_summary = self._page_challenge_summary()
                    loading_after_drag = (
                        not local_mock_target
                        and challenge_summary.get("readyState") == "loading"
                        and not challenge_summary.get("hasSlider")
                    )
                    if loading_after_drag:
                        logger.info(
                            "[SOLVER] Document loading after drag; waiting within solve budget."
                        )
                        challenge_summary = self._wait_for_loading_document(challenge_summary)
                    from .captcha_navigation_receipt import navigation_binding_fields

                    log_target_binding(
                        logger,
                        "post_drag",
                        challenge_summary,
                        self.target_url,
                        navigation=navigation_binding_fields(self, challenge_summary),
                    )
                    if challenge_summary.get("probeFailed"):
                        self._preflight_retryable_failure()
                        return finish(False, preserve_target=not local_mock_target)
                    if loading_after_drag:
                        if challenge_summary.get(
                            "readyState"
                        ) == "loading" and not challenge_summary.get("hasSlider"):
                            self._preflight_retryable_failure("challenge_loading")
                            return finish(False, preserve_target=True)
                        if challenge_summary.get("hasSlider") and not ready_target_matches(
                            challenge_summary, self.target_url
                        ):
                            self._preflight_retryable_failure("slider_not_found")
                            return finish(False, preserve_target=True)
                    logger.info(
                        "[SOLVER] Challenge diagnostic: "
                        f"{self._challenge_failure_diagnostic(challenge_summary)}"
                    )
                    if challenge_summary.get("authenticatedPage"):
                        logger.info("[SOLVER] Auction page is accessible after drag; treating as solved.")
                        self.last_failure_reason = None
                        self._close_solver_ws()
                        return finish(True)
                    if (
                        not local_mock_target
                        and challenge_summary.get("hasSlider")
                        and not challenge_summary.get("explicitFailure")
                        and nc_retry_replays < nc_retry_replay_limit
                    ):
                        # Preserve the live handle position. The next pass uses
                        # the current rectangles to drag only the residual
                        # distance, matching the path that has solved real NC
                        # challenges. Explicit failures are reset below.
                        nc_retry_replays += 1
                        logger.info(
                            "[SOLVER] Slider is still present without an explicit failure; "
                            f"keeping its live position and switching to the next drag profile "
                            "without spending a main attempt "
                            f"({nc_retry_replays}/{nc_retry_replay_limit})."
                        )
                        self._close_solver_ws()
                        attempt = max(attempt - 1, 0)
                        self._wait_interruptibly(random.uniform(0.4, 0.9))
                        continue
                    if challenge_summary.get("explicitFailure"):
                        if nc_retry_replays < nc_retry_replay_limit:
                            restored = self._reset_failed_nc_challenge()
                            if not restored and not local_mock_target:
                                # Retry input may replace the document after its short poll.
                                # Never classify that new document using the pre-click failure.
                                if self._stop_if_cancelled():
                                    return finish(False)
                                challenge_summary = self._refresh_challenge_summary(challenge_summary)
                                challenge_summary = self._wait_for_loading_document(challenge_summary)
                                if challenge_summary.get("probeFailed"):
                                    self._preflight_retryable_failure()
                                    return finish(False, preserve_target=True)
                                if challenge_summary.get("authenticatedPage"):
                                    self._preflight_already_authenticated()
                                    return finish(True)
                                if challenge_summary.get("readyState") == "loading" and not challenge_summary.get("hasSlider"):
                                    self._preflight_retryable_failure("challenge_loading")
                                    return finish(False, preserve_target=True)
                                if not challenge_summary.get("explicitFailure"):
                                    restored = bool(
                                        challenge_summary.get("hasSlider")
                                        and ready_target_matches(challenge_summary, self.target_url)
                                    )
                                    if not restored:
                                        self._preflight_retryable_failure("slider_not_found")
                                        return finish(False, preserve_target=True)
                            if restored:
                                nc_retry_replays += 1
                                logger.info(
                                    "[SOLVER] Challenge asked to retry; "
                                    f"replaying drag without spending a main attempt "
                                    f"({nc_retry_replays}/{nc_retry_replay_limit})."
                                )
                                self._close_solver_ws()
                                attempt = max(attempt - 1, 0)
                                continue
                        if not local_mock_target and challenge_summary.get("retryableFailure"):
                            logger.warning(
                                "[SOLVER] Retryable challenge attempts exhausted; "
                                "returning to the bounded retry/cooldown policy."
                            )
                            self.last_failure_reason = "challenge_retry_exhausted"
                            self._close_solver_ws()
                            return finish(False)
                        logger.warning("[SOLVER] Official challenge rejected the automated drag; manual verification required.")
                        self.last_failure_reason = "manual_required"
                        self._close_solver_ws()
                        return finish(False)
                    self._reload_page()
                    self._bring_to_front()
                    self._wait_interruptibly(0.2 if local_mock_target else random.uniform(1, 2))

                except SliderEndpointReached:
                    confirmed = self._verify_slider_endpoint()
                    return finish(confirmed, preserve_target=not confirmed)
                except Exception as e:
                    from .captcha_budget import SolveStopped
                    if isinstance(e, (SolveStopped, NCRetryDeferred)):
                        raise
                    logger.exception("[SOLVER] Error during steps")
                    self._close_solver_ws()
                    logger.info("[SOLVER] Exception branch; retrying in 3 seconds")
                    self._wait_interruptibly(3)
                    continue

            logger.warning("[SOLVER] Max attempts (%s) reached without success", max_attempts)
            if self._stop_if_cancelled():
                return finish(False)
            recovered_authenticated_page = bool(
                not local_mock_target and self._recover_authenticated_list_page()
            )
            self._close_solver_ws()
            if recovered_authenticated_page:
                logger.info("[SOLVER] List page is authenticated after challenge attempts; clearing auth lock path.")
                return finish(True)
            if self.last_failure_reason != "cdp_unavailable":
                self.last_failure_reason = "max_attempts_exceeded"
            return finish(False)


__all__ = ["CaptchaOrchestrationMixin"]
