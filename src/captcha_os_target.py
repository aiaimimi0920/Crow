"""Re-measure a focused target and verify real pointer hit before pressing."""

from __future__ import annotations

import json
import logging
import math
import os
import uuid

from .captcha_budget import SolveStopped
from .captcha_dom import eval_in_all_frames

logger = logging.getLogger("src.captcha_os_input")

_INSTALL = r"""
(function() {
    var key = __KEY__, selector = __SELECTOR__, expectedContext = __CONTEXT__;
    return visitAccessibleDocuments(function(doc, offsetX, offsetY, context) {
        if (expectedContext && context !== expectedContext) return null;
        var node = Array.from(doc.querySelectorAll(selector)).find(verificationElementVisible);
        if (!verificationElementVisible(node)) return null;
        var serial = 0, last = null;
        var frame = doc.defaultView.frameElement;
        function origin() {
            if (!frame) return {x:0, y:0};
            if (!verificationElementVisible(frame) || frame.contentDocument !== doc) return null;
            var r = frame.getBoundingClientRect();
            return {x:r.left+frame.clientLeft, y:r.top+frame.clientTop};
        }
        function read() {
            var offset = origin();
            if (!offset || !node.isConnected || !verificationElementVisible(node)) return null;
            var r = node.getBoundingClientRect();
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
                scale:window.devicePixelRatio || 1, event:observed};
        }
        function moved(event) {
            if (!event.isTrusted) return;
            last = {x:event.clientX, y:event.clientY, at:performance.now(),
                buttons:event.buttons, serial:++serial};
        }
        function pressed(event) { if (event.isTrusted) last = null; }
        doc.addEventListener('mousemove', moved, true);
        doc.addEventListener('mousedown', pressed, true);
        var expiry;
        window[key] = {read:read, close:function() {
            clearTimeout(expiry);
            doc.removeEventListener('mousemove', moved, true);
            doc.removeEventListener('mousedown', pressed, true); delete window[key];
        }};
        expiry = setTimeout(function() { if (window[key]) window[key].close(); }, 30000);
        return read();
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
        self.scale = 1.0
        self.installed = False

    def _evaluate(self, expression):
        result = self.solver._send_cdp(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "silent": True},
        )
        return (result or {}).get("result", {}).get("value")

    def _fail(self, reason):
        self.solver.last_failure_reason = "screen_mapping_" + reason

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
        )
        # Even a lost acknowledgement may have installed the listener.
        self.installed = True
        # Omnibox focus makes document.hasFocus() false even in the active window.
        # Require native window ownership; the trusted DOM hit is checked before press.
        if not self.solver._linux_window_has_focus(self.solver._linux_window_id):
            return self._fail("target_unavailable")
        snapshot = self._evaluate(eval_in_all_frames(expression))
        if not self._valid(snapshot):
            return self._fail("target_unavailable")
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
                return self._fail("target_unavailable")
            snapshot = self._evaluate(f"window[{json.dumps(self.key)}]?.read()")
            if not self._valid(snapshot) or float(snapshot["scale"]) != self.scale:
                return self._fail("target_unavailable")
            if any(
                abs(float(snapshot["rect"][k]) - float(self.rect[k])) > 1.5
                for k in ("x", "y", "width", "height")
            ):
                return self._fail("target_changed")
            event = snapshot.get("event")
            if not isinstance(event, dict) or event.get("buttons") != 0:
                return self._fail("pointer_unobserved")
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
                    return self._fail("pointer_unobserved")
                if not 0 <= age <= 1500:
                    return self._fail("pointer_unobserved")
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
                    return self._fail("target_unavailable")
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

    def close(self):
        if not self.installed:
            return
        try:
            self._evaluate(f"window[{json.dumps(self.key)}]?.close()")
        except SolveStopped:
            # The solve budget has expired; the target may already be closed.
            pass
        except Exception:
            logger.debug("[SOLVER] Pointer probe cleanup unavailable", exc_info=True)
        finally:
            self.installed = False
