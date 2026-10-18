"""Bounded CDP interaction with exact reference targets, never the challenge page."""

import json
import random
import time

import websocket

from tools.pc2_reference_navigation import EMPTY_POINT, SNAPSHOT, safe_navigation
from tools.pc2_solver_manual_window import active_manual_window


class ReferencePage:
    def __init__(self, target):
        self.connection = websocket.create_connection(
            target["webSocketDebuggerUrl"], suppress_origin=True, timeout=2
        )
        self.sequence = 0
        self.depth = 0
        self.origin = target["url"]

    def call(self, method, params):
        if active_manual_window() and params.get("type") != "mouseReleased":
            raise OSError("Human authentication window became active")
        if time.monotonic() >= getattr(self, "deadline", float("inf")) and params.get("type") != "mouseReleased":
            raise TimeoutError("Reference browsing deadline reached")
        self.sequence += 1
        self.connection.send(
            json.dumps({"id": self.sequence, "method": method, "params": params})
        )
        # Bounded unsolicited events as well as socket timeout.
        deadline = min(time.monotonic() + 2, getattr(self, "deadline", float("inf")))
        for _ in range(64):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.connection.settimeout(remaining)
            result = json.loads(self.connection.recv())
            if result.get("id") == self.sequence:
                if result.get("error"):
                    raise OSError("Reference page command rejected")
                return result.get("result", {})
        raise OSError("Reference page response unavailable")

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        if result.get("exceptionDetails"):
            raise OSError("Reference page evaluation failed")
        return result.get("result", {}).get("value")

    def step(self):
        page = self.evaluate(SNAPSHOT)
        if not isinstance(page, dict) or not safe_navigation(
            page.get("url"), self.origin
        ):
            return False
        width, height = float(page["width"]), float(page["height"])
        if width < 40 or height < 40:
            return True
        x, y = random.uniform(20, width - 20), random.uniform(20, height - 20)
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        if random.random() < 0.35:
            self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": x,
                    "y": y,
                    "deltaX": 0,
                    "deltaY": random.choice((-120, 120)),
                },
            )
        elif self.evaluate(f"{EMPTY_POINT}({x},{y})"):
            self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
            try:
                pass
            finally:
                self.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        "x": x,
                        "y": y,
                        "button": "left",
                        "clickCount": 1,
                    },
                )
        links = [
            a
            for a in page.get("links", [])
            if safe_navigation(a.get("url"), self.origin)
            and a.get("url") != page["url"]
        ]
        if not self.depth and links and random.random() < 0.2:
            link = random.choice(links)
            # Navigate the validated URL directly, avoiding arbitrary site click handlers.
            self.call("Page.navigate", {"url": link["url"]})
            self.depth = 1
        return True

    def close(self):
        self.connection.close()
