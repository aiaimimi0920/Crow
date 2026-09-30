from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_status_can_surface_hybrid_collection_runtime_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-1", url="https://x/stage-http-hybrid-1"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "loop_mode": True,
                "submit_enabled": True,
                "session_id": "hybrid-live-ops",
                "decision_counts": {
                    "browserless_success": 3,
                    "browser_fallback_required": 2,
                },
                "reason_counts": {
                    "challenge_detected": 2,
                },
                "termination_reason": "fallback_escalation_threshold_reached",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                "effective_mode_counts": {"hybrid": 1, "browser": 2},
                "guidance_applied_count": 2,
                "guidance_status": "investigate_challenge_spike",
                "guidance_recommended_mode": "browser",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440112&page=7",
                    "page": 7,
                    "location_code": "440112",
                    "category": "50025969",
                },
                "last_probe_summary": {
                    "item_count": 0,
                    "has_script": False,
                    "body_has_login": False,
                    "body_has_captcha": False,
                    "body_has_punish": True,
                    "body_has_challenge": True,
                },
                "last_submit_result": {
                    "batch": {"status": "skipped", "new": 0},
                    "progress": {"status": "skipped"},
                },
                "last_browser_fallback_opened": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
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
        hybrid_summary = body["collection_stage"]["hybrid_collection_runtime_summary"]
        assert hybrid_summary["runner_mode"] == "hybrid"
        assert hybrid_summary["loop_mode"] is True
        assert hybrid_summary["decision_counts"]["browserless_success"] == 3
        assert hybrid_summary["decision_counts"]["browser_fallback_required"] == 2
        assert hybrid_summary["browserless_success_count"] == 3
        assert hybrid_summary["browser_fallback_required_count"] == 2
        assert hybrid_summary["top_fallback_reason"] == "challenge_detected"
        assert hybrid_summary["last_decision"] == "browser_fallback_required"
        assert hybrid_summary["last_reason"] == "challenge_detected"
        assert hybrid_summary["requested_mode"] == "hybrid"
        assert hybrid_summary["last_effective_mode"] == "browser"
        assert hybrid_summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert hybrid_summary["effective_mode_counts"]["browser"] == 2
        assert hybrid_summary["guidance_applied_count"] == 2
        assert hybrid_summary["guidance_status"] == "investigate_challenge_spike"
        assert hybrid_summary["last_task_page"] == 7
        assert hybrid_summary["last_task_location_code"] == "440112"
        assert hybrid_summary["last_probe_body_has_challenge"] is True
        assert hybrid_summary["last_probe_body_has_punish"] is True
        assert hybrid_summary["last_submit_batch_status"] == "skipped"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_last_decision"] == "browser_fallback_required"
        assert overview["hybrid_collection_top_fallback_reason"] == "challenge_detected"
        assert overview["hybrid_collection_last_effective_mode"] == "browser"
        assert overview["hybrid_collection_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_guidance_applied_count"] == 2
        assert overview["hybrid_collection_browserless_success_count"] == 3
        assert overview["hybrid_collection_browser_fallback_required_count"] == 2
        assert overview["hybrid_collection_last_task_page"] == 7
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_runtime_summary_treats_unknown_nested_payloads_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "decision_counts": "unknown",
                "reason_counts": "unknown",
                "effective_mode_counts": "unknown",
                "iterations": "unknown",
                "guidance_applied_count": "unknown",
                "last_task": "unknown",
                "last_probe_summary": "unknown",
                "last_submit_result": "unknown",
                "last_browser_fallback_opened": "unknown",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["decision_counts"] == {}
    assert summary["reason_counts"] == {}
    assert summary["effective_mode_counts"] == {}
    assert summary["iterations"] == 0
    assert summary["guidance_applied_count"] == 0
    assert summary["last_task_url"] is None
    assert summary["last_task_page"] is None
    assert summary["last_probe_item_count"] == 0
    assert summary["last_submit_batch_status"] is None
    assert summary["last_submit_batch_new"] == 0
    assert summary["last_submit_progress_status"] is None
    assert summary["last_browser_fallback_opened"] is False

