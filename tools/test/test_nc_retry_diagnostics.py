"""NC reset telemetry is safe, bounded and never evidence of solved CAPTCHA."""

import json
import logging

import pytest

from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import project_line, summarize

FIXED = {
    "NC slider restored after retry click.": "nc_retry_restored",
    "NC retry click recovered an authenticated page.": "nc_retry_authenticated",
    "NC retry document uncertain; deferring without further clicks.": "nc_retry_uncertain",
}


@pytest.mark.parametrize(("message", "phase"), FIXED.items())
def test_fixed_reset_messages_have_no_free_text(message, phase):
    assert diagnostics.diagnostic_event("[SOLVER] " + message) == {
        "kind": "local_solver_diagnostic",
        "phase": phase,
    }


@pytest.mark.parametrize(
    "candidate",
    ["widget_centerline", "widget_vertical", "retry_text", "widget_fallback"],
)
def test_click_diagnostic_keeps_only_candidate_identity_not_coordinates(candidate):
    event = diagnostics.diagnostic_event(
        f"[SOLVER] Clicking NC retry target 1/8 ({candidate}) at (592,506)"
    )
    assert event == {
        "kind": "local_solver_diagnostic",
        "phase": "nc_retry_click",
        "candidate_index": 1,
        "candidate_count": 8,
        "candidate_kind": candidate,
    }


@pytest.mark.parametrize(
    "message",
    [
        "Clicking NC retry target 0/8 (retry_text) at (1,2)",
        "Clicking NC retry target 9/8 (retry_text) at (1,2)",
        "Clicking NC retry target 1/99 (retry_text) at (1,2)",
        "Clicking NC retry target 1/8 (secret) at (1,2)",
        "Clicking NC retry target 1/8 (retry_text) at (nan,2)",
        "NC slider restored after retry click. https://private.invalid/?token=secret",
    ],
)
def test_malformed_or_private_retry_messages_are_not_published(message):
    assert diagnostics.diagnostic_event("[SOLVER] " + message) is None


@pytest.mark.parametrize(
    ("outcome", "restored", "phase"),
    [
        ({"slider": {"x": 1}}, True, "nc_retry_restored"),
        ({"authenticated": True}, True, "nc_retry_authenticated"),
        ({"probeFailed": True}, False, "nc_retry_uncertain"),
        ({"loading": True}, False, "nc_retry_uncertain"),
        ({"cancelled": True}, False, "nc_retry_uncertain"),
    ],
)
def test_actual_reset_logger_is_admitted_and_restored(
    monkeypatch, outcome, restored, phase
):
    events = []
    logger = logging.getLogger("src.captcha_nc_retry")
    before = logger.level, logger.filters[:]
    root = logging.getLogger()
    root_before = root.level, root.handlers[:]
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    solver = CaptchaSolver(target_url="https://example.invalid/")
    solver._nc_retry_targets = lambda: {
        "widget": {"x": 0, "y": 0, "width": 100, "height": 30}
    }
    solver._click_css_point = lambda *a, **kw: True
    solver._wait_interruptibly = lambda *_a: None
    solver._nc_retry_outcome = lambda **_kw: outcome
    with diagnostics.solver_attempt_diagnostics():
        assert solver._reset_failed_nc_challenge() is restored
        logger.info("private URL or token must not escape")
    assert [event["phase"] for event in events] == ["nc_retry_click", phase]
    assert (logger.level, logger.filters) == before
    assert (root.level, root.handlers) == root_before
    assert "private" not in json.dumps(events)


def project(second, **event):
    return project_line(
        f"2026-10-28T04:00:{second:02d}Z " + json.dumps(event), "container-a"
    )


def test_safe_projection_and_summary_preserve_reset_without_claiming_success():
    start = project(
        0,
        kind="local_solver_start",
        target_url="https://sf-item.taobao.com/sf_item/123.htm",
    )
    retry = project(
        1,
        kind="local_solver_diagnostic",
        phase="nc_retry_click",
        candidate_index=1,
        candidate_count=8,
        candidate_kind="widget_centerline",
        secret="must-not-escape",
    )
    restored = project(2, kind="local_solver_diagnostic", phase="nc_retry_restored")
    end = project(
        3,
        kind="local_solver_end",
        success=False,
        failure_reason="challenge_retry_exhausted",
    )
    assert retry is not None and restored is not None
    report = summarize([start, retry, restored, end])
    attempt = report["attempts"][0]
    assert [row["phase"] for row in attempt["nc_retry_events"]] == [
        "nc_retry_click",
        "nc_retry_restored",
    ]
    assert attempt["nc_retry_events"][0]["candidate_index"] == 1
    assert not attempt["verified"] and not attempt["automatic_local_success"]
    assert not attempt["auth_confirmed"]
    assert "must-not-escape" not in json.dumps(report)


def test_retry_filter_is_bounded_and_does_not_leak_if_output_fails(monkeypatch, caplog):
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    logger = logging.getLogger("src.captcha_nc_retry")
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        for _ in range(100):
            logger.info("[SOLVER] NC slider restored after retry click.")
        logger.info("private message")
        logger.warning("retained warning")
    assert len(events) == 64
    assert caplog.messages == ["retained warning"]

    def broken(_event):
        raise OSError("sink unavailable")

    monkeypatch.setattr(diagnostics, "log_event", broken)
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        logger.info("[SOLVER] NC slider restored after retry click.")
    assert caplog.messages == ["retained warning"]


@pytest.mark.parametrize("index,count", [(True, 8), (1, "8"), (0, 8), (9, 8), (1, 99)])
def test_projection_rejects_invalid_counts_and_untrusted_candidate_kind(index, count):
    event = project(
        1,
        kind="local_solver_diagnostic",
        phase="nc_retry_click",
        candidate_index=index,
        candidate_count=count,
        candidate_kind="private-token",
    )
    assert event["candidate_kind"] == "unknown"
    assert "candidate_index" not in event and "candidate_count" not in event
    assert "private-token" not in json.dumps(event)


def test_summary_bounds_retry_evidence_and_ignores_terminal_or_foreign_events():
    start = project(
        0, kind="local_solver_start", target_url="https://sf.taobao.com/list/1.htm"
    )
    restored = project(
        1, kind="local_solver_diagnostic", phase="nc_retry_authenticated", success=True
    )
    foreign = dict(restored, container_id="container-b")
    end = project(2, kind="local_solver_end", success=False, failure_reason="cancelled")
    report = summarize([start, foreign] + [restored] * 100 + [end, restored])
    attempt = report["attempts"][0]
    assert len(attempt["nc_retry_events"]) == 64
    assert not attempt["verified"] and not attempt["local_success"]
    assert not attempt["auth_confirmed"]
