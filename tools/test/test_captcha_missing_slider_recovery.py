"""Missing-slider recovery must not consume the only undelivered drag attempt."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from tools.test.test_captcha_solve_loading_transition import (
    AUTHENTICATED,
    FAILED,
    LOADING,
    SLIDER,
    TARGET,
    solve_probe,
)

READY = {"readyState": "complete", "href": TARGET, "hasSlider": True}
REJECTED = {**FAILED, "readyState": "complete", "href": TARGET, "hasSlider": False}


def recovery_probe(monkeypatch, after, *, restored=True, sliders=(None, SLIDER)):
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [REJECTED, *after], sliders=sliders
    )
    solver._reset_failed_nc_challenge.return_value = restored
    return solver, clock, reads, waits


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("loading", [False, True])
def test_restored_slider_uses_remaining_main_attempt(monkeypatch, restored, loading):
    solver, _, _, waits = recovery_probe(
        monkeypatch, ([LOADING] if loading else []) + [READY], restored=restored
    )
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    assert solver.last_failure_reason is None
    assert (0.25 in waits) is loading
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._do_drag.assert_called_once()
    assert solver._find_slider.call_count == 2
    solver._reload_page.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()


@pytest.mark.parametrize("restored", [False, True])
def test_retry_authentication_is_checked_before_attempt_exhaustion(
    monkeypatch, restored
):
    solver, _, _, _ = recovery_probe(monkeypatch, [AUTHENTICATED], restored=restored)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    solver._do_drag.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    solver._reload_page.assert_not_called()


def test_recovery_cannot_create_an_unbounded_no_slider_loop(monkeypatch):
    solver, _, _, _ = recovery_probe(
        monkeypatch,
        [READY, REJECTED, READY, REJECTED],
        sliders=(None, None, None, None),
    )
    # Each successful reset is followed by fresh slider evidence, then the next
    # lookup loses it again. Only the existing two recovery credits are usable.
    solver._confirm_missing_slider = Mock(side_effect=lambda summary: (None, summary))
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    assert solver._reset_failed_nc_challenge.call_count == 2
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()


def test_zero_recovery_budget_never_clicks_retry_widget(monkeypatch):
    solver, _, _, _ = recovery_probe(monkeypatch, [READY])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize("restored", [False, True])
def test_restoration_spends_existing_replay_credit_not_extra_input(
    monkeypatch, restored
):
    solver, _, _, _ = recovery_probe(monkeypatch, [READY, REJECTED], restored=restored)
    solver._wait_for_verification_success.return_value = False
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("ready_state", ["interactive", "complete"])
def test_foreign_recovered_slider_never_receives_drag(
    monkeypatch, restored, ready_state
):
    solver, _, _, _ = recovery_probe(
        monkeypatch,
        [{**READY, "href": TARGET.replace("123", "456"), "readyState": ready_state}],
        restored=restored,
    )
    assert solver.solve(max_attempts=2, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize(
    ("after", "reason"),
    [({"probeFailed": True}, "cdp_unavailable"), (LOADING, "challenge_loading")],
)
def test_uncertain_restoration_preserves_page(monkeypatch, restored, after, reason):
    solver, _, _, _ = recovery_probe(monkeypatch, [after], restored=restored)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == reason
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_after_retry_prevents_probe_or_new_input(monkeypatch, reason):
    solver, clock, reads, _ = recovery_probe(monkeypatch, [READY])
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)

    def stop():
        if reason == "cancelled":
            budget.event.set()
        else:
            clock[0] = 100
        return True

    solver._reset_failed_nc_challenge.side_effect = stop
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == reason
    assert reads[0] == 1
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize("state", ["authenticated", "blank", "foreign", "error"])
def test_recovery_requires_real_bound_payload_not_retry_return_value(
    monkeypatch, state
):
    from tools.test.test_captcha_dom_evaluation import DocumentSolver

    document = {
        "url": TARGET,
        "text": "auction evidence " * 12,
        "html": '<html><body><div id="J_StartPrice">123</div></body></html>',
    }
    if state == "blank":
        document["html"] = ""
    elif state == "foreign":
        document["url"] = TARGET.replace("123", "456")
    elif state == "error":
        document["text"] = "验证失败"
        document["nodes"] = [{"selectors": [".errloading"]}]
    summary = DocumentSolver(document, TARGET)._page_challenge_summary()
    solver, _, _, _ = recovery_probe(monkeypatch, [summary])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is (
        state == "authenticated"
    )
    solver._do_drag.assert_not_called()


def test_local_mock_keeps_original_main_attempt_contract(monkeypatch):
    solver, _, reads, _ = recovery_probe(monkeypatch, [READY])
    solver._is_local_mock_slider_target = Mock(return_value=True)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert reads[0] == 1
    solver._do_drag.assert_not_called()
