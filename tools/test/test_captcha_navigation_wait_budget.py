"""Only budgeted navigation may wait longer, without replay or longer I/O slices."""

from threading import Event

import pytest
import websocket

from src.captcha_deferral import TargetNavigationUnconfirmed
from tools.test.cdp_navigation_wait_fixtures import navigation_probe
from tools.test.test_captcha_target_open_recovery import opening_solver

ACK = {"frameId": "frame", "loaderId": "loader"}


@pytest.mark.parametrize("delay", [0.1, 5, 7, 12, 14.9])
@pytest.mark.parametrize("previous_timeout", [None, 0.25, 5])
def test_navigation_waits_for_the_same_ack_in_bounded_receive_slices(
    monkeypatch, delay, previous_timeout
):
    solver, socket, now = navigation_probe(
        monkeypatch, [(delay, {"id": 1, "result": ACK})], timeout=previous_timeout
    )
    assert solver._send_cdp("Page.navigate") == ACK
    assert now[0] == pytest.approx(100 + delay)
    assert socket.timeout == previous_timeout
    assert len(socket.messages) == 1 and solver.message_id == 2
    assert all(0 < wait <= 5 for wait in socket.waits)


@pytest.mark.parametrize("delay", [15, 15.1, 100])
def test_navigation_cannot_accept_an_ack_at_or_after_the_command_deadline(
    monkeypatch, delay
):
    solver, socket, now = navigation_probe(
        monkeypatch, [(delay, {"id": 1, "result": ACK})]
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 115
    assert socket.waits == [5, 5, 5]
    assert len(socket.messages) == 1 and socket.timeout == 5
    assert solver.last_failure_reason is None


@pytest.mark.parametrize("budget", [False, True])
def test_ordinary_queries_keep_the_original_command_deadline(monkeypatch, budget):
    solver, socket, now = navigation_probe(
        monkeypatch, [(7, {"id": 1, "result": ACK})], budget=budget
    )
    assert solver._send_cdp("Runtime.evaluate") is None
    assert now[0] == 105 and socket.waits == [5]
    assert len(socket.messages) == 1 and socket.timeout == 5


def test_similarly_named_navigation_command_keeps_the_ordinary_limit(monkeypatch):
    solver, socket, now = navigation_probe(monkeypatch, [(7, {"id": 1, "result": ACK})])
    assert solver._send_cdp("Page.navigateToHistoryEntry") is None
    assert now[0] == 105 and len(socket.messages) == 1


@pytest.mark.parametrize("timeout", [None, 0.25, 5])
def test_unbudgeted_navigation_does_not_expand_existing_limits(monkeypatch, timeout):
    solver, socket, now = navigation_probe(
        monkeypatch, [(7, {"id": 1, "result": ACK})], budget=False, timeout=timeout
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 100 + (5 if timeout is None else timeout)
    assert socket.timeout == timeout and len(socket.waits) == 1


@pytest.mark.parametrize("budget,deadline", [(False, 105), (True, 115)])
def test_unrelated_frames_do_not_extend_navigation_or_change_request_identity(
    monkeypatch, budget, deadline
):
    solver, socket, now = navigation_probe(
        monkeypatch,
        [
            (1, {"method": "Page.frameStoppedLoading"}),
            (1, {"id": 999}),
            (20, {"id": 1, "result": ACK}),
        ],
        budget=budget,
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == deadline
    assert len(socket.messages) == 1 and socket.messages[0]["id"] == 1
    assert all(wait <= 5 for wait in socket.waits)


def test_slow_send_consumes_the_navigation_command_deadline(monkeypatch):
    solver, socket, now = navigation_probe(
        monkeypatch, [(12, {"id": 1, "result": ACK})], send_delay=4
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 115 and socket.waits == [5, 5, 1]
    assert socket.timeouts[0] == 5 and len(socket.messages) == 1


@pytest.mark.parametrize("remaining", [2.5, 8])
def test_shorter_solve_deadline_closes_connection_without_success(
    monkeypatch, remaining
):
    solver, socket, now = navigation_probe(
        monkeypatch, [(20, {"id": 1, "result": ACK})]
    )
    solver._solve_budget.deadline = 100 + remaining
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 100 + remaining
    assert solver.last_failure_reason == "deadline_exceeded"
    assert solver.ws is None and socket.closed and len(socket.messages) == 1


@pytest.mark.parametrize("stop", ["event", "checker"])
def test_cancellation_during_receive_is_observed_within_one_original_slice(
    monkeypatch, stop
):
    cancel = Event()
    solver, socket, now = navigation_probe(
        monkeypatch,
        [(20, {"id": 1, "result": ACK})],
        on_wait=lambda at: cancel.set() if at >= 106 else None,
    )
    if stop == "event":
        solver._solve_budget.event = cancel
    else:
        monkeypatch.setattr(solver, "_cancel_requested", cancel.is_set)
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 110 and socket.waits == [5, 5]
    assert solver.last_failure_reason == "cancelled"
    assert solver.ws is None and socket.closed and len(socket.messages) == 1


@pytest.mark.parametrize("stop", ["event", "checker", "deadline"])
def test_matching_ack_cannot_win_over_a_stop(monkeypatch, stop):
    solver, socket, now = navigation_probe(monkeypatch, [])

    def stopped_ack():
        if stop == "event":
            solver._solve_budget.event.set()
        elif stop == "checker":
            monkeypatch.setattr(solver, "_cancel_requested", lambda: True)
        else:
            solver._solve_budget.deadline = now[0]
        return {"id": 1, "result": ACK}

    socket.frames = [(7, stopped_ack)]
    assert solver._send_cdp("Page.navigate") is None
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )
    assert socket.closed and len(socket.messages) == 1


@pytest.mark.parametrize(
    "failure",
    [
        {"id": 1, "error": {"code": -32000}},
        OSError("closed socket"),
        websocket.WebSocketConnectionClosedException("closed"),
    ],
)
def test_explicit_errors_after_a_polling_timeout_do_not_retry_or_replay(
    monkeypatch, failure
):
    solver, socket, now = navigation_probe(monkeypatch, [(7, failure)], timeout=0.25)
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 107 and socket.waits == [5, 5]
    assert socket.timeout == 0.25 and len(socket.messages) == 1


def test_noncooperative_late_ack_is_not_accepted(monkeypatch):
    solver, socket, now = navigation_probe(
        monkeypatch, [(16, {"id": 1, "result": ACK})], cooperative=False
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 116 and len(socket.messages) == 1
    assert socket.timeout == 5


def test_timed_out_navigation_cannot_supply_the_next_commands_ack(monkeypatch):
    solver, socket, now = navigation_probe(
        monkeypatch,
        [(16, {"id": 1, "result": ACK}), (0.1, {"id": 2, "result": {"ok": True}})],
    )
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 115 and socket.timeout == 5
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert [message["id"] for message in socket.messages] == [1, 2]
    assert socket.timeout == 5


def test_immediate_socket_timeouts_cannot_spin_until_the_total_deadline(monkeypatch):
    solver, socket, now = navigation_probe(monkeypatch, [])
    calls = []

    def timed_out():
        calls.append(True)
        raise websocket.WebSocketTimeoutException("immediate timeout")

    monkeypatch.setattr(socket, "recv", timed_out)
    assert solver._send_cdp("Page.navigate") is None
    assert now[0] == 100 and len(calls) == 3
    assert len(socket.messages) == 1 and socket.timeout == 5


def test_expired_navigation_starts_no_send_or_request_identity(monkeypatch):
    solver, socket, now = navigation_probe(monkeypatch, [])
    solver._solve_budget.deadline = now[0]
    assert solver._send_cdp("Page.navigate") is None
    assert socket.messages == [] and solver.message_id == 1
    assert solver.last_failure_reason == "deadline_exceeded" and socket.closed


@pytest.mark.parametrize(
    "reply",
    [
        ACK,
        {},
        {"frameId": "frame", "errorText": "not accepted"},
        {"frameId": "frame", "isDownload": True},
        {"frameId": "frame", "loaderId": None},
    ],
)
def test_delayed_navigation_reply_still_requires_the_existing_receipt_contract(
    monkeypatch, reply
):
    transport, socket, _ = navigation_probe(
        monkeypatch, [(7, {"id": 1, "result": reply})]
    )
    solver, payload, put = opening_solver(monkeypatch)
    solver._solve_budget = transport._solve_budget
    monkeypatch.setattr(
        solver, "_connect_to_target", lambda *_: setattr(solver, "ws", socket) or True
    )
    if reply == ACK:
        assert solver._open_target_tab() is payload
        assert solver._navigation_receipt.frame_id == "frame"
        assert payload["url"] == solver.target_url
    else:
        with pytest.raises(TargetNavigationUnconfirmed):
            solver._open_target_tab()
        assert solver._navigation_receipt is None
    assert put.call_count == len(socket.messages) == 1
    assert solver._opened_target_ids == {"owned-tab"}
