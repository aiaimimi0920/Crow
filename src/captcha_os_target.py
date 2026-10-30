"""Re-measure a focused target and verify real pointer hit before pressing."""

from __future__ import annotations

import json
import logging
import math
import os
import uuid

from .captcha_budget import SolveStopped
from .captcha_dom import eval_in_all_frames
from .captcha_slider_geometry import GEOMETRY_HELPERS

logger = logging.getLogger("src.captcha_os_input")

_SNAPSHOT_CHECKS = {
    "binding_missing",
    "binding_document",
    "binding_expired",
    "binding_changed",
    "node_unavailable",
    "frame_unavailable",
    "track_unavailable",
}

_INSTALL = r"""
(function() {
    __GEOMETRY_HELPERS__
    var key = __KEY__, selector = __SELECTOR__, expectedContext = __CONTEXT__;
    var bindingKey = __BINDING_KEY__, anchor = bindingKey ? window[bindingKey] : null;
    function unavailable(check) {
        return bindingKey ? {probe_failure:check} : null;
    }
    function install(doc, node, frame, boundTrack) {
        if (!verificationElementVisible(node)) return unavailable('node_unavailable');
        var serial = 0, last = null;
        var pressSeen = false, pressOnTarget = false, pressedMoves = 0, releaseSeen = false;
        function origin() {
            if (!frame) return {x:0, y:0};
            if (!verificationElementVisible(frame) || frame.contentDocument !== doc) return null;
            var r = frame.getBoundingClientRect();
            return {x:r.left+frame.clientLeft, y:r.top+frame.clientTop};
        }
        function read() {
            var offset = origin();
            if (anchor && !sliderBindingValid(anchor)) {
                return unavailable(Date.now() >= anchor.expiresAt ? 'binding_expired' : 'binding_changed');
            }
            if (!offset) return unavailable('frame_unavailable');
            if (!node.isConnected || node.ownerDocument !== doc ||
                !verificationElementVisible(node)) return unavailable('node_unavailable');
            if (anchor && boundTrack && (!boundTrack.isConnected ||
                boundTrack.ownerDocument !== doc || !verificationElementVisible(boundTrack))) {
                return unavailable('track_unavailable');
            }
            var r = node.getBoundingClientRect();
            var trackRect = anchor ? sliderTrackRect(boundTrack, node, offset.x, offset.y) : null;
            if (anchor && boundTrack && !trackRect) return unavailable('track_unavailable');
            var observed = null;
            if (last) {
                var hit = doc.elementFromPoint(last.x, last.y);
                var x = last.x+offset.x, y = last.y+offset.y;
                observed = {x:x, y:y, buttons:last.buttons, serial:last.serial,
                    age:performance.now()-last.at,
                    hit:!!hit && (hit === node || node.contains(hit)) &&
                        (!frame || document.elementFromPoint(x,y) === frame)};
            }
            return {rect: {x:r.left+offset.x, y:r.top+offset.y, width:r.width, height:r.height},
                focused:document.hasFocus(), visible:document.visibilityState === 'visible',
                scale:window.devicePixelRatio || 1, event:observed,
                geometry_bound:!!anchor,
                track_rect:trackRect};
        }
        function moved(event) {
            if (!event.isTrusted) return;
            last = {x:event.clientX, y:event.clientY, at:performance.now(),
                buttons:event.buttons, serial:++serial};
            if (pressSeen && !releaseSeen && (event.buttons & 1)) {
                pressedMoves = Math.min(10000, pressedMoves+1);
            }
        }
        function pressed(event) {
            if (!event.isTrusted) return;
            last = null;
            if (event.button !== 0 || pressSeen) return;
            pressSeen = true;
            pressOnTarget = event.target === node || node.contains(event.target);
        }
        function released(event) {
            if (event.isTrusted && event.button === 0 && pressSeen) releaseSeen = true;
        }
        doc.addEventListener('mousemove', moved, true);
        doc.addEventListener('mousedown', pressed, true);
        doc.addEventListener('mouseup', released, true);
        var expiry;
        window[key] = {read:read, close:function() {
            clearTimeout(expiry);
            doc.removeEventListener('mousemove', moved, true);
            doc.removeEventListener('mousedown', pressed, true);
            doc.removeEventListener('mouseup', released, true); delete window[key];
            // Read even after success hides/removes the handle; this is not a success proof.
            return {press_seen:pressSeen, press_on_target:pressOnTarget,
                pressed_moves:pressedMoves, release_seen:releaseSeen,
                document_current:frame ? frame.isConnected && frame.contentDocument === doc : document === doc};
        }};
        expiry = setTimeout(function() { if (window[key]) window[key].close(); }, 30000);
        return read();
    }
    if (bindingKey) {
        // An expired/detached binding must never silently select another frame/node.
        if (!anchor || !anchor.node) return unavailable('binding_missing');
        if (anchor.node.ownerDocument !== anchor.doc) return unavailable('binding_document');
        clearTimeout(anchor.expiry);
        delete window[bindingKey];
        return install(anchor.doc, anchor.node, anchor.frame, anchor.track);
    }
    return visitAccessibleDocuments(function(doc, offsetX, offsetY, context) {
        if (expectedContext && context !== expectedContext) return null;
        var node = Array.from(doc.querySelectorAll(selector)).find(verificationElementVisible);
        return install(doc, node, doc.defaultView.frameElement, null);
    }, true);
})()
"""


