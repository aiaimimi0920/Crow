"""Loading grace bounds real CDP reads, not only the sleeps between them."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from tools.test.test_captcha_cdp_command_budget import probe

LOADING = {"readyState": "loading", "hasSlider": False, "hardBlock": True}
SLIDER = {"readyState": "complete", "hasSlider": True}
TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
AUTHENTICATED = {
    "readyState": "complete",
    "href": TARGET,
    "_verificationHtml": '<html><body><div id="J_StartPrice">123</div></body></html>',
}


def reply(number, summary):
    return {"id": number, "result": {"result": {"value": summary}}}


def loading_probe(monkeypatch, frames, **kwargs):
    solver, sock, now = probe(monkeypatch, frames, **kwargs)
    solver._wait_interruptibly = lambda seconds: now.__setitem__(0, now[0] + seconds)
    solver.connect_tab = Mock(return_value=True)
    solver._poll_until_authenticated = Mock(side_effect=AssertionError("No login wait"))
    solver._reset_failed_nc_challenge = Mock(side_effect=AssertionError("No input"))
    return solver, sock, now


@pytest.mark.parametrize("budget", [False, True])
def test_loading_reads_share_the_eight_second_window(monkeypatch, budget):
    solver, sock, now = loading_probe(
        monkeypatch, [(4, reply(1, LOADING)), (4, reply(2, LOADING))], budget=budget
    )
    result = solver._wait_for_loading_document(LOADING)
    assert all(result[key] == value for key, value in LOADING.items())
    assert now[0] == pytest.approx(108)
    assert len(sock.messages) == 2 and sock.timeout == 5
    assert not sock.closed and solver.last_failure_reason is None


@pytest.mark.parametrize("ready", [SLIDER, AUTHENTICATED])
def test_noncooperative_late_loading_read_is_not_admitted(monkeypatch, ready):
    solver, sock, now = loading_probe(
        monkeypatch,
        [(4, reply(1, LOADING)), (4, reply(2, ready))],
        cooperative=False,
    )
    solver.target_url = TARGET
    result = solver._wait_for_loading_document(LOADING)
    assert all(result[key] == value for key, value in LOADING.items())
    assert now[0] == pytest.approx(108.5)
    assert sock.timeout == 5 and len(sock.messages) == 2


def test_loading_read_ready_within_window_keeps_existing_success_path(monkeypatch):
    solver, sock, now = loading_probe(
        monkeypatch, [(4, reply(1, LOADING)), (3, reply(2, SLIDER))]
    )
    assert solver._wait_for_loading_document(LOADING)["hasSlider"]
    assert now[0] == pytest.approx(107.5)
    assert len(sock.messages) == 2 and sock.timeout == 5


def test_sleep_exhausting_loading_window_starts_no_fresh_probe(monkeypatch):
    solver, sock, now = loading_probe(monkeypatch, [])
    solver._wait_interruptibly = lambda _seconds: now.__setitem__(0, 108)
    assert solver._wait_for_loading_document(LOADING) == LOADING
    assert not sock.messages


@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_stop_after_loading_sleep_precedes_even_a_ready_snapshot(monkeypatch, stop):
    solver, sock, now = loading_probe(monkeypatch, [(0, reply(1, SLIDER))], budget=True)
    cancelled = [False]
    solver.cancel_checker = lambda: cancelled[0]

    def stop_wait(_seconds):
        cancelled[0] = stop == "cancelled"
        if stop == "deadline_exceeded":
            solver._solve_budget.deadline = now[0]
        else:
            now[0] = 108

    solver._wait_interruptibly = stop_wait
    with pytest.raises(SolveStopped, match=stop):
        solver._wait_for_loading_document(LOADING)
    assert solver.last_failure_reason == stop
    assert not sock.messages and sock.closed


@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_stop_during_loading_read_is_not_overwritten_by_local_timeout(
    monkeypatch, stop
):
    solver, sock, now = loading_probe(monkeypatch, [], budget=True)
    cancelled = [False]
    solver.cancel_checker = lambda: cancelled[0]

    def stopped_reply():
        cancelled[0] = stop == "cancelled"
        if stop == "deadline_exceeded":
            solver._solve_budget.deadline = now[0]
        return reply(1, SLIDER)

    sock.frames = [(0.1, stopped_reply)]
    with pytest.raises(SolveStopped, match=stop):
        solver._wait_for_loading_document(LOADING)
    assert solver.last_failure_reason == stop and sock.closed


@pytest.mark.parametrize("stage", ["preflight", "missing_slider", "post_drag"])
def test_loading_timeout_full_solve_defers_without_additional_recovery_or_input(
    monkeypatch, stage
):
    solver, sock, now = loading_probe(
        monkeypatch,
        [(0, reply(1, LOADING)), (4, reply(2, LOADING)), (4, reply(3, SLIDER))],
    )
    forbidden = (
        "_find_slider",
        "_reload_page",
        "_recover_authenticated_list_page",
        "_solve_with_ddddocr",
        "_solve_with_playwright_stealth",
    )
    for name in forbidden:
        setattr(solver, name, Mock(side_effect=AssertionError("No fallback or input")))
    solver._bring_to_front = Mock()
    if stage != "preflight":
        solver._preflight_current_challenge = Mock(return_value={"connected": True})
        solver._find_slider = Mock(return_value=None)
    if stage == "post_drag":
        solver._find_slider.return_value = {"x": 20, "y": 40, "width": 42, "height": 30}
        solver._os_mouse_enabled = Mock(return_value=False)
        solver._get_track_width = Mock(return_value=300)
        solver._get_track_rect = Mock(return_value=None)
        solver._do_drag = Mock(return_value=1)

        def verification():
            now[0] = 100
            return False

        solver._wait_for_verification_success = verification
    solver._close_owned_target_tabs = Mock()
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "challenge_loading"
    assert now[0] == pytest.approx(108)
    assert sock.closed and len(sock.messages) == 3
    assert all(m["method"] == "Runtime.evaluate" for m in sock.messages)
    for name in forbidden:
        if stage != "preflight" and name == "_find_slider":
            getattr(solver, name).assert_called_once()
        else:
            getattr(solver, name).assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None
    if stage == "post_drag":
        solver._do_drag.assert_called_once()
        solver._close_owned_target_tabs.assert_not_called()


def test_probe_failure_before_loading_deadline_keeps_transport_classification(
    monkeypatch,
):
    solver, sock, now = loading_probe(
        monkeypatch,
        [(0, reply(1, LOADING)), (1, {"id": 2, "error": {"code": -32601}})],
    )
    result = solver._preflight_current_challenge()
    assert result["retryable_failure"] and not result["manual_required"]
    assert solver.last_failure_reason == "cdp_unavailable"
    assert now[0] == pytest.approx(101.25) and sock.closed


@pytest.mark.parametrize("budget", [False, True])
@pytest.mark.parametrize(
    "method", ["Runtime.evaluate", "Page.navigate", "Page.captureScreenshot"]
)
def test_explicit_command_deadline_caps_all_original_windows(
    monkeypatch, budget, method
):
    solver, sock, now = probe(
        monkeypatch, [(2, {"id": 1, "result": {"ok": True}})], budget=budget
    )
    assert solver._send_cdp(method, deadline=101) is None
    assert now[0] == pytest.approx(101)
    assert len(sock.messages) == 1 and sock.timeout == 5
    assert solver.last_failure_reason is None and not sock.closed


def test_explicit_expired_command_deadline_sends_nothing(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [])
    assert solver._send_cdp("Runtime.evaluate", deadline=100) is None
    assert not sock.messages and sock.timeout == 5 and solver.message_id == 1


def test_local_command_limit_cannot_extend_original_or_next_command(monkeypatch):
    solver, sock, now = probe(
        monkeypatch,
        [(6, {"id": 1, "result": {}}), (1, {"id": 2, "result": {"ok": True}})],
        budget=True,
    )
    assert solver._send_cdp("Runtime.evaluate", deadline=120) is None
    assert now[0] == pytest.approx(105)
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert sock.timeout == 5 and len(sock.messages) == 2


def test_send_and_unrelated_frames_consume_same_explicit_deadline(monkeypatch):
    solver, sock, now = probe(
        monkeypatch,
        [(0.4, {"id": 999, "result": {}}), (0.4, {"id": 1, "result": {}})],
        send_delay=0.4,
    )
    assert solver._send_cdp("Runtime.evaluate", deadline=101) is None
    assert now[0] == pytest.approx(101)
    assert len(sock.messages) == 1 and sock.timeout == 5


def test_shorter_solve_deadline_still_closes_socket_and_keeps_reason(monkeypatch):
    solver, sock, now = loading_probe(monkeypatch, [(4, reply(1, SLIDER))], budget=True)
    solver._solve_budget.deadline = 101
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._wait_for_loading_document(LOADING)
    assert now[0] == pytest.approx(101)
    assert solver.last_failure_reason == "deadline_exceeded" and sock.closed


def test_explicit_deadline_exhausted_by_send_starts_no_receive(monkeypatch):
    solver, sock, now = probe(monkeypatch, [(0, {"id": 1, "result": {}})], send_delay=2)
    assert solver._send_cdp("Runtime.evaluate", deadline=101) is None
    assert now[0] == 102 and len(sock.frames) == 1
    assert len(sock.messages) == 1 and sock.timeout == 5


def test_successful_short_deadline_is_not_inherited_by_next_command(monkeypatch):
    solver, sock, _ = probe(
        monkeypatch,
        [(0.1, {"id": 1, "result": {}}), (1, {"id": 2, "result": {"ok": True}})],
    )
    assert solver._send_cdp("Runtime.evaluate", deadline=100.2) == {}
    assert solver._send_cdp("Runtime.evaluate") == {"ok": True}
    assert sock.timeout == 5


def test_cancellation_remains_prior_to_both_expired_deadlines(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [], budget=True)
    solver._solve_budget.deadline = 100
    solver.cancel_checker = lambda: True
    assert solver._send_cdp("Runtime.evaluate", deadline=100) is None
    assert solver.last_failure_reason == "cancelled" and sock.closed
    assert not sock.messages and solver.message_id == 1


def test_non_loading_summary_refresh_preserves_legacy_call_shape(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [(0.1, reply(1, SLIDER))])
    send = Mock(wraps=solver._send_cdp)
    solver._send_cdp = send
    assert solver._refresh_challenge_summary({})["hasSlider"]
    assert send.call_args.kwargs == {} and len(sock.messages) == 1
