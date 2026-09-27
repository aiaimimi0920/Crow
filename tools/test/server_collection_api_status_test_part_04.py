from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_repeated_old_completion_id_does_not_clear_a_new_manual_required_state(monkeypatch, tmp_path) -> None:
    from src import server

    completion_id = "pc2-old-completion"
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, current_id, **_kwargs: {
            "status": "completed",
            "completion_id": current_id,
            "refreshed": True,
            "retry_queued": False,
        },
    )
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("first challenge", encoding="utf-8")

    first = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )
    assert first["auth_state_confirmed"] is True

    server.RUNTIME.recovery.replace_confirmations({})
    server.RUNTIME.control.paused = True
    server.RUNTIME.control.reason = "manual_required"
    server.RUNTIME.solver.last_status = "manual_required"
    server.RUNTIME.solver.failure_reason = "manual_required"
    flag_path.write_text("new challenge", encoding="utf-8")

    stale = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )

    assert stale["ok"] is False
    assert stale["auth_state_confirmed"] is False
    assert "stale" in stale["error"]
    assert flag_path.exists()
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.solver.last_status == "manual_required"

def test_collection_observer_auth_complete_rejects_unconfirmed_cleanup(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda: "file is busy")
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, completion_id, **_kwargs: {
            "status": "completed",
            "completion_id": completion_id,
            "refreshed": True,
            "retry_queued": False,
        },
    )
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": "pc2-unconfirmed"}
    )

    assert payload["ok"] is False
    assert payload["auth_state_confirmed"] is False
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True
    assert "file is busy" in payload["error"]

def test_pc2_auth_complete_requires_completion_id(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-current")

    payload = server._collection_observer_auth_complete_payload(
        {
            "source": "pc2_local_solver",
            "challenge_id": "challenge-current",
        }
    )

    assert payload["ok"] is False
    assert payload["auth_state_confirmed"] is False
    assert payload["paused"] is True
    assert "completion_id is required" in payload["error"]

def test_resume_after_cooldown_only_clears_collection_auth_pause(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )
    remembered_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        server,
        "_remember_solver_auth_completion",
        lambda request: remembered_requests.append(dict(request)),
    )
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_resume_after_cooldown_payload(
        {"source": "pc2_local_solver", "resume_request_id": "pc2-resume-1"}
    )

    assert payload["ok"] is True
    assert payload["action"] == "resume_after_cooldown"
    assert payload["resume_request_id"] == "pc2-resume-1"
    assert payload["auth_state_confirmed"] is True
    assert payload["manual_auth_completed"] is False
    assert payload["paused"] is False
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is False
    assert payload["cookie_snapshot"]["status"] == "skipped"
    assert server.RUNTIME.solver.last_status == "resumed_after_cooldown"
    assert not (tmp_path / "force_unlock.flag").exists()
    assert remembered_requests == [server.RUNTIME.recovery.last_request]

def test_resume_after_cooldown_preserves_reporting_node_for_challenge_grace(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    remembered_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        server,
        "_remember_solver_auth_completion",
        lambda request: remembered_requests.append(dict(request)),
    )
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_resume_after_cooldown_payload(
        {
            "source": "pc2_local_solver",
            "resume_request_id": "pc2-resume-node-source",
            "scope": "detail",
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
        }
    )

    assert payload["ok"] is True
    assert remembered_requests == [
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "scope": "detail",
        }
    ]

