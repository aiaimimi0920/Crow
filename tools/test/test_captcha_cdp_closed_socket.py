"""A confirmed closed transport is not a transient missing page response."""

from types import SimpleNamespace

import pytest
import websocket

from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_cdp_command_budget import probe
from tools.test.test_captcha_verification_terminal_failure import PollSolver


@pytest.mark.parametrize("phase", ["send", "receive"])
@pytest.mark.parametrize("connected", [True, None])
def test_explicit_closed_exception_stops_only_the_failed_socket(
    monkeypatch, phase, connected
):
    solver, sock, _ = probe(monkeypatch, [], budget=True)
    if connected is not None:
        sock.connected = connected
    calls = []

    def closed(*_args):
        calls.append(phase)
        raise websocket.WebSocketConnectionClosedException("synthetic closure")

    monkeypatch.setattr(sock, "send" if phase == "send" else "recv", closed)
    assert solver._send_cdp("Runtime.evaluate") is None
    identity = solver.message_id
    assert solver._send_cdp("Runtime.evaluate") is None
    assert calls == [phase]
    assert solver.message_id == identity == 2
    replacement = SimpleNamespace(
        send=lambda _raw: None,
        recv=lambda: '{"id": 2, "result": {"current": true}}',
    )
    solver.ws = replacement
    assert solver._send_cdp("Page.getLayoutMetrics") == {"current": True}


def test_already_disconnected_socket_starts_no_io_or_request_identity(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [])
    sock.connected = False
    assert solver._send_cdp("Runtime.evaluate") is None
    assert not sock.messages and solver.message_id == 1


@pytest.mark.parametrize("failure", [OSError, websocket.WebSocketTimeoutException])
def test_nonterminal_receive_failure_preserves_later_recovery(monkeypatch, failure):
    solver, sock, _ = probe(
        monkeypatch, [(0.1, {"id": 2, "result": {"current": True}})]
    )
    recv = sock.recv
    calls = []

    def transient():
        calls.append(True)
        if len(calls) == 1:
            raise failure("synthetic transient failure")
        return recv()

    monkeypatch.setattr(sock, "recv", transient)
    assert solver._send_cdp("Runtime.evaluate") is None
    assert solver._send_cdp("Page.getLayoutMetrics") == {"current": True}
    assert len(sock.messages) == 2 and solver.message_id == 3


@pytest.mark.parametrize("phase", ["entry", "verify", "summary"])
@pytest.mark.parametrize("closed_by", ["connected", "exception"])
def test_closed_verification_exits_without_remaining_poll_sends_or_waits(
    phase, closed_by
):
    solver = PollSolver([{"probeFailed": True}])
    sock = SimpleNamespace(connected=True)
    solver.ws = sock

    def close():
        if closed_by == "connected":
            sock.connected = False
        else:
            solver._closed_cdp_socket = sock

    if phase == "entry":
        close()
    elif phase == "verify":
        verify = solver._verify_success

        def verify_closed():
            close()
            return verify()

        solver._verify_success = verify_closed
    else:
        summary = solver._page_challenge_summary

        def summary_closed():
            close()
            return summary()

        solver._page_challenge_summary = summary_closed

    assert solver._wait_for_verification_success() is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver.verifications == (0 if phase == "entry" else 1)
    assert solver.summary_reads == (1 if phase == "summary" else 0)
    assert len(solver.waits) == (1 if phase == "summary" else 0)


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_reason_wins_over_closed_transport(reason):
    solver = PollSolver([{}])
    solver.ws = SimpleNamespace(connected=False)

    def stop():
        solver.last_failure_reason = reason
        return True

    solver._stop_if_cancelled = stop
    assert solver._wait_for_verification_success() is False
    assert solver.last_failure_reason == reason
    assert solver.verifications == solver.summary_reads == 0


def test_real_closed_verification_does_not_repeat_failed_socket_io(monkeypatch):
    solver, sock, _ = probe(monkeypatch, [], budget=True)
    solver.target_url = "https://example.test/owned-fixture"
    waits, receives = [], []
    solver._wait_interruptibly = waits.append

    def closed():
        receives.append(True)
        raise websocket.WebSocketConnectionClosedException("synthetic closure")

    monkeypatch.setattr(sock, "recv", closed)
    assert CaptchaSolver._wait_for_verification_success(solver) is False
    assert len(receives) == len(sock.messages) == 1
    assert not waits and solver.last_failure_reason == "cdp_unavailable"


def test_real_solve_preserves_page_without_reconnect_reload_or_input_replay(
    monkeypatch,
):
    from tools.test.test_captcha_cdp_command_budget import ClockSocket
    from tools.test.test_captcha_solve_loading_transition import SLIDER, solve_probe

    solver, clock, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    sock = ClockSocket(clock, [])
    solver.ws = sock
    solver._opened_target_ids.add("owned-recovery-page")
    for name in (
        "_send_cdp",
        "_verify_success",
        "_page_challenge_summary",
        "_wait_for_verification_success",
    ):
        setattr(solver, name, getattr(CaptchaSolver, name).__get__(solver))

    def closed():
        raise websocket.WebSocketConnectionClosedException("synthetic closure")

    monkeypatch.setattr(sock, "recv", closed)
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert len(sock.messages) == 1 and sock.closed and solver.ws is None
    assert solver._opened_target_ids == {"owned-recovery-page"}
    solver.connect_tab.assert_not_called()
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("release_fails", [False, True])
def test_closed_socket_does_not_skip_best_effort_mouse_release(
    monkeypatch, release_fails
):
    solver, sock, _ = probe(monkeypatch, [], budget=True)
    solver._cdp_mouse_down = True
    solver._cdp_mouse_position = (100, 50)

    def closed():
        raise websocket.WebSocketConnectionClosedException("synthetic closure")

    monkeypatch.setattr(sock, "recv", closed)
    assert solver._send_cdp("Runtime.evaluate") is None
    send = sock.send

    def release(raw):
        send(raw)
        if release_fails:
            raise websocket.WebSocketConnectionClosedException(
                "synthetic release failure"
            )

    monkeypatch.setattr(sock, "send", release)
    solver._close_solver_ws()
    assert [m["id"] for m in sock.messages] == [1, 2]
    assert sock.messages[-1]["method"] == "Input.dispatchMouseEvent"
    assert sock.messages[-1]["params"]["type"] == "mouseReleased"
    assert sock.messages[-1]["params"]["buttons"] == 0
    assert not solver._cdp_mouse_down and solver.message_id == 3
    assert sock.closed and solver.ws is None
