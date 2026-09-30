from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_runtime_history_summary_treats_unknown_count_keys_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-key-1",
            "decision_counts": {"unknown": 5, "browserless_success": 2},
            "reason_counts": {"unknown": 4, "challenge_detected": 1},
            "termination_reason": "unknown",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_decision_counts"] == {"browserless_success": 2}
    assert summary["recent_reason_counts"] == {"challenge_detected": 1}
    assert summary["recent_browserless_success_count"] == 2
    assert summary["recent_top_fallback_reason"] == "challenge_detected"
    assert summary["recent_top_termination_reason"] is None

def test_hybrid_collection_runtime_history_summary_treats_whitespace_unknown_termination_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-term-1",
            "termination_reason": " unknown ",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "session_id": "hist-term-2",
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_top_termination_reason"] == "max_runs_reached"

def test_hybrid_collection_runtime_history_summary_treats_negative_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-neg-1",
            "decision_counts": {"browserless_success": -2, "browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": -3, "captcha_detected": 2},
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_decision_counts"] == {"browser_fallback_required": 1}
    assert summary["recent_reason_counts"] == {"captcha_detected": 2}
    assert summary["recent_browserless_success_count"] == 0
    assert summary["recent_browser_fallback_required_count"] == 1
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["recent_top_fallback_reason"] == "captcha_detected"

def test_hybrid_collection_strategy_guidance_treats_unknown_history_available_as_missing():
    server_module = importlib.import_module("src.server")

    guidance = server_module._hybrid_collection_strategy_guidance(
        {},
        {"available": "unknown"},
    )

    assert guidance == {
        "guidance_status": "no_history_available",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_guidance_reason": "history_unavailable",
    }

def test_hybrid_collection_strategy_guidance_treats_unknown_history_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    guidance = server_module._hybrid_collection_strategy_guidance(
        {},
        {
            "available": True,
            "recent_runs": "unknown",
            "recent_browserless_success_rate": "unknown",
            "recent_browser_fallback_required_count": "unknown",
            "recent_top_fallback_reason": "unknown",
            "recent_top_termination_reason": "unknown",
        },
    )

    assert guidance == {
        "guidance_status": "insufficient_history",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_guidance_reason": "insufficient_history",
    }

def test_http_status_can_surface_hybrid_collection_action_hint_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-22", url="https://x/stage-http-hybrid-22"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_worker_dispatched": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "operator_escalation",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "session_id": "hint-trend-1",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "session_id": "hint-trend-2",
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "session_id": "hint-trend-3",
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
        trend_summary = body["collection_stage"]["hybrid_collection_action_hint_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_hint_entry_count"] == 3
        assert trend_summary["recent_action_hint_counts"] == {
            "inspect unresolved high-priority backlog; suggested mode=browser": 1,
            "continue hybrid with budget watch; suggested mode=hybrid": 2,
        }
        assert trend_summary["recent_distinct_action_hint_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert trend_summary["current_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert trend_summary["previous_distinct_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_previous_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_action_hint_change_count"] == 1
        assert overview["hybrid_collection_action_hint_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_action_hint_trend_summary_treats_unknown_hints_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "session_id": "hint-unknown-1",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "operator_action_hint": "unknown",
            "session_id": "hint-unknown-2",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_action_hint_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_hint_entry_count"] == 1
    assert summary["recent_action_hint_counts"] == {
        "inspect unresolved high-priority backlog; suggested mode=browser": 1,
    }
    assert summary["recent_distinct_action_hint_count"] == 1
    assert summary["recent_change_count"] == 0
    assert summary["top_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert summary["current_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert summary["previous_distinct_action_hint"] is None
    assert summary["last_change_at"] is None

def test_hybrid_collection_trend_summaries_treat_unknown_change_timestamps_as_missing(
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
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "trend-ts-1",
                        "operator_action_hint": "keep hybrid; suggested mode=hybrid",
                        "operator_final_guidance_label": "Stable ready state",
                        "operator_final_guidance_priority": "info",
                        "operator_final_guidance_message": "Stable ready state: keep hybrid and continue monitoring.",
                        "operator_digest_status": "ready",
                        "operator_digest_priority": "info",
                        "operator_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
                        "intervention_status": "ready",
                        "intervention_priority": "info",
                        "intervention_reason": "browserless_fast_path_stable",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "trend-ts-2",
                        "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                        "operator_final_guidance_label": "Escalating intervention",
                        "operator_final_guidance_priority": "high",
                        "operator_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                        "operator_digest_status": "intervention_required",
                        "operator_digest_priority": "high",
                        "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
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

    escalation_events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "trend-ts-esc-1",
                        "operator_escalation_source": "recovery_policy",
                        "escalation_kind": "repeated_repin_cycle",
                        "operator_escalation_audit_message": "Persistent intervention required [source=recovery_policy]",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "trend-ts-esc-2",
                        "operator_escalation_source": "intervention_stability",
                        "escalation_kind": "intervention_stability",
                        "operator_escalation_audit_message": "Escalating intervention [source=intervention_stability]",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    action_hint_summary = server_module._hybrid_collection_action_hint_trend_summary(data_root)
    final_guidance_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)
    digest_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)
    intervention_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)
    escalation_summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert action_hint_summary["recent_change_count"] == 1
    assert action_hint_summary["last_change_at"] is None
    assert final_guidance_summary["recent_change_count"] == 1
    assert final_guidance_summary["last_change_at"] is None
    assert digest_summary["recent_change_count"] == 1
    assert digest_summary["last_change_at"] is None
    assert intervention_summary["recent_change_count"] == 1
    assert intervention_summary["last_change_at"] is None
    assert escalation_summary["recent_source_change_count"] == 1
    assert escalation_summary["last_source_change_at"] is None
