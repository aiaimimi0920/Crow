"""Transport failures must not masquerade as an official manual challenge."""

import json
from threading import Event
from unittest.mock import Mock

import pytest
import websocket

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution


@pytest.mark.parametrize(
    "failure", [OSError("offline"), websocket.WebSocketTimeoutException("busy")]
)
def test_challenge_connection_failure_remains_retryable(monkeypatch, failure):
    solver = CaptchaSolver(target_url="https://sf.taobao.com/list/50025969__2.htm")
    solver.current_target_url = solver.target_url + "/_____tmd_____/punish"
    monkeypatch.setattr(websocket, "create_connection", Mock(side_effect=failure))

    assert not solver._connect_to_target(
        "ws://127.0.0.1:9223/devtools/page/test", "challenge"
    )
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver.ws is None


def test_failed_bootstrap_probe_does_not_trigger_manual_handoff(monkeypatch):
    solver = CaptchaSolver()
    solver.current_target_url = (
        "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"
    )
    sock = Mock()
    monkeypatch.setattr(websocket, "create_connection", Mock(return_value=sock))
    monkeypatch.setattr(solver, "_send_cdp", Mock(return_value=None))
    monkeypatch.setattr(
        solver,
        "connect_tab",
        lambda: solver._connect_to_target("ws://localhost/test", "test"),
    )

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is False
    assert result["connected"] is False
    assert solver.last_failure_reason == "cdp_unavailable"
    sock.close.assert_called_once()


@pytest.mark.parametrize("mock_target", [False, True])
def test_mouse_transport_failure_is_retryable(monkeypatch, mock_target):
    solver = CaptchaSolver()
    monkeypatch.setattr(solver, "_send_cdp", Mock(return_value=None))
    if mock_target:
        assert solver._do_drag_local_mock(100, 100, 200) is None
    else:
        assert not solver._dispatch_mouse("mouseMoved", 100, 100)
    assert solver.last_failure_reason == "cdp_unavailable"


@pytest.mark.parametrize("expired", [False, True])
def test_mouse_transport_failure_preserves_cancel_or_deadline(monkeypatch, expired):
    solver = CaptchaSolver()
    cancel = Event()
    if not expired:
        cancel.set()
    solver._solve_budget = SolveBudget(
        deadline=0 if expired else 100, cancel_event=cancel, clock=lambda: 1
    )
    monkeypatch.setattr(solver, "_send_cdp", Mock(return_value=None))

    assert not solver._dispatch_mouse("mouseMoved", 100, 100)
    assert solver.last_failure_reason == (
        "deadline_exceeded" if expired else "cancelled"
    )


@pytest.mark.parametrize("reason", ["cdp_unavailable", "manual_required"])
def test_pc2_execution_handoff_still_requires_official_manual_reason(
    monkeypatch, reason
):
    solver = Mock(last_failure_reason=reason)
    solver.solve.return_value = False
    monkeypatch.setattr(
        pc2_solver_execution, "_solver_class", lambda: Mock(return_value=solver)
    )
    monkeypatch.setattr(pc2_solver_execution, "log_event", Mock())
    if reason == "manual_required":
        with pytest.raises(pc2_solver_execution.ManualChallengeRequired):
            pc2_solver_execution.run_solver_local(
                "http://localhost:9223", "https://sf.taobao.com/list/test"
            )
    else:
        assert not pc2_solver_execution.run_solver_local(
            "http://localhost:9223", "https://sf.taobao.com/list/test"
        )


@pytest.mark.parametrize("lost_ack", [False, True])
def test_failed_drag_releases_even_an_unacknowledged_button(monkeypatch, lost_ack):
    solver = CaptchaSolver()
    solver.ws = Mock()
    monkeypatch.setattr(
        solver, "_send_cdp", Mock(return_value=None if lost_ack else {})
    )
    assert solver._dispatch_mouse("mousePressed", 100, 100) is (not lost_ack)
    if not lost_ack:
        solver._send_cdp.return_value = None
        assert not solver._dispatch_mouse("mouseMoved", 110, 100, buttons=1)
    released = json.loads(solver.ws.send.call_args.args[0])
    assert released["params"]["type"] == "mouseReleased"
    assert released["params"]["buttons"] == 0
    assert solver._cdp_mouse_down is False
    assert solver.last_failure_reason == "cdp_unavailable"


