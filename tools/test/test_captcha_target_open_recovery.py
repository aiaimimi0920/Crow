"""Retry target preparation without multiplying slow challenge renderers."""

from threading import Event
from unittest.mock import Mock

import pytest

from src import captcha_cdp
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver


def opening_solver(monkeypatch):
    solver = CaptchaSolver(target_url="https://sf.taobao.com/list/test.htm")
    payload = {
        "id": "owned-tab",
        "url": "about:blank",
        "webSocketDebuggerUrl": "ws://localhost/owned-tab",
    }
    put = Mock(return_value=Mock(status_code=200, json=Mock(return_value=payload)))
    monkeypatch.setattr(captcha_cdp.requests, "put", put)
    return solver, payload, put


@pytest.mark.parametrize("first_failure", [False, OSError("navigation timeout")])
def test_preparation_retry_reuses_the_created_target(monkeypatch, first_failure):
    solver, payload, put = opening_solver(monkeypatch)
    preparation = Mock(side_effect=[first_failure, True])
    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", preparation)
    assert solver._open_target_tab() is payload
    assert put.call_count == 1
    assert preparation.call_count == 2
    assert all(call.args[0] is payload for call in preparation.call_args_list)
    assert solver._opened_target_ids == {"owned-tab"}


def test_failed_preparation_is_bounded_to_one_created_target(monkeypatch):
    solver, _, put = opening_solver(monkeypatch)
    preparation = Mock(return_value=False)
    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", preparation)
    assert solver._open_target_tab() is None
    assert put.call_count == 1
    assert preparation.call_count == 3
    assert solver._opened_target_ids == {"owned-tab"}


def test_failed_create_can_retry_before_a_target_is_known(monkeypatch):
    solver, payload, put = opening_solver(monkeypatch)
    put.side_effect = [OSError("unavailable"), put.return_value]
    monkeypatch.setattr(
        solver, "_prepare_opened_target_before_navigation", Mock(return_value=True)
    )
    assert solver._open_target_tab() is payload
    assert put.call_count == 2


def test_preparation_cancellation_does_not_create_another_target(monkeypatch):
    solver, _, put = opening_solver(monkeypatch)
    cancelled = Event()
    solver._solve_budget = SolveBudget(cancel_event=cancelled)
    preparation = Mock(side_effect=lambda *_args: cancelled.set() or False)
    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", preparation)
    with pytest.raises(SolveStopped):
        solver._open_target_tab()
    assert put.call_count == 1
    assert preparation.call_count == 1


def test_local_mock_open_does_not_enter_identity_preparation(monkeypatch):
    solver, payload, put = opening_solver(monkeypatch)
    solver.target_url = "file:///tmp/mock_slider.html"
    preparation = Mock(
        side_effect=AssertionError("local mock has no identity preflight")
    )
    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", preparation)
    assert solver._open_target_tab() is payload
    assert put.call_count == 1
    preparation.assert_not_called()


def stopping_budget(solver, stop):
    now = [10.0]
    cancelled = Event()
    solver._solve_budget = SolveBudget(
        deadline=11.0,
        clock=lambda: now[0],
        cancel_event=None if stop == "checker" else cancelled,
    )
    if stop == "checker":
        solver.cancel_checker = cancelled.is_set

    def trigger():
        if stop == "deadline":
            now[0] = 11.0
        else:
            cancelled.set()

    return trigger


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
@pytest.mark.parametrize("outcome", ["raise", "success", "failure"])
def test_stop_in_final_preparation_is_not_an_ordinary_open_result(
    monkeypatch, stop, outcome
):
    solver, _, put = opening_solver(monkeypatch)
    trigger = stopping_budget(solver, stop)
    calls = []

    def prepare(*_args):
        calls.append(True)
        if len(calls) < 3:
            return False
        trigger()
        if outcome == "raise":
            solver._bounded_io_timeout(5)
        return outcome == "success"

    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", prepare)
    reason = "deadline_exceeded" if stop == "deadline" else "cancelled"
    with pytest.raises(SolveStopped, match=reason):
        solver._open_target_tab()
    assert put.call_count == 1
    assert len(calls) == 3
    assert solver._opened_target_ids == {"owned-tab"}


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
@pytest.mark.parametrize("identity_first", [False, True])
def test_stop_during_create_retains_ownership_without_preparing_target(
    monkeypatch, stop, identity_first
):
    solver, payload, put = opening_solver(monkeypatch)
    if not identity_first:
        solver.target_url = "file:///tmp/mock_slider.html"
    trigger = stopping_budget(solver, stop)
    reply = put.return_value
    put.side_effect = lambda *_a, **_k: trigger() or reply
    preparation = Mock(side_effect=AssertionError("stopped target must not navigate"))
    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", preparation)
    reason = "deadline_exceeded" if stop == "deadline" else "cancelled"
    with pytest.raises(SolveStopped, match=reason):
        solver._open_target_tab()
    assert put.call_count == 1
    assert solver._opened_target_ids == {payload["id"]}
    assert solver.target_id is None
    preparation.assert_not_called()


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
def test_stopped_open_exits_solve_and_preserves_the_recovery_page(monkeypatch, stop):
    solver, _, put = opening_solver(monkeypatch)
    trigger = stopping_budget(solver, stop)
    budget = solver._solve_budget
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_k: budget)
    monkeypatch.setattr(solver, "_get_json", lambda _endpoint: [])
    calls = []

    def prepare(*_args):
        calls.append(True)
        if len(calls) == 3:
            trigger()
            return True
        return False

    monkeypatch.setattr(solver, "_prepare_opened_target_before_navigation", prepare)
    forbidden = Mock(side_effect=AssertionError("stopped open must exit solve"))
    for name in (
        "_headed_playwright_enabled",
        "_find_slider",
        "_close_cdp_target",
        "_reload_page",
    ):
        monkeypatch.setattr(solver, name, forbidden)

    assert solver.solve() is False
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )
    assert put.call_count == 1 and len(calls) == 3
    assert solver._opened_target_ids == {"owned-tab"}
    assert solver._solve_budget is None
    assert not solver.lock.locked()
    forbidden.assert_not_called()
