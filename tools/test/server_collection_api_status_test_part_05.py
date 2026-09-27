from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_auth_cookie_snapshot_retry_records_failure_then_success(monkeypatch) -> None:
    from src import server

    results: list[object] = [
        RuntimeError("CDP reset"),
        {"refreshed": False, "reason": "cookie_snapshot_candidate_unhealthy"},
        {"refreshed": True, "cookie_count": 5},
    ]

    def fake_refresh(_payload):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(server.RUNTIME.cookie_snapshot, "state", {})
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 3)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(server, "_refresh_auth_cookie_snapshot", fake_refresh)

    server._run_auth_cookie_snapshot_retry({}, "pc2-cookie-retry")
    status = server._auth_cookie_snapshot_runtime_status()

    assert status["status"] == "completed"
    assert status["completion_id"] == "pc2-cookie-retry"
    assert status["attempts"] == 3
    assert status["refreshed"] is True
    assert status["result"]["cookie_count"] == 5

def test_auth_cookie_snapshot_retry_stops_after_bounded_attempts(monkeypatch) -> None:
    from src import server

    calls: list[int] = []
    monkeypatch.setattr(server.RUNTIME.cookie_snapshot, "state", {})
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 2)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: calls.append(1) or {"refreshed": False, "reason": "cdp_endpoint_unhealthy"},
    )

    server._run_auth_cookie_snapshot_retry({}, "pc2-cookie-failed")
    status = server._auth_cookie_snapshot_runtime_status()

    assert len(calls) == 2
    assert status["status"] == "failed"
    assert status["attempts"] == 2
    assert status["retry_queued"] is False

def test_auth_cookie_snapshot_success_finalizes_matching_paused_challenge(monkeypatch, tmp_path) -> None:
    from src import server

    completion_id = "pc2-two-phase-success"
    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf-item.taobao.com/sf_item/1.htm",
    }
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.cookie_snapshot, "state", {})
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "pending_token", None)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", dict(request))
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-two-phase")
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 1)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: {"refreshed": True, "cookie_count": 5},
    )
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    server._run_auth_cookie_snapshot_retry(
        {},
        completion_id,
        finalize_auth=True,
        expected_challenge_id="challenge-two-phase",
        completion_request=request,
    )
    status = server._auth_cookie_snapshot_runtime_status()

    assert status["status"] == "completed"
    assert status["auth_state_confirmed"] is True
    assert status["result"]["auth_finalization"]["auth_state_confirmed"] is True
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.recovery.challenge_id is None
    assert server.RUNTIME.solver.last_status == "manual_auth_completed"
    assert not (tmp_path / "force_unlock.flag").exists()
    assert server._auth_completion_was_confirmed(completion_id) is True

def test_auth_cookie_snapshot_failure_keeps_paused_challenge(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.cookie_snapshot, "state", {})
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-still-paused")
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 1)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: {"refreshed": False, "reason": "cookie_snapshot_candidate_unhealthy"},
    )
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    server._run_auth_cookie_snapshot_retry(
        {},
        "pc2-two-phase-failed",
        finalize_auth=True,
        expected_challenge_id="challenge-still-paused",
        completion_request={"node_id": "pc2"},
    )
    status = server._auth_cookie_snapshot_runtime_status()

    assert status["status"] == "failed"
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.recovery.challenge_id == "challenge-still-paused"
    assert (tmp_path / "force_unlock.flag").exists()

def test_cookie_snapshot_success_for_old_challenge_cannot_clear_new_pause(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.recovery, "confirmations", {})
    monkeypatch.setattr(server.RUNTIME.cookie_snapshot, "state", {})
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-new")
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 1)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: {"refreshed": True, "cookie_count": 5},
    )
    (tmp_path / "force_unlock.flag").write_text("new challenge", encoding="utf-8")

    server._run_auth_cookie_snapshot_retry(
        {},
        "pc2-two-phase-stale",
        finalize_auth=True,
        expected_challenge_id="challenge-old",
        completion_request={"node_id": "pc2"},
    )
    status = server._auth_cookie_snapshot_runtime_status()

    assert status["status"] == "completed"
    assert status["auth_state_confirmed"] is False
    assert status["result"]["auth_finalization"]["stale_challenge"] is True
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.recovery.challenge_id == "challenge-new"
    assert (tmp_path / "force_unlock.flag").exists()
    assert server._auth_completion_was_confirmed("pc2-two-phase-stale") is False

def test_refresh_auth_cookie_snapshot_writes_only_after_healthy_probe(monkeypatch, tmp_path) -> None:
    from src import server

    snapshot_path = tmp_path / "taobao-cookies.json"
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[tuple[list[dict[str, object]], str]] = []

    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://host.docker.internal:9223")
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda exported, sample_urls, **_kwargs: {"healthy": True, "healthy_samples": 1, "sample_count": len(sample_urls), "sample_results": []},
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda exported, path: writes.append((list(exported), str(path))))

    result = server._refresh_auth_cookie_snapshot({"sample_urls": ["https://sf.taobao.com/list/50025969__2.htm"]})

    assert result["refreshed"] is True
    assert result["cookie_count"] == 1
    assert result["health"]["healthy_samples"] == 1
    assert writes == [(cookies, str(snapshot_path))]

