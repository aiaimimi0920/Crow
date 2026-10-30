"""Explicit scoped compatibility mirrors never grant global pause authority."""

import json
from pathlib import Path

import pytest

from src.runtime_state import RuntimeState
from src.solver_scope_runtime import SolverScopeRuntime


@pytest.fixture
def manual(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    server._begin_solver_challenge(
        {
            "scope": "seed",
            "node_id": "pc2",
            "cdp_endpoint": "http://pc2.example:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        }
    )
    assert server._mark_solver_manual_required(scope="seed", manual_only=True) is None
    return server, SolverScopeRuntime(
        server.RUNTIME, tmp_path, lambda: tmp_path / "legacy.json", 900
    )


def test_new_mirror_is_scoped_but_raw_legacy_presence_is_preserved(manual):
    server, scopes = manual
    assert scopes.manual_flag_exists() is True
    assert scopes.global_manual_pause_active() is False
    assert (
        server._captcha_solver_runtime_status()["global_manual_pause_active"] is False
    )
    assert server._collection_effectively_paused() is True
    assert server._collection_scope_effectively_paused("seed") is True
    assert server._collection_scope_effectively_paused("detail") is False
    assert scopes.scope_effectively_paused("detail") is False


@pytest.mark.parametrize(
    "raw", ["manual", "[]", "{}", "{", '{"scope":null,"manual_required":true}']
)
def test_legacy_unknown_or_malformed_flag_stays_global(manual, raw):
    server, scopes = manual
    path = Path(scopes.manual_flag_path())
    path.write_text(raw, encoding="utf-8")
    assert scopes.global_manual_pause_active() is True
    assert server._collection_scope_effectively_paused("detail") is True
    assert server._mark_solver_manual_required(scope="seed", manual_only=True) is None
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize(
    "filename", ["force_unlock-seed.flag", "solver-challenge-state-seed.json"]
)
@pytest.mark.parametrize(
    "key,value",
    [
        ("challenge_id", "newer"),
        ("manual_required", False),
        ("manual_only", False),
        ("last_request", {}),
        ("scope", "detail"),
    ],
)
def test_mirror_requires_matching_durable_scope_and_counterpart(
    manual, filename, key, value
):
    _server, scopes = manual
    path = scopes.data_dir / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[key] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert scopes.global_manual_pause_active() is True


@pytest.mark.parametrize(
    "filename", ["force_unlock-seed.flag", "solver-challenge-state-seed.json"]
)
def test_missing_or_unreadable_counterpart_fails_closed(manual, filename):
    _server, scopes = manual
    path = scopes.data_dir / filename
    path.write_text("{", encoding="utf-8")
    assert scopes.global_manual_pause_active() is True
    path.unlink()
    assert scopes.global_manual_pause_active() is True


def test_true_global_manual_transition_is_not_a_mirror(manual):
    server, scopes = manual
    assert server._mark_solver_manual_required(manual_only=True) is None
    assert scopes.global_manual_pause_active() is True
    assert server._collection_scope_effectively_paused("detail") is True


def test_detail_cleanup_keeps_the_seed_mirror_and_manual_state(manual):
    server, scopes = manual
    legacy = Path(scopes.manual_flag_path())
    before = legacy.read_bytes()
    server._begin_solver_challenge(
        {
            "scope": "detail",
            "node_id": "pc2",
            "cdp_endpoint": "http://pc2.example:9224",
            "target_url": "https://sf-item.taobao.com/sf_item/123.htm",
        }
    )
    assert server._clear_solver_manual_required_pause(scope="detail") is None
    assert legacy.read_bytes() == before
    assert scopes.status("seed")["manual_only"] is True
    assert scopes.status("detail")["paused"] is False
    assert scopes.global_manual_pause_active() is False


def test_operator_pause_still_applies_with_a_proven_scoped_mirror(manual):
    server, scopes = manual
    server.RUNTIME.control.set_pause(True, "operator")
    assert scopes.global_manual_pause_active() is False
    assert server._collection_scope_effectively_paused("detail") is True


def test_reloaded_runtime_can_validate_mirror_without_rewriting_history(manual):
    _server, scopes = manual
    paths = list(scopes.data_dir.glob("*"))
    before = {path.name: path.read_bytes() for path in paths}
    reloaded = SolverScopeRuntime(
        RuntimeState(), scopes.data_dir, scopes.legacy_state_path, 900
    )
    assert reloaded.global_manual_pause_active() is False
    assert reloaded.scope_effectively_paused("seed") is True
    assert reloaded.scope_effectively_paused("detail") is False
    assert {path.name: path.read_bytes() for path in paths} == before


def test_manual_publication_does_not_take_another_scope_recovery_request(manual):
    server, scopes = manual
    server.RUNTIME.recovery.set_request({"scope": "detail", "node_id": "other"})
    assert server._mark_solver_manual_required(scope="seed", manual_only=True) is None
    assert scopes.global_manual_pause_active() is False
    payload = json.loads(Path(scopes.manual_flag_path()).read_text(encoding="utf-8"))
    assert payload["last_request"] == scopes.read("seed")["last_request"]


@pytest.mark.parametrize(
    "key,value",
    [("publication_id", "other"), ("manual_only", 1), ("flag_kind", "global")],
)
def test_counterpart_needs_exact_typed_publication_identity(manual, key, value):
    _server, scopes = manual
    path = Path(scopes.manual_flag_path("seed"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[key] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert scopes.global_manual_pause_active() is True


def test_replaced_global_during_validation_cannot_produce_a_false_proof(
    manual, monkeypatch
):
    _server, scopes = manual
    legacy = Path(scopes.manual_flag_path())
    read_bytes = Path.read_bytes
    calls = []

    def replace_after_read(path):
        raw = read_bytes(path)
        if path == legacy:
            calls.append(None)
            if len(calls) == 1:
                path.write_text("operator", encoding="utf-8")
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    assert scopes.global_manual_pause_active() is True
    assert len(calls) == 2


def test_publication_holds_runtime_lock_until_both_flags_are_written(
    manual, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from src import solver_manual_pause
    from tools.test.test_solver_scope_runtime import observe_contention

    server, scopes = manual
    contended = observe_contention(server.RUNTIME, monkeypatch)
    entered, release, changed = threading.Event(), threading.Event(), threading.Event()
    publish = solver_manual_pause.write_json

    def held_publish(path, payload):
        if Path(path) == Path(scopes.manual_flag_path("seed")):
            entered.set()
            assert release.wait(5)
        return publish(path, payload)

    def change_recovery():
        with server.RUNTIME.lock:
            server.RUNTIME.recovery.set_request({"scope": "detail", "node_id": "other"})
            changed.set()

    monkeypatch.setattr(solver_manual_pause, "write_json", held_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            server._mark_solver_manual_required, scope="seed", manual_only=True
        )
        try:
            assert entered.wait(5)
            second = pool.submit(change_recovery)
            assert contended.wait(5)
            assert not changed.is_set()
        finally:
            release.set()
        assert first.result(timeout=5) is None
        second.result(timeout=5)
    assert scopes.global_manual_pause_active() is False


def test_production_application_uses_the_same_pause_policy(
    manual, monkeypatch, tmp_path
):
    from src.collection_application import create_application

    _server, scopes = manual
    monkeypatch.setenv("FAPAI_DB_ENABLED", "0")
    with_application = create_application(data_root=tmp_path)
    try:
        host = with_application.host
        assert host._solver_global_manual_pause_active() is False
        assert host._captcha_solver_runtime_status()["force_unlock_flag_exists"] is True
        assert (
            host._captcha_solver_runtime_status()["global_manual_pause_active"] is False
        )
        assert host._collection_scope_effectively_paused("seed") is True
        assert host._collection_scope_effectively_paused("detail") is False
        Path(scopes.manual_flag_path()).write_text("operator", encoding="utf-8")
        assert host._collection_scope_effectively_paused("detail") is True
    finally:
        with_application.close()
