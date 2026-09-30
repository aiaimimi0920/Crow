from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_open_unresolved_escalation_window_duration(tmp_path: Path, monkeypatch):
    import datetime

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16", url="https://x/stage-http-hybrid-16"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))

    class _FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 5, 19, 0, 15, 0)

    monkeypatch.setattr(server_module.datetime, "datetime", _FakeDateTime)

    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "uwd-esc-1",
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
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["window_open"] is True
        assert summary["current_window_duration_seconds"] == 300
        assert summary["current_window_duration_minutes"] == 5.0
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] == 300
        assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] == 5.0
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_escalated_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-17", url="https://x/stage-http-hybrid-17"), event_type="seed")

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
                "generated_at": "2026-05-19 00:40:00",
                "runner_mode": "browser",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "effective_mode_source": "recovery_policy",
                "guidance_applied": True,
                "guidance_status": "monitor_hybrid_runtime",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "repeated_repin_cycle_detected",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 1,
                "last_effective_mode": "browser",
                "termination_reason": "operator_escalation",
                "last_decision": "browser_worker_dispatched",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
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
                "generated_at": "2026-05-19 00:40:00",
                "session_id": "life-esc-1",
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
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "escalated"
        assert summary["lifecycle_reason"] == "unresolved_escalation_window_open"
        assert summary["window_open"] is True
        assert summary["policy_status"] == "escalate_repeated_repin"
        assert summary["recommended_follow_up"] == "prefer_browser_and_investigate_escalation"
        assert summary["suggested_mode"] == "browser"
        assert summary["priority_hint"] == "high_priority_backlog_present"
        assert summary["active_unresolved_priority"] == "high"
        assert summary["active_high_priority_unresolved_count"] == 1
        assert summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "intervention_required"
        assert intervention_summary["intervention_required"] is True
        assert intervention_summary["intervention_priority"] == "high"
        assert intervention_summary["intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert intervention_summary["preferred_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert intervention_summary["suggested_mode"] == "browser"
        assert intervention_summary["lifecycle_state"] == "escalated"
        assert intervention_summary["window_open"] is True
        assert intervention_summary["active_high_priority_unresolved_count"] == 1
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is True
        assert intervention_summary["recent_unresolved_count"] == 1
        assert intervention_summary["recent_resolution_rate"] == 0.0
        assert intervention_summary["recovery_latency_available"] is False
        assert intervention_summary["last_recovery_latency_minutes"] is None
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "escalated"
        assert overview["hybrid_collection_lifecycle_reason"] == "unresolved_escalation_window_open"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "prefer_browser_and_investigate_escalation"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "browser"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "high_priority_backlog_present"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] == "high"
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 1
        assert overview["hybrid_collection_lifecycle_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_operator_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_operator_intervention_required"] is True
        assert overview["hybrid_collection_operator_intervention_priority"] == "high"
        assert overview["hybrid_collection_operator_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "browser"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_retrial_window_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-18", url="https://x/stage-http-hybrid-18"), event_type="seed")

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
                "generated_at": "2026-05-19 00:41:00",
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
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
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
                "generated_at": "2026-05-19 00:40:30",
                "session_id": "life-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "allow_hybrid_retrial",
                "effective_mode": "hybrid",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:40:00",
                "session_id": "life-rec-esc-1",
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
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "retrial_window_open"
        assert summary["lifecycle_reason"] == "hybrid_retrial_budget_active"
        assert summary["policy_status"] == "allow_hybrid_retrial"
        assert summary["recommended_follow_up"] == "continue_hybrid_with_budget_watch"
        assert summary["suggested_mode"] == "hybrid"
        assert summary["priority_hint"] == "no_active_priority_backlog"
        assert summary["active_unresolved_priority"] is None
        assert summary["active_high_priority_unresolved_count"] == 0
        assert summary["operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "monitor"
        assert intervention_summary["intervention_required"] is False
        assert intervention_summary["intervention_priority"] == "warning"
        assert intervention_summary["intervention_reason"] == "hybrid_retrial_budget_active"
        assert intervention_summary["preferred_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert intervention_summary["suggested_mode"] == "hybrid"
        assert intervention_summary["lifecycle_state"] == "retrial_window_open"
        assert intervention_summary["window_open"] is False
        assert intervention_summary["active_high_priority_unresolved_count"] == 0
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is True
        assert intervention_summary["recent_unresolved_count"] == 0
        assert intervention_summary["recent_resolution_rate"] == 1.0
        assert intervention_summary["recovery_latency_available"] is True
        assert intervention_summary["last_recovery_latency_minutes"] == 0.5
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "retrial_window_open"
        assert overview["hybrid_collection_lifecycle_reason"] == "hybrid_retrial_budget_active"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "continue_hybrid_with_budget_watch"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "hybrid"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "no_active_priority_backlog"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
        assert overview["hybrid_collection_lifecycle_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_status"] == "monitor"
        assert overview["hybrid_collection_operator_intervention_required"] is False
        assert overview["hybrid_collection_operator_intervention_priority"] == "warning"
        assert overview["hybrid_collection_operator_intervention_reason"] == "hybrid_retrial_budget_active"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()
