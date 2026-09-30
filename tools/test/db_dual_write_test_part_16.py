from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_hybrid_collection_operator_escalation_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10", url="https://x/stage-http-hybrid-10"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-2",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
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
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_event_count"] == 2
        assert summary["recent_escalation_kind_counts"]["repeated_repin_cycle"] == 2
        assert summary["recent_policy_status_counts"]["escalate_repeated_repin"] == 2
        assert summary["recent_operator_escalation_source_counts"]["recovery_policy"] == 2
        assert summary["top_escalation_kind"] == "repeated_repin_cycle"
        assert summary["top_operator_escalation_source"] == "recovery_policy"
        assert summary["top_policy_status"] == "escalate_repeated_repin"
        assert summary["last_event_session_id"] == "oe-2"
        assert summary["last_operator_escalation_source"] == "recovery_policy"
        assert summary["last_operator_escalation_audit_message"] == "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_operator_escalation_count"] == 2
        assert overview["hybrid_collection_top_operator_escalation_kind"] == "repeated_repin_cycle"
        assert overview["hybrid_collection_top_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_top_operator_escalation_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_last_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_last_operator_escalation_audit_message"] == "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_escalation_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:23:00",
                        "session_id": "oe-unknown-1",
                        "escalation_kind": "repeated_repin_cycle",
                        "operator_escalation_source": "recovery_policy",
                        "policy_status": "escalate_repeated_repin",
                        "operator_escalation_audit_message": "audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "escalation_kind": "unknown",
                        "operator_escalation_source": "unknown",
                        "policy_status": "unknown",
                        "operator_escalation_audit_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_event_count"] == 2
    assert summary["recent_escalation_kind_counts"] == {"repeated_repin_cycle": 1}
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_policy_status_counts"] == {"escalate_repeated_repin": 1}
    assert summary["top_escalation_kind"] == "repeated_repin_cycle"
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["top_policy_status"] == "escalate_repeated_repin"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_operator_escalation_source"] is None
    assert summary["last_operator_escalation_audit_message"] is None

def test_http_status_can_surface_hybrid_collection_operator_escalation_event_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10b", url="https://x/stage-http-hybrid-10b"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-trend-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-trend-2",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        {
            "generated_at": "2026-05-18 18:25:00",
            "session_id": "oe-trend-3",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
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
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_event_entry_count"] == 3
        assert summary["recent_operator_escalation_source_counts"] == {
            "recovery_policy": 1,
            "intervention_stability": 2,
        }
        assert summary["recent_distinct_operator_escalation_source_count"] == 2
        assert summary["recent_source_change_count"] == 1
        assert summary["top_operator_escalation_source"] == "intervention_stability"
        assert summary["current_operator_escalation_source"] == "intervention_stability"
        assert summary["current_escalation_kind"] == "intervention_stability"
        assert summary["current_operator_escalation_audit_message"] == "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
        assert summary["previous_distinct_operator_escalation_source"] == "recovery_policy"
        assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_operator_escalation_source"] == "intervention_stability"
        assert overview["hybrid_collection_previous_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_operator_escalation_source_change_count"] == 1
        assert overview["hybrid_collection_operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_operator_escalation_event_trend_summary_treats_unknown_sources_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-trend-unknown-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "operator_escalation_audit_message": "Persistent intervention required [source=recovery_policy]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-trend-unknown-2",
            "escalation_kind": "unknown",
            "operator_escalation_source": "unknown",
            "operator_escalation_audit_message": "unknown",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_event_entry_count"] == 1
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_distinct_operator_escalation_source_count"] == 1
    assert summary["recent_source_change_count"] == 0
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["current_operator_escalation_source"] == "recovery_policy"
    assert summary["current_escalation_kind"] == "repeated_repin_cycle"
    assert summary["current_operator_escalation_audit_message"] == "Persistent intervention required [source=recovery_policy]"
    assert summary["previous_distinct_operator_escalation_source"] is None
    assert summary["last_source_change_at"] is None

def test_hybrid_collection_operator_escalation_event_trend_summary_treats_unknown_kind_and_audit_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:24:00",
                "session_id": "oe-trend-unknown-adjacent-1",
                "operator_escalation_source": "recovery_policy",
                "escalation_kind": "unknown",
                "operator_escalation_audit_message": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_event_entry_count"] == 1
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_distinct_operator_escalation_source_count"] == 1
    assert summary["recent_source_change_count"] == 0
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["current_operator_escalation_source"] == "recovery_policy"
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_distinct_operator_escalation_source"] is None
    assert summary["last_source_change_at"] is None

def test_http_status_can_surface_shifted_hybrid_collection_operator_escalation_event_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10c", url="https://x/stage-http-hybrid-10c"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-stability-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-stability-2",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
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
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "source_recently_shifted"
        assert summary["stability_severity"] == "high"
        assert summary["current_operator_escalation_source"] == "intervention_stability"
        assert summary["current_escalation_kind"] == "intervention_stability"
        assert summary["current_operator_escalation_audit_message"] == "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
        assert summary["previous_operator_escalation_source"] == "recovery_policy"
        assert summary["recent_source_change_count"] == 1
        assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
        assert summary["operator_readable_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_operator_escalation_source_stability_status"] == "source_recently_shifted"
        assert overview["hybrid_collection_operator_escalation_source_stability_severity"] == "high"
        assert overview["hybrid_collection_operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    finally:
        httpd.shutdown()
        httpd.server_close()
