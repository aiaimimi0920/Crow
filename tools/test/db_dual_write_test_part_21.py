from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_hybrid_collection_escalation_priority_mix_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-19", url="https://x/stage-http-hybrid-19"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:40:00",
            "session_id": "prio-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:41:00",
            "session_id": "prio-esc-2",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "pin_browser_mode_temporarily",
            "policy_priority": "warning",
            "top_policy_reason": "challenge_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:42:00",
            "session_id": "prio-esc-3",
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
            "generated_at": "2026-05-19 00:40:30",
            "session_id": "prio-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:41:30",
            "session_id": "prio-rec-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "pin_browser_mode_temporarily",
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
        summary = body["collection_stage"]["hybrid_collection_escalation_priority_mix_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_escalation_priority_counts"] == {"high": 2, "warning": 1}
        assert summary["recent_resolved_priority_counts"] == {"high": 1, "warning": 1}
        assert summary["recent_unresolved_priority_counts"] == {"high": 1}
        assert summary["recent_high_priority_escalation_count"] == 2
        assert summary["recent_high_priority_resolved_count"] == 1
        assert summary["recent_high_priority_unresolved_count"] == 1
        assert summary["top_recent_escalation_priority"] == "high"
        assert summary["top_recent_unresolved_priority"] == "high"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_high_priority_escalation_count"] == 2
        assert overview["hybrid_collection_recent_high_priority_resolved_count"] == 1
        assert overview["hybrid_collection_recent_high_priority_unresolved_count"] == 1
        assert overview["hybrid_collection_top_recent_escalation_priority"] == "high"
        assert overview["hybrid_collection_top_recent_unresolved_priority"] == "high"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_escalation_priority_mix_trend_summary_treats_unknown_priorities_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:40:00",
                        "session_id": "prio-unknown-1",
                        "policy_priority": "unknown",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:41:00",
                        "session_id": "prio-unknown-2",
                        "policy_priority": "high",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:41:30",
                "session_id": "prio-rec-unknown-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_escalation_priority_mix_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_escalation_priority_counts"] == {"high": 1}
    assert summary["recent_resolved_priority_counts"] == {"high": 1}
    assert summary["recent_unresolved_priority_counts"] == {}
    assert summary["recent_high_priority_escalation_count"] == 1
    assert summary["recent_high_priority_resolved_count"] == 1
    assert summary["recent_high_priority_unresolved_count"] == 0
    assert summary["top_recent_escalation_priority"] == "high"
    assert summary["top_recent_resolved_priority"] == "high"
    assert summary["top_recent_unresolved_priority"] is None

def test_hybrid_collection_escalation_priority_mix_trend_summary_treats_unknown_recovery_timestamp_as_missing(
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
                "generated_at": "2026-05-19 00:41:00",
                "session_id": "prio-ts-1",
                "policy_priority": "high",
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
                "session_id": "prio-rec-ts-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_escalation_priority_mix_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_escalation_priority_counts"] == {"high": 1}
    assert summary["recent_resolved_priority_counts"] == {}
    assert summary["recent_unresolved_priority_counts"] == {"high": 1}
    assert summary["recent_high_priority_escalation_count"] == 1
    assert summary["recent_high_priority_resolved_count"] == 0
    assert summary["recent_high_priority_unresolved_count"] == 1
    assert summary["top_recent_escalation_priority"] == "high"
    assert summary["top_recent_resolved_priority"] is None
    assert summary["top_recent_unresolved_priority"] == "high"

def test_http_status_can_surface_re_pin_browser_mode_temporarily_after_failed_release_window(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-7", url="https://x/stage-http-hybrid-7"), event_type="seed")

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
                "generated_at": "2026-05-18 18:30:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "stop_on_fallback",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=13", "page": 13},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:27:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-1",
        },
        {
            "generated_at": "2026-05-18 18:28:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-2",
        },
        {
            "generated_at": "2026-05-18 18:29:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-3",
        },
        {
            "generated_at": "2026-05-18 18:30:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "guard-4",
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
                "generated_at": "2026-05-18 18:25:30",
                "session_id": "guard-switch-1",
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
                "generated_at": "2026-05-18 18:26:00",
                "session_id": "guard-release-1",
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "re_pin_browser_mode_temporarily"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "challenge_detected_after_release"
        assert "re_pin_browser_mode" in policy["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "re_pin_browser_mode_temporarily"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "challenge_detected_after_release"
    finally:
        httpd.shutdown()
        httpd.server_close()
