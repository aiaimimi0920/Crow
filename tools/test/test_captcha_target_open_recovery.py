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
    put = Mock(return_value=Mock(json=Mock(return_value=payload)))
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
    put.side_effect = [OSError("unavailable"), Mock(json=Mock(return_value=payload))]
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
