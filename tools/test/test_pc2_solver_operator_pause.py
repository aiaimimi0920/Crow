"""Explicit operator pauses stop new work, not just collection task claims."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_scope_policy as policy
from tools.pc2_solver_failure_guard import failure_mutation_block_reason
from tools.pc2_solver_manual_handoff import report_execution_block
from tools.test import test_pc2_solver_failure_ownership as failure_tests
from tools.test import test_pc2_solver_work_selection_loop as selection_tests

work_loop = selection_tests.work_loop
run_failed_loop = failure_tests.run_failed_loop
CDP = "http://127.0.0.1:9223"
TARGET = "https://sf-item.taobao.com/sf_item/123.htm"


def owned(**changes):
    return {
        "scope": "detail",
        "paused": True,
        "running": False,
        "manual_required": False,
        "manual_only": False,
        "challenge_id": "detail-one",
        "last_request": {"node_id": "pc2", "target_url": TARGET},
        **changes,
    }


@pytest.mark.parametrize(
    "pause", [{"pause_reason": "operator"}, {"operator_paused": True}]
)
def test_execution_gate_respects_explicit_operator_pause(monkeypatch, pause):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = owned(**pause)
    original = deepcopy(status)
    assert policy.node_solver_execution_block_reason(status, CDP, "pc2") == (
        "operator_paused"
    )
    assert status == original


@pytest.mark.parametrize("reason", [None, "captcha_solver", "manual_required"])
def test_challenge_pause_is_not_an_operator_pause(monkeypatch, reason):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    assert (
        policy.node_solver_execution_block_reason(
            owned(pause_reason=reason), CDP, "pc2"
        )
        is None
    )


def test_resumed_status_does_not_keep_a_stale_operator_reason(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = owned(paused=False, pause_reason="operator", operator_paused=False)
    assert policy.node_solver_execution_block_reason(status, CDP, "pc2") is None


@pytest.mark.parametrize(
    "pause", [{"pause_reason": "operator"}, {"operator_paused": True}]
)
def test_poll_pause_precedes_compaction_reset_probes_and_state_changes(
    work_loop, monkeypatch, pause
):
    status, _state, _original, probes, saved, events, poll = work_loop
    status.update(pause)
    before = deepcopy(status)
    compact, reset = Mock(return_value={}), Mock(side_effect=lambda _a, _b, s, _d: s)
    monkeypatch.setattr(loop, "compact_active_challenge_pages", compact)
    monkeypatch.setattr(loop, "reset_forced_solver_scopes", reset)

    poll()

    compact.assert_not_called()
    reset.assert_not_called()
    assert probes == saved == []
    assert status == before
    assert {
        "kind": "local_solver_execution_blocked",
        "reason": "operator_paused",
    } in events


@pytest.mark.parametrize(
    "pause", [{"pause_reason": "operator"}, {"operator_paused": True}]
)
def test_operator_pause_arriving_during_probe_blocks_new_execution(
    work_loop, monkeypatch, pause
):
    status, _state, _original, _probes, _saved, events, poll = work_loop
    latest = deepcopy(status)
    latest.update(pause)
    reads = [status, latest]
    monkeypatch.setattr(loop, "read_solver_status", lambda _api: deepcopy(reads.pop(0)))
    monkeypatch.setattr(
        loop, "probe_requested_targets", lambda *_a, **_kw: ({"id": "fixture"}, TARGET)
    )
    monkeypatch.setattr(loop, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_kw: None)
    solve = Mock(return_value=False)
    failed = Mock(return_value=None)
    monkeypatch.setattr(loop, "run_solver_local_with_deadline", solve)
    monkeypatch.setattr(loop, "record_failed_attempt", failed)

    poll()

    solve.assert_not_called()
    failed.assert_not_called()
    assert reads == []
    assert {
        "kind": "local_solver_execution_blocked",
        "reason": "operator_paused",
    } in events


@pytest.mark.parametrize(
    "pause", [{"pause_reason": "operator"}, {"operator_paused": True}]
)
def test_global_pause_cannot_be_erased_by_a_scoped_failure_projection(
    monkeypatch, pause
):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    started = owned()
    latest = owned(scopes={"detail": owned()}, **pause)
    before = deepcopy(latest)
    assert failure_mutation_block_reason(started, latest, TARGET, CDP, "pc2") == (
        "operator_paused"
    )
    assert latest == before


@pytest.mark.parametrize(
    "pause", [{"pause_reason": "operator"}, {"operator_paused": True}]
)
def test_pause_after_failure_keeps_budget_without_rotating_or_escalating(
    run_failed_loop, pause
):
    latest = failure_tests.active()
    latest.update(pause)
    result = run_failed_loop(latest)
    result.rotate.assert_not_called()
    result.browse.assert_not_called()
    result.report.assert_not_called()
    assert result.state["slider_attempts"] == result.state["consecutive_failures"] == 1
    assert result.state["manual_pushed"] is False
    assert result.state["slider_next_attempt_at"] > 1000
    assert len(result.reads) == 3


def test_extracted_manual_handoff_keeps_report_then_blocked_event_order():
    events = []
    status = owned(manual_only=True, manual_required=False)
    report = Mock(
        return_value={
            "ok": True,
            "status": "manual_required",
            "captcha_solver": {"challenge_id": "new"},
            "unused": "private-fixture",
        }
    )
    report_execution_block("manual_only", status, report, events.append)
    report.assert_called_once_with()
    assert events == [
        {
            "kind": "manual_challenge_reported",
            "status": "manual_required",
            "ok": True,
            "error": None,
            "challenge_id": "new",
        },
        {"kind": "local_solver_execution_blocked", "reason": "manual_only"},
    ]


@pytest.mark.parametrize("reason", ["operator_paused", "nas_solver_running"])
def test_nonmanual_execution_block_does_not_create_a_manual_report(reason):
    events, report = [], Mock()
    report_execution_block(reason, owned(), report, events.append)
    report.assert_not_called()
    assert events == [{"kind": "local_solver_execution_blocked", "reason": reason}]
