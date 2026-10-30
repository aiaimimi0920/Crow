"""Lifecycle HTTP must stop between targets and share the solver's I/O budget."""

from threading import Event
from types import SimpleNamespace

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

PAGE = {
    "id": "first",
    "type": "page",
    "url": "https://fixture.local/challenge",
    "webSocketDebuggerUrl": "ws://fixture/first",
}


def attach_budget(solver, *, stopped=None):
    now = [10.0]
    event = Event()
    budget = SolveBudget(deadline=10.25, clock=lambda: now[0], cancel_event=event)
    if stopped == "deadline":
        now[0] = budget.deadline
    elif stopped == "event":
        event.set()
    elif stopped == "checker":
        solver.cancel_checker = lambda: True
    solver._solve_budget = budget
    return now, event


def mock_http(monkeypatch, on_request=None):
    calls = []

    def request(url, *, timeout):
        calls.append((url, timeout))
        if on_request:
            on_request()
        return SimpleNamespace(status_code=200, json=lambda: {**PAGE, "id": "blank"})

    monkeypatch.setattr("src.captcha_target_lifecycle.requests.get", request)
    monkeypatch.setattr("src.captcha_target_lifecycle.requests.put", request)
    return calls


@pytest.mark.parametrize("method", ["_close_cdp_target", "_open_keepalive_tab"])
def test_lifecycle_http_timeout_is_capped_to_remaining_budget(monkeypatch, method):
    solver = CaptchaSolver()
    attach_budget(solver)
    calls = mock_http(monkeypatch)
    args = ("owned",) if method == "_close_cdp_target" else ()
    assert getattr(solver, method)(*args)
    assert len(calls) == 1
    assert calls[0][1] == pytest.approx(0.25)


@pytest.mark.parametrize("method", ["_close_cdp_target", "_open_keepalive_tab"])
@pytest.mark.parametrize("stopped", ["deadline", "event", "checker"])
def test_stopped_lifecycle_does_not_start_http(monkeypatch, method, stopped):
    solver = CaptchaSolver()
    attach_budget(solver, stopped=stopped)
    calls = mock_http(monkeypatch)
    args = ("owned",) if method == "_close_cdp_target" else ()
    with pytest.raises(SolveStopped):
        getattr(solver, method)(*args)
    assert calls == []


@pytest.mark.parametrize("stop", ["deadline", "event"])
def test_owned_cleanup_stops_after_first_completed_close(monkeypatch, stop):
    solver = CaptchaSolver()
    solver._opened_target_ids.update({"first", "second", "third"})
    now, event = attach_budget(solver)

    def finish_first():
        if stop == "deadline":
            now[0] = 11
        else:
            event.set()

    calls = mock_http(monkeypatch, finish_first)
    assert solver._close_owned_target_tabs() == 1
    assert len(calls) == 1
    closed = calls[0][0].rsplit("/", 1)[-1]
    assert solver._opened_target_ids == {"first", "second", "third"} - {closed}


def test_cleanup_handles_cancellation_between_entry_check_and_http(monkeypatch):
    solver = CaptchaSolver()
    solver._opened_target_ids.add("first")
    attach_budget(solver)
    checks = iter([False, True])
    solver.cancel_checker = lambda: next(checks)
    calls = mock_http(monkeypatch)
    assert solver._close_owned_target_tabs() == 0
    assert solver._opened_target_ids == {"first"}
    assert calls == []


@pytest.mark.parametrize("stopped", ["deadline", "event", "checker"])
def test_expired_compaction_neither_opens_nor_closes_pages(monkeypatch, stopped):
    solver = CaptchaSolver()
    solver._opened_target_ids.update({"first", "second"})
    attach_budget(solver, stopped=stopped)
    monkeypatch.setattr(solver, "_page_target_limit", lambda: 2)
    calls = mock_http(monkeypatch)
    with pytest.raises(SolveStopped):
        solver._compact_cdp_pages_if_needed([PAGE, {**PAGE, "id": "second"}])
    assert calls == []


def test_compaction_cancelled_during_keepalive_does_not_close_pages(monkeypatch):
    solver = CaptchaSolver()
    solver._opened_target_ids.update({"first", "second"})
    _, event = attach_budget(solver)
    monkeypatch.setattr(solver, "_page_target_limit", lambda: 2)
    calls = mock_http(monkeypatch, event.set)
    with pytest.raises(SolveStopped):
        solver._compact_cdp_pages_if_needed([PAGE, {**PAGE, "id": "second"}])
    assert len(calls) == 1
    assert "/json/new?about:blank" in calls[0][0]


def test_duplicate_pruning_stops_before_next_close(monkeypatch):
    solver = CaptchaSolver(target_url=PAGE["url"])
    _, event = attach_budget(solver)
    solver._opened_target_ids.update({"first", "second", "third"})
    monkeypatch.setattr(solver, "_is_challenge_tab", lambda _tab: True)
    calls = mock_http(monkeypatch, event.set)
    with pytest.raises(SolveStopped):
        solver._prune_duplicate_challenge_tabs(
            [PAGE, {**PAGE, "id": "second"}, {**PAGE, "id": "third"}]
        )
    assert len(calls) == 1
    assert calls[0][0].endswith("/json/close/second")
    assert solver._opened_target_ids == {"first", "third"}


@pytest.mark.parametrize("stop", ["deadline", "event"])
def test_stop_during_final_cleanup_cannot_publish_success(monkeypatch, stop):
    solver = CaptchaSolver(target_url=PAGE["url"])
    solver._opened_target_ids.add("first")
    now, event = attach_budget(solver)
    budget = solver._solve_budget
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    monkeypatch.setattr(
        solver, "_preflight_current_challenge", lambda: {"already_authenticated": True}
    )
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: True)

    def stop_during_close():
        if stop == "deadline":
            now[0] = 11
        else:
            event.set()

    calls = mock_http(monkeypatch, stop_during_close)
    assert solver.solve() is False
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )
    assert len(calls) == 1
    assert not solver._opened_target_ids
    assert solver._solve_budget is None
    assert not solver.lock.locked()