def test_resume_after_cooldown_is_idempotent_for_same_request_id(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")
    request = {"source": "pc2_local_solver", "resume_request_id": "pc2-resume-repeat"}

    first = server._collection_observer_resume_after_cooldown_payload(request)
    server.RUNTIME.recovery.replace_confirmations({})
    second = server._collection_observer_resume_after_cooldown_payload(request)

    assert first["ok"] is True
    assert first["idempotent"] is False
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert second["manual_auth_completed"] is False

@pytest.mark.parametrize("action", ["auth_complete", "resume_after_cooldown"])
def test_old_pc2_request_cannot_clear_new_challenge(monkeypatch, tmp_path, action) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-b")
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("new challenge", encoding="utf-8")

    if action == "auth_complete":
        payload = server._collection_observer_auth_complete_payload(
            {
                "source": "pc2_local_solver",
                "completion_id": "old-completion",
                "challenge_id": "challenge-a",
            }
        )
    else:
        payload = server._collection_observer_resume_after_cooldown_payload(
            {
                "source": "pc2_local_solver",
                "resume_request_id": "old-resume",
                "challenge_id": "challenge-a",
            }
        )

    assert payload["ok"] is False
    assert payload["stale_challenge"] is True
    assert payload["challenge_id"] == "challenge-b"
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.solver.last_status == "manual_required"
    assert server.RUNTIME.solver.failure_reason == "manual_required"
    assert flag_path.exists()

def test_solver_challenge_id_survives_api_process_restart(monkeypatch, tmp_path) -> None:
    from src import server

    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", dict(request))
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)

    challenge_id = server._begin_solver_challenge()
    state_path = tmp_path / "solver-challenge-state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert persisted["challenge_id"] == challenge_id
    assert persisted["last_request"] == request

    server.RUNTIME.recovery.challenge_id = None
    server.RUNTIME.recovery.last_request = dict(request)
    server.RUNTIME.control.paused = False
    server.RUNTIME.control.reason = None

    assert server._begin_solver_challenge() == challenge_id
    assert server._restore_solver_challenge_state() is True
    assert server.RUNTIME.recovery.challenge_id == challenge_id
    assert server.RUNTIME.recovery.last_request == request
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.control.reason == "captcha_solver"

def test_different_solver_request_starts_new_persisted_challenge(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)
    monkeypatch.setattr(server.time, "time_ns", lambda: 1001)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/first.htm",
        },
    )
    first_id = server._begin_solver_challenge()

    server.RUNTIME.recovery.challenge_id = None
    server.RUNTIME.control.paused = False
    server.RUNTIME.control.reason = None
    server.RUNTIME.recovery.last_request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    monkeypatch.setattr(server.time, "time_ns", lambda: 1002)

    second_id = server._begin_solver_challenge()

    assert first_id == "captcha-1001"
    assert second_id == "captcha-1002"
    persisted = json.loads((tmp_path / "solver-challenge-state.json").read_text(encoding="utf-8"))
    assert persisted["challenge_id"] == second_id

def test_paused_challenge_changes_only_when_node_owner_changes(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)
    monkeypatch.setattr(server.time, "time_ns", lambda: 2001)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/first.htm",
        },
    )
    first_id = server._begin_solver_challenge()
    server.RUNTIME.control.paused = True
    server.RUNTIME.control.reason = "captcha_solver"

    server.RUNTIME.recovery.last_request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    assert server._begin_solver_challenge() == first_id

    server.RUNTIME.recovery.last_request = {
        "node_id": "pc3",
        "cdp_endpoint": "http://192.168.15.105:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    monkeypatch.setattr(server.time, "time_ns", lambda: 2002)

    assert server._begin_solver_challenge() == "captcha-2002"

def test_challenge_cleanup_failure_keeps_runtime_paused(monkeypatch, tmp_path) -> None:
    from src import server

    class UnremovableChallengeState:
        def unlink(self, *, missing_ok: bool = False) -> None:
            raise OSError("challenge state is busy")

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-current")
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: UnremovableChallengeState())

    error = server._clear_solver_manual_required_pause()

    assert "challenge state is busy" in str(error)
    assert server.RUNTIME.recovery.challenge_id == "challenge-current"
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.control.reason == "captcha_solver"
    assert server.RUNTIME.solver.last_status == "manual_required"

def test_resume_after_cooldown_clears_persisted_challenge_state(monkeypatch, tmp_path) -> None:
    from src import server

    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", dict(request))
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)
    challenge_id = server._begin_solver_challenge()
    server.RUNTIME.control.paused = True
    server.RUNTIME.control.reason = "captcha_solver"

    payload = server._collection_observer_resume_after_cooldown_payload(
        {
            "source": "pc2_local_solver",
            "resume_request_id": "pc2-resume-persisted-challenge",
            "challenge_id": challenge_id,
        }
    )

    assert payload["ok"] is True
    assert payload["auth_state_confirmed"] is True
    assert server.RUNTIME.recovery.challenge_id is None
    assert not (tmp_path / "solver-challenge-state.json").exists()
