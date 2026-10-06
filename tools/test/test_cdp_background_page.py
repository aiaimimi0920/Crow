"""Background creation must never fall back to foreground navigation."""

import json

import pytest

from tools import cdp_background_page as subject
from tools import taobao_login_health as health


class Connection:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply)

    def settimeout(self, timeout):
        assert 0 < timeout <= 3

    def close(self):
        self.closed = True


@pytest.fixture
def setup(monkeypatch):
    closed = []
    connection = Connection([{"id": 1, "result": {"targetId": "owned"}}])
    target = {"id": "owned", "type": "page", "webSocketDebuggerUrl": "ws://owned"}
    monkeypatch.setattr(health, "list_cdp_targets", lambda *_: [target])
    monkeypatch.setattr(health, "cdp_page_target_limit", lambda: 8)
    monkeypatch.setattr(
        health, "close_cdp_target", lambda _, value: closed.append(value)
    )
    monkeypatch.setattr(subject.time, "sleep", lambda _: None)

    def read(_, path):
        assert path == "/json/version", "foreground HTTP creation is forbidden"
        return {"webSocketDebuggerUrl": "ws://browser"}

    def connect(url, **kwargs):
        assert url == "ws://browser"
        assert kwargs == {"suppress_origin": True, "timeout": 3}
        return connection

    monkeypatch.setattr(health, "read_cdp_json", read)
    monkeypatch.setattr(subject.websocket, "create_connection", connect)
    return connection, target, closed


def test_create_background_once_ignoring_events(setup):
    connection, target, closed = setup
    connection.replies = iter(
        [
            {"method": "Target.targetCreated"},
            {"id": 1, "result": {"targetId": "owned"}},
        ]
    )
    assert subject.open_background_page("http://fixture", "about:blank") == target
    assert connection.sent == [
        {
            "id": 1,
            "method": "Target.createTarget",
            "params": {"url": "about:blank", "background": True},
        }
    ]
    assert connection.closed
    assert not closed


def test_capacity_does_not_compact_or_connect(monkeypatch, setup):
    connection, _, closed = setup
    monkeypatch.setattr(health, "cdp_page_target_limit", lambda: 1)
    monkeypatch.setattr(
        health, "compact_cdp_pages_if_needed", lambda *_: pytest.fail("compact")
    )
    with pytest.raises(RuntimeError, match="capacity"):
        subject.open_background_page("http://fixture", "about:blank")
    assert not connection.sent and not connection.closed and not closed


@pytest.mark.parametrize(
    "reply",
    [
        {"id": 1, "error": {"message": "rejected"}},
        {"id": 1, "result": {}},
        TimeoutError("lost response"),
    ],
)
def test_failed_creation_never_retries_or_closes_foreign_target(setup, reply):
    connection, _, closed = setup
    connection.replies = iter([reply])
    with pytest.raises((RuntimeError, TimeoutError)):
        subject.open_background_page("http://fixture", "about:blank")
    assert len(connection.sent) == 1
    assert connection.closed and not closed


def test_missing_metadata_closes_only_acknowledged_owned_target(monkeypatch, setup):
    connection, _, closed = setup
    foreign = {"id": "foreign", "type": "page", "webSocketDebuggerUrl": "ws://foreign"}
    monkeypatch.setattr(health, "list_cdp_targets", lambda *_: [foreign])
    with pytest.raises(RuntimeError, match="unavailable"):
        subject.open_background_page("http://fixture", "about:blank")
    assert closed == ["owned"]
    assert connection.closed


def test_missing_browser_endpoint_does_not_create(monkeypatch, setup):
    connection, _, closed = setup
    monkeypatch.setattr(health, "read_cdp_json", lambda *_: {})
    with pytest.raises(RuntimeError, match="endpoint unavailable"):
        subject.open_background_page("http://fixture", "about:blank")
    assert not connection.sent and not closed
