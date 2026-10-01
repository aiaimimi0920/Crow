from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_collection_api_lightweight_status_separates_raw_capture_from_ai_finalized(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 1,
                "seed_scan_job_completed": 2,
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
                "seed_occurrence_total": 16,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["total_ids"] == 16
    assert payload["captured_count"] == 8
    assert payload["ai_finalized_count"] == 3
    assert payload["db_processed_ids"] == 3
    assert payload["db_detail_captured_ids"] == 8
    assert payload["collection_stage"]["detail_stage"]["raw_archived"] == 5
    assert payload["collection_stage"]["detail_stage"]["archived"] == 8
    assert payload["collection_stage"]["detail_stage"]["ai_finalized"] == 3

def test_collection_api_lightweight_status_exposes_analysis_only_status_fields(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 2,
                "seed_item_analysis_failed": 1,
                "seed_item_analysis_blocked": 1,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)

    payload = server._collection_api_lightweight_status_payload()
    detail_stage = payload["collection_stage"]["detail_stage"]

    assert payload["raw_capture_pending_count"] == 5
    assert payload["raw_captured_count"] == 5
    assert payload["analysis_ready_count"] == 6
    assert payload["analysis_in_progress_count"] == 2
    assert payload["analysis_pending_count"] == 8
    assert payload["analysis_blocked_count"] == 1
    assert payload["analysis_finalized_count"] == 3
    assert payload["detail_failed_count"] == 2
    assert payload["detail_blocked_count"] == 1
    assert detail_stage["raw_pending"] == 4
    assert detail_stage["raw_in_progress"] == 1
    assert detail_stage["raw_failed"] == 2
    assert detail_stage["raw_blocked"] == 1
    assert detail_stage["analysis_ready"] == 6
    assert detail_stage["analysis_backlog"] == 8
    assert detail_stage["analysis_finalized"] == 3

def test_solver_force_unlock_flag_path_uses_persistent_state_dir(monkeypatch, tmp_path) -> None:
    from src import server

    state_dir = tmp_path / "solver-state"
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(state_dir))
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {"node_id": "pc2"})

    assert Path(server._solver_force_unlock_flag_path()) == state_dir / "force_unlock.flag"
    assert server._write_solver_manual_required_flag(1234.0) is None
    payload = json.loads((state_dir / "force_unlock.flag").read_text(encoding="utf-8"))
    assert payload["last_request"]["node_id"] == "pc2"

def test_collection_api_lightweight_status_surfaces_manual_required_solver_state(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", time.time() - 5)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_api_lightweight_status_payload()

    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True
    assert payload["captcha_solver"]["elapsed_seconds"] >= 5

def test_collection_api_lightweight_status_treats_force_unlock_flag_as_durable_manual_required(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True

def test_collection_api_lightweight_status_does_not_pause_for_transient_solver_run(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver", raising=False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "running")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", time.time() - 3)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is False
    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["paused"] is False

def test_collection_api_lightweight_status_preserves_operator_pause_during_solver_run(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "operator", raising=False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "running")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", time.time() - 3)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["paused"] is True

def test_collection_observer_page_contains_three_collection_modules() -> None:
    from src import server

    html = server._collection_observer_page_html()

    assert "Crow 采集观察台" in html
    if "商品链接采集" in html:
        assert "商品详情页采集" in html
        assert "商品详情页 AI 分析" in html
        assert "/api/collection/overview" in html
        assert "/api/collection/items" in html
    else:
        assert '<div id="app"></div>' in html
        assert "/assets/index-" in html

def test_collection_observer_overview_wraps_lightweight_status(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_occurrence_total": 12,
                "seed_item_pending_detail": 4,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)

    payload = server._collection_observer_overview_payload()

    assert payload["ok"] is True
    assert payload["modules"]["links"]["total"] == 12
    assert payload["modules"]["details"]["captured"] == 8
    assert payload["modules"]["analysis"]["finalized"] == 3

def test_pc1_auth_auto_resume_state_summary_reads_shared_state(tmp_path, monkeypatch) -> None:
    from src import server

    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)
    state_path = tmp_path / "secrets" / "pc1-auth-auto-resume-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "mode": "pc1_auth_auto_resume_watch",
                "status": "completed",
                "started_at": "2026-08-12T01:00:00Z",
                "completed_at": "2026-08-12T01:03:30Z",
                "poll_seconds": 5,
                "max_wait_seconds": 1800,
                "api_base": "http://192.168.15.200:8001/api",
                "cdp_endpoint": "http://127.0.0.1:9225",
            }
        ),
        encoding="utf-8",
    )

    summary = server._pc1_auth_auto_resume_state_summary(Path(data_root))

    assert summary["available"] is True
    assert summary["mode"] == "pc1_auth_auto_resume_watch"
    assert summary["status"] == "completed"
    assert summary["poll_seconds"] == 5
    assert summary["max_wait_seconds"] == 1800
    assert summary["wait_elapsed_seconds"] == 210
    assert summary["api_base"] == "http://192.168.15.200:8001/api"
    assert summary["cdp_endpoint"] == "http://127.0.0.1:9225"

