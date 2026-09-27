from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_hybrid_retrial_budget_after_pin_release(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-8", url="https://x/stage-http-hybrid-8"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=14", "page": 14},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:37:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-1",
        },
        {
            "generated_at": "2026-05-18 18:38:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-2",
        },
        {
            "generated_at": "2026-05-18 18:39:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:35:30",
                "session_id": "budget-switch-1",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "guidance_status": "prefer_browser_fallback",
                "top_guidance_reason": "challenge_detected",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    recovery_events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    recovery_events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:39:30",
                "session_id": "budget-release-1",
                "transition_kind": "pin_released",
                "from_policy_status": "pin_browser_mode_temporarily",
                "to_policy_status": "allow_hybrid_retrial",
                "from_mode_pin_active": True,
                "to_mode_pin_active": False,
                "from_effective_recommended_mode": "browser",
                "to_effective_recommended_mode": "hybrid",
                "from_top_policy_reason": "challenge_detected",
                "to_top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "allow_hybrid_retrial"
        assert policy["effective_recommended_mode"] == "hybrid"
        assert policy["mode_pin_active"] is False
        assert policy["hybrid_retrial_budget_total"] == 1
        assert policy["hybrid_retrial_attempts_used"] == 1
        assert policy["hybrid_retrial_budget_remaining"] == 0
        assert policy["last_recovery_transition_kind"] == "pin_released"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_budget_remaining"] == 0
        assert overview["hybrid_collection_recovery_last_transition_kind"] == "pin_released"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_escalate_repeated_repin_after_multiple_release_cycles(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-9", url="https://x/stage-http-hybrid-9"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:50:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "monitor_hybrid_runtime",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "mixed_runtime_signals",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "stop_on_fallback",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=15", "page": 15},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:47:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "cycle-1",
        },
        {
            "generated_at": "2026-05-18 18:48:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "cycle-2",
        },
        {
            "generated_at": "2026-05-18 18:49:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "cycle-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:45:10",
                        "session_id": "cycle-switch-1",
                        "requested_mode": "hybrid",
                        "effective_mode": "browser",
                        "guidance_status": "prefer_browser_fallback",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:46:10",
                        "session_id": "cycle-switch-2",
                        "requested_mode": "hybrid",
                        "effective_mode": "browser",
                        "guidance_status": "investigate_challenge_spike",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
            ]
        ) + "\n",
        encoding="utf-8",
    )

    recovery_events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    recovery_events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:45:00",
                        "session_id": "cycle-rel-1",
                        "transition_kind": "pin_released",
                        "from_policy_status": "pin_browser_mode_temporarily",
                        "to_policy_status": "allow_hybrid_retrial",
                        "from_mode_pin_active": True,
                        "to_mode_pin_active": False,
                        "from_effective_recommended_mode": "browser",
                        "to_effective_recommended_mode": "hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:46:00",
                        "session_id": "cycle-pin-1",
                        "transition_kind": "pin_activated",
                        "from_policy_status": "allow_hybrid_retrial",
                        "to_policy_status": "pin_browser_mode_temporarily",
                        "from_mode_pin_active": False,
                        "to_mode_pin_active": True,
                        "to_effective_recommended_mode": "browser",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:47:00",
                        "session_id": "cycle-rel-2",
                        "transition_kind": "pin_released",
                        "from_policy_status": "pin_browser_mode_temporarily",
                        "to_policy_status": "allow_hybrid_retrial",
                        "from_mode_pin_active": True,
                        "to_mode_pin_active": False,
                        "to_effective_recommended_mode": "hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:48:00",
                        "session_id": "cycle-pin-2",
                        "transition_kind": "pin_activated",
                        "from_policy_status": "allow_hybrid_retrial",
                        "to_policy_status": "pin_browser_mode_temporarily",
                        "from_mode_pin_active": False,
                        "to_mode_pin_active": True,
                        "to_effective_recommended_mode": "browser",
                    },
                    ensure_ascii=False,
                ),
            ]
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "escalate_repeated_repin"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "repeated_repin_cycle_detected"
        assert "investigate_repeated_repin_cycle" in policy["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "repeated_repin_cycle_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_receipt_control_plane_can_repair_missing_backup_from_repository_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_manual_review_receipt(
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {
                "full_address": "A",
                "community_name": "B",
                "business_area": "C",
                "latitude": 1.0,
                "longitude": 2.0,
            },
        }
    )

    data_root = tmp_path / "datas"
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_root))
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(importlib.import_module("src.collection_stage_status"), "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(importlib.import_module("src.collection_stage_status"), "load_optimization_loop_progress_snapshot", lambda path=None: {})
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.RUNTIME.started_at
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.RUNTIME.started_at = 0
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_status") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        backup_summary = status_body["manual_review_control_plane_backup"]
        assert backup_summary["backup_state"] == "in_sync"
        assert backup_summary["backup_reason"] == "repaired_missing_backup"
        assert backup_summary["all_backup_files_present"] is True
        repairs_summary = status_body["manual_review_control_plane_backup_repairs_summary"]
        assert repairs_summary["repair_count"] == 1
        assert repairs_summary["last_repair_reason"] == "repaired_missing_backup"
        integrity = status_body["manual_review_control_plane_integrity"]
        assert integrity["integrity_status"] == "repaired_recently"
        assert integrity["attention_required"] is False
        assert integrity["follow_up_recommended"] is True
        stability = status_body["manual_review_control_plane_stability"]
        assert stability["stability_status"] == "watch_repaired_repository"
        assert stability["attention_required"] is False
        assert stability["follow_up_recommended"] is True
        guidance = status_body["manual_review_control_plane_guidance"]
        assert guidance["guidance_status"] == "monitor_recent_repair"
        assert guidance["requires_operator_action"] is False
        assert guidance["priority"] == "warning"
        assert status_body["manual_review_control_plane_storage"]["state_source"] == "repository"
        assert "manual_review_receipt_jobs_summary" in status_body
        assert "manual_review_receipt_operations_summary" in status_body
        assert (data_root / "avm" / "manual_review_receipts.json").exists()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_backup_repairs") as resp:
            repairs_body = json.loads(resp.read().decode("utf-8"))
        assert repairs_body["repair_count"] == 1
        assert repairs_body["repairs"][0]["reason"] == "repaired_missing_backup"
        assert repairs_body["manual_review_control_plane_backup_repairs_summary"]["repair_count"] == 1

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_integrity_history") as resp:
            integrity_body = json.loads(resp.read().decode("utf-8"))
        assert integrity_body["transition_count"] >= 1
        assert integrity_body["history"][0]["integrity_status"] == "repaired_recently"
        assert integrity_body["manual_review_control_plane_integrity_history_summary"]["last_integrity_status"] == "repaired_recently"
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.RUNTIME.started_at = original_start_time