def test_hybrid_collection_runtime_summary_treats_negative_numeric_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "iterations": -3,
                "guidance_applied_count": -2,
                "last_task": {"page": -7},
                "last_probe_summary": {"item_count": -4},
                "last_submit_result": {"batch": {"new": -5}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["iterations"] == 0
    assert summary["guidance_applied_count"] == 0
    assert summary["last_task_page"] is None
    assert summary["last_probe_item_count"] == 0
    assert summary["last_submit_batch_new"] == 0

def test_hybrid_collection_runtime_summary_treats_unknown_count_keys_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "decision_counts": {"unknown": 4, "browserless_success": 2},
                "reason_counts": {"unknown": 3, "challenge_detected": 1},
                "effective_mode_counts": {"unknown": 5, "hybrid": 2},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["decision_counts"] == {"browserless_success": 2}
    assert summary["reason_counts"] == {"challenge_detected": 1}
    assert summary["effective_mode_counts"] == {"hybrid": 2}
    assert summary["top_fallback_reason"] == "challenge_detected"

def test_hybrid_collection_runtime_summary_treats_unknown_text_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "runner_mode": "unknown",
                "requested_mode": "unknown",
                "effective_mode_source": "unknown",
                "session_id": "unknown",
                "top_fallback_reason": "unknown",
                "termination_reason": "unknown",
                "operator_action_hint": "unknown",
                "guidance_status": "unknown",
                "recovery_policy_status": "unknown",
                "last_decision": "unknown",
                "last_reason": "unknown",
                "last_effective_mode": "unknown",
                "last_task": {
                    "url": "unknown",
                    "location_code": "unknown",
                    "category": "unknown",
                },
                "last_submit_result": {
                    "batch": {"status": "unknown"},
                    "progress": {"status": "unknown"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["generated_at"] is None
    assert summary["runner_mode"] is None
    assert summary["requested_mode"] is None
    assert summary["effective_mode_source"] is None
    assert summary["session_id"] is None
    assert summary["top_fallback_reason"] is None
    assert summary["termination_reason"] is None
    assert summary["operator_action_hint"] is None
    assert summary["guidance_status"] is None
    assert summary["recovery_policy_status"] is None
    assert summary["last_decision"] is None
    assert summary["last_reason"] is None
    assert summary["last_effective_mode"] is None
    assert summary["last_task_url"] is None
    assert summary["last_task_location_code"] is None
    assert summary["last_task_category"] is None
    assert summary["last_submit_batch_status"] is None
    assert summary["last_submit_progress_status"] is None

def test_http_status_can_surface_hybrid_collection_runtime_history_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-2", url="https://x/stage-http-hybrid-2"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "hist-1",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "hist-2",
        },
        {
            "generated_at": "2026-05-18 18:03:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "hist-3",
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
        history_summary = body["collection_stage"]["hybrid_collection_runtime_history_summary"]
        assert history_summary["available"] is True
        assert history_summary["entry_count"] == 3
        assert history_summary["recent_runs"] == 3
        assert history_summary["recent_decision_counts"]["browserless_success"] == 2
        assert history_summary["recent_decision_counts"]["browser_fallback_required"] == 1
        assert history_summary["recent_browserless_success_count"] == 2
        assert history_summary["recent_browser_fallback_required_count"] == 1
        assert history_summary["recent_browserless_success_rate"] == pytest.approx(2 / 3)
        assert history_summary["recent_reason_counts"]["challenge_detected"] == 1
        assert history_summary["recent_top_fallback_reason"] == "challenge_detected"
        assert history_summary["recent_top_termination_reason"] == "max_runs_reached"
        assert history_summary["last_generated_at"] == "2026-05-18 18:03:00"
        assert history_summary["last_session_id"] == "hist-3"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_runs"] == 3
        assert overview["hybrid_collection_recent_browserless_success_count"] == 2
        assert overview["hybrid_collection_recent_browser_fallback_required_count"] == 1
        assert overview["hybrid_collection_recent_browserless_success_rate"] == pytest.approx(2 / 3)
        assert overview["hybrid_collection_recent_top_fallback_reason"] == "challenge_detected"
        assert overview["hybrid_collection_recent_top_termination_reason"] == "max_runs_reached"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_hybrid_collection_runtime_history_summary_treats_unknown_nested_payloads_as_missing(
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
            "session_id": "hist-unknown-1",
            "decision_counts": "unknown",
            "reason_counts": "unknown",
            "termination_reason": "unknown",
        },
        {
            "generated_at": "unknown",
            "session_id": "unknown",
            "decision_counts": {"browserless_success": "unknown"},
            "reason_counts": {"challenge_detected": "unknown"},
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_runs"] == 2
    assert summary["recent_decision_counts"] == {}
    assert summary["recent_reason_counts"] == {}
    assert summary["recent_browserless_success_count"] == 0
    assert summary["recent_browser_fallback_required_count"] == 0
    assert summary["recent_browser_worker_dispatched_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["recent_top_fallback_reason"] is None
    assert summary["recent_top_termination_reason"] == "max_runs_reached"
    assert summary["last_generated_at"] is None
    assert summary["last_session_id"] is None
