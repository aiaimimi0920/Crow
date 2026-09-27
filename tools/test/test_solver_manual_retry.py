"""Manual retry respects scoped ownership and legacy flag compatibility."""

import json

import pytest

from src.runtime_state import RuntimeState
from src.solver_manual_retry import (
    manual_flag_is_manual_only,
    manual_flag_request,
    manual_flag_scope,
    manual_retry_enabled,
)


@pytest.mark.parametrize("backend", ["native", "facade"])
def test_flag_readers_observe_replacement_and_opaque_legacy_flags(
    monkeypatch, tmp_path, backend
):
    from src import server

    path = tmp_path / "manual.flag"
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(path))
    if backend == "native":
        get_scope = lambda: manual_flag_scope(
            lambda: str(path), server._normalize_challenge_scope
        )
        get_mode = lambda: manual_flag_is_manual_only(lambda: str(path))
        get_request = lambda: manual_flag_request(str(path))
    else:
        get_scope = server._solver_manual_flag_scope
        get_mode = server._solver_manual_flag_is_manual_only
        get_request = server._solver_manual_flag_request
    for scope, mode, expected in [("seed", " YES ", True), ("detail", False, False)]:
        request = {"node_id": scope}
        path.write_text(
            json.dumps({"scope": scope, "manual_only": mode, "last_request": request}),
            encoding="utf-8",
        )
        assert get_scope() == scope
        assert get_mode() is expected
        assert get_request() == request
    for content in ["manual lock", "[]", '{"manual_only": "off"}']:
        path.write_text(content, encoding="utf-8")
        assert get_scope() is None
        assert get_mode() is False
        assert get_request() == {}
    path.unlink()
    assert get_scope() is None
    assert get_mode() is False
    assert get_request() == {}


@pytest.mark.parametrize("backend", ["native", "facade"])
@pytest.mark.parametrize(
    "scope,inferred,state,flag_owner,global_mode,flag_mode,enabled,expected",
    [
        ("seed", None, {"manual_only": True}, "detail", False, False, True, False),
        ("seed", None, {}, "detail", True, True, False, True),
        ("seed", None, {"challenge_id": "active"}, None, True, True, True, True),
        ("seed", None, {"manual_required": True}, None, False, False, False, False),
        (None, "detail", {"challenge_id": "active"}, None, True, True, True, True),
        (None, None, {}, None, True, False, True, False),
        (None, None, {}, None, False, True, True, False),
        (None, None, {}, None, False, False, False, False),
        (None, None, {}, None, False, False, True, True),
    ],
)
def test_retry_eligibility_preserves_scope_and_global_precedence(
    monkeypatch,
    backend,
    scope,
    inferred,
    state,
    flag_owner,
    global_mode,
    flag_mode,
    enabled,
    expected,
):
    from src import server

    runtime = RuntimeState()
    runtime.recovery.require_manual(42, manual_only=global_mode)
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda _: inferred)
    monkeypatch.setattr(server, "_solver_scope_runtime_status", lambda _: state)
    monkeypatch.setattr(server, "_solver_manual_flag_scope", lambda: flag_owner)
    monkeypatch.setattr(server, "_solver_manual_flag_is_manual_only", lambda: flag_mode)
    monkeypatch.setattr(server, "_runtime_env_flag", lambda *_: enabled)
    if backend == "native":
        result = manual_retry_enabled(
            runtime=runtime,
            scope=scope,
            infer_scope=lambda _: inferred,
            scope_status=lambda _: state,
            flag_scope=lambda: flag_owner,
            flag_manual_only=lambda: flag_mode,
            configured_enabled=lambda: enabled,
        )
    else:
        result = server._manual_solver_retry_enabled(scope)
    assert result is expected
