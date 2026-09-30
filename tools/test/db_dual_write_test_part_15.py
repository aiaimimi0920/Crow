from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_operator_intervention_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_intervention_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "intervention-unknown-1",
                        "transition_kind": "status_changed",
                        "to_intervention_status": "monitor",
                        "to_intervention_priority": "warning",
                        "to_final_guidance_label": "Transitioning intervention",
                        "to_final_guidance_priority": "warning",
                        "to_final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "transition_kind": "unknown",
                        "to_intervention_status": "unknown",
                        "to_intervention_priority": "unknown",
                        "to_final_guidance_label": "unknown",
                        "to_final_guidance_priority": "unknown",
                        "to_final_guidance_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_intervention_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_event_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"status_changed": 1}
    assert summary["recent_to_intervention_status_counts"] == {"monitor": 1}
    assert summary["top_transition_kind"] == "status_changed"
    assert summary["top_to_intervention_status"] == "monitor"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_transition_kind"] is None
    assert summary["last_to_intervention_status"] is None
    assert summary["last_to_intervention_priority"] is None
    assert summary["last_to_final_guidance_label"] is None
    assert summary["last_to_final_guidance_priority"] is None
    assert summary["last_to_final_guidance_message"] is None

def test_http_status_can_surface_hybrid_collection_mode_switch_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-4", url="https://x/stage-http-hybrid-4"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "s-1",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "prefer_browser_fallback",
            "top_guidance_reason": "challenge_detected",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "s-2",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "investigate_challenge_spike",
            "top_guidance_reason": "challenge_detected",
        },
    ]
    switch_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in switch_entries) + "\n",
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
        switch_summary = body["collection_stage"]["hybrid_collection_mode_switch_event_summary"]
        assert switch_summary["available"] is True
        assert switch_summary["entry_count"] == 2
        assert switch_summary["recent_switch_count"] == 2
        assert switch_summary["recent_target_mode_counts"]["browser"] == 2
        assert switch_summary["top_target_mode"] == "browser"
        assert switch_summary["recent_guidance_status_counts"]["prefer_browser_fallback"] == 1
        assert switch_summary["recent_guidance_status_counts"]["investigate_challenge_spike"] == 1
        assert switch_summary["top_guidance_reason"] == "challenge_detected"
        assert switch_summary["last_switch_at"] == "2026-05-18 18:12:00"
        assert switch_summary["last_switch_session_id"] == "s-2"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_mode_switch_count"] == 2
        assert overview["hybrid_collection_top_switch_target_mode"] == "browser"
        assert overview["hybrid_collection_top_switch_guidance_reason"] == "challenge_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_mode_switch_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "switch-unknown-1",
                        "effective_mode": "browser",
                        "guidance_status": "prefer_browser_fallback",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "effective_mode": "unknown",
                        "guidance_status": "unknown",
                        "top_guidance_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_mode_switch_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_switch_count"] == 2
    assert summary["recent_target_mode_counts"] == {"browser": 1}
    assert summary["recent_guidance_status_counts"] == {"prefer_browser_fallback": 1}
    assert summary["top_target_mode"] == "browser"
    assert summary["top_guidance_reason"] == "challenge_detected"
    assert summary["last_switch_at"] is None
    assert summary["last_switch_session_id"] is None

def test_http_status_can_surface_hybrid_collection_recovery_policy(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-5", url="https://x/stage-http-hybrid-5"), event_type="seed")

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
                "generated_at": "2026-05-18 18:20:00",
                "runner_mode": "browser",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "guidance_applied": True,
                "guidance_status": "prefer_browser_fallback",
                "guidance_recommended_mode": "browser",
                "top_guidance_reason": "challenge_detected",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 1,
                "last_effective_mode": "browser",
                "termination_reason": "max_runs_reached",
                "last_decision": "browser_worker_dispatched",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=12", "page": 12},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:17:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "rp-1",
        },
        {
            "generated_at": "2026-05-18 18:18:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "rp-2",
        },
        {
            "generated_at": "2026-05-18 18:19:00",
            "runner_mode": "browser",
            "decision_counts": {"browser_worker_dispatched": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "rp-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_entries = [
        {
            "generated_at": "2026-05-18 18:17:30",
            "session_id": "sw-1",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "prefer_browser_fallback",
            "top_guidance_reason": "challenge_detected",
        },
        {
            "generated_at": "2026-05-18 18:18:30",
            "session_id": "sw-2",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "investigate_challenge_spike",
            "top_guidance_reason": "challenge_detected",
        },
    ]
    switch_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in switch_entries) + "\n",
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
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "pin_browser_mode_temporarily"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "challenge_detected"
        assert policy["recent_mode_switch_count"] == 2
        assert policy["top_switch_target_mode"] == "browser"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "pin_browser_mode_temporarily"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "challenge_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_hybrid_collection_recovery_policy_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-6", url="https://x/stage-http-hybrid-6"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:21:00",
            "session_id": "rp-ev-1",
            "transition_kind": "pin_activated",
            "from_policy_status": "steady_hybrid",
            "to_policy_status": "pin_browser_mode_temporarily",
            "from_mode_pin_active": False,
            "to_mode_pin_active": True,
            "to_effective_recommended_mode": "browser",
        },
        {
            "generated_at": "2026-05-18 18:22:00",
            "session_id": "rp-ev-2",
            "transition_kind": "pin_released",
            "from_policy_status": "pin_browser_mode_temporarily",
            "to_policy_status": "allow_hybrid_retrial",
            "from_mode_pin_active": True,
            "to_mode_pin_active": False,
            "to_effective_recommended_mode": "hybrid",
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
        summary = body["collection_stage"]["hybrid_collection_recovery_policy_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_transition_count"] == 2
        assert summary["recent_transition_kind_counts"]["pin_activated"] == 1
        assert summary["recent_transition_kind_counts"]["pin_released"] == 1
        assert summary["recent_to_policy_status_counts"]["pin_browser_mode_temporarily"] == 1
        assert summary["recent_to_policy_status_counts"]["allow_hybrid_retrial"] == 1
        assert summary["last_transition_kind"] == "pin_released"
        assert summary["last_to_policy_status"] == "allow_hybrid_retrial"
        assert summary["last_transition_session_id"] == "rp-ev-2"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_recovery_policy_transition_count"] == 2
        assert overview["hybrid_collection_last_recovery_transition_kind"] == "pin_released"
        assert overview["hybrid_collection_last_recovery_to_policy_status"] == "allow_hybrid_retrial"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_recovery_policy_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:21:00",
                        "session_id": "rp-unknown-1",
                        "transition_kind": "pin_activated",
                        "to_policy_status": "pin_browser_mode_temporarily",
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

    summary = server_module._hybrid_collection_recovery_policy_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_transition_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"pin_activated": 1}
    assert summary["recent_to_policy_status_counts"] == {"pin_browser_mode_temporarily": 1}
    assert summary["top_transition_kind"] == "pin_activated"
    assert summary["top_to_policy_status"] == "pin_browser_mode_temporarily"
    assert summary["last_transition_at"] is None
    assert summary["last_transition_session_id"] is None
    assert summary["last_transition_kind"] is None
    assert summary["last_to_policy_status"] is None
