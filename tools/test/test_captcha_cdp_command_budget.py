"""CDP command waits share one monotonic budget across send and unrelated frames."""

import json
from threading import Event

import pytest
import websocket

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver


class ClockSocket:
    def __init__(self, now, frames, *, timeout=5, send_delay=0, cooperative=True):
        self.now = now
        self.frames = list(frames)
        self.timeout = timeout
        self.send_delay = send_delay
        self.cooperative = cooperative
        self.timeouts = []
        self.messages = []
        self.closed = False

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeouts.append(value)
        self.timeout = value

    def send(self, raw):
        self.messages.append(json.loads(raw))
        self.now[0] += self.send_delay

    def recv(self):
        delay, payload = self.frames.pop(0)
        if self.cooperative and self.timeout is not None and delay > self.timeout:
            self.now[0] += self.timeout
            raise websocket.WebSocketTimeoutException("synthetic timeout")
        self.now[0] += delay
        return json.dumps(payload() if callable(payload) else payload)

    def close(self):
        self.closed = True


def probe(monkeypatch, frames, *, budget=False, **socket_args):
    now = [100.0]
    monkeypatch.setattr("src.captcha_cdp_command.time.monotonic", lambda: now[0])
    monkeypatch.setattr("src.captcha_cdp_command.time.time", lambda: now[0])
    solver = CaptchaSolver()
    sock = ClockSocket(now, frames, **socket_args)
    solver.ws = sock
    if budget:
        solver._solve_budget = SolveBudget(deadline=200, clock=lambda: now[0])
    return solver, sock, now


@pytest.mark.parametrize("budget", [False, True])
@pytest.mark.parametrize(
    "unrelated", [{"method": "Page.frameStoppedLoading"}, {"id": 999, "result": {}}]
)
def test_unrelated_frames_do_not_restart_the_response_budget(
    monkeypatch, budget, unrelated
):
    solver, sock, now = probe(
        monkeypatch,
        [(4.8, unrelated), (0.4, {"id": 1, "result": {"ok": True}})],
        budget=budget,
    )
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == pytest.approx(105)
    assert sock.timeout == 5
    assert len(sock.messages) == 1


@pytest.mark.parametrize("budget", [False, True])
def test_slow_send_consumes_the_same_command_budget(monkeypatch, budget):
    solver, sock, now = probe(
        monkeypatch,
        [(2, {"id": 1, "result": {"ok": True}})],
        budget=budget,
        send_delay=4,
    )
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == pytest.approx(105)
    assert sock.timeout == 5


@pytest.mark.parametrize("budget", [False, True])
def test_noncooperative_late_reply_is_not_accepted(monkeypatch, budget):
    solver, sock, now = probe(
        monkeypatch,
        [(6, {"id": 1, "result": {"ok": True}})],
        budget=budget,
        cooperative=False,
    )
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == 106
    assert not sock.closed


@pytest.mark.parametrize("stop", ["event", "deadline"])
def test_stop_during_matching_reply_does_not_return_success(monkeypatch, stop):
    cancel = Event()
    solver, sock, now = probe(monkeypatch, [], budget=True)
    solver._solve_budget.event = cancel

    def late_reply():
        if stop == "event":
            cancel.set()
        else:
            now[0] = 201
        return {"id": 1, "result": {"ok": True}}

    sock.frames = [(0.1, late_reply)]
    assert solver._send_cdp("Runtime.evaluate") is None
    assert solver.last_failure_reason == (
        "cancelled" if stop == "event" else "deadline_exceeded"
    )
    assert sock.closed and solver.ws is None


def test_wall_clock_jump_cannot_skip_the_reply(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [(0.1, {"id": 1, "result": {"ok": True}})])
    wall = iter([100, 10000])
    monkeypatch.setattr("src.captcha_cdp_command.time.time", lambda: next(wall))
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert len(sock.frames) == 0


@pytest.mark.parametrize("timeout", [None, 0.25, 5])
def test_existing_socket_timeout_is_restored_after_success(monkeypatch, timeout):
    solver, sock, _ = probe(
        monkeypatch,
        [(0.1, {"id": 1, "result": {"ok": True}})],
        timeout=timeout,
        budget=True,
    )
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert sock.timeout == timeout


def test_shorter_unbudgeted_socket_timeout_is_not_expanded(monkeypatch):
    solver, sock, now = probe(monkeypatch, [(1, {"id": 1, "result": {}})], timeout=0.25)
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == 100.25
    assert sock.timeout == 0.25


@pytest.mark.parametrize("budget,success", [(False, False), (True, True)])
def test_screenshot_preserves_existing_receive_limits(monkeypatch, budget, success):
    solver, sock, _ = probe(
        monkeypatch, [(8, {"id": 1, "result": {"data": "fixture"}})], budget=budget
    )
    result = solver._send_cdp("Page.captureScreenshot")
    assert (result == {"data": "fixture"}) is success
    assert sock.timeout == 5


def test_unrelated_frame_does_not_change_expected_id_or_duplicate_send(monkeypatch):
    solver, sock, _ = probe(
        monkeypatch,
        [(1, {"id": 999, "result": {"wrong": True}}), (1, {"id": 1, "result": {}})],
    )
    assert solver._send_cdp("Runtime.evaluate") == {}
    assert solver.message_id == 2
    assert len(sock.messages) == 1


def test_expired_solver_budget_starts_no_send(monkeypatch):
    solver, sock, now = probe(monkeypatch, [], budget=True)
    now[0] = 201
    assert solver._send_cdp("Runtime.evaluate") is None
    assert not sock.messages and solver.last_failure_reason == "deadline_exceeded"


def test_shorter_solver_budget_remains_authoritative(monkeypatch):
    solver, sock, now = probe(
        monkeypatch,
        [(2, {"method": "Page.frameStoppedLoading"}), (1, {"id": 1, "result": {}})],
        budget=True,
    )
    solver._solve_budget.deadline = 102.5
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == 102.5
    assert solver.last_failure_reason == "deadline_exceeded"
    assert sock.closed


def test_a_small_final_wait_does_not_shrink_the_next_command(monkeypatch):
    solver, sock, _ = probe(
        monkeypatch,
        [
            (4.8, {"method": "Page.frameStoppedLoading"}),
            (0.1, {"id": 1, "result": {}}),
            (1, {"id": 2, "result": {"ok": True}}),
        ],
        budget=True,
    )
    assert solver._send_cdp("Runtime.evaluate") == {}
    assert sock.timeout == 5
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert sock.timeout == 5 and len(sock.messages) == 2


def test_late_send_starts_no_receive(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [(0, {"id": 1, "result": {}})], send_delay=6)
    assert solver._send_cdp("Runtime.evaluate") is None
    assert len(sock.frames) == 1


def test_protocol_error_keeps_the_socket_timeout(monkeypatch):
    solver, sock, _ = probe(
        monkeypatch,
        [(0.1, {"id": 1, "error": {"code": -32601}})],
        timeout=0.25,
        budget=True,
    )
    assert solver._send_cdp("Runtime.evaluate") is None
    assert sock.timeout == 0.25
