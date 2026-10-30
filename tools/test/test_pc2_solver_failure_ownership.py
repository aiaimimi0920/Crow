"""A late failed attempt cannot mutate a completed or superseded request."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store

CDP = "http://127.0.0.1:9223"
TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
PROBE = {"_target_id": "old-page", "_target_url": TARGET}


def active():
    local = {
        "scope": "detail",
        "challenge_id": "old",
        "paused": True,
        "manual_required": False,
        "last_status": "running",
        "last_request": {"node_id": "pc2", "target_url": TARGET},
    }
    return {**local, "running": False, "scopes": {"detail": deepcopy(local)}}


def changed(kind):
    status = active()
    own = status["scopes"]["detail"]
    if kind == "completed_with_other_scope_active":
        own.update(
            challenge_id=None,
            paused=False,
            manual_required=False,
            last_status="manual_auth_completed",
            last_request={},
        )
        status.update(paused=True, manual_required=True)
        status["scopes"]["seed"] = {
            "challenge_id": "seed-new",
            "paused": True,
            "manual_required": True,
        }
    elif kind == "generation_changed":
        own["challenge_id"] = "new"
    elif kind == "owner_changed":
        own["last_request"]["node_id"] = "pc1"
    elif kind == "target_changed":
        own["last_request"]["target_url"] = TARGET.replace("123", "456")
    elif kind == "manual_takeover":
        own["manual_only"] = True
    elif kind == "operator_paused":
        own["operator_paused"] = True
    elif kind == "node_blocked":
        own["node_solver_blocked"] = True
    elif kind == "nas_running":
        status["running"] = True
    elif kind == "scope_missing":
        status["scopes"] = {"seed": {"challenge_id": "seed-new"}}
    elif kind == "unavailable":
        return {"error": "offline fixture"}
    return status


@pytest.fixture
def run_failed_loop(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
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
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_: None)
    monkeypatch.setattr(loop, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(
        loop, "probe_requested_targets", lambda *_a, **_k: (PROBE, TARGET)
    )
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **_: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 100)
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(failure, "FALLBACK_FAIL_THRESHOLD", 1)
    monkeypatch.setattr(failure, "FALLBACK_STALL_SECONDS", 0)
    logs = []
    monkeypatch.setattr(loop, "log_event", logs.append)
    monkeypatch.setattr(failure, "log_event", logs.append)

    def run(
        latest,
        *,
        manual=True,
        reason="challenge_retry_exhausted",
        state_values=None,
        cooldown_threshold=100,
    ):
        state = store._default_fallback_state()
        state.update(challenge_id="old", scope="detail", window_started_at=10.0)
        state.update(state_values or {})
        monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", cooldown_threshold)
        monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
        store._save_fallback_state(state)
        current = [active()]
        reads = []

        def read(_api):
            reads.append(deepcopy(current[0]))
            return deepcopy(current[0])

        monkeypatch.setattr(loop, "read_solver_status", read)
        monkeypatch.setattr(failure, "read_solver_status", read, raising=False)

        def solve(*_args, failure_details, **_kwargs):
            current[0] = deepcopy(latest)
            failure_details["failure_reason"] = reason
            return False

        monkeypatch.setattr(loop, "run_solver_local_with_deadline", solve)
        rotate = Mock(return_value={"probe_target": PROBE})
        browse, report = Mock(), Mock(return_value={"ok": True})
        monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
        monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
        monkeypatch.setattr(failure, "_report_manual_captcha", report)
        monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: manual)

        class StopLoop(BaseException):
            pass

        def stop(_seconds):
            raise StopLoop

        monkeypatch.setattr(loop.time, "sleep", stop)
        with pytest.raises(StopLoop):
            loop.local_solver_loop(
                api_base_url="https://nas.test/api",
                cdp_endpoint=CDP,
                expected_node_id="pc2",
                poll_seconds=30,
            )
        return SimpleNamespace(
            rotate=rotate,
            browse=browse,
            report=report,
            reads=reads,
            logs=logs,
            state=store._load_fallback_state(),
        )

    return run


@pytest.mark.parametrize(
    "kind",
    [
        "completed_with_other_scope_active",
        "generation_changed",
        "owner_changed",
        "target_changed",
        "manual_takeover",
        "operator_paused",
        "node_blocked",
        "nas_running",
        "scope_missing",
        "unavailable",
    ],
)
def test_changed_request_blocks_failure_side_effects_but_keeps_budget(
    run_failed_loop, kind
):
    result = run_failed_loop(changed(kind))

    result.rotate.assert_not_called()
    result.browse.assert_not_called()
    result.report.assert_not_called()
    assert result.state["slider_attempts"] == result.state["consecutive_failures"] == 1
    assert result.state["manual_pushed"] is False
    assert result.state["slider_next_attempt_at"] > 1000
    assert len(result.reads) == 3  # poll, execution boundary, failure boundary


def test_blocked_cleanup_still_reaches_existing_shared_cooldown(run_failed_loop):
    result = run_failed_loop(
        changed("unavailable"),
        state_values={"consecutive_failures": 9, "slider_attempts": 2},
        cooldown_threshold=10,
    )

    result.rotate.assert_not_called()
    result.browse.assert_not_called()
    result.report.assert_not_called()
    assert result.state["consecutive_failures"] == 10
    assert result.state["slider_attempts"] == 3
    assert result.state["solver_cooldown_until"] == 1180.0
    assert result.state["slider_next_attempt_at"] is None
    assert result.state["manual_pushed"] is False
    assert len(result.reads) == 3  # poll, execution boundary, failure boundary


@pytest.mark.parametrize("manual", [False, True])
def test_same_owned_request_retains_rotation_and_existing_escalation(
    run_failed_loop, manual
):
    result = run_failed_loop(active(), manual=manual)

    result.rotate.assert_called_once_with(CDP, TARGET, probe_target=PROBE)
    assert result.report.call_count == int(manual)
    assert result.browse.call_count == int(not manual)
    assert result.state["slider_attempts"] == result.state["consecutive_failures"] == 1


@pytest.mark.parametrize(
    "reason", ["cdp_unavailable", "cancelled", "deadline_exceeded"]
)
def test_unconfirmed_attempt_still_preserves_page_without_extra_status_read(
    run_failed_loop, reason
):
    result = run_failed_loop(changed("unavailable"), reason=reason)

    result.rotate.assert_not_called()
    result.browse.assert_not_called()
    result.report.assert_not_called()
    assert len(result.reads) == 2
    assert result.state["slider_attempts"] == result.state["consecutive_failures"] == 1
