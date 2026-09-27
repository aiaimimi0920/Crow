from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_collection_observer_item_payload_loads_one_item(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def collection_observer_item_detail(self, item_id, *, max_chars):
            return {
                "item": {"item_id": item_id, "title": "测试房产"},
                "max_chars": max_chars,
                "artifacts": {"final_json": {"json": {"community_name": "测试小区"}}},
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_item_payload({"item_id": ["1001"], "max_chars": ["123"]})

    assert payload["item"]["item_id"] == "1001"
    assert payload["max_chars"] == 123
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "测试小区"

def test_collection_observer_reanalysis_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def requeue_seed_detail_analysis(self, item_id, *, reason):
            return {
                "ok": True,
                "item_id": item_id,
                "status": "raw_detail_captured",
                "reason": reason,
                "analysis_attempt_count": 3,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_reanalysis_payload({"item_id": "1001"})

    assert payload["ok"] is True
    assert payload["item_id"] == "1001"
    assert payload["status"] == "raw_detail_captured"
    assert payload["analysis_attempt_count"] == 3

def test_collection_observer_manual_update_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def manual_update_flat_item(self, item_id, updates):
            return {
                "ok": True,
                "item_id": item_id,
                "updated_fields": sorted(updates),
                "flat_item": {"item_id": item_id, **updates},
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_manual_update_payload(
        {"item_id": "1001", "updates": {"title": "手动标题", "transaction_price": "123"}}
    )

    assert payload["ok"] is True
    assert payload["item_id"] == "1001"
    assert payload["updated_fields"] == ["title", "transaction_price"]
    assert payload["flat_item"]["title"] == "手动标题"

def test_collection_observer_runtime_control_can_pause_and_resume(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)

    paused = server._collection_observer_runtime_control_payload("pause")

    assert paused["ok"] is True
    assert paused["runtime_state"] == "暂停中"
    assert server.RUNTIME.control.paused is True

    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", time.time() - 300)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    resumed = server._collection_observer_runtime_control_payload("resume")

    assert resumed["ok"] is True
    assert resumed["runtime_state"] == "运行中"
    assert server.RUNTIME.control.paused is False
    assert not (tmp_path / "force_unlock.flag").exists()
    assert server.RUNTIME.solver.last_status == "resumed"
    assert server.RUNTIME.solver.failure_reason is None
    assert server.RUNTIME.solver.running is False
    assert resumed["captcha_solver"]["running"] is False

def test_collection_api_lightweight_status_keeps_running_when_manual_required_only_targets_detail_and_seed_work_remains(
    monkeypatch,
) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 9,
                "seed_scan_job_in_progress": 1,
                "seed_scan_job_completed": 2,
                "seed_scan_progress_pending": 20,
                "seed_scan_progress_in_progress": 1,
                "seed_scan_progress_exhausted": 0,
                "seed_scan_progress_blocked": 0,
                "seed_item_pending_detail": 30,
                "seed_item_in_progress": 0,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 0,
                "seed_item_analysis_failed": 0,
                "seed_item_analysis_blocked": 0,
                "seed_item_detail_completed": 10,
                "seed_item_detail_failed": 0,
                "seed_item_detail_blocked": 0,
                "seed_occurrence_total": 200,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {"target_url": "https://sf-item.taobao.com/sf_item/647559663666.htm?__captcha_solver_bg=1"},
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 1000.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 1000.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 1000.0)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["runtime_state"] == "运行中"

def test_collection_api_lightweight_status_reports_pending_auth_when_manual_required_targets_seed_stage(
    monkeypatch,
) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 9,
                "seed_scan_job_in_progress": 1,
                "seed_scan_job_completed": 2,
                "seed_scan_progress_pending": 20,
                "seed_scan_progress_in_progress": 1,
                "seed_scan_progress_exhausted": 0,
                "seed_scan_progress_blocked": 0,
                "seed_item_pending_detail": 30,
                "seed_item_in_progress": 0,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 0,
                "seed_item_analysis_failed": 0,
                "seed_item_analysis_blocked": 0,
                "seed_item_detail_completed": 10,
                "seed_item_detail_failed": 0,
                "seed_item_detail_blocked": 0,
                "seed_occurrence_total": 200,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1"},
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 1000.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 1000.0, raising=False)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 1000.0)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["runtime_state"] == "待认证"

def test_collection_observer_auth_complete_clears_pause_and_marks_manual_auth(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, _completion_id: {"status": "skipped", "refreshed": False, "retry_queued": False},
    )
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", time.time() - 10)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "running")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {"target_url": "https://contest.local/auth"})
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {"source": "desktop", "refresh_cookie_snapshot": False}
    )

    assert payload["ok"] is True
    assert payload["action"] == "auth_complete"
    assert payload["auth_state_confirmed"] is True
    assert payload["runtime_state"] == "运行中"
    assert payload["manual_auth_completed"] is True
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.solver.last_status == "manual_auth_completed"
    assert server.RUNTIME.solver.failure_reason is None
    assert server.RUNTIME.solver.running is False
    assert payload["captcha_solver"]["running"] is False
    assert server.RUNTIME.recovery.resume_epoch > 0
    assert not (tmp_path / "force_unlock.flag").exists()

