"""Uncertain post-click documents must not authorize stale retry input."""

from unittest.mock import Mock

import pytest

from tools.test.test_captcha_nc_retry_readiness import SLIDER, retry_probe
from tools.test.test_captcha_solve_loading_transition import (
    FAILED,
    LOADING,
    solve_probe,
)


@pytest.mark.parametrize("stale_authenticated", [False, True])
def test_probe_failure_cannot_complete_consecutive_ready_samples(
    monkeypatch, stale_authenticated
):
    failed = {"probeFailed": True, "authenticatedPage": stale_authenticated}
    solver, calls = retry_probe(monkeypatch, [SLIDER] * 3, [{}, {}, failed])

    outcome = solver._nc_retry_outcome(timeout_seconds=2.0)

    assert outcome.get("probeFailed") is True
    assert outcome.get("authenticated") is not True
    assert "slider" not in outcome
    assert len(calls) == 2


def test_loading_document_cannot_complete_consecutive_ready_samples(monkeypatch):
    solver, calls = retry_probe(
        monkeypatch,
        [SLIDER] * 5,
        [{}, {}, {"readyState": "loading", "hasSlider": True}, {}, {}, {}],
    )

    assert solver._nc_retry_outcome(timeout_seconds=2.0)["slider"] == SLIDER
    assert len(calls) == 5


@pytest.mark.parametrize("stale_slider", [False, True])
def test_still_loading_document_defers_without_geometry_probe(
    monkeypatch, stale_slider
):
    loading = {"readyState": "loading", "hasSlider": stale_slider}
    solver, calls = retry_probe(monkeypatch, [SLIDER] * 3, [loading] * 20)

    outcome = solver._nc_retry_outcome(timeout_seconds=1.0)

    assert outcome.get("loading") is True
    assert outcome.get("authenticated") is False
    assert "slider" not in outcome
    assert calls == []


def retry_click_probe(solver):
    solver._nc_retry_targets = Mock(
        return_value={"widget": {"x": 10, "y": 20, "width": 280, "height": 40}}
    )
    solver._click_css_point = Mock(return_value=True)


@pytest.mark.parametrize(
    "outcome", [{"probeFailed": True}, {"loading": True}, {"cancelled": True}]
)
def test_uncertain_outcome_never_tries_another_pre_click_coordinate(
    monkeypatch, outcome
):
    solver, _ = retry_probe(monkeypatch, [])
    retry_click_probe(solver)
    solver._nc_retry_outcome = Mock(return_value=outcome)

    assert solver._reset_failed_nc_challenge() is False
    solver._click_css_point.assert_called_once()
    solver._nc_retry_outcome.assert_called_once_with(timeout_seconds=3.0)


@pytest.mark.parametrize("state", ["probe_failure", "loading"])
def test_real_post_click_poll_stops_stale_coordinate_fanout(monkeypatch, state):
    summary = (
        {"probeFailed": True} if state == "probe_failure" else {"readyState": "loading"}
    )
    solver, calls = retry_probe(monkeypatch, [], [summary] * 150)
    retry_click_probe(solver)

    assert solver._reset_failed_nc_challenge() is False
    solver._click_css_point.assert_called_once()
    assert calls == []


def test_transient_loading_can_still_restore_slider_in_original_poll(monkeypatch):
    solver, calls = retry_probe(
        monkeypatch, [SLIDER] * 3, [{"readyState": "loading"}, {}, {}, {}]
    )
    retry_click_probe(solver)

    assert solver._reset_failed_nc_challenge() is True
    solver._click_css_point.assert_called_once()
    assert len(calls) == 3


def test_ready_authenticated_document_still_finishes_without_more_input(monkeypatch):
    summary = {"readyState": "complete", "authenticatedPage": True}
    solver, calls = retry_probe(monkeypatch, [], [summary])
    retry_click_probe(solver)

    assert solver._reset_failed_nc_challenge() is True
    solver._click_css_point.assert_called_once()
    assert calls == []


def test_confirmed_unrestored_widget_retains_existing_candidate_retry(monkeypatch):
    solver, _ = retry_probe(monkeypatch, [])
    retry_click_probe(solver)
    solver._nc_retry_outcome = Mock(
        side_effect=[{"authenticated": False}, {"slider": SLIDER}]
    )

    assert solver._reset_failed_nc_challenge() is True
    assert solver._click_css_point.call_count == 2


@pytest.mark.parametrize(
    ("summary", "reason"),
    [({"probeFailed": True}, "cdp_unavailable"), (LOADING, "challenge_loading")],
)
def test_solve_classifies_uncertain_reset_without_more_clicks_or_drags(
    monkeypatch, summary, reason
):
    from types import SimpleNamespace

    from src import captcha_nc_retry
    from src.captcha_solver import CaptchaSolver

    ready_retry = {
        **FAILED,
        "href": "https://sf-item.taobao.com/sf_item/123.htm",
        "readyState": "complete",
    }
    solver, clock, _, _ = solve_probe(
        monkeypatch, [FAILED, ready_retry, summary], sliders=[SLIDER]
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
    assert solver.last_failure_reason == reason
    solver._click_css_point.assert_called_once()
    solver._do_drag.assert_called_once()
    solver._find_slider.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None
