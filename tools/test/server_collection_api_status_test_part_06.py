from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_run_solver_waits_for_configured_worker_quiescence(monkeypatch, tmp_path) -> None:
    from src import server

    events: list[object] = []

    class FakeSolver:
        last_failure_reason = None

        def solve(self):
            events.append("solve")
            return True

    def build_solver(_request):
        events.append("build")
        return FakeSolver()

    def wait_for_cdp(_request, *, deadline, cancel_checker):
        assert deadline > clock[0]
        assert not cancel_checker()
        events.append("cdp_ready")
        return True

    clock = [0.0]
    class WaitEvent(threading.Event):
        def wait(self, timeout=None):
            clock[0] += timeout or 0
            events.append(("wait", timeout))
            return False

    monkeypatch.setenv("FAPAI_SOLVER_WORKER_QUIESCE_SECONDS", "7")
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(server.threading, "Event", WaitEvent)
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", wait_for_cdp, raising=False)
    monkeypatch.setattr(server, "_build_solver_for_request", build_solver)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "force_unlock.flag"))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
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

    assert events[-3:] == ["cdp_ready", "build", "solve"]
    assert sum(value for kind, value in events[:-3] if kind == "wait") == pytest.approx(7)
    assert server.RUNTIME.solver.last_status == "solved"

def test_wait_for_solver_cdp_ready_requires_consecutive_healthy_probes(monkeypatch) -> None:
    from src import server

    calls: list[str] = []
    sleep_calls: list[float] = []
    clock = [0.0]
    class WaitEvent(threading.Event):
        def wait(self, timeout=None):
            clock[0] += timeout or 0
            sleep_calls.append(timeout or 0)
            return False

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 3
        if len(calls) == 1:
            raise OSError("browser restarting")
        return FakeResponse()

    monkeypatch.setenv("FAPAI_SOLVER_CDP_READY_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr(server, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(server.threading, "Event", WaitEvent)
    monkeypatch.setattr(server.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    assert server._wait_for_solver_cdp_ready({"cdp_endpoint": "http://192.168.15.104:9224"}) is True
    assert calls == [
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
    ]
    assert sum(sleep_calls) == pytest.approx(4)

def test_mark_manual_required_requests_running_solver_cancel(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = 1234.0
    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.recovery, "cancel_epoch", 0, raising=False)

    flag_error = server._mark_solver_manual_required()

    assert flag_error is None
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.recovery.cancel_epoch == fake_now
    assert flag_path.exists()

def test_manual_only_captcha_report_preserves_detail_target_and_disables_auto_retry(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    challenge_state_path = tmp_path / "solver-challenge-state.json"
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: challenge_state_path)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "pending_token", None)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "manual_only", False, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)

    payload = server._manual_only_captcha_report_payload(
        {
            "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "manual_only": True,
        }
    )

    assert payload["status"] == "manual_required"
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["manual_only"] is True
    assert payload["captcha_solver"]["manual_retry_enabled"] is False
    assert str(payload["captcha_solver"]["challenge_id"]).startswith("captcha-")
    assert payload["captcha_solver"]["last_request"]["target_url"] == (
        "https://sf-item.taobao.com/sf_item/3001.htm"
    )
    assert flag_path.exists()
    assert challenge_state_path.exists()

    monkeypatch.setattr(server.RUNTIME.recovery, "manual_only", False)
    assert server._manual_solver_retry_enabled() is False

def test_solver_cancel_for_manual_required_preserves_manual_pause(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]
    flag_path = tmp_path / "force_unlock.flag"
    sleep_calls: list[float] = []

    class FakeSolver:
        last_failure_reason = "cancelled"
        cancel_checker = None

        def solve(self):
            fake_now[0] = 1001.0
            server._mark_solver_manual_required()
            return False

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if flag_path.exists():
            flag_path.unlink()

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "cancel_epoch", 0, raising=False)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.solver.running is False
    assert server.RUNTIME.solver.last_status == "manual_required"
    assert server.RUNTIME.solver.failure_reason == "manual_required"
    assert flag_path.exists()
    assert sleep_calls == []

def test_manual_required_auto_retry_queues_solver_after_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: True)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 500.0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 500.0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 500.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_attempts", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert queued == [
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        }
    ]
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.solver.last_status == "manual_retry_queued"
    assert server.RUNTIME.solver.failure_reason is None
    assert server.RUNTIME.recovery.retry_last_epoch == 900.0
    assert not flag_path.exists()

def test_manual_required_auto_retry_delegates_pc2_without_clearing_pause(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert queued == []
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.solver.last_status == "manual_required"
    assert server.RUNTIME.solver.failure_reason == "manual_required"
    assert flag_path.exists()

def test_manual_required_auto_retry_respects_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 500.0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 500.0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115"},
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 500.0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=799.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "cooldown_active"
    assert result["next_retry_epoch"] == 800.0
    assert queued == []
    assert server.RUNTIME.control.paused is True
    assert flag_path.exists()

def test_manual_required_auto_retry_delegates_remote_pc2_even_when_cdp_is_unreachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: False)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 500.0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 500.0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 500.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_attempts", 7, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert result["solver_request"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert queued == []
    # manual_required 状态必须原样保留，不能被清成“可继续采集”
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.solver.failure_reason == "manual_required"
    assert flag_path.exists()
    # PC2 owns the retry clock; the NAS monitor must not consume its cooldown.
    assert server.RUNTIME.recovery.retry_attempts == 7
    assert server.RUNTIME.recovery.retry_last_epoch == 500.0

def test_manual_required_auto_retry_queues_when_cdp_endpoint_is_reachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    probed: list[str] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(
        server,
        "_probe_solver_cdp_endpoint",
        lambda endpoint: probed.append(endpoint) is None,
    )
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 500.0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 500.0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 500.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_attempts", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert probed == ["http://host.docker.internal:9223"]
    assert len(queued) == 1
    assert server.RUNTIME.control.paused is False
    assert not flag_path.exists()

def test_probe_solver_cdp_endpoint_reports_unreachable_endpoint_as_unhealthy() -> None:
    from src import server

    # 端口 1 上不会有 CDP 监听，探测必须返回 False 而不是抛异常
    assert server._probe_solver_cdp_endpoint("http://127.0.0.1:1") is False
