"""A missing navigation ACK cannot authorize replay or recovery-page cleanup."""

import json
from unittest.mock import Mock

import pytest
import websocket

from src.captcha_budget import SolveStopped
from src.captcha_deferral import TargetNavigationUnconfirmed
from src.captcha_nc_retry import NCRetryDeferred
from tools import pc2_solver_execution as execution
from tools.test.test_captcha_target_open_recovery import opening_solver, stopping_budget


@pytest.mark.parametrize("outcome", [None, OSError("navigation reply SECRET")])
def test_uncertain_navigation_is_not_replayed_by_target_preparation(
    monkeypatch, caplog, outcome
):
    solver, _, put = opening_solver(monkeypatch)
    connect = Mock(return_value=True)
    send = Mock(side_effect=[outcome, {}, {}])
    monkeypatch.setattr(solver, "_connect_to_target", connect)
    monkeypatch.setattr(solver, "_send_cdp", send)
    with pytest.raises(TargetNavigationUnconfirmed) as deferred:
        solver._open_target_tab()
    assert deferred.value.reason == "cdp_unavailable"
    assert "SECRET" not in str(deferred.value)
    assert put.call_count == connect.call_count == send.call_count == 1
    assert send.call_args.args[0] == "Page.navigate"
    assert solver._opened_target_ids == {"owned-tab"}
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("outcome", [None, OSError("navigation reply SECRET")])
@pytest.mark.parametrize("max_attempts", [1, 3])
def test_uncertain_navigation_exits_real_solve_without_fallback_or_cleanup(
    monkeypatch, max_attempts, outcome
):
    solver, _, put = opening_solver(monkeypatch)
    socket = Mock()
    connect = Mock(side_effect=lambda *_: setattr(solver, "ws", socket) or True)
    navigate = Mock(side_effect=[outcome])
    fallback = Mock(return_value=False)
    close_page = Mock()
    monkeypatch.setattr(solver, "_get_json", lambda _: [])
    monkeypatch.setattr(solver, "_connect_to_target", connect)
    monkeypatch.setattr(solver, "_send_cdp", navigate)
    monkeypatch.setattr(solver, "_headed_playwright_enabled", fallback)
    monkeypatch.setattr(solver, "_close_cdp_target", close_page)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _: None)
    monkeypatch.setattr(solver, "_recover_authenticated_list_page", lambda: False)
    assert solver.solve(max_attempts=max_attempts) is False
    assert put.call_count == connect.call_count == navigate.call_count == 1
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver._opened_target_ids == {"owned-tab"}
    assert solver._solve_budget is None and not solver.lock.locked()
    assert solver.ws is None
    socket.close.assert_called_once_with()
    fallback.assert_not_called()
    close_page.assert_not_called()


def test_connection_failure_before_navigation_can_still_retry(monkeypatch):
    solver, payload, put = opening_solver(monkeypatch)
    connect = Mock(side_effect=[False, True])
    navigate = Mock(return_value={"frameId": "frame", "loaderId": "loader"})
    monkeypatch.setattr(solver, "_connect_to_target", connect)
    monkeypatch.setattr(solver, "_send_cdp", navigate)
    assert solver._open_target_tab() is payload
    assert put.call_count == 1 and connect.call_count == 2
    navigate.assert_called_once_with("Page.navigate", {"url": solver.target_url})
    assert payload["url"] == solver.current_target_url == solver.target_url


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
@pytest.mark.parametrize("outcome", ["missing", "raise", "success", "stopped"])
def test_navigation_stop_keeps_cancellation_priority_and_page(
    monkeypatch, stop, outcome
):
    solver, _, put = opening_solver(monkeypatch)
    trigger = stopping_budget(solver, stop)
    budget = solver._solve_budget
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_k: budget)
    monkeypatch.setattr(solver, "_get_json", lambda _: [])
    monkeypatch.setattr(solver, "_connect_to_target", Mock(return_value=True))

    def navigate(*_args):
        trigger()
        if outcome == "raise":
            raise OSError("navigation reply SECRET")
        if outcome == "stopped":
            solver._bounded_io_timeout(5)
        return (
            {"frameId": "frame", "loaderId": "loader"} if outcome == "success" else None
        )

    navigation = Mock(side_effect=navigate)
    forbidden = Mock(side_effect=AssertionError("stopped navigation must exit"))
    monkeypatch.setattr(solver, "_send_cdp", navigation)
    for name in ("_headed_playwright_enabled", "_close_cdp_target", "_reload_page"):
        monkeypatch.setattr(solver, name, forbidden)
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )
    assert put.call_count == navigation.call_count == 1
    assert solver._opened_target_ids == {"owned-tab"}
    assert solver._solve_budget is None and not solver.lock.locked()
    forbidden.assert_not_called()