def test_collection_observer_auth_complete_keeps_pause_while_cookie_snapshot_is_pending(monkeypatch, tmp_path) -> None:
    from src import server

    calls: list[dict[str, object]] = []

    def fake_schedule(
        payload: dict[str, object],
        completion_id: str | None,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append(
            {
                **dict(payload),
                "scheduled_completion_id": completion_id,
                "finalize_auth": kwargs.get("finalize_auth"),
                "expected_challenge_id": kwargs.get("expected_challenge_id"),
            }
        )
        return {
            "status": "pending",
            "refreshed": False,
            "retry_queued": True,
            "completion_id": completion_id,
        }

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", fake_schedule)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {"source": "desktop", "completion_id": "desktop-completion-1"}
    )

    assert calls == [
        {
            "source": "desktop",
            "completion_id": "desktop-completion-1",
            "refresh_cookie_snapshot": True,
            "scheduled_completion_id": "desktop-completion-1",
            "finalize_auth": True,
            "expected_challenge_id": None,
        }
    ]
    assert payload["ok"] is True
    assert payload["paused"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["auth_state_confirmed"] is False
    assert payload["auth_confirmation_pending"] is True
    assert payload["cookie_snapshot"]["status"] == "pending"
    assert payload["cookie_snapshot"]["retry_queued"] is True
    assert server.RUNTIME.solver.last_status == "manual_required"
    assert (tmp_path / "force_unlock.flag").exists()

def test_pc2_auth_complete_cannot_disable_cookie_snapshot_gate(monkeypatch, tmp_path) -> None:
    from src import server

    scheduled_payloads: list[dict[str, object]] = []

    def fake_schedule(
        payload: dict[str, object],
        completion_id: str | None,
        **_kwargs: object,
    ) -> dict[str, object]:
        scheduled_payloads.append(dict(payload))
        return {
            "status": "pending",
            "completion_id": completion_id,
            "refreshed": False,
            "retry_queued": True,
        }

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", fake_schedule)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", "challenge-gate-required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {
            "source": "pc2_local_solver",
            "completion_id": "pc2-gate-required",
            "challenge_id": "challenge-gate-required",
            "refresh_cookie_snapshot": False,
        }
    )

    assert scheduled_payloads[0]["refresh_cookie_snapshot"] is True
    assert payload["ok"] is True
    assert payload["auth_state_confirmed"] is False
    assert payload["auth_confirmation_pending"] is True
    assert payload["paused"] is True
    assert (tmp_path / "force_unlock.flag").exists()

def test_collection_observer_auth_complete_keeps_pause_when_cookie_refresh_fails(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, completion_id, **_kwargs: {
            "status": "failed",
            "completion_id": completion_id,
            "refreshed": False,
            "retry_queued": False,
            "result": {"error": "cdp unavailable"},
        },
    )
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")

    payload = server._collection_observer_auth_complete_payload({"source": "desktop"})

    assert payload["ok"] is False
    assert payload["auth_state_confirmed"] is False
    assert payload["paused"] is True
    assert payload["cookie_snapshot"]["refreshed"] is False
    assert "cdp unavailable" in payload["cookie_snapshot"]["result"]["error"]
    assert server.RUNTIME.solver.last_status == "manual_required"

def test_collection_observer_auth_complete_is_idempotent_for_repeated_completion_id(monkeypatch, tmp_path) -> None:
    from src import server

    completion_id = "pc2-completion-idempotent"
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
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    first = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )
    server.RUNTIME.recovery.replace_confirmations({})
    second = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )

    assert first["ok"] is True
    assert first["auth_state_confirmed"] is True
    assert first["idempotent"] is False
    assert second["ok"] is True
    assert second["auth_state_confirmed"] is True
    assert second["idempotent"] is True
    assert second["completion_id"] == completion_id
    assert second["captcha_solver"]["manual_required"] is False
    assert second["captcha_solver"]["force_unlock_flag_exists"] is False
