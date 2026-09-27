from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_repository_persists_collection_stage_state_and_search_task_cursors(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="stage-1",
            status="done",
            detail_captured=True,
            source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
            business_area="Lujiazui",
        ),
        event_type="sniff_saved",
        event_payload={
            "source_file": "datas/archive/2026/2026-05-11.json",
            "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        },
    )

    db_item = repo.get_flat_item("stage-1")
    assert db_item["seed_status"] == "stored"
    assert db_item["detail_status"] in {"archived", "enriched"}
    assert db_item["analysis_status"] == "ready"
    assert db_item["analysis_ready"] is True
    assert db_item["analysis_model_version"] == "avm_multidim_v1"
    assert db_item["seed_source_page_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"

    task = {
        "location_code": "310115",
        "category": "50025969",
        "st_param": "2",
        "page": 1,
        "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=310115&st_param=2&auction_start_seg=-1&page=1",
    }
    repo.bootstrap_search_task(task, leased_by="sess-a")
    claimed = repo.claim_search_task("sess-a")
    assert claimed is not None
    assert claimed["location_code"] == "310115"
    assert claimed["page"] == 1

    repo.report_search_task_progress(url=claimed["url"], page_num=1, has_next=True, max_page=3)
    counts = repo.search_task_counts()
    assert counts["search_pending"] == 1

    claimed_next = repo.claim_search_task("sess-b")
    assert claimed_next is not None
    assert claimed_next["page"] == 2
    repo.report_search_task_progress(url=claimed_next["url"], page_num=2, has_next=False)
    counts = repo.search_task_counts()
    assert counts["search_done"] == 1

    with repo.session_factory() as session:
        task_row = session.get(PropertySearchTask, "310115:50025969:2")
        assert task_row is not None
        assert task_row.status == "done"

def test_seed_collection_service_bootstraps_and_claims_db_search_tasks(tmp_path: Path):
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "all_locations.json").write_text(
        json.dumps([{"code": "310115", "name": "浦东新区"}], ensure_ascii=False),
        encoding="utf-8",
    )
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    (jobs_root / "priority.json").write_text(json.dumps(["310115"], ensure_ascii=False), encoding="utf-8")

    service = SeedCollectionService(
        repository=repo,
        jobs_dir=str(jobs_root),
        data_root=str(data_root),
        adapter=TaobaoJudicialAuctionAdapter(),
    )
    result = service.next_task("seed-session-1", paused=False)

    assert result["task"] is not None
    assert result["task"]["location_code"] == "310115"
    assert result["task"]["st_param"] == "2"
    counts = repo.search_task_counts()
    assert counts["search_in_progress"] == 1

