"""Maintenance uses the same bounded, single-send navigation confirmation path."""

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution
from tools.test.pc2_maintenance_budget_fixtures import (
    OPERATIONS,
    TARGETS,
    maintenance_probe,
)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("scope", TARGETS)
@pytest.mark.parametrize("delay", [7.0, 12.0, 14.9])
def test_maintenance_accepts_late_ack_without_another_create_or_navigation(
    monkeypatch, operation, scope, delay
):
    probe = maintenance_probe(monkeypatch, delay=delay)
    result = getattr(execution, operation)("http://127.0.0.1:9223", TARGETS[scope])
    assert result["opened"] is True
    assert result["probe_target"]["_target_id"] == "fresh"
    assert probe.now[0] == pytest.approx(100 + delay)
    assert probe.put.call_count == 1
    assert len(probe.socket.messages) == 1
    assert probe.socket.messages[0]["method"] == "Page.navigate"
    assert probe.create_budgets == [probe.budget]
    assert all(0 < wait <= 5 for wait in probe.socket.waits)
    assert probe.socket.closed
    probe.close_target.assert_not_called()
    opener = probe.owners[-1]
    assert opener._solve_budget is None and not opener.lock.locked()
    assert opener._opened_target_ids == {"fresh"}


@pytest.mark.parametrize("operation", OPERATIONS)
def test_create_time_consumes_the_same_maintenance_deadline(monkeypatch, operation):
    probe = maintenance_probe(monkeypatch, delay=10, remaining=8, create_delay=3)
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    assert probe.now[0] == 108
    assert probe.put.call_count == len(probe.socket.messages) == 1
    assert probe.owners[-1].last_failure_reason == "deadline_exceeded"
    assert probe.owners[-1]._opened_target_ids == {"fresh"}
    assert probe.socket.closed
    probe.close_target.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_navigation_still_defers_after_fifteen_seconds_without_replay(
    monkeypatch, operation
):
    probe = maintenance_probe(monkeypatch, delay=20)
    result = getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    assert result["opened"] is False
    assert result["reason"] == "target_navigation_unconfirmed"
    assert result["probe_target"]["_target_id"] == "fresh"
    assert result["probe_target"]["_navigation_unconfirmed"] is True
    assert probe.now[0] == 115
    assert probe.put.call_count == len(probe.socket.messages) == 1
    assert probe.socket.closed
    assert probe.owners[-1]._opened_target_ids == {"fresh"}
    probe.close_target.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_cancellation_during_ack_wait_retains_page_and_stops(monkeypatch, operation):
    probe = maintenance_probe(monkeypatch, delay=20)
    probe.socket.on_wait = lambda _at: probe.budget.event.set()
    with pytest.raises(SolveStopped, match="cancelled"):
        getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    assert probe.now[0] == 105
    assert probe.put.call_count == len(probe.socket.messages) == 1
    assert probe.owners[-1].last_failure_reason == "cancelled"
    assert probe.owners[-1]._opened_target_ids == {"fresh"}
    assert probe.socket.closed
    probe.close_target.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_expired_maintenance_budget_starts_no_create(monkeypatch, operation):
    probe = maintenance_probe(monkeypatch, remaining=0)
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    probe.put.assert_not_called()
    assert probe.socket.messages == []
    probe.close_target.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("outcome", ["opened", "none"])
@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_maintenance_checks_stop_after_open_returns(
    monkeypatch, operation, outcome, stop
):
    probe = maintenance_probe(monkeypatch)

    def open_target(solver):
        solver.ws = probe.socket
        solver._opened_target_ids.add("fresh")
        if stop == "cancelled":
            probe.budget.event.set()
        else:
            probe.now[0] = probe.budget.deadline
        return (
            {"id": "fresh", "url": solver.target_url} if outcome == "opened" else None
        )

    monkeypatch.setattr(CaptchaSolver, "_open_target_tab", open_target)
    with pytest.raises(SolveStopped, match=stop):
        getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    opener = probe.owners[-1]
    assert opener.last_failure_reason == stop
    assert opener._solve_budget is None and not opener.lock.locked()
    assert opener._opened_target_ids == {"fresh"}
    assert probe.socket.closed
    probe.close_target.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_maintenance_uses_existing_runtime_limit_configuration(monkeypatch, operation):
    monkeypatch.setenv("CROW_SOLVER_MAX_RUNTIME_SECONDS", "9.5")
    monkeypatch.delenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", raising=False)
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: [])
    observed = []

    def open_target(solver):
        observed.append(solver._solve_budget.remaining())
        return {"id": "fresh", "url": solver.target_url}

    monkeypatch.setattr(CaptchaSolver, "_open_target_tab", open_target)
    result = getattr(execution, operation)("http://127.0.0.1:9223", TARGETS["detail"])
    assert result["opened"] is True
    assert len(observed) == 1 and 8.5 < observed[0] <= 9.5
