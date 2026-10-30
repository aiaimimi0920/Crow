"""Post-click NC recovery must retain the requested collection identity."""

from unittest.mock import Mock

import pytest

from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_nc_retry_readiness import SLIDER, retry_probe
from tools.test.test_captcha_nc_retry_uncertain import retry_click_probe
from tools.test.test_captcha_solve_loading_transition import FAILED, solve_probe

SEED = (
    "https://sf.taobao.com/list/50025969__2.htm?location_code=3301"
    "&st_param=1&auction_start_seg=0&page=2"
)
DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"


def ready(target, **changes):
    return {"readyState": "complete", "href": target, "hasSlider": True, **changes}


def target_probe(monkeypatch, target, summaries):
    solver, calls = retry_probe(monkeypatch, [SLIDER] * 12, summaries)
    solver.target_url = target
    return solver, calls


@pytest.mark.parametrize(
    ("target", "observed"),
    [
        (SEED, SEED.replace("3301", "3302")),
        (SEED, SEED.replace("page=2", "page=1")),
        (SEED, SEED.split("?", 1)[0]),
        (DETAIL, DETAIL.replace("123", "456")),
        (DETAIL, SEED),
        (SEED, "https://example.com/list/50025969__2.htm"),
    ],
)
@pytest.mark.parametrize("state", ["interactive", "complete"])
def test_foreign_retry_document_never_authorizes_slider_recovery(
    monkeypatch, target, observed, state
):
    summary = ready(observed, readyState=state)
    solver, calls = target_probe(monkeypatch, target, [summary] * 12)

    outcome = solver._nc_retry_outcome(timeout_seconds=3)

    assert outcome.get("targetUnavailable") is True
    assert "slider" not in outcome and not outcome.get("authenticated")
    assert calls == []


@pytest.mark.parametrize("summary", [{}, {"href": DETAIL}, {"readyState": "complete"}])
def test_incomplete_identity_is_uncertain_not_recovered(monkeypatch, summary):
    solver, calls = target_probe(monkeypatch, DETAIL, [summary] * 12)
    assert solver._nc_retry_outcome().get("targetUnavailable") is True
    assert calls == []


@pytest.mark.parametrize("target", [SEED, DETAIL])
@pytest.mark.parametrize("state", ["interactive", "complete"])
def test_bound_retry_slider_keeps_original_three_sample_rule(
    monkeypatch, target, state
):
    summary = ready(target, readyState=state)
    solver, calls = target_probe(monkeypatch, target, [summary] * 3)
    assert solver._nc_retry_outcome()["slider"] == SLIDER
    assert len(calls) == 3


def test_bound_seed_challenge_ignores_only_existing_nonidentity_parameters(monkeypatch):
    observed = (
        SEED.replace(".htm?", ".htm/_____tmd_____/punish?") + "&x5secdata=private"
    )
    solver, calls = target_probe(monkeypatch, SEED, [ready(observed)] * 3)
    assert solver._nc_retry_outcome()["slider"] == SLIDER
    assert len(calls) == 3


def test_identity_change_cannot_complete_two_old_geometry_samples(monkeypatch):
    summaries = [ready(DETAIL), ready(DETAIL), ready(DETAIL.replace("123", "456"))]
    solver, calls = target_probe(monkeypatch, DETAIL, summaries)
    outcome = solver._nc_retry_outcome()
    assert outcome.get("targetUnavailable") is True and "slider" not in outcome
    assert len(calls) == 2


@pytest.mark.parametrize("target", [SEED, DETAIL])
def test_foreign_authenticated_flag_cannot_bypass_retry_target_validation(
    monkeypatch, target
):
    solver, calls = target_probe(
        monkeypatch, target, [ready("https://example.com/", authenticatedPage=True)]
    )
    outcome = solver._nc_retry_outcome()
    assert outcome.get("targetUnavailable") is True
    assert not outcome.get("authenticated") and calls == []


def test_loading_retry_can_still_reach_bound_slider_in_original_poll(monkeypatch):
    solver, calls = target_probe(
        monkeypatch,
        DETAIL,
        [{"readyState": "loading"}, *[ready(DETAIL)] * 3],
    )
    assert solver._nc_retry_outcome(timeout_seconds=2)["slider"] == SLIDER
    assert len(calls) == 3


def test_foreign_post_click_document_stops_all_remaining_click_candidates(monkeypatch):
    solver, calls = target_probe(
        monkeypatch,
        DETAIL,
        [ready(DETAIL, hasSlider=False, explicitFailure=True), *[ready(SEED)] * 12],
    )
    retry_click_probe(solver)
    assert solver._reset_failed_nc_challenge() is False
    solver._click_css_point.assert_called_once()
    assert calls == []


@pytest.mark.parametrize("state", ["interactive", "complete"])
def test_full_solve_does_not_replay_or_reload_a_foreign_recovered_slider(
    monkeypatch, state
):
    from types import SimpleNamespace

    from src import captcha_nc_retry

    foreign = ready(DETAIL.replace("123", "456"), readyState=state, hardBlock=True)
    solver, clock, reads, _ = solve_probe(
        monkeypatch,
        [FAILED, ready(DETAIL, **FAILED), foreign],
        sliders=[SLIDER, SLIDER, SLIDER, SLIDER],
    )
    monkeypatch.setattr(
        captcha_nc_retry, "time", SimpleNamespace(time=lambda: clock[0])
    )
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    retry_click_probe(solver)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    assert reads[0] == 4
    solver._click_css_point.assert_called_once()
    solver._find_slider.assert_called_once()
    solver._do_drag.assert_called_once()
    solver.connect_tab.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("target", [SEED, DETAIL])
def test_bound_authenticated_proof_remains_success_without_geometry(
    monkeypatch, target
):
    summary = ready(target, hasSlider=False, authenticatedPage=True)
    solver, calls = target_probe(monkeypatch, target, [summary])
    assert solver._nc_retry_outcome() == {"authenticated": True, "summary": summary}
    assert calls == []


def test_cancelled_retry_still_stops_before_reading_the_page(monkeypatch):
    solver, calls = target_probe(monkeypatch, DETAIL, [ready(DETAIL)] * 3)
    solver._stop_if_cancelled = Mock(return_value=True)
    solver._refresh_challenge_summary = Mock()
    assert solver._nc_retry_outcome() == {"cancelled": True}
    solver._refresh_challenge_summary.assert_not_called()
    assert calls == []
