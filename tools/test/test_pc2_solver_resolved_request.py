"""Completed control-plane requests cannot reanimate leftover challenge pages."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_scope_policy as policy
from tools.pc2_solver_state_store import _default_fallback_state

CDP = "http://127.0.0.1:9223"
TARGET = "https://sf.taobao.com/list/example.htm"


def resolved(**changes):
    return {
        "last_status": "manual_auth_completed",
        "paused": False,
        "manual_required": False,
        "running": False,
        "challenge_id": None,
        "last_request": {"target_url": TARGET, "node_id": "pc2"},
        "scopes": {
            name: {"paused": False, "manual_required": False, "challenge_id": None}
            for name in ("seed", "detail")
        },
        **changes,
    }


@pytest.mark.parametrize("last_status", ["manual_auth_completed", "solved"])
def test_resolved_owned_request_is_not_eligible_again(monkeypatch, last_status):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = resolved(last_status=last_status)
    before = deepcopy(status)
    assert policy.node_solver_execution_block_reason(status, CDP, "pc2") == (
        "request_already_resolved"
    )
    assert status == before


@pytest.mark.parametrize(
    "changes",
    [
        {"last_status": "manual_retry"},
        {"last_status": "resumed"},
        {"last_status": "resumed_after_cooldown"},
        {"last_status": "idle"},
        {"last_status": None},
        {"challenge_id": "new-challenge"},
        {"paused": True},
        {"paused": None},
        {"manual_required": True},
        {"manual_required": None},
        {"running": None},
        {"force_reset_required": True},
    ],
)
def test_incomplete_or_new_request_is_not_suppressed(monkeypatch, changes):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    assert (
        policy.node_solver_execution_block_reason(resolved(**changes), CDP, "pc2")
        is None
    )


@pytest.mark.parametrize("key", ["scopes", "collection_scopes"])
def test_new_scoped_challenge_overrides_old_aggregate_completion(monkeypatch, key):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = resolved()
    status.pop("scopes")
    status[key] = {
        "detail": {
            "challenge_id": "detail-new",
            "paused": True,
            "manual_required": False,
            "last_request": {
                "target_url": "https://sf-item.taobao.com/item/1",
                "node_id": "pc2",
            },
        }
    }
    assert policy.node_solver_execution_block_reason(status, CDP, "pc2") is None
    selected = policy.select_solver_scope_status(status)
    assert selected["challenge_id"] == "detail-new"
    assert policy.node_solver_execution_block_reason(selected, CDP, "pc2") is None


@pytest.fixture
def run_loop(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    state = _default_fallback_state()
    monkeypatch.setattr(loop, "hold_manual_window", lambda _: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_: None)
    monkeypatch.setattr(
        loop, "IdlePointer", lambda _: SimpleNamespace(tick=lambda *_: None)
    )
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "log_event", lambda _: None)
    monkeypatch.setattr(loop, "compact_active_challenge_pages", lambda *_: {})
    monkeypatch.setattr(
        loop, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value
    )
    monkeypatch.setattr(loop, "_load_fallback_state", lambda: state)
    monkeypatch.setattr(loop, "_save_fallback_state", lambda _: None)
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_: None)
    monkeypatch.setattr(loop, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(loop, "record_failed_attempt", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "match_solver_request_target_url", lambda *_: TARGET)
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **_: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )

    def run(initial, *, latest=None, iterations=3):
        calls, polls = [], [0]
        monkeypatch.setattr(
            loop,
            "read_solver_status",
            lambda _: initial if not calls else (latest or initial),
        )

        def probe(*_args, **options):
            calls.append(("probe", options["periodic"]))
            return {"_target_id": "leftover-page"}, TARGET

        monkeypatch.setattr(loop, "probe_requested_targets", probe)
        monkeypatch.setattr(
            loop,
            "run_solver_local_with_deadline",
            lambda *_a, **_k: calls.append(("solve",)) or False,
        )

        class StopLoop(BaseException):
            pass

        def sleep(_):
            polls[0] += 1
            if polls[0] >= iterations:
                raise StopLoop

        monkeypatch.setattr(loop.time, "sleep", sleep)
        with pytest.raises(StopLoop):
            loop.local_solver_loop(
                cdp_endpoint=CDP, expected_node_id="pc2", poll_seconds=30
            )
        return calls

    return run


def test_resolved_idle_loop_never_probes_or_solves_old_page(run_loop):
    assert run_loop(resolved()) == []


@pytest.mark.parametrize("status", ["manual_retry", "resumed_after_cooldown"])
def test_legacy_reset_periodic_probe_still_executes(run_loop, status):
    assert run_loop(resolved(last_status=status), iterations=1) == [
        ("probe", True),
        ("solve",),
    ]


def test_new_challenge_still_executes_immediately(run_loop):
    assert run_loop(resolved(paused=True, challenge_id="new"), iterations=1) == [
        ("probe", False),
        ("solve",),
    ]


def test_auth_completion_during_probe_blocks_execution(run_loop):
    calls = run_loop(
        resolved(paused=True, challenge_id="old"), latest=resolved(), iterations=1
    )
    assert calls == [("probe", False)]
