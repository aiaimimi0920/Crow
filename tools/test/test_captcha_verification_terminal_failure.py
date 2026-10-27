"""Stop redundant polling only after repeated, complete, target-bound NC failure."""

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_slider import CaptchaSliderMixin

DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"


def failed_summary(**changes):
    return {
        "href": DETAIL + "/_____tmd_____/punish",
        "readyState": "complete",
        "explicitFailure": True,
        "retryableFailure": True,
        "hasSlider": False,
        "hasChallengeWidget": True,
        "loginRequired": False,
        "authenticatedPage": False,
        **changes,
    }


class PollSolver(CaptchaSliderMixin):
    def __init__(self, summaries, successes=(), local_mock=False):
        self.target_url = DETAIL
        self.summaries = summaries
        self.successes = successes
        self.local_mock = local_mock
        self.verifications = 0
        self.summary_reads = 0
        self.waits = []
        self.cancelled = False
        self.on_wait = lambda: None
        self.last_failure_reason = "unchanged"

    def _is_local_mock_slider_target(self):
        return self.local_mock

    def _local_mock_verification_mode(self):
        return "strict_success_text" if self.local_mock else None

    def _stop_if_cancelled(self):
        return self.cancelled

    def _verify_success(self):
        index = self.verifications
        self.verifications += 1
        return self.successes[index] if index < len(self.successes) else False

    def _page_challenge_summary(self):
        index = min(self.summary_reads, len(self.summaries) - 1)
        self.summary_reads += 1
        return dict(self.summaries[index])

    def _wait_interruptibly(self, seconds):
        self.waits.append(seconds)
        self.on_wait()


def test_confirmed_retry_state_returns_to_existing_retry_policy_after_two_samples():
    solver = PollSolver([failed_summary()])
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == solver.summary_reads == 2
    assert len(solver.waits) == 1
    assert solver.last_failure_reason == "unchanged"


@pytest.mark.parametrize(
    "changes",
    [
        {"explicitFailure": False},
        {"explicitFailure": "true"},
        {"retryableFailure": False},
        {"retryableFailure": None},
        {"hasSlider": True},
        {"hasSlider": None},
        {"hasChallengeWidget": False},
        {"hasChallengeWidget": None},
        {"loginRequired": True},
        {"loginRequired": None},
        {"probeFailed": True},
        {"readyState": "loading"},
        {"readyState": "interactive"},
        {"href": "https://sf-item.taobao.com/sf_item/456.htm"},
        {"href": "https://untrusted.invalid/?next=" + DETAIL},
    ],
)
def test_incomplete_transient_or_foreign_failure_keeps_original_poll_budget(changes):
    solver = PollSolver([failed_summary(**changes)])
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == solver.summary_reads == 6
    assert len(solver.waits) == 5


@pytest.mark.parametrize(
    "gap", [{}, {"probeFailed": True}, failed_summary(hasSlider=True)]
)
def test_unconfirmed_sample_breaks_consecutive_failure_evidence(gap):
    solver = PollSolver([failed_summary(), gap, failed_summary(), failed_summary()])
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == 4
    assert len(solver.waits) == 3


def test_explicit_success_wins_before_second_failure_sample():
    solver = PollSolver([failed_summary()], successes=(False, True))
    assert solver._wait_for_verification_success() is True
    assert solver.verifications == 2
    assert solver.summary_reads == 1


def test_authenticated_payload_still_wins_before_failure_policy():
    solver = PollSolver([{"authenticatedPage": True}])
    assert solver._wait_for_verification_success() is True
    assert solver.verifications == solver.summary_reads == 1


def test_local_mock_keeps_its_original_terminal_and_wait_contract():
    solver = PollSolver([failed_summary()], local_mock=True)
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == 10
    assert solver.summary_reads == 0
    assert solver.waits == [0.15] * 9


def test_cancel_between_failure_samples_never_starts_second_probe():
    solver = PollSolver([failed_summary()])
    solver.on_wait = lambda: setattr(solver, "cancelled", True)
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == solver.summary_reads == 1


def test_deadline_during_failure_wait_is_not_swallowed():
    solver = PollSolver([failed_summary()])

    def expire():
        raise SolveStopped("deadline_exceeded")

    solver.on_wait = expire
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._wait_for_verification_success()
    assert solver.verifications == 1


@pytest.mark.parametrize("max_checks", [0, 1])
def test_short_budget_never_adds_a_probe_to_confirm_failure(max_checks):
    solver = PollSolver([failed_summary()])
    assert solver._wait_for_verification_success(max_checks=max_checks) is False
    assert solver.verifications == 1
    assert solver.waits == []


def test_consecutive_counter_is_local_to_each_verification_wait():
    solver = PollSolver([failed_summary()])
    assert solver._wait_for_verification_success(max_checks=1) is False
    assert solver._wait_for_verification_success() is False
    assert solver.verifications == 3


def test_full_solve_keeps_two_replays_and_existing_failure_reason(monkeypatch):
    from src.captcha_solver import CaptchaSolver

    solver = CaptchaSolver(target_url=DETAIL)
    calls = {"drags": 0, "resets": 0, "verifications": 0}
    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {"connected": True, "has_slider": True},
    )
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: False)
    monkeypatch.setattr(solver, "connect_tab", lambda: True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: None)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _seconds: None)
    monkeypatch.setattr(solver, "_os_mouse_enabled", lambda: False)
    monkeypatch.setattr(solver, "_get_track_width", lambda: 300)
    monkeypatch.setattr(solver, "_get_track_rect", lambda: None)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda **_kw: {"x": 20, "y": 40, "width": 42, "height": 30},
    )
    monkeypatch.setattr(solver, "_page_challenge_summary", failed_summary)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: 0)
    monkeypatch.setattr(solver, "_close_solver_ws", lambda: None)
    monkeypatch.setattr(
        solver, "_send_cdp", lambda *_a, **_kw: pytest.fail("no browser I/O")
    )

    def drag(*_args):
        calls["drags"] += 1
        return 1

    def reset():
        calls["resets"] += 1
        return True

    def verify():
        calls["verifications"] += 1
        return False

    monkeypatch.setattr(solver, "_do_drag", drag)
    monkeypatch.setattr(solver, "_reset_failed_nc_challenge", reset)
    monkeypatch.setattr(solver, "_verify_success", verify)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=2) is False
    assert calls == {"drags": 3, "resets": 2, "verifications": 6}
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    assert not solver.lock.locked() and solver._solve_budget is None


def test_current_cdp_expressions_produce_the_required_terminal_evidence(monkeypatch):
    from tools.test.test_captcha_dom_evaluation import DocumentSolver

    solver = DocumentSolver(
        {
            "url": DETAIL + "/_____tmd_____/punish",
            "text": "验证失败 点击框体重试",
            "nodes": [
                {"selectors": [".nc-container"]},
                {"selectors": [".errloading"], "parent": 0},
            ],
        },
        DETAIL,
    )
    waits, evaluations = [], []
    evaluate = solver._send_cdp

    def counted_evaluate(*args, **kwargs):
        evaluations.append(args[0])
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(solver, "_send_cdp", counted_evaluate)
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: False)
    monkeypatch.setattr(solver, "_stop_if_cancelled", lambda: False, raising=False)
    monkeypatch.setattr(solver, "_wait_interruptibly", waits.append, raising=False)
    assert solver._wait_for_verification_success() is False
    assert len(waits) == 1
    assert evaluations == ["Runtime.evaluate"] * 4