class OSPointerTarget:
    """One Linux action; the temporary listener is always removed by the caller."""

    def __init__(self, solver, info, x, y):
        self.solver = solver
        self.info = info if isinstance(info, dict) else {}
        self.enabled = os.name != "nt" and bool(self.info.get("selector"))
        self.key = "__crow_pointer_" + uuid.uuid4().hex
        self.point = (float(x), float(y))
        self.rect = None
        self.track_rect = None
        self.geometry_bound = False
        self.scale = 1.0
        self.installed = False
        self.backend_completed = False

    def _evaluate(self, expression):
        result = self.solver._send_cdp(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "silent": True},
        )
        return (result or {}).get("result", {}).get("value")

    def run_drag(self, start_x, start_y, distance, slider_info, profile_variant_index):
        """Own the listener lifetime even when native input is interrupted."""
        try:
            result = self.solver._do_drag_os_target(
                start_x, start_y, distance, slider_info, profile_variant_index, self
            )
            self.backend_completed = result is not None
            return result
        finally:
            self.close()

    def _fail(self, reason, check="target"):
        self.solver.last_failure_reason = "screen_mapping_" + reason
        logger.info(
            "[SOLVER] OS pointer probe failed reason=%s check=%s", reason, check
        )

    @staticmethod
    def _snapshot_check(snapshot, fallback):
        check = snapshot.get("probe_failure") if isinstance(snapshot, dict) else None
        return (
            check if isinstance(check, str) and check in _SNAPSHOT_CHECKS else fallback
        )

    @staticmethod
    def _valid(snapshot):
        if not isinstance(snapshot, dict) or not snapshot.get("visible"):
            return False
        try:
            rect = snapshot["rect"]
            values = [float(rect[k]) for k in ("x", "y", "width", "height")]
            scale = float(snapshot["scale"])
            return (
                all(math.isfinite(v) for v in values)
                and min(values[2:]) > 5
                and 0.25 <= scale <= 8
            )
        except (KeyError, TypeError, ValueError):
            return False

    def open(self):
        if not self.enabled:
            return True
        expression = (
            _INSTALL.replace("__KEY__", json.dumps(self.key))
            .replace("__SELECTOR__", json.dumps(self.info["selector"]))
            .replace("__CONTEXT__", json.dumps(self.info.get("context")))
            .replace("__BINDING_KEY__", json.dumps(self.info.get("binding_key")))
            .replace("__GEOMETRY_HELPERS__", GEOMETRY_HELPERS)
        )
        # Even a lost acknowledgement may have installed the listener.
        self.installed = True
        # Omnibox focus makes document.hasFocus() false even in the active window.
        # Require native window ownership; the trusted DOM hit is checked before press.
        if not self.solver._linux_window_has_focus(self.solver._linux_window_id):
            return self._fail("target_unavailable", "open_native_focus")
        snapshot = self._evaluate(eval_in_all_frames(expression))
        if not self._valid(snapshot):
            return self._fail(
                "target_unavailable", self._snapshot_check(snapshot, "open_snapshot")
            )
        if self.info.get("binding_key"):
            if snapshot.get("geometry_bound") is not True:
                return self._fail("target_unavailable", "open_binding")
            self.geometry_bound = True
            self.track_rect = snapshot.get("track_rect")
        try:
            ratios = [
                (self.point[i] - float(self.info[k])) / float(self.info[size])
                for i, (k, size) in enumerate((("x", "width"), ("y", "height")))
            ]
            if not all(math.isfinite(r) and 0 <= r <= 1 for r in ratios):
                return self._fail("target_invalid")
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return self._fail("target_invalid")
        self.rect = snapshot["rect"]
        self.scale = float(snapshot["scale"])
        self.point = tuple(
            float(self.rect[k]) + ratios[i] * float(self.rect[size])
            for i, (k, size) in enumerate((("x", "width"), ("y", "height")))
        )
        return True

    def verify(self, pointer, mapped):
        """At most two bounded corrections; never press on missing/occluded evidence."""
        x, y = float(mapped["x"]), float(mapped["y"])
        previous_serial = 0
        for correction in range(3):
            self.solver._wait_interruptibly(0.04)
            if not self.solver._linux_window_has_focus(self.solver._linux_window_id):
                return self._fail("target_unavailable", "native_focus")
            snapshot = self._evaluate(f"window[{json.dumps(self.key)}]?.read()")
            if not self._valid(snapshot) or float(snapshot["scale"]) != self.scale:
                return self._fail(
                    "target_unavailable", self._snapshot_check(snapshot, "snapshot")
                )
            if any(
                abs(float(snapshot["rect"][k]) - float(self.rect[k])) > 1.5
                for k in ("x", "y", "width", "height")
            ):
                return self._fail("target_changed")
            if self.geometry_bound and not self._same_track(snapshot.get("track_rect")):
                return self._fail("target_changed")
            event = snapshot.get("event")
            if not isinstance(event, dict) or event.get("buttons") != 0:
                return self._fail("pointer_unobserved", "event_buttons")
            try:
                dx, dy = (
                    self.point[0] - float(event["x"]),
                    self.point[1] - float(event["y"]),
                )
                serial = int(event["serial"])
                age = float(event["age"])
                if (
                    not all(math.isfinite(v) for v in (dx, dy))
                    or serial <= previous_serial
                ):
                    return self._fail("pointer_unobserved", "event_serial")
                if not 0 <= age <= 1500:
                    return self._fail("pointer_unobserved", "event_age")
            except (KeyError, TypeError, ValueError):
                return self._fail("pointer_unobserved")
            delta = math.hypot(dx, dy)
            cursor = self.solver._get_os_cursor_position(pointer)
            if math.dist(cursor, (x, y)) > 2.5:
                return self._fail("pointer_changed")
            if delta <= 2 and event.get("hit") is True:
                if not self.solver._linux_window_has_focus(
                    self.solver._linux_window_id
                ):
                    return self._fail("target_unavailable", "native_focus")
                logger.info(
                    "[SOLVER] OS pointer hit verified delta=%.1fpx corrections=%d",
                    delta,
                    correction,
                )
                return cursor
            if correction == 2 or delta * self.scale > 64 or delta <= 2:
                return self._fail("pointer_missed")
            previous_serial = serial
            x, y = x + dx * self.scale, y + dy * self.scale
            self.solver._move_os_cursor_bounded(pointer, x, y, 0.15)
        return self._fail("pointer_missed")

    def _same_track(self, rect):
        if rect is None or self.track_rect is None:
            return rect is self.track_rect
        try:
            for key in (
                "left",
                "top",
                "width",
                "height",
                "offsetWidth",
                "handleOffsetLeft",
                "handleOffsetWidth",
            ):
                before, after = self.track_rect.get(key), rect.get(key)
                if before is None or after is None:
                    if before is not after:
                        return False
                elif (
                    not math.isfinite(float(after))
                    or abs(float(before) - float(after)) > 1.5
                ):
                    return False
        except (AttributeError, TypeError, ValueError):
            return False
        return True

    def close(self):
        if not self.installed:
            return
        receipt = None
        try:
            receipt = self._evaluate(f"window[{json.dumps(self.key)}]?.close()")
        except SolveStopped:
            # The solve budget has expired; the target may already be closed.
            pass
        except Exception:
            logger.debug("[SOLVER] Pointer probe cleanup unavailable", exc_info=True)
        finally:
            self.installed = False
        try:
            self._log_input_receipt(receipt)
        except Exception:  # noqa: BLE001, S110 -- optional telemetry cannot affect input cleanup
            # Optional diagnostics must never affect input, cancellation or cleanup.
            pass

    def _log_input_receipt(self, receipt):
        booleans = ("press_seen", "press_on_target", "release_seen", "document_current")
        if (
            not isinstance(receipt, dict)
            or any(type(receipt.get(key)) is not bool for key in booleans)
            or type(receipt.get("pressed_moves")) is not int
            or not 0 <= receipt["pressed_moves"] <= 10000
        ):
            logger.info(
                "[SOLVER] OS input receipt unavailable backendCompleted=%s",
                self.backend_completed,
            )
            return
        logger.info(
            "[SOLVER] OS input receipt backendCompleted=%s pressSeen=%s "
            "pressOnTarget=%s pressedMoves=%d releaseSeen=%s documentCurrent=%s",
            self.backend_completed,
            receipt["press_seen"],
            receipt["press_on_target"],
            receipt["pressed_moves"],
            receipt["release_seen"],
            receipt["document_current"],
        )