@pytest.mark.parametrize("error", [websocket.WebSocketTimeoutException, OSError])
def test_real_cdp_lost_navigation_reply_sends_once_and_closes_socket(
    monkeypatch, error
):
    solver, _, put = opening_solver(monkeypatch)
    socket = Mock()
    socket.gettimeout.return_value = 5
    socket.recv.side_effect = error("lost navigation ACK")
    monkeypatch.setattr(solver, "_get_json", lambda _: [])
    monkeypatch.setattr(
        solver,
        "_connect_to_target",
        lambda *_: setattr(solver, "ws", socket) or True,
    )
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert put.call_count == socket.send.call_count == 1
    assert socket.recv.call_count == (
        3 if error is websocket.WebSocketTimeoutException else 1
    )
    assert json.loads(socket.send.call_args.args[0])["method"] == "Page.navigate"
    assert solver.message_id == 2
    assert solver.ws is None
    socket.close.assert_called_once_with()


def test_next_solve_can_reuse_the_retained_page_without_navigation(monkeypatch):
    solver, payload, put = opening_solver(monkeypatch)
    tabs = []
    monkeypatch.setattr(solver, "_get_json", lambda _: tabs)
    connect = Mock(return_value=True)
    navigation = Mock(return_value=None)
    monkeypatch.setattr(solver, "_connect_to_target", connect)
    monkeypatch.setattr(solver, "_send_cdp", navigation)
    assert solver.solve(max_attempts=3) is False
    # The page may finish navigation after its ACK was lost. Only a fresh
    # directory and document probe in a later solve can establish its state.
    tabs.append(dict(payload, url=solver.target_url))
    preflight = Mock(return_value={"authenticatedPage": True})
    monkeypatch.setattr(solver, "_page_challenge_summary", preflight)
    close = Mock(return_value=True)
    monkeypatch.setattr(solver, "_close_cdp_target", close)
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None
    assert put.call_count == navigation.call_count == preflight.call_count == 1
    assert connect.call_count == 2
    close.assert_called_once_with("owned-tab")
    assert solver._opened_target_ids == set()
    assert solver._solve_budget is None and not solver.lock.locked()


def test_direct_stop_from_navigation_is_not_converted_to_uncertainty(monkeypatch):
    solver, _, _ = opening_solver(monkeypatch)
    monkeypatch.setattr(solver, "_connect_to_target", Mock(return_value=True))
    monkeypatch.setattr(
        solver, "_send_cdp", Mock(side_effect=SolveStopped("cancelled"))
    )
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._open_target_tab()


@pytest.mark.parametrize("deferred", [TargetNavigationUnconfirmed, NCRetryDeferred])
def test_uncertain_exit_finishes_socket_and_state_before_unlock(monkeypatch, deferred):
    solver, _, _ = opening_solver(monkeypatch)
    socket = Mock()
    solver.ws = socket
    monkeypatch.setattr(
        solver, "_preflight_current_challenge", Mock(side_effect=deferred())
    )
    cleanup = solver._close_solver_ws
    observed = []

    def close():
        observed.append(
            (
                solver.lock.locked(),
                solver._solve_budget is not None,
                solver.last_failure_reason,
            )
        )
        cleanup()

    monkeypatch.setattr(solver, "_close_solver_ws", close)
    assert solver.solve(max_attempts=3) is False
    assert observed == [(True, True, "cdp_unavailable")]
    socket.close.assert_called_once_with()
    assert solver._solve_budget is None and not solver.lock.locked()


def test_real_navigation_deferral_retains_reason_through_worker_reply(monkeypatch):
    solver, _, put = opening_solver(monkeypatch)
    monkeypatch.setattr(solver, "_get_json", lambda _: [])
    monkeypatch.setattr(solver, "_connect_to_target", Mock(return_value=True))
    navigate = Mock(return_value=None)
    monkeypatch.setattr(solver, "_send_cdp", navigate)
    monkeypatch.setattr(execution, "_solver_class", lambda: lambda **_: solver)
    monkeypatch.setattr(execution, "log_event", lambda _: None)
    monkeypatch.setattr("tools.pc2_solver_diagnostics.log_event", lambda _: None)
    record = Mock()
    monkeypatch.setattr(execution, "record_failed_drags", record)
    connection = Mock()
    execution._run_solver_process_entry(
        connection, "offline", solver.target_url, 3, None, 0
    )
    connection.send.assert_called_once_with(
        {"success": False, "failure_reason": "cdp_unavailable"}
    )
    connection.close.assert_called_once_with()
    assert put.call_count == navigate.call_count == 1
    assert solver._opened_target_ids == {"owned-tab"}
    assert record.call_args.kwargs == {"allow_open": False}
