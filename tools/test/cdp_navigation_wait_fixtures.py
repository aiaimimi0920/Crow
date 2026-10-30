"""Virtual socket that retains a pending CDP frame across receive timeouts."""

import json

import websocket

from tools.test.test_captcha_cdp_command_budget import ClockSocket, probe


class NavigationSocket(ClockSocket):
    def __init__(self, *args, on_wait=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_wait = on_wait
        self.waits = []

    def recv(self):
        self.waits.append(self.timeout)
        delay, payload = self.frames[0]
        timed_out = (
            self.cooperative and self.timeout is not None and delay > self.timeout
        )
        elapsed = self.timeout if timed_out else delay
        self.now[0] += elapsed
        if self.on_wait is not None:
            self.on_wait(self.now[0])
        if timed_out:
            self.frames[0] = (delay - elapsed, payload)
            raise websocket.WebSocketTimeoutException("synthetic polling timeout")
        self.frames.pop(0)
        if isinstance(payload, BaseException):
            raise payload
        return json.dumps(payload() if callable(payload) else payload)


def navigation_probe(monkeypatch, frames, *, budget=True, **kwargs):
    solver, _, now = probe(monkeypatch, [], budget=budget)
    socket = NavigationSocket(now, frames, **kwargs)
    solver.ws = socket
    return solver, socket, now
