from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_stable_hybrid_collection_operator_digest_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16k", url="https://x/stage-http-hybrid-16k"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "session_id": "digest-stability-3",
                "operator_digest_status": "ready",
                "operator_digest_priority": "info",
                "operator_digest_message": stable_message,
            },
            ensure_ascii=False,
        )
        + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_operator_digest_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_digest"
        assert summary["stability_severity"] == "info"
        assert summary["current_digest_status"] == "ready"
        assert summary["current_digest_priority"] == "info"
        assert summary["current_digest_message"] == stable_message
        assert summary["previous_digest_message"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Operator digest remains stable with no recent message changes."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_digest_stability_status"] == "stable_digest"
        assert overview["hybrid_collection_digest_stability_severity"] == "info"
        assert overview["hybrid_collection_digest_stability_explanation"] == "Operator digest remains stable with no recent message changes."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_operator_intervention_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16c", url="https://x/stage-http-hybrid-16c"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_intervention_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "intervention-evt-1",
            "transition_kind": "status_changed",
            "from_intervention_status": "ready",
            "to_intervention_status": "monitor",
            "from_intervention_required": False,
            "to_intervention_required": False,
            "from_intervention_priority": "info",
            "to_intervention_priority": "warning",
            "from_intervention_reason": "browserless_fast_path_stable",
            "to_intervention_reason": "hybrid_retrial_budget_active",
            "to_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "to_suggested_mode": "hybrid",
            "to_final_guidance_label": "Transitioning intervention",
            "to_final_guidance_priority": "warning",
            "to_final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "effective_mode": "hybrid",
            "task_url": "https://sf.taobao.com/list/50025969__2.htm?page=20",
            "task_page": 20,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "intervention-evt-2",
            "transition_kind": "status_changed",
            "from_intervention_status": "monitor",
            "to_intervention_status": "intervention_required",
            "from_intervention_required": False,
            "to_intervention_required": True,
            "from_intervention_priority": "warning",
            "to_intervention_priority": "high",
            "from_intervention_reason": "hybrid_retrial_budget_active",
            "to_intervention_reason": "high_priority_unresolved_escalation_backlog",
            "to_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "to_suggested_mode": "browser",
            "to_final_guidance_label": "Escalating intervention",
            "to_final_guidance_priority": "high",
            "to_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "effective_mode": "browser",
            "task_url": "https://sf.taobao.com/list/50025969__2.htm?page=21",
            "task_page": 21,
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_event_count"] == 2
        assert summary["recent_transition_kind_counts"] == {"status_changed": 2}
        assert summary["recent_to_intervention_status_counts"] == {
            "monitor": 1,
            "intervention_required": 1,
        }
        assert summary["top_transition_kind"] == "status_changed"
        assert summary["top_to_intervention_status"] == "intervention_required"
        assert summary["last_event_at"] == "2026-05-18 18:13:00"
        assert summary["last_event_session_id"] == "intervention-evt-2"
        assert summary["last_transition_kind"] == "status_changed"
        assert summary["last_to_intervention_status"] == "intervention_required"
        assert summary["last_to_intervention_priority"] == "high"
        assert summary["last_to_final_guidance_label"] == "Escalating intervention"
        assert summary["last_to_final_guidance_priority"] == "high"
        assert summary["last_to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_intervention_event_count"] == 2
        assert overview["hybrid_collection_last_intervention_event_at"] == "2026-05-18 18:13:00"
        assert overview["hybrid_collection_last_intervention_transition_kind"] == "status_changed"
        assert overview["hybrid_collection_last_to_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_last_to_intervention_priority"] == "high"
        assert overview["hybrid_collection_last_to_final_guidance_label"] == "Escalating intervention"
        assert overview["hybrid_collection_last_to_final_guidance_priority"] == "high"
        assert overview["hybrid_collection_last_to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_escalating_hybrid_collection_operator_intervention_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16d", url="https://x/stage-http-hybrid-16d"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "intervention-stability-1",
                        "intervention_status": "ready",
                        "intervention_priority": "info",
                        "intervention_reason": "browserless_fast_path_stable",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:12:00",
                        "session_id": "intervention-stability-2",
                        "intervention_status": "intervention_required",
                        "intervention_priority": "high",
                        "intervention_reason": "high_priority_unresolved_escalation_backlog",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "escalating"
        assert summary["stability_severity"] == "high"
        assert summary["current_intervention_status"] == "intervention_required"
        assert summary["previous_intervention_status"] == "ready"
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Intervention escalated from ready to intervention_required recently."
        assert summary["stability_action_hint"] == "prefer browser and investigate escalating intervention"
        final_guidance = body["collection_stage"]["hybrid_collection_operator_final_guidance_summary"]
        assert final_guidance["available"] is True
        assert final_guidance["guidance_label"] == "Escalating intervention"
        assert final_guidance["guidance_priority"] == "high"
        assert final_guidance["guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
        assert final_guidance["preferred_action_hint"] == "prefer browser and investigate escalating intervention"
        assert final_guidance["suggested_mode"] == "browser"
        assert final_guidance["intervention_status"] == "intervention_required"
        assert final_guidance["stability_status"] == "escalating"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_intervention_stability_status"] == "escalating"
        assert overview["hybrid_collection_intervention_stability_severity"] == "high"
        assert overview["hybrid_collection_intervention_stability_explanation"] == "Intervention escalated from ready to intervention_required recently."
        assert overview["hybrid_collection_intervention_stability_action_hint"] == "prefer browser and investigate escalating intervention"
        assert overview["hybrid_collection_operator_final_guidance_label"] == "Escalating intervention"
        assert overview["hybrid_collection_operator_final_guidance_priority"] == "high"
        assert overview["hybrid_collection_operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_stable_ready_hybrid_collection_operator_intervention_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16e", url="https://x/stage-http-hybrid-16e"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "session_id": "intervention-stability-3",
                "intervention_status": "ready",
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
            },
            ensure_ascii=False,
        )
        + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_ready"
        assert summary["stability_severity"] == "info"
        assert summary["current_intervention_status"] == "ready"
        assert summary["previous_intervention_status"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Intervention remains ready with no recent status changes."
        assert summary["stability_action_hint"] == "keep hybrid and continue monitoring"
        final_guidance = body["collection_stage"]["hybrid_collection_operator_final_guidance_summary"]
        assert final_guidance["available"] is True
        assert final_guidance["guidance_label"] == "Stable ready state"
        assert final_guidance["guidance_priority"] == "info"
        assert final_guidance["guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
        assert final_guidance["preferred_action_hint"] == "keep hybrid and continue monitoring"
        assert final_guidance["suggested_mode"] == "hybrid"
        assert final_guidance["intervention_status"] == "ready"
        assert final_guidance["stability_status"] == "stable_ready"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_intervention_stability_status"] == "stable_ready"
        assert overview["hybrid_collection_intervention_stability_severity"] == "info"
        assert overview["hybrid_collection_intervention_stability_explanation"] == "Intervention remains ready with no recent status changes."
        assert overview["hybrid_collection_intervention_stability_action_hint"] == "keep hybrid and continue monitoring"
        assert overview["hybrid_collection_operator_final_guidance_label"] == "Stable ready state"
        assert overview["hybrid_collection_operator_final_guidance_priority"] == "info"
        assert overview["hybrid_collection_operator_final_guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_strategy_guidance(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-3", url="https://x/stage-http-hybrid-3"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:05:00",
                "runner_mode": "hybrid",
                "loop_mode": True,
                "submit_enabled": True,
                "session_id": "guidance-live",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "top_fallback_reason": "challenge_detected",
                "termination_reason": "fallback_escalation_threshold_reached",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=9", "page": 9},
                "last_probe_summary": {"item_count": 0, "has_script": False, "body_has_challenge": True, "body_has_punish": True},
                "last_submit_result": {},
                "last_browser_fallback_opened": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "g-1",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "g-2",
        },
        {
            "generated_at": "2026-05-18 18:03:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "g-3",
        },
        {
            "generated_at": "2026-05-18 18:04:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "g-4",
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
        guidance = body["collection_stage"]["hybrid_collection_strategy_guidance"]
        assert guidance["guidance_status"] == "investigate_challenge_spike"
        assert guidance["priority"] == "high"
        assert guidance["recommended_mode"] == "browser"
        assert guidance["top_guidance_reason"] == "challenge_detected"
        assert "review_challenge_recovery_path" in guidance["recommended_actions"]
        assert "switch_operator_mode_to_browser" in guidance["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_guidance_status"] == "investigate_challenge_spike"
        assert overview["hybrid_collection_recommended_mode"] == "browser"
        assert overview["hybrid_collection_guidance_priority"] == "high"
    finally:
        httpd.shutdown()
        httpd.server_close()
