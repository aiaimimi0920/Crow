import types

from tools import pc2_solver_auth_pending, pc2_solver_fallback, pc2_solver_state_store
from tools.test.pc2_local_solver_test_context import *
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def test_resume_after_cooldown_clears_state_only_after_nas_confirmation(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    pending = pc2_local_solver._mark_collection_resume_pending(state, now=1000.0)
    request_id = pending["collection_resume_request_id"]
    monkeypatch.setattr(
        pc2_solver_fallback,
        "notify_collection_resume_after_cooldown",
        lambda *_args, **_kwargs: {
            **_confirmed_resume_payload(request_id),
            "request_attempts": 1,
        },
    )

    result = pc2_local_solver._retry_pending_collection_resume(
        "http://nas/api",
        state=pending,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["confirmed"] is True
    assert result["pending"] is False
    assert persisted["collection_resume_pending"] is False
    assert persisted["collection_resume_request_id"] is None
    assert persisted["slider_attempts"] == 0
    assert persisted["solver_cooldown_until"] is None


def test_implementation_functions_keep_declared_runtime_owner() -> None:
    originals = {}
    for module_name in pc2_local_solver._IMPLEMENTATION_MODULES:
        module = __import__(module_name, fromlist=["*"])
        for name in module.__all__:
            value = getattr(module, name)
            if (
                isinstance(value, types.FunctionType)
                and value.__module__ == module.__name__
            ):
                originals[name] = value

    assert originals
    for name, original in originals.items():
        rebound = getattr(pc2_local_solver, name)
        assert rebound is original
        assert rebound.__globals__ is original.__globals__


def test_stale_auth_completion_is_abandoned_for_new_challenge(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-a",
            "slider_attempts": 4,
            "auth_complete_pending": True,
            "auth_completion_id": "completion-a",
            "auth_complete_next_retry_at": 1000.0,
        }
    )
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(
        pc2_solver_auth_pending,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {
            "ok": False,
            "stale_challenge": True,
            "challenge_id": "challenge-b",
            "request_attempts": 1,
        },
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api",
        state=state,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["superseded"] is True
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["slider_attempts"] == 0
    assert persisted["challenge_id"] is None


def test_local_loop_does_not_run_solver_during_persisted_cooldown(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1100.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {"paused": True, "manual_required": True, "running": False},
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("solver must not run during cooldown")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_local_loop_resumes_collection_after_cooldown_without_running_solver(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    resume_ids: list[str] = []
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {"paused": True, "manual_required": True, "running": False},
    )

    def fake_resume(_api, request_id, challenge_id=None):
        resume_ids.append(request_id)
        return {**_confirmed_resume_payload(request_id), "request_attempts": 1}

    monkeypatch.setattr(
        pc2_solver_fallback, "notify_collection_resume_after_cooldown", fake_resume
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cooldown expiry must not run solver")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(resume_ids) == 1
    assert persisted["collection_resume_pending"] is False
    assert persisted["slider_attempts"] == 0
