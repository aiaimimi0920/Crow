"""No browser or mouse: exercise solver cancellation, retries, and cleanup."""
import json
import threading
import time

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver


def retry_solver(monkeypatch):
    solver = CaptchaSolver()
    monkeypatch.setattr(solver, "_preflight_current_challenge", lambda: {})
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: True)
    monkeypatch.setattr(solver, "connect_tab", lambda: False)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: solver._opened_target_ids.clear())
    return solver


def test_connection_retry_wait_obeys_total_deadline_and_releases_lock(monkeypatch):
    solver = retry_solver(monkeypatch)
    solver._opened_target_ids.add("solver-owned-test-tab")
    started = time.monotonic()
    assert solver.solve(deadline=started + 0.05) is False
    assert time.monotonic() - started < 1
    assert solver.last_failure_reason == "deadline_exceeded"
    assert not solver.lock.locked()
    assert solver._solve_budget is None
    assert not solver._opened_target_ids


def test_cancel_event_wakes_retry_without_waiting_five_seconds(monkeypatch):
    solver = retry_solver(monkeypatch)
    cancel = threading.Event()
    entered = threading.Event()
    monkeypatch.setattr(solver, "connect_tab", lambda: entered.set() or False)
    result = []
    thread = threading.Thread(target=lambda: result.append(solver.solve(cancel_event=cancel)))
    thread.start()
    try:
        assert entered.wait(1)
        cancel.set()
        thread.join(timeout=1)
        assert result == [False]
        assert solver.last_failure_reason == "cancelled"
        assert not solver.lock.locked()
    finally:
        cancel.set()
        thread.join(timeout=2)


def test_waiting_for_busy_solver_does_not_mutate_running_state(monkeypatch):
    solver = retry_solver(monkeypatch)
    solver.last_failure_reason = "active-run-marker"
    solver.lock.acquire()
    try:
        assert solver.solve(deadline=time.monotonic() + 0.02) is False
        assert solver.lock.locked()
        assert solver.last_failure_reason == "active-run-marker"
    finally:
        solver.lock.release()


def test_late_success_is_not_published_and_manual_page_is_preserved(monkeypatch):
    solver = retry_solver(monkeypatch)
    budget = SolveBudget(deadline=2, clock=lambda: 1)
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)

    def late_success():
        budget.clock = lambda: 3
        return {"already_authenticated": True}

    monkeypatch.setattr(solver, "_preflight_current_challenge", late_success)
    assert solver.solve() is False
    assert solver.last_failure_reason == "deadline_exceeded"
    budget.clock = lambda: 1
    budget.reason = None
    monkeypatch.setattr(solver, "_preflight_current_challenge", lambda: {"manual_required": True})
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: pytest.fail("Manual page must remain open"))
    assert solver.solve() is False
    assert solver.last_failure_reason == "manual_required"


def test_io_timeout_is_capped_and_expired_budget_never_starts_network(monkeypatch):
    solver = CaptchaSolver()
    solver._solve_budget = SolveBudget(deadline=11, clock=lambda: 10)
    assert solver._bounded_io_timeout(5) == 1
    solver._solve_budget.clock = lambda: 12
    monkeypatch.setattr("src.captcha_target.requests.get", lambda *args, **kwargs: pytest.fail("No expired network call"))
    with pytest.raises(SolveStopped):
        solver._get_json("list")


def test_drag_expiration_releases_pressed_cdp_button(monkeypatch):
    solver = CaptchaSolver()
    now = [0.0]
    events = []

    class AdvancingEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            now[0] += seconds

    class Socket:
        def settimeout(self, value):
            assert value <= 0.1

        def send(self, raw):
            events.append(json.loads(raw)["params"])

        def close(self):
            pass

    solver.ws = Socket()
    monkeypatch.setattr(solver, "_send_cdp", lambda _method, params: events.append(params) or {})
    monkeypatch.setattr("src.captcha_slider.random.uniform", lambda low, high: low)
    budget = SolveBudget(deadline=0.13, cancel_event=AdvancingEvent(), clock=lambda: now[0])
    with pytest.raises(SolveStopped), budget.scope(solver):
        solver._do_drag(50, 60, 100)
    assert [event["type"] for event in events] == ["mouseMoved", "mouseMoved", "mousePressed", "mouseReleased"]
    assert solver.last_failure_reason == "deadline_exceeded"
    assert solver.ws is None
    assert solver._cdp_mouse_down is False


def test_reload_wait_and_expired_cleanup_do_not_extend_deadline(monkeypatch):
    solver = CaptchaSolver()
    solver._opened_target_ids.add("retained-manual-tab")
    monkeypatch.setattr(solver, "_send_cdp", lambda *args, **kwargs: {})
    monkeypatch.setattr(solver, "_close_cdp_target", lambda *_: pytest.fail("Expired cleanup must not start I/O"))
    start = time.monotonic()
    budget = SolveBudget(deadline=start + 0.02)
    with budget.scope(solver):
        solver._reload_page()
        assert solver._stop_if_cancelled()
        assert solver._close_owned_target_tabs() == 0
    assert time.monotonic() - start < 1
    assert solver._opened_target_ids == {"retained-manual-tab"}
