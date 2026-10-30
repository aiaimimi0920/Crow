"""Explain target mismatch from an existing snapshot without exposing identity."""

import json
import logging
from unittest.mock import Mock

import pytest

from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import project_line, summarize
from tools.test.test_captcha_nc_retry_preclick_binding import deferred_reset, probe
from tools.test.test_captcha_solve_loading_transition import FAILED, SLIDER, solve_probe

SEED = "https://sf.taobao.com/list/all.htm"
TARGET = SEED + "?location_code=3301&st_param=PRIVATE_MARKER&auction_start_seg=1&page=2"


def snapshot(href=TARGET, **extra):
    return {"href": href, "readyState": "complete", **extra}


def fields(href=TARGET, target=TARGET, **extra):
    from src.captcha_target_diagnostics import target_binding_fields

    return target_binding_fields(snapshot(href, **extra), target)


def test_queryless_challenge_reports_each_missing_identity_not_a_success():
    result = fields(SEED + "/_____tmd_____/verify?x5secdata=PRIVATE_MARKER")
    assert result == {
        "binding": "query_changed",
        "location_code": "current_missing",
        "st_param": "current_missing",
        "auction_start_seg": "current_missing",
        "page": "current_missing",
    }
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize(
    ("href", "target", "expected"),
    [
        (TARGET, TARGET, "match"),
        (TARGET.replace("all.htm", "other.htm"), TARGET, "path_changed"),
        ("https://sf-item.taobao.com/sf_item/123.htm", TARGET, "scope_changed"),
        (TARGET, "https://evil.invalid/?PRIVATE_MARKER", "request_invalid"),
        (None, TARGET, "current_invalid"),
        ([], TARGET, "current_invalid"),
        (
            "https://user:PRIVATE_MARKER@sf.taobao.com/list/all.htm",
            TARGET,
            "current_invalid",
        ),
        ("https://sf.taobao.com:invalid/list/all.htm", TARGET, "current_invalid"),
        ("https://[invalid/PRIVATE_MARKER", TARGET, "current_invalid"),
    ],
)
def test_binding_classification_uses_existing_canonical_policy(href, target, expected):
    result = fields(href, target)
    assert result["binding"] == expected
    if expected != "match":
        assert all(
            value == "not_compared" for key, value in result.items() if key != "binding"
        )
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize(
    ("href", "target", "relation"),
    [
        (SEED + "?page=1", SEED + "?page=2", "different"),
        (SEED, SEED + "?page=2", "current_missing"),
        (SEED + "?page=2", SEED, "request_missing"),
        (SEED, SEED, "both_absent"),
        (SEED + "?page=2&page=2", SEED + "?page=2", "different"),
        (SEED + "?page=1&page=2", SEED + "?page=2&page=1", "equal"),
    ],
)
def test_query_comparison_preserves_duplicates_and_ignores_order(
    href, target, relation
):
    assert fields(href, target)["page"] == relation


def test_challenge_tokens_and_detail_aliases_do_not_change_binding():
    assert fields(TARGET + "&x5secdata=PRIVATE_MARKER")["binding"] == "match"
    assert (
        fields(
            "https://susong-item.taobao.com/auction/123.htm/_____tmd_____/verify",
            "https://sf-item.taobao.com/sf_item/123.htm",
        )["binding"]
        == "match"
    )


def test_preflight_uses_one_existing_summary_without_new_browser_io(monkeypatch):
    solver = CaptchaSolver(target_url=TARGET)
    solver.connect_tab = Mock(return_value=True)
    solver._page_challenge_summary = Mock(return_value=snapshot(hasSlider=True))
    solver._send_cdp = Mock(side_effect=AssertionError("no additional I/O"))
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver._preflight_current_challenge()["has_slider"] is True
    solver._page_challenge_summary.assert_called_once_with()
    solver._send_cdp.assert_not_called()
    assert events == [event("preflight", "match", "equal")]


def event(stage, binding, relation):
    return {
        "kind": "local_solver_diagnostic",
        "phase": "target_binding",
        "stage": stage,
        "binding": binding,
        **{
            key: relation
            for key in ("location_code", "st_param", "auction_start_seg", "page")
        },
    }


