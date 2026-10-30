"""Native CDP helpers release only the HTTP sessions they create."""

from types import SimpleNamespace

import pytest
from requests import ReadTimeout

from src import cdp_cookie_transport as transport

ENDPOINT = "http://fixture.invalid:9223"
WEBSOCKET = "ws://fixture.invalid:9223/devtools/browser/fixture"


class Cancelled(BaseException):
    pass


@pytest.fixture
def http(monkeypatch):
    sessions = []

    class Session:
        def __init__(self):
            self.trust_env = True
            self.calls = []
            self.close_calls = 0
            self.payload = {
                "webSocketDebuggerUrl": WEBSOCKET,
                "User-Agent": "fixture-UA",
            }
            self.error = None
            sessions.append(self)

        def get(self, url, **options):
            assert self.trust_env is False and self.close_calls == 0
            self.calls.append((url, options))
            if self.error:
                raise self.error
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: self.payload
            )

        def close(self):
            self.close_calls += 1

    monkeypatch.setattr(transport.requests, "Session", Session)
    monkeypatch.setattr(transport, "_load_cached_cdp_websocket", lambda _: "")
    monkeypatch.setattr(transport, "_write_cached_cdp_websocket", lambda *_: None)
    return SimpleNamespace(sessions=sessions, factory=Session)


@pytest.mark.parametrize("helper", ["health", "endpoint", "user_agent"])
@pytest.mark.parametrize("outcome", ["success", "timeout", "invalid", "cancelled"])
def test_owned_http_session_closes_on_every_exit(http, monkeypatch, helper, outcome):
    session = http.factory()
    monkeypatch.setattr(transport.requests, "Session", lambda: session)
    if outcome == "timeout":
        session.error = ReadTimeout("synthetic timeout")
    elif outcome == "invalid":
        session.payload = None
    elif outcome == "cancelled":
        session.error = Cancelled()
    invoke = {
        "health": transport.cdp_endpoint_is_healthy,
        "endpoint": transport._resolve_cdp_endpoint,
        "user_agent": transport.resolve_cdp_user_agent,
    }[helper]
    if outcome == "cancelled":
        with pytest.raises(Cancelled):
            invoke(ENDPOINT)
    else:
        result = invoke(ENDPOINT)
        expected = {
            "health": outcome == "success",
            "endpoint": WEBSOCKET if outcome == "success" else ENDPOINT,
            "user_agent": "fixture-UA"
            if outcome == "success"
            else transport.DEFAULT_USER_AGENT,
        }[helper]
        assert result == expected
    expected_calls = (
        2 if helper == "health" and outcome in ("timeout", "invalid") else 1
    )
    assert len(session.calls) == expected_calls
    assert session.close_calls == 1
    assert all(
        options["timeout"] == (3.0 if helper == "health" else 10)
        for _, options in session.calls
    )


@pytest.mark.parametrize(
    "outcome",
    ["success", "discovery", "connect", "send", "receive", "decode", "cancelled"],
)
def test_cookie_export_releases_http_and_websocket_on_failure(
    http, monkeypatch, outcome
):
    sockets = []
    if outcome == "discovery":

        def discovery(session, _endpoint):
            assert session.close_calls == 0
            raise ReadTimeout("synthetic discovery failure")

        monkeypatch.setattr(
            transport, "_resolve_cdp_websocket_for_cookie_export", discovery
        )

    class WebSocket:
        close_calls = 0

        def settimeout(self, _timeout):
            pass

        def send(self, payload):
            assert '"method": "Storage.getCookies"' in payload
            if outcome == "send":
                raise OSError("synthetic send failure")

        def recv(self):
            if outcome == "receive":
                raise OSError("synthetic receive failure")
            if outcome == "cancelled":
                raise Cancelled
            return (
                "invalid-json"
                if outcome == "decode"
                else '{"id":1,"result":{"cookies":[]}}'
            )

        def close(self):
            self.close_calls += 1

    def connect(url, **options):
        assert url == WEBSOCKET and options == {"timeout": 20}
        if outcome == "connect":
            raise OSError("synthetic connect failure")
        socket = WebSocket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(transport.websocket, "create_connection", connect)
    if outcome == "success":
        assert transport._export_cdp_cookies_via_websocket(ENDPOINT, ()) == []
    else:
        error = (
            Cancelled
            if outcome == "cancelled"
            else (ValueError if outcome == "decode" else OSError)
        )
        with pytest.raises(error):
            transport._export_cdp_cookies_via_websocket(ENDPOINT, ())
    assert len(http.sessions) == 1 and http.sessions[0].close_calls == 1
    assert all(socket.close_calls == 1 for socket in sockets)


def test_fast_paths_do_not_allocate_an_http_session(http):
    assert transport.cdp_endpoint_is_healthy("") is False
    assert transport.cdp_endpoint_is_healthy(WEBSOCKET) is True
    assert transport._resolve_cdp_endpoint(WEBSOCKET) == WEBSOCKET
    assert transport.resolve_cdp_user_agent(WEBSOCKET) == transport.DEFAULT_USER_AGENT
    assert http.sessions == []


def test_repeated_metadata_probes_do_not_retain_owned_sessions(http):
    for _ in range(100):
        assert transport.resolve_cdp_user_agent(ENDPOINT) == "fixture-UA"
    assert len(http.sessions) == 100
    assert all(session.close_calls == 1 for session in http.sessions)
