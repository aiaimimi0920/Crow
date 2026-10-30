from __future__ import annotations

import logging
import math
import os
import random
import time
from urllib.parse import urlsplit, urlunsplit

from src.project_environment import getenv as project_getenv

from .captcha_budget import SolveStopped
from .captcha_dom import eval_in_all_frames
from .captcha_os_target import OSPointerTarget
from .captcha_target_diagnostics import log_target_binding
from .captcha_verification import ready_target_matches
from .collection.adapters.taobao_auth_target import canonical_auth_target
from .collection.adapters.taobao_solver_target import _split_web_target_url

logger = logging.getLogger(__name__)


class NCRetryDeferred(Exception):
    """Stop this solve without further input, navigation or target cleanup."""

    reason = "cdp_unavailable"


class NCRetryInputUnconfirmed(NCRetryDeferred):
    """The retry click may have reached the page despite a missing CDP ACK."""


class NCRetryTargetUnconfirmed(NCRetryDeferred):
    """The current document cannot authorize retry input for this request."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class CaptchaNCRetryMixin:
    def _do_drag_local_mock(self, start_x, start_y, distance):
        """Deterministic drag path for the local mock slider harness."""
        target_x = start_x + distance
        target_y = start_y

        def dispatch_mouse_event(params):
            if params["type"] == "mousePressed":
                self._cdp_mouse_down = True
                self._cdp_mouse_position = (params["x"], params["y"])
            result = self._send_cdp("Input.dispatchMouseEvent", params)
            if result is not None:
                self._cdp_mouse_position = (params["x"], params["y"])
                if params["type"] == "mouseReleased":
                    self._cdp_mouse_down = False
                return True
            logger.warning("[SOLVER] CDP mouse input is unavailable; returning to bounded retry.")
            self._release_cdp_mouse()
            if not self._stop_if_cancelled():
                self.last_failure_reason = "cdp_unavailable"
            return False

        steps = max(24, min(48, int(abs(distance) / 8)))
        if not dispatch_mouse_event({
            "type": "mouseMoved",
            "x": start_x,
            "y": start_y,
            "button": "left",
        }):
            return None
        self._wait_interruptibly(0.02)
        if not dispatch_mouse_event({
            "type": "mousePressed",
            "x": start_x,
            "y": start_y,
            "button": "left",
            "clickCount": 1,
        }):
            return None
        self._wait_interruptibly(0.02)
        for index in range(1, steps + 1):
            if self._stop_if_cancelled():
                return None
            ratio = index / steps
            eased = ratio * ratio * (3 - 2 * ratio)
            x = start_x + (distance * eased)
            y = target_y + math.sin(ratio * math.pi) * 0.3
            if not dispatch_mouse_event({
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "left",
            }):
                return None
            self._wait_interruptibly(0.008)
        self._wait_interruptibly(0.02)
        if not dispatch_mouse_event({
            "type": "mouseReleased",
            "x": target_x,
            "y": target_y,
            "button": "left",
            "clickCount": 1,
        }):
            return None
        self._wait_interruptibly(0.1)
        return target_x

    def _nc_widget_rect(self):
        js_script = """
        (function() {
            var el = firstVisibleMatch(document, __NC_WIDGET_SELECTOR__, function(node) {
                var r = node.getBoundingClientRect();
                return r.width >= 8 && r.height >= 8;
            });
            if (!el) return null;
            var r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) return null;
            return {x: r.left, y: r.top, width: r.width, height: r.height,
                selector: __NC_WIDGET_SELECTOR__, context: 'main'};
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {"expression": eval_in_all_frames(js_script), "returnByValue": True})
        if ret and "result" in ret and isinstance(ret["result"].get("value"), dict):
            return ret["result"]["value"]
        return None

    def _nc_retry_targets(self):
        js_script = """
        (function() {
            function visibleRect(el, frameOffsetX, frameOffsetY, selector, context) {
                if (!verificationElementVisible(el)) return null;
                var rect = el.getBoundingClientRect();
                if (rect.width < 8 || rect.height < 8) return null;
                return {
                    x: rect.left + frameOffsetX,
                    y: rect.top + frameOffsetY,
                    width: rect.width,
                    height: rect.height,
                    selector: selector || (el.id ? '#' + CSS.escape(el.id) : null),
                    context: context
                };
            }

            function eligible(node) {
                var r = node.getBoundingClientRect();
                return r.width >= 8 && r.height >= 8;
            }

            function scan(doc, frameOffsetX, frameOffsetY, context) {
                var result = {
                    widget: null,
                    retryText: null,
                    slider: null
                };
                var widget = firstVisibleMatch(doc, __NC_WIDGET_SELECTOR__, eligible);
                result.widget = visibleRect(widget, frameOffsetX, frameOffsetY, __NC_WIDGET_SELECTOR__, context);
                var slider = firstVisibleMatch(doc, __NC_HANDLE_SELECTOR__, eligible);
                result.slider = visibleRect(slider, frameOffsetX, frameOffsetY, __NC_HANDLE_SELECTOR__, context);
                var errorWidget = firstVisibleMatch(doc, __NC_ERROR_SELECTOR__, eligible);
                result.retryText = visibleRect(errorWidget, frameOffsetX, frameOffsetY, __NC_ERROR_SELECTOR__, context);

                var allNodes = doc.querySelectorAll('div, span, p, button, a');
                for (var i = 0; !result.retryText && i < allNodes.length; i++) {
                    var node = allNodes[i];
                    if (!verificationElementVisible(node)) continue;
                    var text = (node.innerText || node.textContent || '').trim();
                    if (!text) continue;
                    if (
                        text.indexOf('点击框体重试') !== -1 ||
                        text.indexOf('验证失败') !== -1 ||
                        text.indexOf('拖动未达标') !== -1 ||
                        text.toLowerCase().indexOf("oops... something's wrong") !== -1 ||
                        text.toLowerCase().indexOf('please refresh page and try again') !== -1
                    ) {
                        result.retryText = visibleRect(node, frameOffsetX, frameOffsetY, null, context);
                        if (result.retryText) break;
                    }
                }
                return result;
            }

            var summary = null;
            visitAccessibleDocuments(function(doc, x, y, context) {
                    if (summary === null) { summary = scan(doc, x, y, context); return null; }
                    var frameSummary = scan(doc, x, y, context);
                    if (!summary.widget && frameSummary.widget) summary.widget = frameSummary.widget;
                    if (!summary.retryText && frameSummary.retryText) summary.retryText = frameSummary.retryText;
                    if (!summary.slider && frameSummary.slider) summary.slider = frameSummary.slider;
                    return null;
            }, true);
            return summary;
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {"expression": eval_in_all_frames(js_script), "returnByValue": True})
        if ret and "result" in ret and isinstance(ret["result"].get("value"), dict):
            return ret["result"]["value"]
        return {}

    def _nc_retry_click_candidates(self, targets):
        candidates = []
        seen = set()

        def add_point(label, rect, x_ratio, y_ratio=0.5):
            if not isinstance(rect, dict):
                return
            width = float(rect.get("width") or 0)
            height = float(rect.get("height") or 0)
            if width < 8 or height < 8:
                return
            x = float(rect.get("x") or 0) + width * x_ratio
            y = float(rect.get("y") or 0) + height * y_ratio
            key = (round(x, 1), round(y, 1))
            if key in seen:
                return
            seen.add(key)
            candidates.append({
                "label": label,
                "x": x,
                "y": y,
                "rect": rect,
            })

        retry_text = targets.get("retryText") if isinstance(targets, dict) else None
        widget = targets.get("widget") if isinstance(targets, dict) else None

        for ratio in (0.5, 0.35, 0.65):
            add_point("widget_centerline", widget, ratio)
        for y_ratio in (0.35, 0.65):
            add_point("widget_vertical", widget, 0.5, y_ratio)
        for ratio in (0.5, 0.35, 0.65):
            add_point("retry_text", retry_text, ratio)
        return candidates

    def _nc_retry_outcome(self, timeout_seconds=8.0):
        from .captcha_nc_retry_outcome import nc_retry_outcome

        return nc_retry_outcome(self, timeout_seconds, clock=lambda: time.time())

    def _click_css_point(self, css_x, css_y, *, slider_info=None):
        if self._os_mouse_enabled():
            try:
                import pyautogui
            except ImportError:
                pyautogui = None
            if pyautogui is not None:
                self._enable_process_dpi_awareness()
                pyautogui.FAILSAFE = False
                pyautogui.PAUSE = 0
                try:
                    focused = self._focus_os_window()
                except SolveStopped:
                    raise
                except Exception as error:  # noqa: BLE001 -- focus failure blocks input
                    self.last_failure_reason = "window_focus_failed"
                    logger.warning("[SOLVER] OS retry window focus failed: %s", error)
                    return False
                if not focused:
                    self.last_failure_reason = "window_focus_failed"
                    logger.warning("[SOLVER] OS window focus failed; skipping retry click.")
                    return False
                probe = OSPointerTarget(self, slider_info, css_x, css_y)
                pressed = False
                try:
                    if probe.enabled:
                        if not probe.open():
                            return False
                        css_x, css_y = probe.point
                        slider_info = {**slider_info, **probe.rect}
                    mapped = self._map_css_to_screen(
                        css_x, css_y, 0, slider_info=slider_info, allow_zero_distance=True
                    )
                    if mapped:
                        logger.info("[SOLVER] OS click at (%.0f,%.0f) source=%s", mapped["x"], mapped["y"], mapped.get("source"))
                        self._move_os_cursor_bounded(
                            pyautogui, mapped["x"], mapped["y"],
                            random.uniform(*( (0.12, 0.25) if os.name == "nt" else (0.2, 0.4) )),
                        )
                        self._wait_interruptibly(random.uniform(0.08, 0.18))
                        if probe.enabled and probe.verify(pyautogui, mapped) is None:
                            return False
                        pressed = True
                        self._set_os_left_button(pyautogui, down=True)
                        self._wait_interruptibly(random.uniform(0.04, 0.1))
                        self._set_os_left_button(pyautogui, down=False)
                        pressed = False
                        return True
                    if os.name != "nt":
                        return False
                finally:
                    try:
                        if pressed:
                            self._set_os_left_button(pyautogui, down=False)
                    finally:
                        probe.close()
                logger.info("[SOLVER] OS click mapping unavailable; falling back to CDP click.")
        if not self._dispatch_mouse(
            "mousePressed", css_x, css_y, buttons=1, click_count=1
        ):
            raise NCRetryInputUnconfirmed
        if not self._dispatch_mouse(
            "mouseReleased", css_x, css_y, buttons=0, click_count=1
        ):
            raise NCRetryInputUnconfirmed
        return True

    def _reset_failed_nc_challenge(self):
        """Click '点击框体重试' so NC rebuilds a fresh slider instead of locking collection."""
        targets = self._nc_retry_targets()
        widget = targets.get("widget") if isinstance(targets, dict) else None
        if not widget:
            widget = self._nc_widget_rect()
            if isinstance(targets, dict) and widget:
                targets["widget"] = widget
        if not widget:
            logger.warning("[SOLVER] NC retry widget not found.")
            return False
        candidates = self._nc_retry_click_candidates(targets)
        if not candidates:
            candidates = [
                {
                    "label": "widget_fallback",
                    "x": widget["x"] + widget["width"] / 2,
                    "y": widget["y"] + widget["height"] / 2,
                    "rect": widget,
                }
            ]
        for index, candidate in enumerate(candidates, 1):
            if self._solver_target_scope(self.target_url) in {"seed", "detail"}:
                if self._stop_if_cancelled():
                    raise NCRetryTargetUnconfirmed("slider_not_found")
                summary = self._refresh_challenge_summary({})
                if self._stop_if_cancelled():
                    raise NCRetryTargetUnconfirmed("slider_not_found")
                from .captcha_navigation_receipt import navigation_binding_fields

                log_target_binding(
                    logger,
                    "retry_preclick",
                    summary,
                    self.target_url,
                    navigation=navigation_binding_fields(self, summary),
                )
                reason = (
                    "cdp_unavailable"
                    if summary.get("probeFailed")
                    else "challenge_loading"
                    if summary.get("readyState") == "loading"
                    else "slider_not_found"
                    if not ready_target_matches(summary, self.target_url)
                    else None
                )
                if reason:
                    logger.info(
                        "[SOLVER] NC retry target unconfirmed; deferring before input: %s",
                        reason,
                    )
                    raise NCRetryTargetUnconfirmed(reason)
                if summary.get("authenticatedPage"):
                    return True
                if summary.get("hasSlider") and not summary.get("explicitFailure"):
                    # Recovery may begin too late for three stable poll samples.
                    # Let the caller revalidate it, never click old widget points.
                    logger.info(
                        "[SOLVER] NC retry document uncertain; deferring without further clicks."
                    )
                    return False
            click_x = candidate["x"]
            click_y = candidate["y"]
            logger.info(
                f"[SOLVER] Clicking NC retry target {index}/{len(candidates)} "
                f"({candidate['label']}) at ({click_x:.0f},{click_y:.0f})"
            )
            if not self._click_css_point(
                click_x, click_y, slider_info=candidate.get("rect") or widget
            ):
                continue
            self._wait_interruptibly(random.uniform(0.6, 1.0))
            outcome = self._nc_retry_outcome(timeout_seconds=3.0)
            if any(
                outcome.get(key)
                for key in ("probeFailed", "loading", "cancelled", "targetUnavailable")
            ):
                logger.info(
                    "[SOLVER] NC retry document uncertain; deferring without further clicks."
                )
                return False
            if outcome.get("authenticated"):
                logger.info("[SOLVER] NC retry click recovered an authenticated page.")
                self.last_failure_reason = None
                return True
            if outcome.get("slider"):
                logger.info("[SOLVER] NC slider restored after retry click.")
                return True
        logger.warning("[SOLVER] NC retry click did not restore a slider.")
        return False

    def _nc_retry_replay_limit(self):
        raw = project_getenv("CROW_SOLVER_NC_RETRY_REPLAYS", "2")
        try:
            return max(int(str(raw or "").strip() or "0"), 0)
        except ValueError:
            return 2

    def _destination_list_url(self):
        href = ""
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": "location.href",
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            href = str(ret["result"]["value"])
        if not href:
            href = str(self.current_target_url or self.target_url or "")
        for target in (self.target_url, href):
            scope = self._solver_target_scope(target)
            if scope in {"seed", "detail"}:
                try:
                    return canonical_auth_target(scope, target)
                except (ValueError, TypeError):
                    continue
        try:
            parsed_href = urlsplit(href)
        except ValueError:
            parsed_href = None
        if parsed_href is not None and "/_____tmd_____/" in parsed_href.path:
            dest = urlunsplit((parsed_href.scheme, parsed_href.netloc, parsed_href.path.split("/_____tmd_____/", 1)[0], "", ""))
            dest = self._normalize_target_url(dest)
            if parsed_href.scheme in {"http", "https"}:
                return dest
        parsed = _split_web_target_url(href)
        if parsed is not None and parsed.hostname == "sf.taobao.com" and parsed.path.startswith("/list/"):
            return self._normalize_target_url(href)
        return "https://sf.taobao.com/list/50025969__2.htm"

    def _recover_authenticated_list_page(self):
        dest = self._destination_list_url()
        if not dest:
            return False
        logger.info("[SOLVER] Probing whether the auction list is already authenticated: %s", dest)
        navigated = self._send_cdp("Page.navigate", {"url": dest})
        if navigated is None:
            return False
        self._wait_interruptibly(3.2)
        summary = self._page_challenge_summary()
        if summary.get("authenticatedPage"):
            self.last_failure_reason = None
            return True
        return False

    def _login_wait_seconds(self):
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return 0
        raw = project_getenv("CROW_SOLVER_LOGIN_WAIT_SECONDS", "120")
        try:
            return max(int(str(raw or "").strip() or "0"), 0)
        except ValueError:
            return 120

    def _looks_like_login_ui(self, summary):
        if not isinstance(summary, dict):
            return False
        href = str(summary.get("href") or "")
        title = str(summary.get("title") or "")
        parsed = _split_web_target_url(href)
        try:
            path = urlsplit(href).path.lower()
        except ValueError:
            path = ""
        return bool(
            summary.get("loginRequired")
            or (parsed is not None and parsed.hostname == "login.taobao.com")
            or "login_jump" in path
            or "/passport/" in path
            or title.strip() == "登录"
        )

    def _poll_until_authenticated(self):
        wait_seconds = self._login_wait_seconds()
        if wait_seconds <= 0:
            return False
        logger.info("[SOLVER] Waiting up to %ss for login/list recovery; keep the Edge window in front.", wait_seconds)
        try:
            self._focus_os_window()
        except Exception:
            self._bring_to_front()
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._stop_if_cancelled():
                return False
            summary = self._page_challenge_summary()
            if summary.get("authenticatedPage"):
                logger.info("[SOLVER] Page became authenticated while waiting for login.")
                self.last_failure_reason = None
                return True
            if summary.get("hasSlider"):
                logger.info(
                    "[SOLVER] Slider returned while waiting for login; handing off to drag solver."
                )
                return False
            if not self._looks_like_login_ui(summary):
                if self._recover_authenticated_list_page():
                    return True
            self._wait_interruptibly(5)
        return False


__all__ = ["CaptchaNCRetryMixin", "NCRetryDeferred", "NCRetryInputUnconfirmed", "NCRetryTargetUnconfirmed"]
