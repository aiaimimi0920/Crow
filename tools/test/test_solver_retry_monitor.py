"""Retry ownership preserves live dependencies and pause safety."""

import pytest

from src.runtime_state import RuntimeState
from src.solver_retry_monitor import SolverRetryMonitor


@pytest.fixture
def retry_host(monkeypatch):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setattr(server, "_manual_solver_retry_enabled", lambda: True)
    monkeypatch.setattr(server, "_solver_submission_pending", lambda: False)
    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda **_: {"manual_required": True}
    )
    monkeypatch.setattr(
        server,
        "_manual_solver_retry_request",
        lambda: {"target_url": "https://example.invalid/item", "scope": "seed"},
    )
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda _: "seed")
    monkeypatch.setattr(server, "_solver_request_delegated_to_node", lambda _: False)
    monkeypatch.setattr(server, "_manual_solver_retry_next_epoch", lambda _: None)
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda _: True)
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda **_: None)
    monkeypatch.setattr(
        server, "_solver_scope_runtime_status", lambda _: {"paused": False}
    )
    return server


def test_retained_retry_entrypoint_uses_current_runtime_and_operator_pause(
    retry_host, monkeypatch
):
    trigger = retry_host._trigger_manual_solver_retry_if_due
    owner = trigger.__self__
    assert isinstance(owner, SolverRetryMonitor)
    for name in owner.__all__:
        assert getattr(retry_host, name).__self__ is owner
        assert getattr(retry_host._CONTEXT, name) is getattr(retry_host, name)
    replacement = RuntimeState()
    replacement.control.set_pause(True, "operator")
    monkeypatch.setattr(retry_host, "RUNTIME", replacement)
    assert trigger(now=100) == {"queued": False, "reason": "operator_paused"}
    assert replacement.control.snapshot().paused is True


def test_probe_state_change_prevents_retry_submission(retry_host, monkeypatch):
    def probe(_endpoint):
        retry_host.RUNTIME.control.set_pause(True, "operator")
        return True

    monkeypatch.setattr(retry_host, "_probe_solver_cdp_endpoint", probe)
    assert retry_host._trigger_manual_solver_retry_if_due(now=100) == {
        "queued": False,
        "reason": "state_changed",
    }
    assert retry_host.RUNTIME.recovery.snapshot().retry_attempts == 0


@pytest.mark.parametrize("outcome", ["error", "active", "custom_false"])
def test_failed_submission_restores_pause_but_custom_false_keeps_contract(
    retry_host, monkeypatch, outcome
):
    marked = []
    monkeypatch.setattr(
        retry_host,
        "_mark_solver_manual_required",
        lambda **kwargs: marked.append(kwargs["scope"]),
    )

    def submit(_request):
        if outcome == "error":
            raise OSError("synthetic submit failure")
        return False

    monkeypatch.setattr(retry_host, "_submit_solver_request", submit)
    result = retry_host._trigger_manual_solver_retry_if_due(
        now=100, submit_solver=submit if outcome == "custom_false" else None
    )
    assert (
        result["reason"]
        == {
            "error": "submit_failed",
            "active": "solver_active",
            "custom_false": "manual_required_retry_due",
        }[outcome]
    )
    assert result["queued"] is (outcome == "custom_false")
    assert marked == ([] if outcome == "custom_false" else ["seed"])
    assert retry_host.RUNTIME.recovery.snapshot().retry_attempts == 1
    assert retry_host.RUNTIME.retry_lock.acquire(blocking=False)
    retry_host.RUNTIME.retry_lock.release()


def test_retry_lock_is_released_when_live_runner_raises(retry_host, monkeypatch):
    trigger = retry_host._trigger_manual_solver_retry_if_due

    def fail(**_kwargs):
        raise OSError("synthetic runner failure")

    monkeypatch.setattr(retry_host, "_run_manual_solver_retry_if_due", fail)
    with pytest.raises(OSError, match="synthetic runner failure"):
        trigger(now=100)
    assert retry_host.RUNTIME.retry_lock.acquire(blocking=False)
    retry_host.RUNTIME.retry_lock.release()
