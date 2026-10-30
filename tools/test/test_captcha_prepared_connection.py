"""A newly prepared target retains its single identity-first CDP connection."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src import captcha_cdp
from src.captcha_budget import SolveStopped
from src.captcha_deferral import TargetNavigationUnconfirmed
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_navigation_receipt import TARGET
from tools.test.test_captcha_target_open_recovery import stopping_budget

BOOTSTRAP = [
    "Runtime.evaluate",
    "Emulation.setUserAgentOverride",
    "Emulation.setTimezoneOverride",
    "Emulation.setLocaleOverride",
    "Page.addScriptToEvaluateOnNewDocument",
    "Runtime.evaluate",
    "Runtime.evaluate",
]


class ReplySocket:
    def __init__(self):
        self.connected = True
        self.timeout = 5
        self.messages = []
        self.closes = 0
        self.navigation = {"frameId": "frame", "loaderId": "loader"}

    def settimeout(self, value):
        self.timeout = value

    def gettimeout(self):
        return self.timeout

    def send(self, raw):
        self.messages.append(json.loads(raw))

    def recv(self):
        message = self.messages[-1]
        result = self.navigation if message["method"] == "Page.navigate" else {}
        return json.dumps({"id": message["id"], "result": result})

    def close(self):
        self.closes += 1
        self.connected = False


def connection_probe(monkeypatch, *, directory=False, target=TARGET):
    solver = CaptchaSolver(target_url=target, cdp_endpoint="http://127.0.0.1:9222")
    payload = {
        "id": "owned-tab",
        "type": "page",
        "url": "about:blank",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/owned-tab",
    }
    put = Mock(return_value=Mock(status_code=200, json=lambda: payload))
    monkeypatch.setattr(captcha_cdp.requests, "put", put)
    sockets = []

    def connect(*_args, **_kwargs):
        socket = ReplySocket()
        sockets.append(socket)
        return socket

    create = Mock(side_effect=connect)
    monkeypatch.setattr(captcha_cdp.websocket, "create_connection", create)
    config = {
        "CROW_BROWSER_USER_AGENT": "Mozilla/5.0 Chrome/151.0.0.0",
        "CROW_BROWSER_IDENTITY_FULL_VERSION": "151.0.0.0",
    }
    monkeypatch.setattr(
        captcha_cdp, "project_getenv", lambda k, d=None: config.get(k, d)
    )
    tabs = [{"id": "unrelated", "url": "https://example.org/"}] if directory else []
    monkeypatch.setattr(solver, "_get_json", lambda _: tabs)
    monkeypatch.setattr(solver, "_compact_cdp_pages_if_needed", lambda *_a, **_k: {})
    monkeypatch.setattr(solver, "_prune_duplicate_challenge_tabs", lambda _: {})
    return solver, payload, sockets, create, put


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize(
    "target", [TARGET, "https://sf-item.taobao.com/sf_item/123.htm"]
)
def test_opened_target_is_bootstrapped_once(monkeypatch, directory, target, caplog):
    solver, _, sockets, create, put = connection_probe(
        monkeypatch, directory=directory, target=target
    )
    with caplog.at_level("INFO", logger="src.captcha_cdp"):
        assert solver.connect_tab()
    assert create.call_count == put.call_count == len(sockets) == 1
    assert solver.ws is sockets[0] and sockets[0].closes == 0
    capture = ["Page.enable", "Network.enable"] if target == TARGET else []
    assert [m["method"] for m in sockets[0].messages] == [
        *BOOTSTRAP,
        *capture,
        "Page.navigate",
    ]
    assert sockets[0].messages[-1]["params"] == {"url": target}
    assert solver._navigation_receipt.target_url == target
    assert "Reusing prepared target connection" in caplog.text


@pytest.mark.parametrize("directory", [False, True])
def test_local_mock_keeps_normal_connection_without_navigation(monkeypatch, directory):
    solver, _, sockets, create, put = connection_probe(
        monkeypatch, directory=directory, target="file:///tmp/mock_slider.html"
    )
    assert solver.connect_tab()
    assert create.call_count == put.call_count == 1
    assert [m["method"] for m in sockets[0].messages] == BOOTSTRAP
    assert solver._navigation_receipt is None


@pytest.mark.parametrize(
    "invalid",
    [
        "no-receipt",
        "wrong-type",
        "wrong-id",
        "wrong-url",
        "unowned",
        "wrong-current-id",
        "wrong-ws",
        "disconnected",
        "unknown-connected",
        "no-ws",
    ],
)
def test_stale_or_disconnected_preparation_falls_back_to_attach_only(
    monkeypatch, invalid
):
    solver, payload, sockets, create, put = connection_probe(monkeypatch)
    assert solver._open_target_tab() is payload
    receipt = solver._navigation_receipt
    if invalid == "no-receipt":
        solver._navigation_receipt = None
    elif invalid == "wrong-type":
        solver._navigation_receipt = Mock()
    elif invalid == "wrong-id":
        solver._navigation_receipt = replace(receipt, target_id="other")
    elif invalid == "wrong-url":
        solver._navigation_receipt = replace(receipt, target_url=TARGET + "&page=3")
    elif invalid == "unowned":
        solver._opened_target_ids.clear()
    elif invalid == "wrong-current-id":
        solver.target_id = "other"
    elif invalid == "wrong-ws":
        solver.target_ws_url = "ws://localhost:9222/devtools/page/other"
    elif invalid == "disconnected":
        solver.ws.connected = False
    elif invalid == "unknown-connected":
        del solver.ws.connected
    elif invalid == "no-ws":
        solver.ws = None
    assert solver._connect_opened_target(payload)
    assert create.call_count == 2 and put.call_count == 1
    assert [m["method"] for m in sockets[1].messages] == BOOTSTRAP
    assert sum(m["method"] == "Page.navigate" for s in sockets for m in s.messages) == 1


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
def test_stop_after_open_cannot_reuse_or_reconnect(monkeypatch, directory, stop):
    solver, _, sockets, create, put = connection_probe(monkeypatch, directory=directory)
    trigger = stopping_budget(solver, stop)
    opening = solver._open_target_tab

    def open_then_stop():
        payload = opening()
        trigger()
        return payload

    monkeypatch.setattr(solver, "_open_target_tab", open_then_stop)
    reason = "deadline_exceeded" if stop == "deadline" else "cancelled"
    with pytest.raises(SolveStopped, match=reason):
        solver.connect_tab()
    assert create.call_count == put.call_count == 1
    assert sockets[0].closes == 1 and solver.ws is None
    assert solver._opened_target_ids == {"owned-tab"}


@pytest.mark.parametrize("directory", [False, True])
def test_uncertain_navigation_never_reconnects_or_replays(monkeypatch, directory):
    solver, _, sockets, create, put = connection_probe(monkeypatch, directory=directory)
    connect = create.side_effect

    def uncertain(*args, **kwargs):
        socket = connect(*args, **kwargs)
        socket.navigation = None
        return socket

    create.side_effect = uncertain
    with pytest.raises(TargetNavigationUnconfirmed):
        solver.connect_tab()
    assert create.call_count == put.call_count == 1
    assert [m["method"] for m in sockets[0].messages] == [
        *BOOTSTRAP,
        "Page.enable",
        "Network.enable",
        "Page.navigate",
    ]
    assert solver._navigation_receipt is None


def test_cached_target_still_gets_a_fresh_attachment(monkeypatch):
    solver, payload, sockets, create, put = connection_probe(monkeypatch)
    assert solver._open_target_tab() is payload
    monkeypatch.setattr(solver, "_get_json", lambda _: [dict(payload)])
    assert solver.connect_tab()
    assert create.call_count == 2 and put.call_count == 1
    assert sockets[0].closes == 1
    assert [m["method"] for m in sockets[1].messages] == BOOTSTRAP
