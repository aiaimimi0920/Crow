"""Native CDP probe identity, request selection and socket cleanup."""

import json

import pytest
import websocket

from tools import pc2_solver_cdp as cdp


def test_cdp_entrypoints_retain_native_owner():
    from tools import pc2_local_solver

    for name in cdp.__all__:
        value = getattr(cdp, name)
        assert getattr(pc2_local_solver, name) is value
        if value.__module__ == cdp.__name__:
            assert value.__globals__ is vars(cdp)


@pytest.mark.parametrize(
    ("tabs", "expected"),
    [
        (
            [{"type": "worker", "url": "worker"}, {"type": "page", "url": " page "}],
            "page",
        ),
        ([{"type": "iframe", "url": " fallback "}], "fallback"),
        ({"error": "unavailable"}, None),
    ],
)
def test_page_url_preserves_page_priority_and_legacy_fallback(
    monkeypatch, tabs, expected
):
    calls = []

    def fetch(url, *, timeout):
        calls.append((url, timeout))
        return tabs

    monkeypatch.setattr(cdp, "fetch_json", fetch)
    assert cdp.get_cdp_page_url("http://cdp/") == expected
    assert calls == [("http://cdp/json/list", 5)]


def test_request_revalidation_uses_live_candidates_and_exact_route():
    target = "https://sf.taobao.com/list/50025969__2.htm?page=4"
    request = {"target_url": target}
    assert cdp.match_solver_request_target_url(request, "", "http://cdp") == target
    assert cdp.match_solver_request_target_url(request, target, "http://cdp") == target
    assert (
        cdp.match_solver_request_target_url(
            request, target + "&__captcha_solver_bg=1", "http://cdp"
        )
        == target
    )
    assert (
        cdp.match_solver_request_target_url(
            request, "https://sf.taobao.com/list/50025969__2.htm?page=5", "http://cdp"
        )
        == ""
    )


def test_slider_probe_closes_failed_socket_before_trying_next_target(monkeypatch):
    sockets = []
    events = []

    class Socket:
        def __init__(self, url):
            self.url = url
            self.message = {}
            self.closed = False

        def settimeout(self, timeout):
            assert timeout == 5

        def send(self, payload):
            self.message = json.loads(payload)

        def recv(self):
            if self.url == "ws://bad":
                raise OSError("private diagnostic must not be logged")
            return json.dumps(
                {
                    "id": self.message["id"],
                    "result": {"result": {"value": {"found": True}}},
                }
            )

        def close(self):
            self.closed = True

    def connect(url, **kwargs):
        assert kwargs == {"suppress_origin": True, "timeout": 5}
        if sockets:
            assert sockets[-1].closed
        socket = Socket(url)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)
    monkeypatch.setattr(cdp, "log_event", events.append)
    monkeypatch.setattr(
        cdp,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {
                "id": key,
                "type": "page",
                "url": "https://example.test/" + key,
                "webSocketDebuggerUrl": "ws://" + key,
            }
            for key in ("bad", "good")
        ],
    )
    result = cdp.check_cdp_browser_for_slider("http://cdp")
    assert result["_target_id"] == "good"
    assert len(sockets) == 2 and all(socket.closed for socket in sockets)
    assert events == [
        {
            "kind": "cdp_slider_probe_target_error",
            "target_id": "bad",
            "error_type": "OSError",
        }
    ]
