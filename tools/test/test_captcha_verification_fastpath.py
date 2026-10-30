"""Read existing explicit success early without moving failure or input budgets."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_dom_evaluation import DocumentSolver
from tools.test.test_captcha_solve_loading_transition import SLIDER, solve_probe
from tools.test.test_captcha_verification_terminal_failure import (
    DETAIL,
    PollSolver,
    failed_summary,
)


@pytest.mark.parametrize("local_mock", [False, True])
def test_full_solve_reads_ready_success_before_live_settle(monkeypatch, local_mock):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    events = []
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: local_mock)
    monkeypatch.setattr(solver, "_local_mock_verification_mode", lambda: "")
    solver._wait_for_verification_success = (
        CaptchaSolver._wait_for_verification_success.__get__(solver)
    )

    def drag(*_args):
        events.append("drag")
        return 1

    def wait(seconds):
        if events:
            events.append(("wait", seconds))

    def verify():
        events.append("verify")
        return True

    solver._do_drag.side_effect = drag
    solver._do_drag_local_mock = Mock(side_effect=drag)
    solver._verify_success = Mock(side_effect=verify)
    solver._wait_interruptibly = wait
    assert solver.solve(max_attempts=1) is True
    expected = ["drag", ("wait", 0.15), "verify"] if local_mock else ["drag", "verify"]
    assert events == expected
    assert solver._do_drag.call_count == int(not local_mock)
    assert solver._do_drag_local_mock.call_count == int(local_mock)
    solver._verify_success.assert_called_once_with()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def record_poll(monkeypatch, summaries):
    solver = PollSolver(summaries)
    events = []
    verify, summary, wait = (
        solver._verify_success,
        solver._page_challenge_summary,
        solver._wait_interruptibly,
    )

    def recorded_verify():
        events.append("verify")
        return verify()

    def recorded_summary():
        events.append("summary")
        return summary()

    def recorded_wait(seconds):
        events.append(("wait", seconds))
        wait(seconds)

    monkeypatch.setattr("src.captcha_slider.random.uniform", lambda lo, _hi: lo)
    monkeypatch.setattr(solver, "_verify_success", recorded_verify)
    monkeypatch.setattr(solver, "_page_challenge_summary", recorded_summary)
    monkeypatch.setattr(solver, "_wait_interruptibly", recorded_wait)
    return solver, events


@pytest.mark.parametrize(
    "summary",
    [
        {},
        {"probeFailed": True},
        failed_summary(readyState="loading"),
        failed_summary(href="https://sf-item.taobao.com/sf_item/456.htm"),
    ],
)
def test_unconfirmed_success_keeps_probe_count_and_total_wait_budget(
    monkeypatch, summary
):
    solver, events = record_poll(monkeypatch, [summary])
    assert solver._wait_for_verification_success() is False
    assert events[:3] == ["verify", ("wait", 1.8), "summary"]
    assert solver.verifications == solver.summary_reads == 6
    assert solver.waits == [1.8] + [0.6] * 5
    assert solver.last_failure_reason == "unchanged"


def test_failure_samples_still_start_after_original_settle(monkeypatch):
    solver, events = record_poll(monkeypatch, [failed_summary()])
    assert solver._wait_for_verification_success() is False
    assert events == [
        "verify",
        ("wait", 1.8),
        "summary",
        ("wait", 0.6),
        "verify",
        "summary",
    ]
    assert solver.verifications == solver.summary_reads == 2
    assert solver.last_failure_reason == "unchanged"


def test_structural_authenticated_summary_keeps_original_settle(monkeypatch):
    solver, events = record_poll(monkeypatch, [{"authenticatedPage": True}])
    assert solver._wait_for_verification_success() is True
    assert events == ["verify", ("wait", 1.8), "summary"]
    assert solver.verifications == solver.summary_reads == 1


def test_cancel_during_settle_never_reads_summary_or_second_probe(monkeypatch):
    solver, events = record_poll(monkeypatch, [failed_summary()])
    solver.on_wait = lambda: setattr(solver, "cancelled", True)
    assert solver._wait_for_verification_success() is False
    assert events == ["verify", ("wait", 1.8)]
    assert solver.verifications == 1 and solver.summary_reads == 0


def test_deadline_during_settle_is_not_swallowed(monkeypatch):
    solver, events = record_poll(monkeypatch, [failed_summary()])

    def expire():
        raise SolveStopped("deadline_exceeded")

    solver.on_wait = expire
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._wait_for_verification_success()
    assert events == ["verify", ("wait", 1.8)]
    assert solver.summary_reads == 0


@pytest.mark.parametrize("max_checks,expected", [(1, False), (6, True)])
def test_explicit_success_appearing_during_settle_needs_next_existing_probe(
    monkeypatch, max_checks, expected
):
    solver, events = record_poll(monkeypatch, [{}])
    solver.on_wait = lambda: setattr(solver, "successes", (False, True))
    assert solver._wait_for_verification_success(max_checks=max_checks) is expected
    assert events[:3] == ["verify", ("wait", 1.8), "summary"]
    assert solver.verifications == (2 if expected else 1)
    assert solver.summary_reads == 1


def test_final_solve_stop_check_rejects_cancel_after_early_success(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    solver._wait_for_verification_success = (
        CaptchaSolver._wait_for_verification_success.__get__(solver)
    )
    cancelled = [False]
    monkeypatch.setattr(solver, "_cancel_requested", lambda: cancelled[0])

    def verify():
        cancelled[0] = True
        return True

    solver._verify_success = verify
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "cancelled"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize(
    "document",
    [
        {"url": DETAIL},
        {"url": DETAIL, "text": "验证通过", "readyState": "loading"},
        {"url": DETAIL.replace("123", "456"), "text": "验证通过"},
        {"url": DETAIL, "text": "验证失败"},
        {
            "url": DETAIL,
            "text": "验证通过",
            "frames": [{"document": {"text": "验证失败"}}],
        },
    ],
)
def test_early_read_still_requires_real_bound_success(monkeypatch, document):
    solver = DocumentSolver(document, DETAIL)
    waits = []
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: False)
    monkeypatch.setattr(solver, "_stop_if_cancelled", lambda: False, raising=False)
    monkeypatch.setattr(solver, "_wait_interruptibly", waits.append, raising=False)
    assert solver._wait_for_verification_success(max_checks=1) is False
    assert len(waits) == 1 and 1.8 <= waits[0] <= 2.4
