"""Safe input receipts are diagnostics, not solve/authentication evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_os_input
from src.captcha_budget import SolveStopped
from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import summarize
from tools.test.test_captcha_input_receipt import RECEIPT
from tools.test.test_captcha_os_target import make_probe, snapshot
from tools.test.test_captcha_pointer_failure_evidence import project

MESSAGE = (
    "[SOLVER] OS input receipt backendCompleted=True pressSeen=True "
    "pressOnTarget=True pressedMoves=2 releaseSeen=True documentCurrent=True"
)


@pytest.mark.parametrize("result", [None, 350])
def test_wrapper_marks_only_returned_backend_completion_and_always_closes(
    monkeypatch, result
):
    solver = SimpleNamespace(_do_drag_os_target=Mock(return_value=result))
    probe = captcha_os_input.OSPointerTarget(solver, None, 100, 50)
    probe.close = Mock()
    monkeypatch.setattr(captcha_os_input, "OSPointerTarget", Mock(return_value=probe))
    assert (
        captcha_os_input.CaptchaOSInputMixin._do_drag_os(solver, 100, 50, 250) == result
    )
    assert probe.backend_completed is (result is not None)
    probe.close.assert_called_once_with()
    solver._do_drag_os_target.assert_called_once_with(100, 50, 250, None, 0, probe)


@pytest.mark.parametrize(
    "error", [RuntimeError("private-sentinel"), SolveStopped("cancelled")]
)
def test_wrapper_preserves_stop_and_exception_with_cleanup(monkeypatch, error):
    solver = SimpleNamespace(_do_drag_os_target=Mock(side_effect=error))
    probe = captcha_os_input.OSPointerTarget(solver, None, 100, 50)
    probe.close = Mock()
    monkeypatch.setattr(captcha_os_input, "OSPointerTarget", Mock(return_value=probe))
    with pytest.raises(type(error)) as caught:
        captcha_os_input.CaptchaOSInputMixin._do_drag_os(solver, 100, 50, 250)
    assert caught.value is error and not probe.backend_completed
    probe.close.assert_called_once_with()


def test_receipt_parser_and_projector_keep_only_safe_strict_fields():
    event = diagnostics.diagnostic_event(MESSAGE)
    assert event == {
        "kind": "local_solver_diagnostic",
        "phase": "input_receipt",
        "backend_completed": True,
        **RECEIPT,
    }
    row = project(1, **event, screen_x=123, screen_y=456, url="private-sentinel")
    assert all(row[key] == value for key, value in event.items())
    assert not {"screen_x", "screen_y", "url"}.intersection(row)
    assert diagnostics.diagnostic_event(MESSAGE + " private-sentinel") is None
    assert (
        diagnostics.diagnostic_event(
            MESSAGE.replace("pressedMoves=2", "pressedMoves=10001")
        )
        is None
    )


@pytest.mark.parametrize("bad", [True, -1, 10001, "2", 1.5, float("nan")])
def test_projector_drops_bad_receipt_counts_and_non_boolean_values(bad):
    row = project(
        1,
        kind="local_solver_diagnostic",
        phase="input_receipt",
        pressed_moves=bad,
        press_seen="True",
    )
    assert row is not None
    assert "pressed_moves" not in row and "press_seen" not in row


def test_receipts_are_bounded_correlated_and_never_increase_success():
    start = project(
        0, kind="local_solver_start", target_url="https://sf-item.taobao.com/"
    )
    receipt = project(1, **diagnostics.diagnostic_event(MESSAGE))
    unavailable = project(
        2,
        kind="local_solver_diagnostic",
        phase="input_receipt_unavailable",
        backend_completed=True,
    )
    end = project(
        3,
        kind="local_solver_end",
        success=False,
        failure_reason="challenge_retry_exhausted",
    )
    report = summarize(
        [receipt, start, dict(receipt, container_id="foreign"), unavailable]
        + [receipt] * 100
        + [end, receipt]
    )
    attempt = report["attempts"][0]
    assert len(attempt["pointer_events"]) == 64
    assert attempt["pointer_events"][0] == {
        "at": unavailable["at"],
        "phase": "input_receipt_unavailable",
        "backend_completed": True,
    }
    assert attempt["pointer_events"][1]["pressed_moves"] == 2
    assert not attempt["drags"] and not attempt["verified"]
    assert (
        report["counts"]["automatic_local_success"]
        == report["counts"]["auth_confirmed"]
        == 0
    )


def test_log_emission_failure_cannot_change_cleanup_result(monkeypatch):
    probe, solver, _, _ = make_probe(monkeypatch, [snapshot()])
    assert probe.open()
    solver._send_cdp = Mock(return_value={"result": {"value": RECEIPT}})
    solver.last_failure_reason = "unchanged"
    monkeypatch.setattr(
        "src.captcha_os_target.logger.info",
        Mock(side_effect=RuntimeError("private-sentinel")),
    )
    probe.close()
    assert not probe.installed and solver.last_failure_reason == "unchanged"
    solver._send_cdp.assert_called_once()
