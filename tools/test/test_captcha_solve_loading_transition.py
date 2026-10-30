"""A loading transition inside a solve must not bypass the existing readiness grace."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_preflight
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
LOADING = {"readyState": "loading", "hasSlider": False, "href": TARGET}
AUTHENTICATED = {"readyState": "complete", "authenticatedPage": True}
FAILED = {"hardBlock": True, "explicitFailure": True, "retryableFailure": True}
SLIDER = {"x": 20, "y": 40, "width": 42, "height": 30}


def solve_probe(monkeypatch, summaries, sliders=()):
    solver = CaptchaSolver(target_url=TARGET)
    clock, reads, waits = [0.0], [0], []
    monkeypatch.setattr(
        captcha_preflight, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )

    def summary(*, deadline=None):
        index = min(reads[0], len(summaries) - 1)
        reads[0] += 1
        return summaries[index].copy()

    def wait(seconds):
        clock[0] += seconds
        waits.append(seconds)

    find_results = iter(sliders)
    solver._preflight_current_challenge = Mock(
        return_value={"connected": True, "has_slider": True}
    )
    solver._find_slider = Mock(side_effect=lambda **_kw: next(find_results, None))
    solver._page_challenge_summary = summary
    solver._wait_interruptibly = wait
    solver._bring_to_front = Mock()
    solver.connect_tab = Mock(return_value=True)
    solver._close_owned_target_tabs = Mock(return_value=0)
    solver._send_cdp = Mock(side_effect=AssertionError("No browser I/O allowed"))
    solver._reset_failed_nc_challenge = Mock(return_value=False)
    solver._poll_until_authenticated = Mock(return_value=False)
    solver._recover_authenticated_list_page = Mock(return_value=False)
    solver._reload_page = Mock()
    solver._os_mouse_enabled = Mock(return_value=False)
    solver._get_track_width = Mock(return_value=300)
    solver._get_track_rect = Mock(return_value=None)
    solver._do_drag = Mock(return_value=1)
    solver._wait_for_verification_success = Mock(return_value=True)
    return solver, clock, reads, waits


@pytest.mark.parametrize("after_reset", [False, True])
def test_loading_inside_solve_can_reach_authenticated_page(monkeypatch, after_reset):
    summaries = ([{"hardBlock": True}] if after_reset else []) + [
        LOADING,
        AUTHENTICATED,
    ]
    solver, clock, _, waits = solve_probe(monkeypatch, summaries)
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is True
    assert solver.last_failure_reason is None
    assert clock[0] == 0.25 and waits == [0.25]
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_loading_after_retry_replay_is_not_immediately_reported_failed(monkeypatch):
    solver, _, _, waits = solve_probe(
        monkeypatch, [FAILED, LOADING, AUTHENTICATED], sliders=[SLIDER]
    )
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge.return_value = True
    assert (
        solver.solve(max_attempts=1, nc_retry_replay_limit=1, slider_find_max_retries=1)
        is True
    )
    assert solver.last_failure_reason is None
    assert 0.25 in waits
    assert solver._do_drag.call_count == 1
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()


def test_loading_can_reveal_slider_without_reloading_or_extra_drag(monkeypatch):
    solver, _, _, waits = solve_probe(
        monkeypatch,
        [LOADING, {"readyState": "complete", "hasSlider": True, "href": TARGET}],
        sliders=[None, SLIDER],
    )
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is True
    assert 0.25 in waits
    assert solver._find_slider.call_count == 2
    assert solver._do_drag.call_count == 1
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()


@pytest.mark.parametrize("after_reset", [False, True])
def test_permanently_loading_page_keeps_original_bounded_failure(
    monkeypatch, after_reset
):
    summaries = ([{"hardBlock": True}] if after_reset else []) + [LOADING]
    solver, clock, reads, waits = solve_probe(monkeypatch, summaries)
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "challenge_loading"
    assert clock[0] == 8 and waits == [0.25] * 32
    assert reads[0] == 32 + int(after_reset)
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()


def test_loading_probe_failure_remains_transport_failure(monkeypatch):
    solver, clock, _, _ = solve_probe(monkeypatch, [LOADING, {"probeFailed": True}])
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "cdp_unavailable" and clock[0] == 0.25
    solver._do_drag.assert_not_called()
    solver._send_cdp.assert_not_called()


def test_loading_cancellation_stops_before_any_further_probe(monkeypatch):
    solver, _, reads, _ = solve_probe(monkeypatch, [LOADING, AUTHENTICATED])
    cancelled = [False]
    solver.cancel_checker = lambda: cancelled[0]

    class CancelEvent:
        def is_set(self):
            return cancelled[0]

        def wait(self, _seconds):
            cancelled[0] = True

    solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
    event = CancelEvent()
    assert solver.solve(max_attempts=1, cancel_event=event) is False
    assert solver.last_failure_reason == "cancelled" and reads[0] == 1
    solver._do_drag.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_loading_wait_never_extends_the_existing_solve_deadline(monkeypatch):
    solver, clock, _, _ = solve_probe(monkeypatch, [LOADING])

    class ClockEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            clock[0] += seconds

    budget = SolveBudget(
        deadline=0.4, clock=lambda: clock[0], cancel_event=ClockEvent()
    )
    solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._solve_attempts(slider_find_max_retries=1, _budget=budget)
    assert clock[0] == pytest.approx(0.4)
    assert solver.last_failure_reason == "deadline_exceeded"
    solver._do_drag.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize(
    "ready",
    [
        {"readyState": "complete", "loginRequired": True},
        {"readyState": "complete", "hardBlock": True},
        {"readyState": "complete", "explicitFailure": True},
    ],
)
def test_finishing_loading_does_not_mean_authentication_succeeded(monkeypatch, ready):
    solver, _, _, _ = solve_probe(monkeypatch, [LOADING, ready])
    assert solver.solve(max_attempts=1) is False
    solver._do_drag.assert_not_called()
    solver._send_cdp.assert_not_called()


def test_loading_foreign_slider_does_not_admit_an_extra_lookup_or_drag(monkeypatch):
    solver, _, _, _ = solve_probe(
        monkeypatch,
        [
            LOADING,
            {
                "readyState": "complete",
                "hasSlider": True,
                "href": TARGET.replace("123", "456"),
            },
        ],
        sliders=[None, SLIDER],
    )
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._do_drag.assert_not_called()


def test_local_mock_keeps_its_existing_loading_failure_contract(monkeypatch):
    solver, clock, _, waits = solve_probe(monkeypatch, [LOADING, AUTHENTICATED])
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: True)
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "challenge_loading"
    assert clock[0] == 0 and waits == []
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize("state", ["authenticated", "blank", "foreign", "error"])
def test_loading_recovery_uses_real_target_bound_payload_proof(monkeypatch, state):
    from tools.test.test_captcha_dom_evaluation import DocumentSolver

    document = {
        "url": TARGET,
        "text": "auction evidence " * 12,
        "html": '<html><body><div id="J_StartPrice">123</div></body></html>',
    }
    if state == "blank":
        document["html"] = ""
    elif state == "foreign":
        document["url"] = TARGET.replace("123", "456")
    elif state == "error":
        document["text"] = "验证失败"
        document["nodes"] = [{"selectors": [".errloading"]}]
    ready = DocumentSolver(document, TARGET)._page_challenge_summary()
    solver, _, _, _ = solve_probe(monkeypatch, [LOADING, ready])
    assert solver.solve(max_attempts=1) is (state == "authenticated")
    solver._do_drag.assert_not_called()
    solver._send_cdp.assert_not_called()
