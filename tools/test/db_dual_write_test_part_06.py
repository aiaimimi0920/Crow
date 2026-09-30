from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_hybrid_collection_operator_intervention_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16b", url="https://x/stage-http-hybrid-16b"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "intervention-trend-1",
            "operator_action_hint": "keep hybrid; suggested mode=hybrid",
            "intervention_status": "ready",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "intervention-trend-2",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "intervention-trend-3",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
        },
    ]
    runtime_history_path.write_text(
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
        trend_summary = body["collection_stage"]["hybrid_collection_operator_intervention_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_status_entry_count"] == 3
        assert trend_summary["recent_intervention_status_counts"] == {
            "ready": 1,
            "intervention_required": 2,
        }
        assert trend_summary["recent_distinct_intervention_status_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_intervention_status"] == "intervention_required"
        assert trend_summary["current_intervention_status"] == "intervention_required"
        assert trend_summary["current_intervention_priority"] == "high"
        assert trend_summary["current_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert trend_summary["previous_distinct_intervention_status"] == "ready"
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_current_intervention_priority"] == "high"
        assert overview["hybrid_collection_current_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert overview["hybrid_collection_previous_intervention_status"] == "ready"
        assert overview["hybrid_collection_intervention_change_count"] == 1
        assert overview["hybrid_collection_intervention_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_intervention_trend_summary_treats_unknown_status_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "intervention-unknown-1",
            "intervention_status": "ready",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "intervention-unknown-2",
            "intervention_status": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_status_entry_count"] == 1
    assert trend_summary["recent_intervention_status_counts"] == {"ready": 1}
    assert trend_summary["recent_distinct_intervention_status_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_intervention_status"] == "ready"
    assert trend_summary["current_intervention_status"] == "ready"
    assert trend_summary["current_intervention_priority"] == "info"
    assert trend_summary["current_intervention_reason"] == "browserless_fast_path_stable"
    assert trend_summary["previous_distinct_intervention_status"] is None
    assert trend_summary["last_change_at"] is None

def test_hybrid_collection_operator_intervention_trend_summary_treats_unknown_priority_and_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
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
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "intervention-unknown-priority-1",
                        "intervention_status": "ready",
                        "intervention_priority": "unknown",
                        "intervention_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:12:00",
                        "session_id": "intervention-unknown-priority-2",
                        "intervention_status": "unknown",
                        "intervention_priority": "unknown",
                        "intervention_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_status_entry_count"] == 1
    assert trend_summary["recent_intervention_status_counts"] == {"ready": 1}
    assert trend_summary["recent_distinct_intervention_status_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_intervention_status"] == "ready"
    assert trend_summary["current_intervention_status"] == "ready"
    assert trend_summary["current_intervention_priority"] is None
    assert trend_summary["current_intervention_reason"] is None
    assert trend_summary["previous_distinct_intervention_status"] is None
    assert trend_summary["last_change_at"] is None

def test_http_status_can_surface_hybrid_collection_operator_final_guidance_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16f", url="https://x/stage-http-hybrid-16f"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    transitioning_message = "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "final-guidance-trend-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "final-guidance-trend-2",
            "operator_final_guidance_label": "Transitioning intervention",
            "operator_final_guidance_priority": "warning",
            "operator_final_guidance_message": transitioning_message,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "final-guidance-trend-3",
            "operator_final_guidance_label": "Transitioning intervention",
            "operator_final_guidance_priority": "warning",
            "operator_final_guidance_message": transitioning_message,
        },
    ]
    runtime_history_path.write_text(
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
        trend_summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_guidance_entry_count"] == 3
        assert trend_summary["recent_guidance_message_counts"] == {
            stable_message: 1,
            transitioning_message: 2,
        }
        assert trend_summary["recent_distinct_guidance_message_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_guidance_message"] == transitioning_message
        assert trend_summary["current_guidance_label"] == "Transitioning intervention"
        assert trend_summary["current_guidance_priority"] == "warning"
        assert trend_summary["current_guidance_message"] == transitioning_message
        assert trend_summary["previous_distinct_guidance_message"] == stable_message
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_final_guidance_label"] == "Transitioning intervention"
        assert overview["hybrid_collection_current_final_guidance_priority"] == "warning"
        assert overview["hybrid_collection_current_final_guidance_message"] == transitioning_message
        assert overview["hybrid_collection_previous_final_guidance_message"] == stable_message
        assert overview["hybrid_collection_final_guidance_change_count"] == 1
        assert overview["hybrid_collection_final_guidance_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_final_guidance_trend_summary_treats_unknown_messages_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "final-guidance-unknown-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "final-guidance-unknown-2",
            "operator_final_guidance_label": "unknown",
            "operator_final_guidance_priority": "unknown",
            "operator_final_guidance_message": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_guidance_entry_count"] == 1
    assert trend_summary["recent_guidance_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_guidance_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_guidance_message"] == stable_message
    assert trend_summary["current_guidance_label"] == "Stable ready state"
    assert trend_summary["current_guidance_priority"] == "info"
    assert trend_summary["current_guidance_message"] == stable_message
    assert trend_summary["previous_distinct_guidance_label"] is None
    assert trend_summary["previous_distinct_guidance_message"] is None
    assert trend_summary["last_change_at"] is None

def test_hybrid_collection_operator_final_guidance_trend_summary_treats_unknown_label_and_priority_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "final-guidance-unknown-meta-1",
                        "operator_final_guidance_label": "unknown",
                        "operator_final_guidance_priority": "unknown",
                        "operator_final_guidance_message": stable_message,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "final-guidance-unknown-meta-2",
                        "operator_final_guidance_label": "unknown",
                        "operator_final_guidance_priority": "unknown",
                        "operator_final_guidance_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_guidance_entry_count"] == 1
    assert trend_summary["recent_guidance_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_guidance_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_guidance_message"] == stable_message
    assert trend_summary["current_guidance_label"] is None
    assert trend_summary["current_guidance_priority"] is None
    assert trend_summary["current_guidance_message"] == stable_message
    assert trend_summary["previous_distinct_guidance_label"] is None
    assert trend_summary["previous_distinct_guidance_message"] is None
    assert trend_summary["last_change_at"] is None

def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_guidance_label": None,
        "current_guidance_priority": None,
        "current_guidance_message": None,
        "previous_guidance_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }

def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_guidance_label": None,
        "current_guidance_priority": None,
        "current_guidance_message": None,
        "previous_guidance_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }

def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_digest_status": None,
        "current_digest_priority": None,
        "current_digest_message": None,
        "previous_digest_status": None,
        "previous_digest_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }
