"""Work arbitration must not let a scoped manual latch starve automatic work."""

from copy import deepcopy

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_retry_state as retry
from tools.pc2_solver_state_store import _default_fallback_state


def scoped_status():
    def scope(name, manual, first_seen):
        target = (
            "https://sf.taobao.com/list/1.htm"
            if name == "seed"
            else "https://sf-item.taobao.com/sf_item/123.htm"
        )
        return {
            "scope": name,
            "challenge_id": name + "-one",
            "first_seen_epoch": first_seen,
            "paused": True,
            "manual_required": manual,
            "manual_only": manual,
            "node_solver_blocked": False,
            "force_reset_required": False,
            "last_request": {"node_id": "pc2", "target_url": target},
        }

    return {
        "running": False,
        "queued": False,
        "nas_solver_active": False,
        "paused": True,
        "scope": "seed",
        "pause_reason": "manual_required",
        "force_unlock_flag_exists": False,
        "manual_required": True,
        "manual_only": True,
        "scopes": {"seed": scope("seed", True, 1), "detail": scope("detail", False, 2)},
    }


@pytest.fixture
def work_loop(monkeypatch):
    class StopPoll(BaseException):
        pass

    status = scoped_status()
    state = _default_fallback_state()
    state.update(
        challenge_id="seed-one",
        scope="seed",
        consecutive_failures=7,
        slider_attempts=3,
        window_started_at=100,
        slider_next_attempt_at=200,
    )
    original = deepcopy(status)
    probes, saved, events = [], [], []
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setattr(loop, "hold_manual_window", lambda _poll: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_a: None)
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a: None)
    monkeypatch.setattr(loop, "log_event", events.append)
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **_kw: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )
    monkeypatch.setattr(loop, "read_solver_status", lambda _api: deepcopy(status))
    monkeypatch.setattr(loop, "compact_active_challenge_pages", lambda *_a: {})
    monkeypatch.setattr(loop, "reset_forced_solver_scopes", lambda _a, _b, s, _d: s)
    monkeypatch.setattr(loop, "_load_fallback_state", lambda: deepcopy(state))
    monkeypatch.setattr(
        loop, "_save_fallback_state", lambda s: saved.append(deepcopy(s))
    )
    monkeypatch.setattr(
        retry, "_save_fallback_state", lambda s: saved.append(deepcopy(s))
    )
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_a: None)
    monkeypatch.setattr(loop.time, "time", lambda: 300)

    def stop(*_a, **_kw):
        raise StopPoll

    def probe(_cdp, targets, **_kw):
        probes.append(targets)
        raise StopPoll

    monkeypatch.setattr(loop, "probe_requested_targets", probe)
    monkeypatch.setattr(loop.time, "sleep", stop)
    monkeypatch.setattr(
        loop,
        "run_solver_local_with_deadline",
        lambda *_a, **_k: pytest.fail("no browser input"),
    )

    def poll():
        with pytest.raises(StopPoll):
            loop.local_solver_loop(poll_seconds=1, expected_node_id="pc2")

    return status, state, original, probes, saved, events, poll


def test_loop_schedules_owned_automatic_detail_without_clearing_seed(work_loop):
    status, _state, original, probes, saved, _events, poll = work_loop
    poll()
    assert probes == [["https://sf-item.taobao.com/sf_item/123.htm"]]
    assert status == original
    assert saved[-1]["challenge_id"] == "detail-one"
    assert saved[-1]["scope"] == "detail"
    assert saved[-1]["consecutive_failures"] == 7
    assert saved[-1]["window_started_at"] == 100
    assert saved[-1]["slider_next_attempt_at"] == 200


def test_acknowledged_bound_manual_latch_switch_keeps_shared_budget(work_loop):
    _status, state, _original, probes, saved, _events, poll = work_loop
    state["manual_pushed"] = True
    poll()
    assert probes == [["https://sf-item.taobao.com/sf_item/123.htm"]]
    assert saved[-1]["manual_pushed"] is False
    assert saved[-1]["consecutive_failures"] == 7


def test_proven_scoped_compatibility_mirror_does_not_starve_detail(work_loop):
    status, state, _original, probes, saved, _events, poll = work_loop
    status.update(force_unlock_flag_exists=True, global_manual_pause_active=False)
    state["manual_pushed"] = True
    poll()
    assert probes == [["https://sf-item.taobao.com/sf_item/123.htm"]]
    assert saved[-1]["scope"] == "detail"
    assert saved[-1]["consecutive_failures"] == 7


def test_unbound_manual_latch_does_not_reach_full_budget_reset(work_loop):
    _status, state, _original, probes, saved, _events, poll = work_loop
    state.update(challenge_id=None, manual_pushed=True)
    poll()
    assert probes == saved == []


@pytest.mark.parametrize(
    "pending",
    ["auth_complete_pending", "collection_resume_pending", "terminal_manual_pending"],
)
def test_loop_does_not_discard_unconfirmed_receipts(work_loop, pending):
    _status, state, _original, probes, saved, _events, poll = work_loop
    state[pending] = True
    poll()
    assert probes == []
    assert all(s["challenge_id"] == "seed-one" for s in saved)


@pytest.mark.parametrize("until", [299, 400])
def test_loop_does_not_skip_cooldown_or_its_resume_ack(work_loop, until):
    _status, state, _original, probes, _saved, _events, poll = work_loop
    state.update(
        solver_cooldown_until=until, solver_cooldown_reason="repeated_solver_failures"
    )
    poll()
    assert probes == []


def test_global_manual_window_precedes_all_work_selection(work_loop, monkeypatch):
    _status, _state, _original, probes, saved, _events, poll = work_loop
    calls = [False, True]
    monkeypatch.setattr(
        loop,
        "hold_manual_window",
        lambda _poll: calls.pop(0) if calls else (_ for _ in ()).throw(SystemExit()),
    )
    with pytest.raises(SystemExit):
        poll()
    assert probes == saved == []


@pytest.mark.parametrize(
    "reason", ["manual_only", "nas_solver_running", "request_owned_elsewhere"]
)
def test_fresh_execution_boundary_can_still_reject_selected_work(
    work_loop, monkeypatch, reason
):
    status, _state, _original, _probes, _saved, events, poll = work_loop
    latest = deepcopy(status)
    detail = latest["scopes"]["detail"]
    if reason == "manual_only":
        detail.update(manual_required=True, manual_only=True)
    elif reason == "nas_solver_running":
        latest["running"] = True
    else:
        detail["last_request"]["node_id"] = "other"
    reads = [status, latest]
    monkeypatch.setattr(loop, "read_solver_status", lambda _api: deepcopy(reads.pop(0)))
    monkeypatch.setattr(
        loop,
        "probe_requested_targets",
        lambda *_a, **_kw: (
            {"id": "fixture"},
            "https://sf-item.taobao.com/sf_item/123.htm",
        ),
    )
    poll()
    assert any(
        event.get("kind") == "local_solver_execution_blocked"
        and event.get("reason") == reason
        for event in events
    )