@pytest.mark.parametrize("late_failure", [False, True])
def test_preflight_never_promotes_a_failed_probe_to_manual(monkeypatch, late_failure):
    solver = CaptchaSolver()
    summaries = iter(
        [{"hardBlock": True}, {"hardBlock": True}, {"probeFailed": True}]
        if late_failure
        else [{"hardBlock": True}, {"probeFailed": True}]
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: True)
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: next(summaries))
    monkeypatch.setattr(solver, "_poll_until_authenticated", lambda: False)
    monkeypatch.setattr(solver, "_reset_failed_nc_challenge", lambda: False)
    result = solver._preflight_current_challenge()
    assert result["manual_required"] is False
    assert solver.last_failure_reason == "cdp_unavailable"


def test_preflight_waits_for_a_loading_challenge_without_manual_handoff(monkeypatch):
    solver = CaptchaSolver()
    monkeypatch.setattr(solver, "connect_tab", lambda: True)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: {"hardBlock": True, "readyState": "loading"},
    )
    assert not solver._preflight_current_challenge()["manual_required"]
    assert solver.last_failure_reason == "challenge_loading"


def test_failed_cdp_summary_explicitly_records_missing_observation(monkeypatch):
    solver = CaptchaSolver()
    monkeypatch.setattr(solver, "_send_cdp", Mock(return_value=None))
    assert solver._page_challenge_summary()["probeFailed"]


def test_failed_refresh_does_not_return_an_unmarked_stale_block(monkeypatch):
    solver = CaptchaSolver()
    monkeypatch.setattr(
        solver, "_page_challenge_summary", Mock(side_effect=OSError("offline"))
    )
    summary = solver._refresh_challenge_summary({"hardBlock": True})
    assert summary["hardBlock"] and summary["probeFailed"]


@pytest.mark.parametrize("empty_summary", [None, {}])
def test_empty_refresh_does_not_reuse_stale_block_as_fresh(monkeypatch, empty_summary):
    solver = CaptchaSolver()
    monkeypatch.setattr(
        solver, "_page_challenge_summary", Mock(return_value=empty_summary)
    )
    summary = solver._refresh_challenge_summary({"hardBlock": True})
    assert summary["probeFailed"]


@pytest.mark.parametrize(
    ("fresh_summary", "reason"),
    [
        ({"loginRequired": True, "readyState": "loading"}, "challenge_loading"),
        ({"readyState": "complete"}, None),
        ({"loginRequired": True, "readyState": "complete"}, "manual_required"),
        ({"hardBlock": True, "readyState": "complete"}, "manual_required"),
    ],
)
def test_login_wait_handoff_uses_current_page_evidence(
    monkeypatch, fresh_summary, reason
):
    solver = CaptchaSolver()
    summaries = iter([{"loginRequired": True}, fresh_summary])
    monkeypatch.setattr(solver, "connect_tab", lambda: True)
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: next(summaries))
    monkeypatch.setattr(solver, "_poll_until_authenticated", lambda: False)
    result = solver._preflight_current_challenge()
    assert result["manual_required"] is (reason == "manual_required")
    assert solver.last_failure_reason == reason


@pytest.mark.parametrize(
    ("summaries", "reason"),
    [
        ([{"hardBlock": True, "readyState": "loading"}], "challenge_loading"),
        ([{"hardBlock": True}, {"probeFailed": True}], "cdp_unavailable"),
        ([{"hardBlock": True}, {"readyState": "loading"}], "challenge_loading"),
        ([{"hardBlock": True}, {"authenticatedPage": True}], None),
        ([{"hardBlock": True}, {"hardBlock": True}], "manual_required"),
    ],
)
def test_no_slider_handoff_requires_fresh_terminal_evidence(
    monkeypatch, summaries, reason
):
    solver = CaptchaSolver()
    responses = iter(summaries)
    monkeypatch.setattr(
        solver, "_preflight_current_challenge", lambda: {"connected": True}
    )
    monkeypatch.setattr(solver, "_find_slider", lambda **kwargs: None)
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: next(responses))
    monkeypatch.setattr(solver, "_reset_failed_nc_challenge", lambda: False)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: None)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    assert solver.solve(max_attempts=1) is (reason is None)
    assert solver.last_failure_reason == reason
