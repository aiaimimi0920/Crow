"""An ambiguous transport send must never reuse its CDP request identity."""

import pytest
import websocket

from tools.test.test_captcha_cdp_command_budget import probe


@pytest.mark.parametrize("budget", [False, True])
@pytest.mark.parametrize("failure", [OSError, websocket.WebSocketTimeoutException])
@pytest.mark.parametrize(
    "stale",
    [{"result": {"old": True}}, {"error": {"code": -32000}}],
    ids=["late-success", "late-error"],
)
def test_failed_send_cannot_relabel_a_late_reply_as_the_next_command(
    monkeypatch, budget, failure, stale
):
    solver, sock, _ = probe(
        monkeypatch,
        [(0.1, {"id": 1, **stale}), (0.1, {"id": 2, "result": {"current": True}})],
        budget=budget,
    )
    send = sock.send

    def ambiguous_send(raw):
        send(raw)
        if len(sock.messages) == 1:
            raise failure("synthetic send failure after write")

    monkeypatch.setattr(sock, "send", ambiguous_send)
    assert solver._send_cdp("Runtime.evaluate", {"expression": "void 0"}) is None
    assert solver._send_cdp("Page.getLayoutMetrics") == {"current": True}
    assert [message["id"] for message in sock.messages] == [1, 2]
    assert [message["method"] for message in sock.messages] == [
        "Runtime.evaluate",
        "Page.getLayoutMetrics",
    ]
    assert solver.message_id == 3 and sock.timeout == 5
    assert not sock.frames


@pytest.mark.parametrize("failure", [OSError, websocket.WebSocketTimeoutException])
def test_best_effort_release_also_reserves_identity_before_send(monkeypatch, failure):
    solver, sock, _ = probe(
        monkeypatch,
        [(0.1, {"id": 1, "result": {}}), (0.1, {"id": 2, "result": {"current": True}})],
        budget=True,
    )
    solver._cdp_mouse_down = True
    solver._cdp_mouse_position = (100, 50)
    send = sock.send

    def ambiguous_send(raw):
        send(raw)
        if len(sock.messages) == 1:
            raise failure("synthetic release send failure after write")

    monkeypatch.setattr(sock, "send", ambiguous_send)
    solver._release_cdp_mouse()
    assert not solver._cdp_mouse_down
    assert solver._send_cdp("Page.getLayoutMetrics") == {"current": True}
    assert [message["id"] for message in sock.messages] == [1, 2]
    assert sock.messages[0]["params"]["type"] == "mouseReleased"
    assert sock.messages[0]["params"]["buttons"] == 0
    assert solver.message_id == 3 and not sock.frames


def test_serialization_failure_starts_no_transport_or_identity(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [(0.1, {"id": 1, "result": {}})])
    assert solver._send_cdp("Runtime.evaluate", {"invalid": object()}) is None
    assert not sock.messages and solver.message_id == 1
    assert solver._send_cdp("Page.getLayoutMetrics") == {}
    assert [message["id"] for message in sock.messages] == [1]


def test_expired_budget_reserves_no_identity(monkeypatch):
    solver, sock, now = probe(monkeypatch, [], budget=True)
    now[0] = 201
    assert solver._send_cdp("Page.getLayoutMetrics") is None
    assert not sock.messages and solver.message_id == 1
    assert solver.last_failure_reason == "deadline_exceeded"


def test_release_serialization_failure_sends_nothing_and_clears_tracking(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [])
    solver._cdp_mouse_down = True
    solver._cdp_mouse_position = (object(), 50)
    solver._release_cdp_mouse()
    assert not sock.messages and solver.message_id == 1
    assert not solver._cdp_mouse_down


def test_timeout_setup_failure_reserves_no_identity(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [])
    settimeout = sock.settimeout

    def fail_setup(value):
        if value != 5:
            raise OSError("synthetic timeout setup failure")
        settimeout(value)

    monkeypatch.setattr(sock, "settimeout", fail_setup)
    monkeypatch.setattr(solver, "_bounded_io_timeout", lambda seconds: 0.25)
    assert solver._send_cdp("Page.getLayoutMetrics") is None
    assert not sock.messages and solver.message_id == 1
