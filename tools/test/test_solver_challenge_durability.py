"""Challenge publication failures retain confirmed state and recovery snapshots."""

import json
from types import SimpleNamespace

import pytest

from src import archive_json_io
from src.runtime_state import RuntimeState
from src.solver_scope_runtime import SolverScopeRuntime


@pytest.fixture(
    params=["legacy", "native-legacy", "scoped", "completion", "native-completion"]
)
def challenge_writer(request, monkeypatch, tmp_path):
    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    runtime = RuntimeState()
    path = tmp_path / "legacy.json"
    scopes = SolverScopeRuntime(runtime, tmp_path, lambda: path, 900.0)
    snapshot_ids = lambda payload: [payload["challenge_id"]]
    if request.param == "legacy":
        from src import server

        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: path)
        persist = lambda value: server._persist_solver_challenge_state(
            value, {"evidence": "confirmed"}
        )
        cache = lambda: runtime.recovery.snapshot().challenge_id
    elif request.param == "native-legacy":
        from src.solver_challenge_receipts import persist_legacy_challenge

        persist = lambda value: persist_legacy_challenge(
            value,
            {"evidence": "confirmed"},
            path=path,
            read_legacy=lambda: (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            ),
            clock=lambda: 42.0,
        )
        cache = lambda: runtime.recovery.snapshot().challenge_id
    elif request.param in {"completion", "native-completion"}:
        from src import server

        path = tmp_path / "confirmations.json"
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(server, "_auth_completion_confirmation_path", lambda: path)
        persist = server._remember_auth_completion_confirmation
        if request.param == "native-completion":
            from src.auth_completion_store import remember_confirmation

            persist = lambda value: remember_confirmation(
                value, path=path, state=runtime.recovery, clock=lambda: 42.0
            )
        cache = runtime.recovery.confirmation_snapshot
        snapshot_ids = lambda payload: list(payload["confirmations"])
    else:
        path = scopes.state_path("seed")
        persist = lambda value: scopes.persist(
            "seed",
            {
                "challenge_id": value,
                "first_seen_epoch": 10.0,
                "paused": True,
                "last_request": {"evidence": "confirmed"},
            },
        )
        cache = lambda: runtime.control.scope_snapshot("seed")["challenge_id"]
    return SimpleNamespace(
        path=path, persist=persist, cache=cache, snapshot_ids=snapshot_ids
    )


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_failed_challenge_write_retains_snapshots_and_recovers(
    challenge_writer, monkeypatch, failure
):
    writer = challenge_writer
    assert writer.persist("original") is None
    original = writer.path.read_bytes()
    cached = writer.cache()
    pending_pattern = "." + writer.path.name + ".pending-*.tmp"
    retained = {}

    def fail(*_args):
        raise OSError("challenge publication failed")

    with monkeypatch.context() as fault:
        fault.setattr(archive_json_io.os, failure, fail)
        for value in ("attempt-one", "attempt-two"):
            error = writer.persist(value)
            assert error is not None and "challenge publication failed" in error
            assert writer.path.read_bytes() == original
            assert writer.cache() == cached
            snapshots = list(writer.path.parent.glob(pending_pattern))
            assert len(snapshots) == len(retained) + 1
            for path, payload in retained.items():
                assert path.read_bytes() == payload
            retained = {path: path.read_bytes() for path in snapshots}
            assert value in {
                item
                for payload in retained.values()
                for item in writer.snapshot_ids(json.loads(payload))
            }

    assert writer.persist("recovered") is None
    recovered = json.loads(writer.path.read_text(encoding="utf-8"))
    assert "recovered" in writer.snapshot_ids(recovered)
    if "confirmations" in recovered:
        assert writer.cache() == recovered["confirmations"]
    else:
        assert recovered["challenge_id"] == "recovered"
    assert not writer.path.read_bytes().startswith(bytes([239, 187, 191]))
    assert {
        path: path.read_bytes() for path in writer.path.parent.glob(pending_pattern)
    } == retained


def test_legacy_refresh_keeps_challenge_creation_time(monkeypatch, tmp_path):
    from src import server

    path = tmp_path / "legacy.json"
    monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: path)
    assert (
        server._persist_solver_challenge_state("original", {"evidence": "first"})
        is None
    )
    first = json.loads(path.read_text(encoding="utf-8"))
    assert (
        server._persist_solver_challenge_state("original", {"evidence": "second"})
        is None
    )
    refreshed = json.loads(path.read_text(encoding="utf-8"))
    assert refreshed["created_at_epoch"] == first["created_at_epoch"]
    assert refreshed["last_request"] == {"evidence": "second"}


@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        "[]",
        '{"confirmations": []}',
        '{"confirmations": {"kept": "invalid"}}',
        '{"confirmations": {"kept": NaN}}',
        '{"confirmations": {"kept": Infinity}}',
        '{"confirmations": {"kept": true}}',
        '{"confirmations": {"kept": -1}}',
        '{"confirmations": {"": 42}}',
        '{"confirmations": {"same": 42, " same ": 43}}',
    ],
)
def test_completion_write_preserves_unreadable_receipt(monkeypatch, tmp_path, content):
    from src import server

    path = tmp_path / "confirmations.json"
    path.write_text(content, encoding="utf-8")
    runtime = RuntimeState()
    runtime.recovery.record_confirmation("cached", 42.0)
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_auth_completion_confirmation_path", lambda: path)
    before = path.read_bytes()
    cached = runtime.recovery.confirmation_snapshot()

    error = server._remember_auth_completion_confirmation("new")

    assert error is not None
    with pytest.raises(ValueError):
        server._auth_completion_was_confirmed("cached")
    assert path.read_bytes() == before
    assert runtime.recovery.confirmation_snapshot() == cached
    assert list(tmp_path.glob("*.tmp")) == []