def test_auth_cookie_health_probe_uses_current_cdp_user_agent(monkeypatch) -> None:
    from src import server
    from src import auth_cookie_health

    observed: dict[str, object] = {}
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]

    monkeypatch.setattr(
        auth_cookie_health,
        "build_session_from_playwright_cookies",
        lambda _cookies: object(),
    )

    def fake_resolve_user_agent(endpoint: str) -> str:
        observed["endpoint"] = endpoint
        return "Current Edge UA"

    def fake_probe(_url: str, **kwargs: object) -> dict[str, object]:
        observed["user_agent"] = kwargs.get("user_agent")
        return {"final_url": _url, "status": 200, "has_script": True}

    monkeypatch.setattr(auth_cookie_health, "resolve_cdp_user_agent", fake_resolve_user_agent)
    monkeypatch.setattr(auth_cookie_health, "probe_seed_page", fake_probe)
    monkeypatch.setattr(
        auth_cookie_health,
        "classify_taobao_health",
        lambda *_args, **_kwargs: {"status": "healthy", "healthy": True},
    )

    result = server._probe_auth_cookie_snapshot_health(
        cookies,
        ["https://sf.taobao.com/list/50025969__2.htm"],
        cdp_endpoint="http://192.168.15.104:9223",
    )

    assert result["healthy"] is True
    assert observed == {
        "endpoint": "http://192.168.15.104:9223",
        "user_agent": "Current Edge UA",
    }

def test_refresh_auth_cookie_snapshot_derives_node_scoped_path_when_env_is_missing(monkeypatch, tmp_path) -> None:
    from src import server

    repo_root = tmp_path / "project" / "crow"
    repo_root.mkdir(parents=True)
    shared_root = repo_root / "FPFData"
    shared_root.mkdir()
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[tuple[list[dict[str, object]], str]] = []

    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://192.168.15.104:9224")
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT_ROOT", raising=False)
    monkeypatch.delenv("FAPAI_SHARED_DATA_ROOT_HOST", raising=False)
    monkeypatch.setattr(server, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {"cdp_endpoint": "http://192.168.15.104:9224", "node_id": "pc2"},
    )
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda exported, sample_urls, **_kwargs: {"healthy": True, "healthy_samples": 1, "sample_count": len(sample_urls), "sample_results": []},
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda exported, path: writes.append((list(exported), str(path))))

    result = server._refresh_auth_cookie_snapshot({})

    expected = shared_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json"
    assert result["refreshed"] is True
    assert result["path"] == str(expected)
    assert writes == [(cookies, str(expected))]

def test_cookie_snapshot_root_resolves_node_path_inside_shared_mount(monkeypatch, tmp_path) -> None:
    from src import server

    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_ROOT", str(shared_root))
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {"node_id": "pc2", "cdp_endpoint": "http://192.168.15.104:9224"},
    )

    assert server._resolve_auth_cookie_snapshot_path({}) == str(
        shared_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json"
    )

def test_refresh_auth_cookie_snapshot_does_not_overwrite_when_probe_is_unhealthy(monkeypatch, tmp_path) -> None:
    from src import server

    snapshot_path = tmp_path / "taobao-cookies.json"
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[object] = []

    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://host.docker.internal:9223")
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda _exported, _sample_urls, **_kwargs: {
            "healthy": False,
            "healthy_samples": 0,
            "sample_count": 1,
            "sample_results": [{"status": "punish_page", "healthy": False}],
        },
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda *_args: writes.append(_args))

    result = server._refresh_auth_cookie_snapshot({"sample_urls": ["https://sf.taobao.com/list/50025969__2.htm"]})

    assert result["refreshed"] is False
    assert result["reason"] == "cookie_snapshot_candidate_unhealthy"
    assert result["cookie_count"] == 1
    assert result["health"]["healthy_samples"] == 0
    assert writes == []

def test_manual_resume_suppresses_stale_solver_manual_required_result(monkeypatch, tmp_path, caplog) -> None:
    from src import server

    caplog.set_level("INFO", logger="src.server")
    fake_now = [1000.0]

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            fake_now[0] = 1005.0
            server._collection_observer_runtime_control_payload("resume")
            return False

    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.solver.running is False
    assert server.RUNTIME.solver.last_status == "resumed"
    assert server.RUNTIME.solver.failure_reason is None
    assert not flag_path.exists()
    assert "Total time: 5.0s" in caplog.text

def test_run_solver_installs_cancel_checker_for_manual_resume(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "cancelled"
        cancel_checker = None

        def solve(self):
            assert self.cancel_checker is not None
            assert self.cancel_checker() is False
            server.RUNTIME.recovery.resume_epoch = server.RUNTIME.solver.started_at + 1
            assert self.cancel_checker() is True
            return False

    fake_solver = FakeSolver()
    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: fake_solver)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.solver.running is False
    assert server.RUNTIME.solver.last_status == "resumed"
    assert server.RUNTIME.solver.failure_reason is None
    assert not flag_path.exists()
