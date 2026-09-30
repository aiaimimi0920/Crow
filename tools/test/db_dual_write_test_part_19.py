from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_steady_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-19", url="https://x/stage-http-hybrid-19"), event_type="seed")

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
                "generated_at": "2026-05-19 00:42:00",
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
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=23", "page": 23},
                "recovery_policy_status": "steady_hybrid",
                "recovery_policy_priority": "info",
                "recovery_policy_mode_pin_active": False,
                "recovery_policy_effective_recommended_mode": "hybrid",
                "top_policy_reason": "browserless_success_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-19 00:39:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-1",
        },
        {
            "generated_at": "2026-05-19 00:40:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-2",
        },
        {
            "generated_at": "2026-05-19 00:41:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "steady"
        assert summary["lifecycle_reason"] == "browserless_fast_path_stable"
        assert summary["recommended_follow_up"] == "keep_hybrid"
        assert summary["suggested_mode"] == "hybrid"
        assert summary["policy_status"] == "steady_hybrid"
        assert summary["priority_hint"] == "no_active_priority_backlog"
        assert summary["active_unresolved_priority"] is None
        assert summary["active_high_priority_unresolved_count"] == 0
        assert summary["operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "ready"
        assert intervention_summary["intervention_required"] is False
        assert intervention_summary["intervention_priority"] == "info"
        assert intervention_summary["intervention_reason"] == "browserless_fast_path_stable"
        assert intervention_summary["preferred_operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert intervention_summary["suggested_mode"] == "hybrid"
        assert intervention_summary["lifecycle_state"] == "steady"
        assert intervention_summary["window_open"] is False
        assert intervention_summary["active_high_priority_unresolved_count"] == 0
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is False
        assert intervention_summary["recent_unresolved_count"] == 0
        assert intervention_summary["recent_resolution_rate"] == 0.0
        assert intervention_summary["recovery_latency_available"] is False
        assert intervention_summary["last_recovery_latency_minutes"] is None
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "steady"
        assert overview["hybrid_collection_lifecycle_reason"] == "browserless_fast_path_stable"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "keep_hybrid"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "hybrid"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "no_active_priority_backlog"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
        assert overview["hybrid_collection_lifecycle_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_status"] == "ready"
        assert overview["hybrid_collection_operator_intervention_required"] is False
        assert overview["hybrid_collection_operator_intervention_priority"] == "info"
        assert overview["hybrid_collection_operator_intervention_reason"] == "browserless_fast_path_stable"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_aligned_hybrid_collection_action_hint_consistency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-20", url="https://x/stage-http-hybrid-20"), event_type="seed")

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
                "generated_at": "2026-05-19 00:50:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "effective_mode_source": "recovery_policy",
                "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "browser",
                "termination_reason": "operator_escalation",
                "last_decision": "browser_worker_dispatched",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
                "recovery_policy_status": "escalate_repeated_repin",
                "recovery_policy_priority": "high",
                "recovery_policy_mode_pin_active": True,
                "recovery_policy_effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:50:00",
                "session_id": "hint-align-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_action_hint_consistency_summary"]
        assert summary["available"] is True
        assert summary["runtime_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert summary["lifecycle_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert summary["hints_match"] is True
        assert summary["consistency_status"] == "aligned"
        assert summary["drift_reason"] is None
        assert summary["consistency_severity"] == "info"
        assert summary["severity_reason"] == "aligned_hints"
        assert summary["hint_source_preference"] == "runtime_preferred"
        assert summary["preferred_hint_source_detail"] == "runtime_aligned"
        assert summary["preferred_hint_explanation"] == "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
        assert summary["preferred_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_action_hint_consistency_status"] == "aligned"
        assert overview["hybrid_collection_action_hint_hints_match"] is True
        assert overview["hybrid_collection_action_hint_drift_reason"] is None
        assert overview["hybrid_collection_action_hint_consistency_severity"] == "info"
        assert overview["hybrid_collection_action_hint_severity_reason"] == "aligned_hints"
        assert overview["hybrid_collection_action_hint_source_preference"] == "runtime_preferred"
        assert overview["hybrid_collection_action_hint_source_detail"] == "runtime_aligned"
        assert overview["hybrid_collection_action_hint_explanation"] == "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
        assert overview["hybrid_collection_preferred_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_lifecycle_only_hybrid_collection_action_hint_consistency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-21", url="https://x/stage-http-hybrid-21"), event_type="seed")

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
                "generated_at": "2026-05-19 00:51:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=26", "page": 26},
                "recovery_policy_status": "allow_hybrid_retrial",
                "recovery_policy_priority": "info",
                "recovery_policy_mode_pin_active": False,
                "recovery_policy_effective_recommended_mode": "hybrid",
                "top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:50:30",
                "session_id": "hint-lifecycle-only-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "allow_hybrid_retrial",
                "effective_mode": "hybrid",
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_action_hint_consistency_summary"]
        assert summary["available"] is True
        assert summary["runtime_operator_action_hint"] is None
        assert summary["lifecycle_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert summary["hints_match"] is False
        assert summary["consistency_status"] == "lifecycle_only"
        assert summary["drift_reason"] == "runtime_missing"
        assert summary["consistency_severity"] == "warning"
        assert summary["severity_reason"] == "runtime_missing_lifecycle_fallback"
        assert summary["hint_source_preference"] == "lifecycle_preferred"
        assert summary["preferred_hint_source_detail"] == "lifecycle_fallback_used"
        assert summary["preferred_hint_explanation"] == "Runtime action hint is missing; using the lifecycle fallback hint."
        assert summary["preferred_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_action_hint_consistency_status"] == "lifecycle_only"
        assert overview["hybrid_collection_action_hint_hints_match"] is False
        assert overview["hybrid_collection_action_hint_drift_reason"] == "runtime_missing"
        assert overview["hybrid_collection_action_hint_consistency_severity"] == "warning"
        assert overview["hybrid_collection_action_hint_severity_reason"] == "runtime_missing_lifecycle_fallback"
        assert overview["hybrid_collection_action_hint_source_preference"] == "lifecycle_preferred"
        assert overview["hybrid_collection_action_hint_source_detail"] == "lifecycle_fallback_used"
        assert overview["hybrid_collection_action_hint_explanation"] == "Runtime action hint is missing; using the lifecycle fallback hint."
        assert overview["hybrid_collection_preferred_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()
