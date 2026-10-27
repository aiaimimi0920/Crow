"""Safe source attribution for verification errors, without relaxing acceptance."""

import json
import logging

import pytest

from tools.pc2_solver_diagnostics import diagnostic_event
from tools.solver_observation_evidence import project_line
from tools.test.test_captcha_dom_evaluation import DocumentSolver
from tools.test.test_captcha_nc_success_verification import DETAIL, completed_document


@pytest.mark.parametrize(
    "changes,children,text_error,widget_error",
    [
        ({"text": "验证失败"}, [], True, False),
        ({}, [{"selectors": [".errloading"]}], False, True),
        ({"text": "验证失败"}, [{"selectors": [".errloading"]}], True, True),
        ({"frames": [{"document": {"text": "验证失败"}}]}, [], True, False),
        (
            {"frames": [{"document": {"nodes": [{"selectors": [".errloading"]}]}}]},
            [],
            False,
            True,
        ),
        ({}, [], False, False),
    ],
)
def test_verification_logs_boolean_error_sources_only(
    caplog, changes, children, text_error, widget_error
):
    solver = DocumentSolver(completed_document(*children, **changes), DETAIL)
    with caplog.at_level(logging.INFO, logger="src.captcha_slider"):
        success = solver._verify_success()
    record = next(
        record for record in caplog.records if "Verification:" in record.getMessage()
    )
    message = record.getMessage()
    assert "验证失败" not in message and DETAIL not in message
    event = diagnostic_event(message)
    assert event["error_text"] is text_error
    assert event["error_widget"] is widget_error
    assert event["has_error"] is (text_error or widget_error)
    assert success is not (text_error or widget_error)


def test_error_text_guard_is_not_relaxed_for_a_transparent_error_element():
    solver = DocumentSolver(
        completed_document(
            {"selectors": [], "style": {"opacity": "0"}},
            {"selectors": [".errloading"], "parent": 1},
            text="验证失败",
        ),
        DETAIL,
    )
    assert solver._verify_success() is False


@pytest.mark.parametrize(
    "text_error,widget_error",
    [(True, False), (False, True), (True, True), (False, False)],
)
def test_new_source_flags_survive_allowlisted_log_projection(text_error, widget_error):
    event = diagnostic_event(
        "[SOLVER] Verification: success=False, sliderGone=False, "
        f"challengeGone=False, hasError={text_error or widget_error}, "
        f"errorText={text_error}, errorWidget={widget_error}"
    )
    assert event is not None
    result = project_line("2026-10-27T00:00:00Z " + json.dumps(event), "container")
    assert result["error_text"] is text_error
    assert result["error_widget"] is widget_error


def test_legacy_logs_keep_error_source_unknown():
    event = diagnostic_event(
        "[SOLVER] Verification: success=False, sliderGone=False, "
        "challengeGone=False, hasError=True"
    )
    result = project_line("2026-10-27T00:00:00Z " + json.dumps(event), "container")
    assert "error_text" not in event and "error_widget" not in event
    assert "error_text" not in result and "error_widget" not in result


@pytest.mark.parametrize(
    "suffix",
    [
        "errorText=secret, errorWidget=False",
        "errorText=True, errorWidget=True extra=secret",
    ],
)
def test_unbounded_or_nonboolean_error_detail_is_not_admitted(suffix):
    assert (
        diagnostic_event(
            "[SOLVER] Verification: success=False, sliderGone=False, "
            "challengeGone=False, hasError=True, " + suffix
        )
        is None
    )
