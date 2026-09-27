"""Receipt publication and replay remain independent of facade import globals."""

from types import SimpleNamespace

import pytest

from src.auth_cleanup_journal import AuthCleanupIntent
from src.auth_completion_receipts import AuthCompletionReceipts
from src.collection_control_state import new_scope_state
from src.runtime_state import RuntimeState
from src.solver_recovery_state import SolverRecoveryState


def test_receipt_exports_share_native_context_identity():
    from src import server

    for name in AuthCompletionReceipts.__all__:
        method = getattr(server, name)
        assert isinstance(method.__self__, AuthCompletionReceipts)
        assert getattr(server._CONTEXT, name) is method


def test_saved_receipts_follow_path_recovery_and_clock_replacements(
    tmp_path, monkeypatch
):
    from src import server

    remember = server._remember_auth_completion_confirmation
    confirmed = server._auth_completion_was_confirmed
    read = server._read_auth_completion_confirmations
    runtime = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_solver_scope_state_root_path", lambda: tmp_path)
    old_states = []
    for name, epoch in (("first", 10.0), ("second", 20.0)):
        state = SolverRecoveryState()
        monkeypatch.setattr(
            server, "_auth_completion_recovery_state", lambda value=state: value
        )
        monkeypatch.setattr(
            server,
            "_auth_completion_confirmation_path",
            lambda value=name: tmp_path / f"{value}.json",
        )
        monkeypatch.setattr(
            server, "time", SimpleNamespace(time=lambda value=epoch: value)
        )
        assert remember(name) is None
        assert confirmed(name) is True
        assert read() == {name: epoch}
        old_states.append(state.confirmation_snapshot())
    assert confirmed("first") is False
    assert old_states == [{"first": 10.0}, {"second": 20.0}]
    assert runtime.recovery.confirmation_snapshot() == {}


@pytest.mark.parametrize("scope", ["seed", "detail", None])
def test_pending_intent_blocks_cached_and_durable_confirmation(
    tmp_path, monkeypatch, scope
):
    from src import server

    runtime = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_solver_scope_state_root_path", lambda: tmp_path)
    monkeypatch.setattr(
        server,
        "_auth_completion_confirmation_path",
        lambda: tmp_path / "confirmations.json",
    )
    confirmed = server._auth_completion_was_confirmed
    assert server._remember_auth_completion_confirmation("receipt") is None
    assert confirmed("receipt") is True
    state = new_scope_state()
    state["challenge_id"] = "pending-challenge"
    intent = AuthCleanupIntent(tmp_path, scope, state, "receipt")
    assert intent.prepare() is None
    assert confirmed("receipt") is False
    assert "receipt" in runtime.recovery.confirmation_snapshot()
    assert intent.finish() is None
    assert confirmed("receipt") is True
