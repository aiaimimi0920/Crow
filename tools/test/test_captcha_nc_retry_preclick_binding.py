"""NC retry input must not precede the current requested-document check."""

from unittest.mock import Mock

import pytest

from src.captcha_nc_retry import NCRetryTargetUnconfirmed
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_nc_retry_uncertain import retry_click_probe
from tools.test.test_captcha_solve_loading_transition import (
    FAILED,
    SLIDER,
    TARGET,
    solve_probe,
)

SEED = "https://sf.taobao.com/list/all.htm?location_code=3301&page=2"


def ready(target=TARGET, **changes):
    return {"href": target, "readyState": "complete", **changes}


def probe(monkeypatch, observed, target=TARGET):
    solver, _, _, _ = solve_probe(monkeypatch, [observed], sliders=[SLIDER])
    solver.target_url = target
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    retry_click_probe(solver)
    solver._nc_retry_outcome = Mock(return_value={"authenticated": False})
    return solver


def deferred_reset(solver):
    try:
        solver._reset_failed_nc_challenge()
    except NCRetryTargetUnconfirmed as error:
        return error.reason
    return None


@pytest.mark.parametrize(
    ("target", "observed", "reason"),
    [
        (TARGET, ready(TARGET.replace("123", "456")), "slider_not_found"),
        (TARGET, ready(SEED), "slider_not_found"),
        (SEED, ready(SEED.replace("page=2", "page=1")), "slider_not_found"),
        (SEED, ready(SEED.replace("3301", "3302")), "slider_not_found"),
        (SEED, ready(SEED.split("?", 1)[0]), "slider_not_found"),
        (TARGET, {}, "cdp_unavailable"),
        (TARGET, {"href": TARGET}, "slider_not_found"),
        (TARGET, ready(readyState="loading"), "challenge_loading"),
        (TARGET, ready(probeFailed=True), "cdp_unavailable"),
    ],
)
def test_unbound_preclick_document_never_receives_retry_input(
    monkeypatch, target, observed, reason
):
    solver = probe(monkeypatch, observed, target)
    assert deferred_reset(solver) == reason
    solver._click_css_point.assert_not_called()
    solver._nc_retry_outcome.assert_not_called()


@pytest.mark.parametrize("entry", ["preflight", "missing_slider", "after_drag"])
def test_full_solve_defers_without_cleanup_navigation_or_more_input(monkeypatch, entry):
    solver, _, _, _ = solve_probe(monkeypatch, [ready(**FAILED)], sliders=[SLIDER])
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    solver._wait_for_verification_success.return_value = False
    if entry == "preflight":
        solver._preflight_current_challenge = (
            CaptchaSolver._preflight_current_challenge.__get__(solver)
        )
    elif entry == "missing_slider":
        solver._find_slider.side_effect = None
        solver._find_slider.return_value = None
    retry_click_probe(solver)
    solver._nc_retry_outcome = Mock(return_value={"authenticated": False})
    solver._refresh_challenge_summary = Mock(
        return_value=ready(TARGET.replace("123", "456"), **FAILED)
    )
    solver.ws = socket = Mock()
    solver._opened_target_ids.update({"owned"})
    solver.target_id = "owned"

    assert solver.solve(max_attempts=2, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    solver._click_css_point.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    solver._nc_retry_outcome.assert_not_called()
    assert solver._opened_target_ids == {"owned"}
    assert solver.ws is None and socket.close.call_count == 1
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("target", [TARGET, SEED])
@pytest.mark.parametrize("state", ["interactive", "complete"])
def test_bound_retry_preserves_existing_candidate_sequence(monkeypatch, target, state):
    observed = ready(target + "/_____tmd_____/verify", readyState=state)
    # Seed challenge suffix belongs in the path, before its identity query.
    if target == SEED:
        observed["href"] = SEED.replace(".htm?", ".htm/_____tmd_____/verify?")
    solver = probe(monkeypatch, observed, target)
    solver._nc_retry_outcome.side_effect = [
        {"authenticated": False},
        {"slider": SLIDER},
    ]
    assert solver._reset_failed_nc_challenge() is True
    assert solver._click_css_point.call_count == 2


def test_target_change_between_candidates_stops_before_second_click(monkeypatch):
    solver = probe(monkeypatch, ready())
    solver._refresh_challenge_summary = Mock(side_effect=[ready(), ready(SEED)])
    assert deferred_reset(solver) == "slider_not_found"
    solver._click_css_point.assert_called_once()


def test_bound_authenticated_snapshot_needs_no_retry_click(monkeypatch):
    solver = probe(monkeypatch, ready(authenticatedPage=True))
    assert solver._reset_failed_nc_challenge() is True
    solver._click_css_point.assert_not_called()


def test_unbound_other_call_scene_keeps_existing_behavior(monkeypatch):
    solver = probe(monkeypatch, {}, "https://example.test/slider")
    solver._nc_retry_outcome.return_value = {"slider": SLIDER}
    assert solver._reset_failed_nc_challenge() is True
    solver._click_css_point.assert_called_once()


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_after_preclick_read_remains_authoritative(monkeypatch, reason):
    from src.captcha_budget import SolveBudget

    solver, clock, _, _ = solve_probe(monkeypatch, [ready(**FAILED)], sliders=[SLIDER])
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    retry_click_probe(solver)
    reads = [0]

    def snapshot(_):
        reads[0] += 1
        if reads[0] == 1:
            if reason == "cancelled":
                budget.event.set()
            else:
                clock[0] = 100
        return ready(**FAILED)

    solver._refresh_challenge_summary = snapshot
    assert solver.solve(max_attempts=2, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == budget.reason == reason
    solver._click_css_point.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    solver._reload_page.assert_not_called()
