from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_escalation_resolution_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-14", url="https://x/stage-http-hybrid-14"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:20:00",
            "session_id": "trend-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:21:00",
            "session_id": "trend-esc-2",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:22:00",
            "session_id": "trend-esc-3",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
    ]
    escalation_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in escalation_events) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_events = [
        {
            "generated_at": "2026-05-19 00:20:30",
            "session_id": "trend-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:21:30",
            "session_id": "trend-rec-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "allow_hybrid_retrial",
            "effective_mode": "hybrid",
        },
    ]
    recovery_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in recovery_events) + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_escalation_resolution_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_escalation_count"] == 3
        assert summary["recent_recovery_count"] == 2
        assert summary["recent_resolved_count"] == 2
        assert summary["recent_unresolved_count"] == 1
        assert summary["recent_resolution_rate"] == 2 / 3
        assert summary["window_open"] is True
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_escalation_resolved_count"] == 2
        assert overview["hybrid_collection_recent_escalation_unresolved_count"] == 1
        assert overview["hybrid_collection_recent_escalation_resolution_rate"] == 2 / 3
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_recovery_latency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-15", url="https://x/stage-http-hybrid-15"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:30:00",
            "session_id": "lat-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        }
    ]
    escalation_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in escalation_events) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_events = [
        {
            "generated_at": "2026-05-19 00:31:30",
            "session_id": "lat-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        }
    ]
    recovery_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in recovery_events) + "\n",
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
        summary = body["collection_stage"]["hybrid_collection_recovery_latency_summary"]
        assert summary["available"] is True
        assert summary["last_recovery_at"] == "2026-05-19 00:31:30"
        assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
        assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
        assert summary["matched_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_latency_seconds"] == 90
        assert summary["last_recovery_latency_minutes"] == 1.5
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_last_recovery_latency_seconds"] == 90
        assert overview["hybrid_collection_last_recovery_latency_minutes"] == 1.5
        assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] == "steady_hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_recovery_latency_summary_treats_unknown_policy_status_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:30:00",
                "session_id": "lat-unknown-esc-1",
                "policy_status": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:31:30",
                "session_id": "lat-unknown-rec-1",
                "from_policy_status": "unknown",
                "to_policy_status": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["last_recovery_at"] == "2026-05-19 00:31:30"
    assert summary["last_recovery_from_policy_status"] is None
    assert summary["last_recovery_to_policy_status"] is None
    assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
    assert summary["matched_escalation_policy_status"] is None
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5

def test_hybrid_collection_recovery_latency_summary_treats_unknown_recovery_timestamp_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:30:00",
                "session_id": "lat-ts-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "session_id": "lat-ts-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is False
    assert summary["last_recovery_at"] is None
    assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
    assert summary["matched_escalation_at"] is None
    assert summary["matched_escalation_policy_status"] is None
    assert summary["last_recovery_latency_seconds"] is None
    assert summary["last_recovery_latency_minutes"] is None

def test_hybrid_collection_recovery_latency_summary_treats_whitespace_escalation_timestamp_as_normalized(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": " 2026-05-19 00:30:00 ",
                "session_id": "lat-ws-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:31:30",
                "session_id": "lat-ws-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5

def test_hybrid_collection_recovery_latency_summary_treats_negative_latency_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-19 00:30:00",
                "session_id": "lat-neg-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-2-19 00:31:30",
                "session_id": "lat-neg-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["last_recovery_at"] == "2026-2-19 00:31:30"
    assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
    assert summary["matched_escalation_at"] == "2026-10-19 00:30:00"
    assert summary["matched_escalation_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_latency_seconds"] is None
    assert summary["last_recovery_latency_minutes"] is None
