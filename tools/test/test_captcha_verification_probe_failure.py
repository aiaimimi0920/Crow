"""Lost post-input page evidence must not authorize reloads or more input."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import (
    AUTHENTICATED,
    FAILED,
    SLIDER,
    solve_probe,
)
from tools.test.test_captcha_verification_terminal_failure import (
    PollSolver,
    assert_live_waits,
)


def test_failed_summary_keeps_the_existing_transient_recovery_window():
    solver = PollSolver([{"probeFailed": True}])
    assert solver._wait_for_verification_success() is False
    assert solver.last_failure_reason == "unchanged"
    assert solver.verifications == solver.summary_reads == 6
    assert_live_waits(solver, 5)


def test_transient_probe_failure_can_still_reach_authenticated_page():
    solver = PollSolver([{"probeFailed": True}, AUTHENTICATED])
    assert solver._wait_for_verification_success() is True
    assert solver.verifications == solver.summary_reads == 2
    assert_live_waits(solver, 1)


def test_unknown_summary_is_not_silently_counted_as_transport_failure():
    solver = PollSolver([{}])
    assert solver._wait_for_verification_success() is False
    assert solver.last_failure_reason == "unchanged"
    assert solver.verifications == solver.summary_reads == 6
    assert_live_waits(solver, 5)


def test_success_before_later_probe_failure_keeps_existing_success_contract():
    solver = PollSolver([{"probeFailed": True}], successes=(True,))
    assert solver._wait_for_verification_success() is True
    assert solver.summary_reads == 0


def test_local_mock_never_uses_live_probe_failure_policy():
    solver = PollSolver([{"probeFailed": True}], local_mock=True)
    assert solver._wait_for_verification_success() is False
    assert solver.last_failure_reason == "unchanged"
    assert solver.verifications == 10 and solver.summary_reads == 0


@pytest.mark.parametrize("replays", [0, 2])
def test_failed_post_wait_summary_does_not_reload_reset_or_drag_again(
    monkeypatch, replays
):
    solver, _, reads, _ = solve_probe(
        monkeypatch, [{"probeFailed": True}], sliders=[SLIDER, SLIDER]
    )
    solver._wait_for_verification_success.return_value = False
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=replays) is False
    assert solver.last_failure_reason == "cdp_unavailable" and reads[0] == 1
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_real_missing_cdp_response_ends_solve_after_original_poll_budget(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [FAILED], sliders=[SLIDER, SLIDER])
    solver._page_challenge_summary = CaptchaSolver._page_challenge_summary.__get__(
        solver
    )
    solver._wait_for_verification_success = (
        CaptchaSolver._wait_for_verification_success.__get__(solver)
    )
    solver._verify_success = Mock(return_value=False)
    solver._send_cdp = Mock(return_value=None)
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver._verify_success.call_count == 6
    assert solver._send_cdp.call_count == 7
    assert solver._send_cdp.call_args.args[0] == "Runtime.evaluate"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_reason_during_failed_summary_wins_over_transport_failure(
    monkeypatch, reason
):
    solver, _, _, _ = solve_probe(monkeypatch, [FAILED], sliders=[SLIDER])
    solver._wait_for_verification_success.return_value = False
    stopped = [False]

    def summary():
        stopped[0] = True
        return {"probeFailed": True}

    def check():
        if stopped[0]:
            solver.last_failure_reason = reason
        return stopped[0]

    solver._page_challenge_summary = summary
    solver._stop_if_cancelled = check
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == reason
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_solve_stopped_during_probe_is_not_swallowed():
    solver = PollSolver([{}])

    def expire():
        raise SolveStopped("deadline_exceeded")

    solver._page_challenge_summary = expire
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._wait_for_verification_success()
    assert solver.verifications == 1
    assert_live_waits(solver, 0)


def test_valid_authenticated_summary_still_completes_without_replay(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [AUTHENTICATED], sliders=[SLIDER])
    solver._wait_for_verification_success.return_value = False
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
