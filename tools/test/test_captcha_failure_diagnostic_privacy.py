"""Challenge diagnostics are safe before any child-process log filter runs."""

import json
import logging

import pytest

from src.captcha_preflight import CaptchaPreflightMixin
from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import project_line, summarize

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"


def diagnostic(**extra):
    solver = CaptchaPreflightMixin()
    solver.target_url = TARGET
    return solver._challenge_failure_diagnostic(
        {
            "errorCode": "error:opaque_PRIVATE_MARKER/value",
            "title": "PRIVATE_MARKER title\nsecond line",
            "className": "PRIVATE_MARKER class",
            "href": TARGET + "?token=PRIVATE_MARKER#PRIVATE_MARKER",
            "bodyText": "PRIVATE_MARKER body",
            "readyState": "complete",
            "retryableFailure": True,
            **extra,
        }
    )


@pytest.mark.parametrize(
    ("code", "safe", "kind"),
    [
        (None, "none", "absent"),
        ("", "none", "absent"),
        ("error:300", "error:300", "numeric"),
        ("error:123456", "error:123456", "numeric"),
        ("error:300/PRIVATE_MARKER", "other", "opaque"),
        ("error:TJiA4d/Vx6urd", "other", "opaque"),
        ("error:1234567", "other", "opaque"),
        ("error:１２３", "other", "invalid"),
        ("error:300\n", "other", "invalid"),
        (["PRIVATE_MARKER"], "other", "invalid"),
        ({"PRIVATE_MARKER": "error:300"}, "other", "invalid"),
    ],
)
def test_source_diagnostic_never_emits_opaque_code_or_page_context(code, safe, kind):
    message = diagnostic(errorCode=code)
    assert message == (
        f"code={safe} codeKind={kind} ready=complete "
        "targetReady=True probeFailed=False retryable=True"
    )
    assert "PRIVATE_MARKER" not in message
    assert "TJiA4d" not in message
    assert "https:" not in message


@pytest.mark.parametrize(
    ("extra", "ready", "target", "probe"),
    [
        ({"readyState": "loading"}, "loading", False, False),
        ({"readyState": "interactive"}, "interactive", True, False),
        ({"readyState": "PRIVATE_MARKER"}, "unknown", False, False),
        ({"readyState": []}, "unknown", False, False),
        ({"href": TARGET.replace("123", "456")}, "complete", False, False),
        (
            {"href": "https://user:PRIVATE_MARKER@example.test/"},
            "complete",
            False,
            False,
        ),
        ({"probeFailed": True}, "complete", True, True),
    ],
)
def test_existing_snapshot_states_are_bounded_without_extra_io(
    extra, ready, target, probe
):
    assert diagnostic(**extra) == (
        f"code=other codeKind=opaque ready={ready} "
        f"targetReady={target} probeFailed={probe} retryable=True"
    )


def test_real_producer_filter_projection_and_report_agree(monkeypatch, caplog):
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    logger = logging.getLogger("src.captcha_orchestration")
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        logger.info("[SOLVER] Challenge diagnostic: %s", diagnostic())
    assert not caplog.messages
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "challenge_failure",
            "code": "other",
            "code_kind": "opaque",
            "ready_state": "complete",
            "target_ready": True,
            "probe_failed": False,
            "retryable": True,
        }
    ]
    raw = [
        {"kind": "local_solver_start", "target_url": TARGET},
        events[0],
        {
            "kind": "local_solver_end",
            "success": False,
            "failure_reason": "challenge_retry_exhausted",
        },
    ]
    rows = [
        project_line(f"2026-10-29T00:00:0{i}Z " + json.dumps(event), "fixture")
        for i, event in enumerate(raw)
    ]
    report = summarize(rows)
    failure = report["attempts"][0]["last_challenge_failure"]
    assert failure == {
        "at": "2026-10-29T00:00:01Z",
        **{k: v for k, v in events[0].items() if k not in {"kind", "phase"}},
    }
    assert report["counts"]["automatic_local_success"] == 0
    assert report["attempts"][0]["failure_reason"] == "challenge_retry_exhausted"
    assert "PRIVATE_MARKER" not in json.dumps(rows) + json.dumps(report)


@pytest.mark.parametrize("value", [None, [], {}, "PRIVATE_MARKER", 12])
def test_projection_revalidates_new_enums_and_booleans(value):
    event = {
        "kind": "local_solver_diagnostic",
        "phase": "challenge_failure",
        "code_kind": value,
        "ready_state": value,
        "target_ready": value,
        "probe_failed": value,
    }
    row = project_line("2026-10-29T00:00:01Z " + json.dumps(event), "fixture")
    assert row["code_kind"] == "invalid"
    assert row["ready_state"] == "unknown"
    assert "target_ready" not in row and "probe_failed" not in row
    assert "PRIVATE_MARKER" not in json.dumps(row)


def test_legacy_producer_rejects_unicode_numeric_codes():
    event = diagnostics.diagnostic_event(
        "[SOLVER] Challenge diagnostic: code=error:１２３ "
        "title=private class=private path=private retryable=False"
    )
    assert event["code"] == "other"


def test_report_revalidates_new_fields_in_preexisting_event_files():
    start = project_line(
        '2026-10-29T00:00:00Z {"kind":"local_solver_start","target_url":"'
        + TARGET
        + '"}',
        "fixture",
    )
    event = {
        "kind": "local_solver_diagnostic",
        "phase": "challenge_failure",
        "at": "2026-10-29T00:00:01Z",
        "container_id": "fixture",
        "code_kind": "PRIVATE_MARKER",
        "ready_state": "PRIVATE_MARKER",
        "target_ready": "PRIVATE_MARKER",
        "probe_failed": 1,
    }
    failure = summarize([start, event])["attempts"][0]["last_challenge_failure"]
    assert failure == {
        "at": event["at"],
        "code_kind": "invalid",
        "ready_state": "unknown",
    }
