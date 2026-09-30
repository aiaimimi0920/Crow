from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_resolution_overview_treats_overfull_rate_as_clamped():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": 2,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 1.5,
        }
    )

    assert overview["hybrid_collection_recent_escalation_resolved_count"] == 2
    assert overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert overview["hybrid_collection_recent_escalation_resolution_rate"] == 1.0

def test_http_status_can_surface_shifted_hybrid_collection_operator_final_guidance_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16g", url="https://x/stage-http-hybrid-16g"), event_type="seed")

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
            "session_id": "final-guidance-stability-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "final-guidance-stability-2",
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
        summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "guidance_recently_shifted"
        assert summary["stability_severity"] == "warning"
        assert summary["current_guidance_label"] == "Transitioning intervention"
        assert summary["current_guidance_message"] == transitioning_message
        assert summary["previous_guidance_message"] == stable_message
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Final guidance recently shifted from Stable ready state to Transitioning intervention."
        digest = body["collection_stage"]["hybrid_collection_operator_digest_summary"]
        assert digest["available"] is True
        assert digest["digest_status"] == "attention_required"
        assert digest["digest_priority"] == "warning"
        assert digest["final_guidance_message"] == transitioning_message
        assert digest["intervention_status"] == "monitor"
        assert digest["intervention_stability_status"] == "transitioning"
        assert digest["final_guidance_stability_status"] == "guidance_recently_shifted"
        assert digest["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_final_guidance_stability_status"] == "guidance_recently_shifted"
        assert overview["hybrid_collection_final_guidance_stability_severity"] == "warning"
        assert overview["hybrid_collection_final_guidance_stability_explanation"] == "Final guidance recently shifted from Stable ready state to Transitioning intervention."
        assert overview["hybrid_collection_operator_digest_status"] == "attention_required"
        assert overview["hybrid_collection_operator_digest_priority"] == "warning"
        assert overview["hybrid_collection_operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_stable_hybrid_collection_operator_final_guidance_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16h", url="https://x/stage-http-hybrid-16h"), event_type="seed")

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
                "session_id": "final-guidance-stability-3",
                "operator_final_guidance_label": "Stable ready state",
                "operator_final_guidance_priority": "info",
                "operator_final_guidance_message": stable_message,
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
        summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_guidance"
        assert summary["stability_severity"] == "info"
        assert summary["current_guidance_label"] == "Stable ready state"
        assert summary["current_guidance_message"] == stable_message
        assert summary["previous_guidance_message"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Final guidance remains stable with no recent message changes."
        digest = body["collection_stage"]["hybrid_collection_operator_digest_summary"]
        assert digest["available"] is True
        assert digest["digest_status"] == "ready"
        assert digest["digest_priority"] == "info"
        assert digest["final_guidance_message"] == stable_message
        assert digest["intervention_status"] == "ready"
        assert digest["intervention_stability_status"] == "stable_ready"
        assert digest["final_guidance_stability_status"] == "stable_guidance"
        assert digest["operator_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_final_guidance_stability_status"] == "stable_guidance"
        assert overview["hybrid_collection_final_guidance_stability_severity"] == "info"
        assert overview["hybrid_collection_final_guidance_stability_explanation"] == "Final guidance remains stable with no recent message changes."
        assert overview["hybrid_collection_operator_digest_status"] == "ready"
        assert overview["hybrid_collection_operator_digest_priority"] == "info"
        assert overview["hybrid_collection_operator_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_operator_digest_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16i", url="https://x/stage-http-hybrid-16i"), event_type="seed")

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
            "session_id": "digest-trend-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "digest-trend-2",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "digest-trend-3",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
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
        trend_summary = body["collection_stage"]["hybrid_collection_operator_digest_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_digest_entry_count"] == 3
        assert trend_summary["recent_digest_message_counts"] == {
            stable_message: 1,
            transitioning_message: 2,
        }
        assert trend_summary["recent_distinct_digest_message_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_digest_message"] == transitioning_message
        assert trend_summary["current_digest_status"] == "attention_required"
        assert trend_summary["current_digest_priority"] == "warning"
        assert trend_summary["current_digest_message"] == transitioning_message
        assert trend_summary["previous_distinct_digest_status"] == "ready"
        assert trend_summary["previous_distinct_digest_message"] == stable_message
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_digest_status"] == "attention_required"
        assert overview["hybrid_collection_current_digest_priority"] == "warning"
        assert overview["hybrid_collection_current_digest_message"] == transitioning_message
        assert overview["hybrid_collection_previous_digest_message"] == stable_message
        assert overview["hybrid_collection_digest_change_count"] == 1
        assert overview["hybrid_collection_digest_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_digest_trend_summary_treats_unknown_messages_as_missing(
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
            "session_id": "digest-unknown-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "digest-unknown-2",
            "operator_digest_status": "unknown",
            "operator_digest_priority": "unknown",
            "operator_digest_message": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_digest_entry_count"] == 1
    assert trend_summary["recent_digest_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_digest_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_digest_message"] == stable_message
    assert trend_summary["current_digest_status"] == "ready"
    assert trend_summary["current_digest_priority"] == "info"
    assert trend_summary["current_digest_message"] == stable_message
    assert trend_summary["previous_distinct_digest_status"] is None
    assert trend_summary["previous_distinct_digest_message"] is None
    assert trend_summary["last_change_at"] is None

def test_hybrid_collection_operator_digest_trend_summary_treats_unknown_status_and_priority_as_missing(
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
                        "session_id": "digest-unknown-meta-1",
                        "operator_digest_status": "unknown",
                        "operator_digest_priority": "unknown",
                        "operator_digest_message": stable_message,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "digest-unknown-meta-2",
                        "operator_digest_status": "unknown",
                        "operator_digest_priority": "unknown",
                        "operator_digest_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_digest_entry_count"] == 1
    assert trend_summary["recent_digest_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_digest_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_digest_message"] == stable_message
    assert trend_summary["current_digest_status"] is None
    assert trend_summary["current_digest_priority"] is None
    assert trend_summary["current_digest_message"] == stable_message
    assert trend_summary["previous_distinct_digest_status"] is None
    assert trend_summary["previous_distinct_digest_message"] is None
    assert trend_summary["last_change_at"] is None

def test_http_status_can_surface_shifted_hybrid_collection_operator_digest_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16j", url="https://x/stage-http-hybrid-16j"), event_type="seed")

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
            "session_id": "digest-stability-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "digest-stability-2",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
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
        summary = body["collection_stage"]["hybrid_collection_operator_digest_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "digest_recently_shifted"
        assert summary["stability_severity"] == "warning"
        assert summary["current_digest_status"] == "attention_required"
        assert summary["current_digest_priority"] == "warning"
        assert summary["current_digest_message"] == transitioning_message
        assert summary["previous_digest_message"] == stable_message
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Operator digest recently shifted from ready to attention_required."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_digest_stability_status"] == "digest_recently_shifted"
        assert overview["hybrid_collection_digest_stability_severity"] == "warning"
        assert overview["hybrid_collection_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    finally:
        httpd.shutdown()
        httpd.server_close()
