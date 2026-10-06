from __future__ import annotations

import logging
import json
import random
from .captcha_dom import eval_in_all_frames
from .captcha_verification import ready_target_matches

logger = logging.getLogger(__name__)


class CaptchaSliderMixin:
    def _find_slider_once(self):
        """Run one slider lookup pass and return slider info dict or None."""
        selectors_js = json.dumps(self.SLIDER_SELECTORS)

        js_script = f"""
        (function() {{
            var selectors = {selectors_js};

            function tryFind(doc, frameOffsetX, frameOffsetY, context) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (el && el.offsetParent !== null) {{
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 5 && rect.height > 5) {{
                            return {{
                                found: true,
                                x: rect.left + frameOffsetX,
                                y: rect.top + frameOffsetY,
                                width: rect.width,
                                height: rect.height,
                                selector: selectors[i],
                                context: context
                            }};
                        }}
                    }}
                }}
                return null;
            }}

            return visitAccessibleDocuments(tryFind, false);
        }})()
        """
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": eval_in_all_frames(js_script),
            "returnByValue": True
        })

        if ret and "result" in ret and ret["result"].get("value"):
            slider_info = ret["result"]["value"]
            if slider_info.get("found"):
                return slider_info
        return None

    def _find_slider(self, max_retries=15, retry_delay=1):
        """Find slider element using multiple selectors. Returns slider info dict or None."""

        attempts = max(int(max_retries or 0), 1)
        for attempt in range(attempts):
            if self._stop_if_cancelled():
                return None
            slider_info = self._find_slider_once()
            if slider_info:
                return slider_info

            logger.info("[SOLVER] Slider not found; retrying attempt=%s/%s", attempt + 1, attempts)
            if attempt + 1 < attempts and retry_delay:
                self._wait_interruptibly(retry_delay)

        return None

    def _get_track_width(self):
        """Dynamically get the slider track width using multiple selectors."""
        track_selectors_js = json.dumps(self.TRACK_SELECTORS)

        js_script = f"""
        (function() {{
            var selectors = {track_selectors_js};

            function tryFind(doc) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (el) {{
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 50) {{
                            return {{ width: rect.width, selector: selectors[i] }};
                        }}
                    }}
                }}
                return null;
            }}

            return visitAccessibleDocuments(tryFind, false);
        }})()
        """

        ret = self._send_cdp("Runtime.evaluate", {
            "expression": eval_in_all_frames(js_script),
            "returnByValue": True
        })

        if ret and "result" in ret and ret["result"].get("value"):
            info = ret["result"]["value"]
            logger.info("[SOLVER] Track width: %spx selector=%s", info["width"], info["selector"])
            return info["width"]

        # Fallback: try to get from viewport if track not found
        logger.warning("[SOLVER] Could not detect track width; using fallback 340px")
        return 340

    def _get_track_rect(self):
        """Return the live track rectangle so drag distance follows the current handle position."""
        track_selectors_js = json.dumps(self.TRACK_SELECTORS)
        js_script = f"""
        (function() {{
            var selectors = {track_selectors_js};
            function find(doc) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (!el) continue;
                    var rect = el.getBoundingClientRect();
                    if (rect.width > 50 && rect.height > 5) {{
                        var handle = doc.querySelector(__NC_HANDLE_SELECTOR__);
                        return {{
                            left: rect.left,
                            top: rect.top,
                            width: rect.width,
                            height: rect.height,
                            offsetWidth: el.offsetWidth,
                            handleOffsetLeft: handle ? handle.offsetLeft : null,
                            handleOffsetWidth: handle ? handle.offsetWidth : null
                        }};
                    }}
                }}
                return null;
            }}
            return visitAccessibleDocuments(find, false);
        }})()
        """
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": eval_in_all_frames(js_script),
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            value = ret["result"]["value"]
            if isinstance(value, dict) and float(value.get("width") or 0) > 50:
                return value
        return None

    def _verify_success(self):
        """Check if captcha was solved."""
        local_mock_mode = self._local_mock_verification_mode()
        self._last_mock_terminal_state = None
        js_check = """
        (function() {
            var successKeywords = ['验证通过', '通过验证', '验证成功', '验证已通过'];
            var errorKeywords = ['失败', '错误', '再试', 'error', 'fail'];

            function scanDoc(doc) {
                var text = (doc.body && doc.body.innerText) ? doc.body.innerText : '';
                var hasSuccess = false;
                var hasError = false;

                for (var i = 0; i < successKeywords.length; i++) {
                    if (text.trim() === successKeywords[i]) {
                        hasSuccess = true;
                        break;
                    }
                }

                for (var j = 0; j < errorKeywords.length; j++) {
                    if (text.indexOf(errorKeywords[j]) !== -1) {
                        hasError = true;
                        break;
                    }
                }

                // Check for NC success class
                var container = doc.querySelector('.nc-container');
                if (container && container.className) {
                    if (verificationElementVisible(container) && (' ' + container.className + ' ').indexOf(' nc-success ') !== -1) {
                        hasSuccess = true;
                    }
                }

                // Check if slider is still visible
                var sliderVisible = hasVisibleMatch(doc, __VERIFY_SLIDER_SELECTOR__);
                var challengeVisible = hasVisibleMatch(doc, __VERIFY_CHALLENGE_SELECTOR__);
                hasError = hasError || hasVisibleMatch(doc, __NC_ERROR_SELECTOR__);

                return {
                    hasSuccess: hasSuccess,
                    hasError: hasError,
                    sliderVisible: sliderVisible,
                    challengeVisible: challengeVisible
                };
            }

            var result = null;
            visitAccessibleDocuments(function(doc) {
                var scanned = scanDoc(doc);
                if (result === null) { result = scanned; return null; }
                // Only main-document success is evidence; visible frames can veto it.
                result.hasError = result.hasError || scanned.hasError;
                result.sliderVisible = result.sliderVisible || scanned.sliderVisible;
                result.challengeVisible = result.challengeVisible || scanned.challengeVisible;
                return null;
            }, true);
            var mockState = window.__mockSliderState || null;
            var mockStatusNode = document.getElementById('mock-slider-status');
            var mockTrack = document.getElementById('mock-slider-track');
            var mockHandle = document.getElementById('mock-slider-handle');
            var mockStatusText = mockStatusNode && mockStatusNode.innerText ? String(mockStatusNode.innerText) : '';
            var mockChallengeVisible = !!(
                (mockTrack && mockTrack.offsetParent !== null) ||
                (mockHandle && mockHandle.offsetParent !== null)
            );
            return {
                success: result.hasSuccess && !result.sliderVisible && !result.challengeVisible,
                successDetected: result.hasSuccess,
                sliderGone: !result.sliderVisible,
                challengeGone: !result.challengeVisible,
                hasError: result.hasError,
                noError: !result.hasError,
                href: document.location ? String(document.location.href) : '',
                readyState: document.readyState || '',
                mockStateSuccess: !!(mockState && mockState.success),
                mockStateFailure: !!(mockState && mockState.failure),
                mockResolution: mockState && mockState.resolution ? String(mockState.resolution) : '',
                mockStatusText: mockStatusText,
                mockVerifyMode: mockState && mockState.config && mockState.config.verifyMode ? String(mockState.config.verifyMode) : '',
                mockChallengeVisible: mockChallengeVisible
            };
        })()
        """

        ret = self._send_cdp("Runtime.evaluate", {
            "expression": eval_in_all_frames(js_check),
            "returnByValue": True
        })

        if ret and "result" in ret and ret["result"].get("value"):
            result = ret["result"]["value"]
            log_parts = [
                "[SOLVER] Verification: "
                f"success={result.get('success')}",
                f"sliderGone={result.get('sliderGone')}",
                f"challengeGone={result.get('challengeGone')}",
                f"hasError={result.get('hasError')}",
            ]
            if local_mock_mode:
                log_parts.extend([
                    f"mockSuccess={result.get('mockStateSuccess')}",
                    f"mockFailure={result.get('mockStateFailure')}",
                    f"mockMode={result.get('mockVerifyMode') or local_mock_mode}",
                ])
            logger.info("[SOLVER] %s", ", ".join(log_parts))
            no_error = bool(result.get("noError", not result.get("hasError")))
            if local_mock_mode:
                mock_state_success = bool(result.get("mockStateSuccess"))
                mock_state_failure = bool(result.get("mockStateFailure"))
                mock_challenge_visible = bool(result.get("mockChallengeVisible"))
                mock_status_text = str(result.get("mockStatusText") or "")
                mock_status_lower = mock_status_text.lower()
                mock_has_success_text = any(
                    keyword in mock_status_text for keyword in ("验证通过", "通过验证", "验证成功", "验证已通过")
                ) or ("success" in mock_status_lower)
                mock_has_error_text = any(
                    keyword in mock_status_text for keyword in ("失败", "错误", "再试")
                ) or ("error" in mock_status_lower) or ("fail" in mock_status_lower)
                if mock_state_failure or mock_has_error_text or not no_error:
                    if local_mock_mode == "explicit_fail":
                        self._last_mock_terminal_state = "manual_required"
                    elif mock_state_failure:
                        self._last_mock_terminal_state = "terminal_failure"
                    return False
                if local_mock_mode == "teardown_only":
                    return bool(mock_state_success and not mock_challenge_visible)
                return bool(mock_state_success and mock_has_success_text)
            return bool(
                result.get("noError") is True and result.get("hasError") is False
                and result.get("sliderGone") is True and result.get("challengeGone") is True
                and result.get("success") is True
                and ready_target_matches(result, getattr(self, "target_url", None))
            )

        return False

    def _wait_for_verification_success(self, max_checks=6):
        """Poll verification briefly because challenge UI teardown can lag behind the drag."""
        checks = max(int(max_checks or 0), 1)
        local_mock_target = self._is_local_mock_slider_target()
        local_mock_mode = self._local_mock_verification_mode()
        self._last_mock_terminal_state = None
        if local_mock_target:
            checks = max(checks, 10)
        for check_index in range(checks):
            if self._stop_if_cancelled():
                return False
            if self._verify_success():
                return True
            if not local_mock_target:
                challenge_summary = self._page_challenge_summary()
                if challenge_summary.get("authenticatedPage"):
                    logger.info("[SOLVER] Auction page became accessible after drag; treating as solved.")
                    return True
            terminal_state = self._last_mock_terminal_state
            if terminal_state == "manual_required":
                self.last_failure_reason = "manual_required"
                return False
            if terminal_state == "terminal_failure":
                return False
            if local_mock_target and local_mock_mode == "explicit_fail":
                challenge_summary = self._page_challenge_summary()
                if challenge_summary.get("explicitFailure"):
                    self.last_failure_reason = "manual_required"
                    return False
            if check_index < checks - 1:
                if local_mock_target:
                    self._wait_interruptibly(0.15)
                else:
                    self._wait_interruptibly(random.uniform(0.6, 1.1))
        return False

    def _generate_bezier_path(self, start_x, start_y, target_x, target_y):
        """Generate a realistic human-like mouse path using a Cubic Bezier curve."""
        distance = ((target_x - start_x)**2 + (target_y - start_y)**2)**0.5
        p0 = (start_x, start_y)
        p3 = (target_x, target_y)

        # More subtle bow - humans don't always bow much
        bow = random.choice([1, -1]) * random.uniform(2, 12)

        # More varied control points
        p1_x = start_x + (target_x - start_x) * random.uniform(0.15, 0.45)
        p1_y = start_y + bow + random.uniform(-8, 8)

        p2_x = start_x + (target_x - start_x) * random.uniform(0.55, 0.85)
        p2_y = target_y + bow/3 + random.uniform(-8, 8)

        # More varied point density
        num_points = int(distance / random.uniform(2, 6))
        num_points = max(15, min(num_points, 80))

        path = []
        for i in range(num_points + 1):
            t = i / num_points

            # Bezier formula
            x = (1-t)**3 * p0[0] + 3 * (1-t)**2 * t * p1_x + 3 * (1-t) * t**2 * p2_x + t**3 * p3[0]
            y = (1-t)**3 * p0[1] + 3 * (1-t)**2 * t * p1_y + 3 * (1-t) * t**2 * p2_y + t**3 * p3[1]

            # More realistic jitter - humans shake more
            x += random.uniform(-2, 2)
            y += random.uniform(-2.5, 2.5)

            # Custom easing - slow start, fast middle, very slow end
            ease_t = t * t * (3 - 2 * t)

            path.append((x, y, ease_t))

        return path

    def _dispatch_mouse(self, event_type, x, y, *, buttons=0, click_count=0):
        """Send a CDP mouse event. Drag moves MUST keep buttons=1 or NC ignores the path."""
        params = {
            "type": event_type,
            "x": x,
            "y": y,
            "pointerType": "mouse",
            "modifiers": 0,
            "buttons": int(buttons),
        }
        if event_type in {"mousePressed", "mouseReleased"}:
            params["button"] = "left"
            params["clickCount"] = click_count or 1
        elif event_type == "mouseMoved" and buttons:
            params["button"] = "left"
        if event_type == "mousePressed":
            # The input may reach Chromium even if its acknowledgement is lost.
            self._cdp_mouse_down = True
            self._cdp_mouse_position = (x, y)
        result = self._send_cdp("Input.dispatchMouseEvent", params)
        if result is not None:
            self._cdp_mouse_position = (x, y)
            if event_type in {"mousePressed", "mouseReleased"}:
                self._cdp_mouse_down = event_type == "mousePressed"
            return True
        logger.warning("[SOLVER] CDP mouse input is unavailable; returning to bounded retry.")
        self._release_cdp_mouse()
        if not self._stop_if_cancelled():
            self.last_failure_reason = "cdp_unavailable"
        return False

    def _do_drag(self, start_x, start_y, distance):
        """Slow human-like drag. NC rejects paths that are too fast or missing button state."""
        target_x = start_x + distance
        target_y = start_y + random.uniform(-3, 3)

        # 1. Pre-approach: Move near slider (no button)
        pre_x = start_x - random.uniform(18, 36)
        pre_y = start_y + random.uniform(-10, 10)
        if not self._dispatch_mouse("mouseMoved", pre_x, pre_y, buttons=0):
            return None
        self._wait_interruptibly(random.uniform(0.55, 1.05))

        # 2. Approach slider
        if not self._dispatch_mouse("mouseMoved", start_x, start_y, buttons=0):
            return None
        self._wait_interruptibly(random.uniform(0.35, 0.75))

        # 3. Mouse down with hesitation
        if not self._dispatch_mouse(
            "mousePressed", start_x, start_y, buttons=1, click_count=1
        ):
            return None
        self._wait_interruptibly(random.uniform(0.18, 0.38))

        # 4. Generate bezier path
        path = self._generate_bezier_path(start_x, start_y, target_x, target_y)

        # 5. Execute drag with a 2.4–4.2s human velocity curve
        n = max(len(path), 1)
        for i, (px, py, _t) in enumerate(path):
            progress = i / n
            if progress < 0.12:
                delay = random.uniform(0.035, 0.060)
            elif progress < 0.35:
                delay = random.uniform(0.022, 0.038)
            elif progress < 0.72:
                delay = random.uniform(0.018, 0.032)
            elif progress < 0.88:
                delay = random.uniform(0.028, 0.048)
            else:
                delay = random.uniform(0.040, 0.070)
            if random.random() < 0.14:
                delay += random.uniform(0.04, 0.10)
            self._wait_interruptibly(delay)
            if not self._dispatch_mouse(
                "mouseMoved",
                px + random.gauss(0, 0.7),
                py + random.gauss(0, 1.1),
                buttons=1,
            ):
                return None

        # 6. Small overshoot + settle (keep the button down)
        self._wait_interruptibly(random.uniform(0.08, 0.16))
        overshoot = random.uniform(0, 3)
        if not self._dispatch_mouse(
            "mouseMoved", target_x + overshoot, target_y, buttons=1
        ):
            return None
        self._wait_interruptibly(random.uniform(0.06, 0.12))
        for _ in range(random.randint(2, 4)):
            target_x -= random.uniform(0.6, 2.2)
            target_y += random.uniform(-0.8, 0.8)
            if not self._dispatch_mouse("mouseMoved", target_x, target_y, buttons=1):
                return None
            self._wait_interruptibly(random.uniform(0.025, 0.050))
        if not self._dispatch_mouse("mouseMoved", start_x + distance, target_y, buttons=1):
            return None

        # 7. Sample a fresh 1.5-2.5 second hold at the final endpoint.
        self._wait_interruptibly(random.uniform(1.5, 2.5))

        # 8. Release
        if not self._dispatch_mouse(
            "mouseReleased", start_x + distance, target_y, buttons=0, click_count=1
        ):
            return None
        self._wait_interruptibly(random.uniform(0.4, 0.7))

        return start_x + distance


__all__ = ["CaptchaSliderMixin"]