def test_http_status_exposes_collection_stage_snapshot_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-1", url="https://x/stage-http-1"), event_type="seed")
    repo.ensure_seed_search_tasks(["310115"], ["50025969"], sort_param="2")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["collection_stage"]["seed_stage"]["stored"] >= 1
        assert body["collection_stage"]["search_tasks"]["search_pending"] == 1
        assert "analysis_blockers" in body["collection_stage"]
        assert "recommended_actions" in body["collection_stage"]
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_recommended_actions_can_reflect_persisted_action_effectiveness(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-2", url="https://x/stage-http-2", status="pending", detail_archive_path=None), event_type="seed")
    repo.ensure_seed_search_tasks(["310115"], ["50025969"], sort_param="2")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_archive_fetch": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recommended = body["collection_stage"]["recommended_actions"]
        assert "fetch_archives" in recommended["deprioritized_actions"]
        assert "detail_archive_fetch_low_yield" in recommended["feedback_hints"]
        assert "next_best_alternative_actions" in recommended
        assert "operator_summary" in recommended
        summary = body["collection_stage"]["action_effectiveness_summary"]
        assert "detail_archive_fetch" in summary["low_yield_actions"]
        assert summary["top_low_yield_action"] == "detail_archive_fetch"
        assert summary["top_low_yield_actions"] == ["detail_archive_fetch"]
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["top_low_yield_actions"] == ["detail_archive_fetch"]
        assert operator_summary["top_alternative_actions"][0] == "prepare_replay"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_recommended_actions_can_surface_manual_review_fallback(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-3", url="https://x/stage-http-3", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_replay_preparation": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recommended = body["collection_stage"]["recommended_actions"]
        assert recommended["manual_review_candidate"] is True
        assert recommended["fallback_routes"]["prepare_replay"] == "manual_review"
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["manual_review_candidates"] == ["manual_review"]
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_recoverability_summary_and_manual_review_reason(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-4", url="https://x/stage-http-4", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["detail_stage"], "missing_fields": ["latitude"]},
                {"item_id": "mr-2", "title": "样本2", "historical_unrecoverable": True, "analysis_missing_fields": ["price_anchor"], "missing_fields": ["is_occupied"]},
            ],
        },
    )
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_optimization_loop_progress_snapshot",
        lambda path=None: {
            "manual_review_candidate_rounds": 2,
            "manual_review_reasons": {"historical_unrecoverable_gap": 2},
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "human_action_counts": {"manual_location_review": 4, "manual_price_anchor_review": 1},
            "retry_policy_counts": {"human_fix_required_before_retry": 2},
            "top_retry_policy": "human_fix_required_before_retry",
            "handoff_lifecycle_counts": {"awaiting_human_receipt_hard_stop": 2},
            "top_handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
            "pending_ready_signal_counts": {"location_artifacts_complete": 2},
            "top_pending_ready_signal": "location_artifacts_complete",
            "invalid_receipt_reason_counts": {"missing_required_fields": 2},
            "top_invalid_receipt_reason": "missing_required_fields",
            "fallback_usage": {"fetch_archives": {"prepare_replay": 3}},
        },
    )
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recoverability = body["collection_stage"]["recoverability_summary"]
        assert recoverability["future_fixable"] == 0
        assert recoverability["historical_unrecoverable"] == 2
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["top_manual_review_reason"] == "historical_unrecoverable_gap"
        assert operator_summary["manual_review_required"] is True
        scheduler_summary = body["collection_stage"]["scheduler_feedback_summary"]
        assert scheduler_summary["manual_review_candidate_rounds"] == 2
        assert scheduler_summary["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
        assert scheduler_summary["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]
        assert scheduler_summary["top_retry_policy"] == "human_fix_required_before_retry"
        assert scheduler_summary["top_handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
        assert scheduler_summary["top_pending_ready_signal"] == "location_artifacts_complete"
        assert scheduler_summary["top_invalid_receipt_reason"] == "missing_required_fields"
        backlog_summary = body["collection_stage"]["manual_review_backlog_summary"]
        assert backlog_summary["candidate_count"] == 2
        assert backlog_summary["sample_item_ids"] == ["mr-1", "mr-2"]
        assert backlog_summary["top_human_actions"][0] == "manual_location_review"
        assert "full_address" in backlog_summary["top_human_action_instructions"][0]
        assert backlog_summary["human_action_queues"]["manual_location_review"]["count"] == 2
        assert backlog_summary["human_action_queues"]["manual_location_review"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
        assert backlog_summary["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
        assert backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
        assert "重新打开" in backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
        assert "latitude/longitude" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
        assert "coordinate_backfill" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
        assert "坐标" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
        assert "location blocker" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
        assert "核对结论" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
        assert backlog_summary["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["manual_review_required"] is True
        assert overview["top_manual_review_reason"] == "historical_unrecoverable_gap"
        assert overview["top_human_actions"][0] == "manual_location_review"
        assert "full_address" in overview["top_human_action_instructions"][0]
        assert overview["handoff_mode"] == "manual_required_hard_stop"
        assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
        assert overview["auto_retry_policy"]["policy"] == "human_fix_required_before_retry"
        assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
        assert overview["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
        assert overview["top_human_action_queue"]["priority_label"] == "high"
        assert overview["top_human_action_queue"]["suggested_handoff_priority"] == "P0"
        assert "full_address" in overview["top_human_action_queue"]["queue_level_checklist"][0]
        assert "重新打开" in overview["top_human_action_queue"]["suggested_handoff_priority_reason"]
        assert "latitude/longitude" in overview["top_human_action_queue"]["queue_level_completion_criteria"][0]
        assert "coordinate_backfill" in overview["top_human_action_queue"]["reentry_validation_checklist"][0]
        assert "full_address" in overview["top_human_action_queue"]["handoff_artifact_fields"]
        assert "坐标" in overview["top_human_action_queue"]["required_human_evidence"][0]
        assert "location blocker" in overview["top_human_action_queue"]["reentry_blockers_if_incomplete"][0]
        assert "核对结论" in overview["top_human_action_queue"]["required_human_resolution_notes"][0]
        assert overview["top_human_action_queue"]["reentry_ready_signal"] == "location_artifacts_complete"
        assert "full_address" in overview["top_human_action_queue"]["handoff_completion_payload"]["required_fields"]
        assert body["collection_stage"]["scheduler_feedback_summary"]["top_handoff_mode"] == "manual_required_hard_stop"
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_can_surface_manual_review_receipt_ready_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-5", url="https://x/stage-http-5", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        importlib.import_module("src.collection_stage_status"),
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(importlib.import_module("src.collection_stage_status"), "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(importlib.import_module("src.collection_stage_status"), "load_optimization_loop_progress_snapshot", lambda path=None: {})
    monkeypatch.setattr(
        importlib.import_module("src.manual_review_status"),
        "load_manual_review_receipt_snapshot",
        lambda path=None, *, repository=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
    )
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
        assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
        assert body["collection_stage"]["recommended_actions"]["run_coordinate_backfill"] is True
        reentry_summary = body["collection_stage"]["manual_review_reentry_application_summary"]
        assert reentry_summary["reentry_applied"] is False
        overview = body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
        assert overview["should_resume_automation"] is True
        assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
    finally:
        httpd.shutdown()
        httpd.server_close()
