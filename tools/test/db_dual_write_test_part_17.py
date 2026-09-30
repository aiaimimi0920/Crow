from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_persistent_hybrid_collection_operator_escalation_event_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10d", url="https://x/stage-http-hybrid-10d"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:26:00",
                "session_id": "oe-stability-3",
                "escalation_kind": "repeated_repin_cycle",
                "operator_escalation_source": "recovery_policy",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
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
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "persistent_recovery_policy_source"
        assert summary["stability_severity"] == "high"
        assert summary["current_operator_escalation_source"] == "recovery_policy"
        assert summary["current_escalation_kind"] == "repeated_repin_cycle"
        assert summary["previous_operator_escalation_source"] is None
        assert summary["recent_source_change_count"] == 0
        assert summary["last_source_change_at"] is None
        assert summary["operator_readable_explanation"] == "Operator escalation source remains recovery_policy with no recent source changes."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_operator_escalation_source_stability_status"] == "persistent_recovery_policy_source"
        assert overview["hybrid_collection_operator_escalation_source_stability_severity"] == "high"
        assert overview["hybrid_collection_operator_escalation_source_stability_explanation"] == "Operator escalation source remains recovery_policy with no recent source changes."
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_operator_escalation_recovery_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-11", url="https://x/stage-http-hybrid-11"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-19 00:01:00",
            "session_id": "or-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:02:00",
            "session_id": "or-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "allow_hybrid_retrial",
            "effective_mode": "hybrid",
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
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_recovery_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_recovery_count"] == 2
        assert summary["recent_transition_kind_counts"]["escalation_cleared"] == 2
        assert summary["recent_to_policy_status_counts"]["steady_hybrid"] == 1
        assert summary["recent_to_policy_status_counts"]["allow_hybrid_retrial"] == 1
        assert summary["top_transition_kind"] == "escalation_cleared"
        assert summary["last_to_policy_status"] == "allow_hybrid_retrial"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 2
        assert overview["hybrid_collection_last_operator_escalation_recovery_policy_status"] == "allow_hybrid_retrial"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_escalation_recovery_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:01:00",
                        "session_id": "or-unknown-1",
                        "transition_kind": "escalation_cleared",
                        "to_policy_status": "steady_hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "transition_kind": "unknown",
                        "to_policy_status": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_recovery_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_recovery_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"escalation_cleared": 1}
    assert summary["recent_to_policy_status_counts"] == {"steady_hybrid": 1}
    assert summary["top_transition_kind"] == "escalation_cleared"
    assert summary["top_to_policy_status"] == "steady_hybrid"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_to_policy_status"] is None

def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "unknown",
            "top_policy_status": "unknown",
        },
        {
            "available": True,
            "last_event_at": "2026-05-18 18:41:00",
            "last_to_policy_status": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["window_status"] == "closed"
    assert summary["window_open"] is False
    assert summary["last_escalation_at"] is None
    assert summary["last_escalation_policy_status"] is None
    assert summary["last_recovery_at"] == "2026-05-18 18:41:00"
    assert summary["last_recovery_to_policy_status"] is None
    assert summary["current_window_duration_seconds"] is None
    assert summary["current_window_duration_minutes"] is None

def test_hybrid_collection_unresolved_escalation_window_summary_treats_future_duration_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "2099-01-01 00:00:00",
            "top_policy_status": "escalate_repeated_repin",
        },
        {
            "available": False,
        },
    )

    assert summary["available"] is True
    assert summary["window_status"] == "open"
    assert summary["window_open"] is True
    assert summary["last_escalation_at"] == "2099-01-01 00:00:00"
    assert summary["current_window_duration_seconds"] is None
    assert summary["current_window_duration_minutes"] is None

def test_http_status_can_surface_open_unresolved_escalation_window_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-12", url="https://x/stage-http-hybrid-12"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "uw-esc-1",
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

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:09:00",
                "session_id": "uw-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
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
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["available"] is True
        assert summary["window_status"] == "open"
        assert summary["window_open"] is True
        assert summary["last_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_escalation_at"] == "2026-05-19 00:10:00"
        assert summary["last_recovery_at"] == "2026-05-19 00:09:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_window_open"] is True
        assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "escalate_repeated_repin"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_closed_unresolved_escalation_window_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-13", url="https://x/stage-http-hybrid-13"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "cw-esc-1",
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

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:11:00",
                "session_id": "cw-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
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
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["available"] is True
        assert summary["window_status"] == "closed"
        assert summary["window_open"] is False
        assert summary["last_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
        assert summary["last_recovery_at"] == "2026-05-19 00:11:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
        assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "steady_hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()
