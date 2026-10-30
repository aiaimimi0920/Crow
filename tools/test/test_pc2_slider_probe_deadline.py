"""Lightweight CDP commands must not renew their deadline on unrelated frames."""

import json
from types import SimpleNamespace

import pytest
import websocket

from tools import pc2_solver_cdp as owner


@pytest.fixture
def probe(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    sockets, events = [], []
    monkeypatch.setattr(
        owner, "time", SimpleNamespace(monotonic=lambda: clock.now), raising=False
    )
    monkeypatch.setattr(owner, "log_event", events.append)

    class Socket:
        def __init__(self, key, options):
            self.key, self.options = key, options
            self.message, self.timeouts = {}, []
            self.received, self.closed = 0, False

        def settimeout(self, timeout):
            assert 0 < timeout <= 5
            self.timeouts.append(timeout)

        def advance(self, seconds):
            if seconds > self.timeouts[-1]:
                clock.now += self.timeouts[-1]
                raise websocket.WebSocketTimeoutException("synthetic private timeout")
            clock.now += seconds

        def send(self, payload):
            self.message = json.loads(payload)
            self.received = 0
            self.advance(self.options.get("send_seconds", 0))

        def recv(self):
            if self.options.get("cancel"):
                raise KeyboardInterrupt
            self.received += 1
            blocked = self.message["method"] == "Runtime.enable"
            self.advance(self.options.get("recv_seconds", 1 if blocked else 0))
            if blocked and self.received <= self.options.get("frames", 0):
                if self.options.get("frame_kind") == "unmatched":
                    return json.dumps({"id": -1, "result": {}})
                return json.dumps({"method": "Runtime.consoleAPICalled", "params": {}})
            return json.dumps(
                {
                    "id": self.message["id"],
                    "result": {"result": {"value": {"found": True}}},
                }
            )

        def close(self):
            self.closed = True

    def run(options, *, second=False):
        keys = ["slow", "healthy"] if second else ["slow"]
        tabs = [
            {
                "id": key,
                "type": "page",
                "url": "https://example.invalid/" + key,
                "webSocketDebuggerUrl": "ws://fixture/" + key,
            }
            for key in keys
        ]
        monkeypatch.setattr(owner, "fetch_json", lambda *_a, **_kw: tabs)

        def connect(url, **kwargs):
            assert kwargs == {"suppress_origin": True, "timeout": 5}
            assert not sockets or sockets[-1].closed
            key = url.rsplit("/", 1)[-1]
            socket = Socket(key, options if key == "slow" else {})
            sockets.append(socket)
            return socket

        monkeypatch.setattr(websocket, "create_connection", connect)
        result = owner.check_cdp_browser_for_slider("http://fixture")
        return result

    return SimpleNamespace(run=run, clock=clock, sockets=sockets, events=events)


@pytest.mark.parametrize("frame_kind", ["notification", "unmatched"])
def test_unrelated_frames_cannot_extend_five_second_command_deadline(probe, frame_kind):
    result = probe.run({"frames": 12, "frame_kind": frame_kind})
    assert result is None
    assert probe.clock.now <= 105
    assert probe.sockets[0].received <= 5
    assert probe.sockets[0].closed
    assert probe.events == [
        {
            "kind": "cdp_slider_probe_target_error",
            "target_id": "slow",
            "error_type": "TimeoutError",
        }
    ]


def test_timed_out_target_is_closed_before_existing_next_target(probe):
    result = probe.run({"frames": 12}, second=True)
    assert result["_target_id"] == "healthy"
    assert probe.clock.now <= 106
    assert len(probe.sockets) == 2 and all(socket.closed for socket in probe.sockets)


def test_send_time_consumes_the_same_command_budget(probe):
    result = probe.run({"send_seconds": 4, "recv_seconds": 2})
    assert result is None
    assert probe.clock.now <= 105
    assert probe.sockets[0].timeouts[-1] <= 1
    assert probe.sockets[0].closed


def test_matching_response_at_expired_deadline_is_not_accepted(probe):
    assert probe.run({"recv_seconds": 5}) is None
    assert probe.clock.now == 105
    assert probe.sockets[0].closed


def test_in_budget_notifications_preserve_response_matching_and_cleanup(probe):
    result = probe.run({"frames": 2})
    assert result["_target_id"] == "slow"
    assert probe.clock.now == 103
    assert not probe.events and probe.sockets[0].closed
    assert any(timeout < 5 for timeout in probe.sockets[0].timeouts)


def test_each_command_retains_its_own_original_budget(probe):
    result = probe.run({"recv_seconds": 3})
    assert result["_target_id"] == "slow"
    assert probe.clock.now == 106
    assert not probe.events and probe.sockets[0].closed


def test_base_exception_is_not_swallowed_and_still_closes_socket(probe):
    with pytest.raises(KeyboardInterrupt):
        probe.run({"cancel": True})
    assert probe.sockets[0].closed
