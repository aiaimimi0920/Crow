"""Recovery probes must not restart a document still mounting its challenge."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_nc_retry
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

TARGET = "https://sf.taobao.com/list/50025969__2.htm?page=3&location_code=31"


def recovery_solver(monkeypatch):
    solver = CaptchaSolver(target_url=TARGET)
    clock = [0.0]
    monkeypatch.setattr(
        captcha_nc_retry,
        "time",
        SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0]),
    )
    solver._login_wait_seconds = Mock(return_value=30)
    solver._focus_os_window = Mock()
    solver._bring_to_front = Mock()
    solver._wait_interruptibly = lambda seconds: clock.__setitem__(
        0, clock[0] + seconds
    )
    solver._recover_authenticated_list_page = Mock(return_value=False)
    return solver, clock


@pytest.mark.parametrize("mounting_state", ["interactive", "complete"])
def test_delayed_challenge_widget_reaches_slider_instead_of_manual(
    monkeypatch, mounting_state
):
    solver, clock = recovery_solver(monkeypatch)
    document_started = [0.0]

    def summary():
        visible = clock[0] - document_started[0] >= 12
        return {
            "href": TARGET,
            "readyState": "complete" if visible else mounting_state,
            "hardBlock": True,
            "challengePresent": True,
            "hasSlider": visible,
        }

    def navigate_again():
        document_started[0] = clock[0]
        clock[0] += 3.2
        return False

    solver.connect_tab = Mock(return_value=True)
    solver._page_challenge_summary = summary
    solver._recover_authenticated_list_page.side_effect = navigate_again
    solver._reset_failed_nc_challenge = Mock(return_value=False)
    solver._send_cdp = Mock(side_effect=AssertionError("No browser I/O allowed"))
    result = solver._preflight_current_challenge()
    assert result["has_slider"] is True
    assert result["manual_required"] is False
    assert clock[0] == 15
    solver._recover_authenticated_list_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._send_cdp.assert_not_called()


@pytest.mark.parametrize("ready", ["loading", "interactive"])
def test_unsettled_document_does_not_trigger_repeated_recovery_navigation(
    monkeypatch, ready
):
    solver, clock = recovery_solver(monkeypatch)
    solver._page_challenge_summary = Mock(
        return_value={"href": TARGET, "readyState": ready}
    )
    assert solver._poll_until_authenticated() is False
    assert clock[0] == 30
    solver._recover_authenticated_list_page.assert_not_called()


def test_probe_failure_is_not_permission_to_navigate(monkeypatch):
    solver, clock = recovery_solver(monkeypatch)
    solver._page_challenge_summary = Mock(return_value={"probeFailed": True})
    assert solver._poll_until_authenticated() is False
    solver._recover_authenticated_list_page.assert_not_called()
    assert clock[0] == 0


def test_complete_nonlogin_document_keeps_existing_recovery_probe(monkeypatch):
    solver, _ = recovery_solver(monkeypatch)
    solver._page_challenge_summary = Mock(
        return_value={"href": TARGET, "readyState": "complete"}
    )
    solver._recover_authenticated_list_page.return_value = True
    assert solver._poll_until_authenticated() is True
    solver._recover_authenticated_list_page.assert_called_once_with()


def test_login_wait_does_not_navigate_away_from_human_login(monkeypatch):
    solver, clock = recovery_solver(monkeypatch)
    solver._page_challenge_summary = lambda: {
        "href": "https://login.taobao.com/",
        "readyState": "complete",
        "loginRequired": True,
        "authenticatedPage": clock[0] >= 10,
    }
    assert solver._poll_until_authenticated() is True
    assert clock[0] == 10
    solver._recover_authenticated_list_page.assert_not_called()


@pytest.mark.parametrize("cancelled", [False, True])
def test_readiness_wait_preserves_existing_solve_budget(monkeypatch, cancelled):
    solver, clock = recovery_solver(monkeypatch)
    solver._page_challenge_summary = Mock(return_value={"readyState": "interactive"})
    event = SimpleNamespace(
        is_set=lambda: cancelled and clock[0] >= 1,
        wait=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    solver._solve_budget = SolveBudget(
        deadline=1 if not cancelled else 30,
        clock=lambda: clock[0],
        cancel_event=event,
    )
    solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
    reason = "cancelled" if cancelled else "deadline_exceeded"
    with pytest.raises(SolveStopped, match=reason):
        solver._poll_until_authenticated()
    if cancelled:
        assert 1 <= clock[0] <= 1.1
    else:
        assert clock[0] == pytest.approx(1)
    solver._recover_authenticated_list_page.assert_not_called()