def test_post_drag_and_preclick_keep_failure_and_input_budget(monkeypatch):
    observed = snapshot(SEED, **FAILED)
    solver, _, reads, _ = solve_probe(monkeypatch, [observed], sliders=[SLIDER])
    solver.target_url = TARGET
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    from tools.test.test_captcha_nc_retry_uncertain import retry_click_probe

    retry_click_probe(solver)
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    assert reads[0] == 2
    solver._click_css_point.assert_not_called()
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    assert [e for e in events if e["phase"] == "target_binding"] == [
        event(stage, "query_changed", "current_missing")
        for stage in ("post_drag", "retry_preclick")
    ]


def test_preclick_stage_distinguishes_the_preinput_binding_branch(monkeypatch):
    solver = probe(monkeypatch, snapshot(SEED), TARGET)
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert deferred_reset(solver) == "slider_not_found"
    assert events == [event("retry_preclick", "query_changed", "current_missing")]
    solver._click_css_point.assert_not_called()


def project(second, row):
    return project_line(f"2026-10-29T00:00:{second:02d}Z " + json.dumps(row), "fixture")


def test_safe_projection_and_summary_never_infer_success_from_binding():
    rows = [
        project(0, {"kind": "local_solver_start", "target_url": TARGET}),
        project(1, {**event("post_drag", "match", "equal"), "href": TARGET}),
        project(
            2,
            {
                "kind": "local_solver_end",
                "success": False,
                "failure_reason": "slider_not_found",
            },
        ),
    ]
    report = summarize(rows)
    attempt = report["attempts"][0]
    assert attempt["target_binding_events"] == [
        {
            "at": "2026-10-29T00:00:01Z",
            **{
                k: v
                for k, v in rows[1].items()
                if k in event("post_drag", "match", "equal")
                and k not in {"kind", "phase"}
            },
        }
    ]
    assert not attempt["verified"] and not attempt["local_success"]
    assert not attempt["auth_confirmed"]
    assert "PRIVATE_MARKER" not in json.dumps(rows) + json.dumps(report)


@pytest.mark.parametrize("value", [None, [], {}, "PRIVATE_MARKER", 12, True])
def test_projection_revalidates_all_untrusted_fields(value):
    row = event(value, value, value)
    safe = project(1, row)
    assert safe is not None
    assert all(safe[key] == "unknown" for key in row if key not in {"kind", "phase"})
    start = project(0, {"kind": "local_solver_start", "target_url": TARGET})
    untrusted = {**row, "at": safe["at"], "container_id": "fixture"}
    report = summarize([start, untrusted])
    assert "PRIVATE_MARKER" not in json.dumps(safe) + json.dumps(report)


def test_binding_evidence_is_bounded_and_ignores_foreign_or_completed_attempts():
    start = project(0, {"kind": "local_solver_start", "target_url": TARGET})
    binding = project(1, event("retry_preclick", "query_changed", "current_missing"))
    foreign = {**binding, "container_id": "other"}
    end = project(2, {"kind": "local_solver_end", "success": False})
    report = summarize([start, foreign] + [binding] * 100 + [end, binding])
    assert len(report["attempts"][0]["target_binding_events"]) == 64


def test_identity_match_does_not_imply_ready_or_a_success():
    from src.captcha_verification import ready_target_matches

    observed = snapshot(readyState="loading", probeFailed=True)
    assert (
        fields(**{k: v for k, v in observed.items() if k != "href"})["binding"]
        == "match"
    )
    assert not ready_target_matches(observed, TARGET)


def test_real_binding_filter_is_bounded_private_and_restored(monkeypatch, caplog):
    from src.captcha_target_diagnostics import log_target_binding

    logger = logging.getLogger("src.captcha_preflight")
    before = logger.level, logger.filters[:]
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        for _ in range(100):
            log_target_binding(logger, "preflight", snapshot(), TARGET)
        logger.info("PRIVATE_MARKER %s", TARGET)
    assert (logger.level, logger.filters) == before
    assert len(events) == 64 and not caplog.messages
    assert "PRIVATE_MARKER" not in json.dumps(events)

    def broken(_event):
        raise OSError("PRIVATE_MARKER")

    monkeypatch.setattr(diagnostics, "log_event", broken)
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        log_target_binding(logger, "preflight", snapshot(), TARGET)
    assert not caplog.messages


@pytest.mark.parametrize(
    "suffix", [" PRIVATE_MARKER", "\nPRIVATE_MARKER", " " + TARGET]
)
def test_raw_suffixes_cannot_enter_binding_telemetry(suffix):
    message = (
        "[SOLVER] Target binding: stage=preflight binding=match "
        "location_code=equal st_param=equal auction_start_seg=equal page=equal"
    )
    assert diagnostics.diagnostic_event(message + suffix) is None
