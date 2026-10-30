"""Cookie export must consume the owned CDP result, not an event or error."""

import json

import pytest

from src import cdp_cookie_transport as transport

ENDPOINT = "http://example.invalid"
ORIGINS = ("https://sf.taobao.com",)
COOKIES = [{"name": "fixture", "domain": ".taobao.com", "value": "private-cookie"}]
RESULT = {"id": 1, "result": {"cookies": COOKIES}}


class Socket:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.timeouts = []
        self.closed = False

    def send(self, payload):
        assert json.loads(payload) == {"id": 1, "method": "Storage.getCookies"}

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self):
        frame = next(self.frames)
        if isinstance(frame, BaseException):
            raise frame
        return json.dumps(frame)

    def close(self):
        self.closed = True


@pytest.fixture
def install(monkeypatch):
    monkeypatch.setattr(
        transport,
        "_resolve_cdp_websocket_for_cookie_export",
        lambda *_: "ws://example.invalid/devtools/browser/fixture",
    )

    def create(frames):
        socket = Socket(frames)
        monkeypatch.setattr(
            transport.websocket, "create_connection", lambda *_a, **_kw: socket
        )
        return socket

    return create


@pytest.mark.parametrize(
    "unrelated",
    [
        {"method": "Runtime.executionContextCreated", "params": {}},
        {"id": 2, "result": {"cookies": [{"domain": ".taobao.com", "name": "wrong"}]}},
        {"id": True, "result": {"cookies": []}},
        {"id": "1", "result": {"cookies": []}},
        {"result": {"cookies": []}},
    ],
)
def test_unrelated_message_is_not_a_cookie_result(install, unrelated):
    socket = install([unrelated, RESULT])
    assert transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS) == COOKIES
    assert socket.closed


@pytest.mark.parametrize(
    "frame",
    [
        {"id": 1, "error": {"code": -32000, "message": "private-cookie"}},
        {"id": 1},
        {"id": 1, "result": None},
        {"id": 1, "result": {}},
        {"id": 1, "result": {"cookies": None}},
        {"id": 1, "result": {"cookies": "private-cookie"}},
        {"id": 1, "result": {"cookies": [None]}},
        {"id": 1, "result": {"cookies": COOKIES}, "error": {}},
    ],
)
def test_owned_error_or_invalid_result_is_not_success(install, frame):
    socket = install([frame])
    with pytest.raises(RuntimeError) as caught:
        transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS)
    assert "private-cookie" not in str(caught.value)
    assert socket.closed


def test_explicit_empty_cookie_result_remains_valid(install):
    socket = install([{"id": 1, "result": {"cookies": []}}])
    assert transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS) == []
    assert socket.closed


@pytest.mark.parametrize("frame", [None, [], "private-cookie", 1])
def test_non_object_response_is_rejected(install, frame):
    socket = install([frame])
    with pytest.raises(TypeError) as caught:
        transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS)
    assert "private-cookie" not in str(caught.value)
    assert socket.closed


def test_events_share_one_receive_deadline(install, monkeypatch):
    socket = install([{"method": "Inspector.detached"}] * 3)
    clock = iter([100.0, 100.0, 107.0, 120.0])
    monkeypatch.setattr(transport.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS)
    assert socket.timeouts == [20.0, 13.0]
    assert socket.closed


def test_protocol_error_uses_existing_fallback(install, monkeypatch):
    socket = install([{"id": 1, "error": {"code": -32000}}])
    monkeypatch.setenv("CROW_CDP_RECONNECT_ATTEMPTS", "1")
    fallback = []

    def export(endpoint, origins):
        fallback.append((endpoint, origins))
        return COOKIES

    assert (
        transport.export_cdp_cookies(ENDPOINT, ORIGINS, playwright_export=export)
        == COOKIES
    )
    assert fallback == [(ENDPOINT, ORIGINS)]
    assert socket.closed


def test_cancellation_propagates_and_closes_socket(install):
    class Cancelled(BaseException):
        pass

    socket = install([Cancelled()])
    with pytest.raises(Cancelled):
        transport._export_cdp_cookies_via_websocket(ENDPOINT, ORIGINS)
    assert socket.closed