def test_collection_observer_overview_exposes_challenge_metrics_and_auth_watcher(tmp_path, monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_occurrence_total": 12,
                "seed_item_pending_detail": 4,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
            }

    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "decision_counts": {
                    "browserless_success": 3,
                    "browser_fallback_required": 2,
                },
                "reason_counts": {
                    "challenge_detected": 2,
                },
                "last_reason": "challenge_detected",
                "last_decision": "browser_fallback_required",
                "top_fallback_reason": "challenge_detected",
                "last_probe_summary": {
                    "body_has_challenge": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (avm_root / "hybrid_seed_collection_runtime_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "decision_counts": {"browserless_success": 1},
                        "reason_counts": {},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "decision_counts": {"browser_fallback_required": 1},
                        "reason_counts": {"challenge_detected": 1},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    watcher_path = tmp_path / "secrets" / "pc1-auth-auto-resume-state.json"
    watcher_path.parent.mkdir(parents=True, exist_ok=True)
    watcher_path.write_text(
        json.dumps(
            {
                "mode": "pc1_auth_auto_resume_watch",
                "status": "watching",
                "started_at": "2026-08-12T01:00:00Z",
                "poll_seconds": 5,
                "max_wait_seconds": 1800,
                "last_error": "cookie export returned non-zero exit code",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server, "DATA_DIR", str(data_root))
    monkeypatch.setattr(server, "AVM_SERVICE", type("FakeService", (), {"data_dir": str(tmp_path / "unrelated-analysis")})())

    payload = server._collection_observer_overview_payload()

    assert payload["challenge_metrics"]["available"] is True
    assert payload["challenge_metrics"]["current_challenge_detected_count"] == 2
    assert payload["challenge_metrics"]["current_browserless_attempt_count"] == 5
    assert payload["challenge_metrics"]["current_challenge_hit_rate"] == 0.4
    assert payload["challenge_metrics"]["recent_challenge_detected_count"] == 1
    assert payload["challenge_metrics"]["recent_browserless_attempt_count"] == 2
    assert payload["challenge_metrics"]["recent_challenge_hit_rate"] == 0.5
    assert payload["challenge_metrics"]["last_probe_body_has_challenge"] is True
    assert payload["auth_watcher"]["available"] is True
    assert payload["auth_watcher"]["status"] == "watching"
    assert payload["auth_watcher"]["poll_seconds"] == 5
    assert payload["auth_watcher"]["max_wait_seconds"] == 1800
    assert payload["auth_watcher"]["last_error"] == "cookie export returned non-zero exit code"

def test_collection_observer_items_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True
        seen_location_code = None

        def collection_observer_items(self, *, stage, limit, offset, location_code=None):
            self.seen_location_code = location_code
            return {
                "stage": stage,
                "limit": limit,
                "offset": offset,
                "location_code": location_code,
                "total": 1,
                "items": [{"item_id": "1001", "title": "测试房产"}],
            }

    fake = FakeRepository()
    monkeypatch.setattr(server, "DB_REPOSITORY", fake)

    payload = server._collection_observer_items_payload(
        {"stage": ["analysis"], "limit": ["5"], "offset": ["10"], "location_code": ["440115"]}
    )

    assert payload["stage"] == "analysis"
    assert payload["limit"] == 5
    assert payload["offset"] == 10
    assert payload["location_code"] == "440115"
    assert fake.seen_location_code == "440115"
    assert payload["items"][0]["item_id"] == "1001"

def test_collection_observer_regions_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def collection_observer_regions(self, *, stage):
            return {
                "ok": True,
                "stage": stage,
                "regions": [
                    {
                        "location_code": "440115",
                        "label": "广州市 南沙区",
                        "completed": True,
                        "status_label": "收集完成",
                    }
                ],
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_regions_payload({"stage": ["details"]})

    assert payload["ok"] is True
    assert payload["stage"] == "details"
    assert payload["regions"][0]["location_code"] == "440115"
    assert payload["regions"][0]["completed"] is True
    assert payload["db_mode"] is True

def test_collection_observer_reset_region_links_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def reset_seed_link_region(self, location_code):
            return {"ok": True, "location_code": location_code, "reset": {"jobs": 1, "progress": 2}}

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_reset_region_links_payload({"location_code": "440115"})

    assert payload["ok"] is True
    assert payload["location_code"] == "440115"
    assert payload["reset"]["progress"] == 2
    assert payload["db_mode"] is True
