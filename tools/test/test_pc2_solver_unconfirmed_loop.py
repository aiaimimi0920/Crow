"""Exercise the real attempt -> loop -> failure policy without browser/network I/O."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop as loop
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_state_store as store

TARGET = "https://sf-item.taobao.com/sf_item/1.htm"
PROBE = {"_target_id": "pending-page"}


@pytest.mark.parametrize(
    "reason,rotates",
    [
        ("challenge_loading", False),
        ("cdp_unavailable", False),
        ("cancelled", False),
        ("deadline_exceeded", False),
        ("challenge_retry_exhausted", True),
        ("manual_required", False),
    ],
)
def test_loop_honors_real_attempt_failure_metadata(monkeypatch, reason, rotates):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = {
        "paused": True,
        "running": False,
        "manual_required": False,
        "scope": "detail",
        "challenge_id": "one",
        "last_request": {"target_url": TARGET, "node_id": "pc2"},
    }
    events = []
    solver = Mock(last_failure_reason=reason)
    solver.solve.return_value = False
    monkeypatch.setattr(execution, "_solver_class", lambda: lambda **_: solver)
    monkeypatch.setattr(execution, "record_failed_drags", Mock())
    monkeypatch.setattr(execution, "log_event", events.append)
    monkeypatch.setattr(
        loop,
        "run_solver_local_with_deadline",
        partial(execution.run_solver_local_with_deadline, timeout_seconds=0),
    )
    rotate = Mock(return_value={"probe_target": PROBE})
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", Mock())
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
    monkeypatch.setattr(failure, "log_event", events.append)
    monkeypatch.setattr(loop, "log_event", events.append)
    monkeypatch.setattr(loop, "hold_manual_window", lambda _: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_: None)
    monkeypatch.setattr(
        loop, "IdlePointer", lambda _: SimpleNamespace(tick=lambda *_: None)
    )
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "compact_active_challenge_pages", lambda *_: {})
    monkeypatch.setattr(
        loop, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value
    )
    monkeypatch.setattr(loop, "read_solver_status", lambda _: status)
    monkeypatch.setattr(failure, "read_solver_status", lambda _: status)
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_: None)
    monkeypatch.setattr(loop, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(
        loop, "probe_requested_targets", lambda *_a, **_k: (PROBE, TARGET)
    )
    report = Mock(return_value={"status": "manual_required"})
    monkeypatch.setattr(loop, "notify_manual_challenge", report)
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **_: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )

    class StopLoop(BaseException):
        pass

    def sleep(_):
        raise StopLoop

    monkeypatch.setattr(loop, "time", SimpleNamespace(time=lambda: 1000.0, sleep=sleep))
    with pytest.raises(StopLoop):
        loop.local_solver_loop(
            cdp_endpoint="http://127.0.0.1:9223", expected_node_id="pc2"
        )
    assert not any(event["kind"] == "loop_error" for event in events)
    assert rotate.call_count == int(rotates)
    saved = store._load_fallback_state()
    if reason == "manual_required":
        report.assert_called_once()
        assert saved["manual_pushed"] is True
        assert saved["slider_attempts"] == 0
    else:
        report.assert_not_called()
        assert saved["slider_attempts"] == saved["consecutive_failures"] == 1
        assert any(
            event.get("failure_reason") == reason
            for event in events
            if event["kind"] == "local_solver_failure"
        )
