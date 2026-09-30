from tools.test.db_dual_write_test_context import *  # noqa: F401,F403
from tools.test.collection_job_checks import wait_for_http_job


def test_http_status_can_surface_incomplete_manual_review_receipt(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-6", url="https://x/stage-http-6", status="pending", detail_archive_path=None), event_type="seed")

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
                    "payload": {"full_address": "A"},
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_receipt_status"] == "receipt_incomplete"
        assert receipt_summary["invalid_receipt_count"] == 1
        assert receipt_summary["top_invalid_receipt_reason"] == "missing_required_fields"
        assert receipt_summary["top_receipt_fix_actions"] == ["complete_required_fields"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "awaiting_valid_receipt"
        assert overview["should_resume_automation"] is False
        assert overview["top_invalid_receipt_reason"] == "missing_required_fields"
        assert overview["top_receipt_fix_actions"] == ["complete_required_fields"]
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_receipt_control_plane_can_feed_status_summary_end_to_end(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAPAI_CONTROL_PLANE_TOKEN", "isolated-operator")
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-7", url="https://x/stage-http-7", status="pending", detail_archive_path=None), event_type="seed")

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
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.RUNTIME.started_at
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.RUNTIME.started_at = 0
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False
    monkeypatch.setattr(server_module, "run_recent_enrich_maintenance", lambda **kwargs: {"generated_at": "x"})

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts",
            data=json.dumps(
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
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", server_module.CONTROL_TOKEN_HEADER: "isolated-operator"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            write_body = json.loads(resp.read().decode("utf-8"))
        assert write_body["operation"] == "created"
        assert write_body["execution_mode"] == "async"

        job = wait_for_http_job(
            f"http://127.0.0.1:{port}", write_body["status_url"],
            {server_module.CONTROL_TOKEN_HEADER: "isolated-operator"},
        )
        assert job["status"] == "completed", job

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/avm/health") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = status_body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
        assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
        overview = status_body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
        assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
        jobs_summary = status_body["collection_stage"]["manual_review_receipt_jobs_summary"]
        assert jobs_summary["last_job_status"] == "completed"
        assert jobs_summary["last_job_receipt_key"]["action"] == "manual_location_review"
        operations_summary = status_body["collection_stage"]["manual_review_receipt_operations_summary"]
        assert operations_summary["last_operation_type"] == "created"
        assert operations_summary["last_operation_receipt_key"]["action"] == "manual_location_review"
        assert operations_summary["last_async_operation_receipt_key"]["action"] == "manual_location_review"
        storage_summary = status_body["collection_stage"]["manual_review_control_plane_storage"]
        assert storage_summary["state_source"] == "repository"
        assert storage_summary["repository_enabled"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.RUNTIME.started_at = original_start_time

def test_http_receipt_control_plane_prefers_database_backed_state_when_repo_enabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAPAI_CONTROL_PLANE_TOKEN", "isolated-operator")
    repo = _make_repo(tmp_path)

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server_module, "run_recent_enrich_maintenance", lambda **kwargs: {"generated_at": "x"})
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
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.RUNTIME.started_at
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.RUNTIME.started_at = 0
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts",
            data=json.dumps(
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
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", server_module.CONTROL_TOKEN_HEADER: "isolated-operator"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            write_body = json.loads(resp.read().decode("utf-8"))
        assert write_body["operation"] == "created"
        assert write_body["execution_mode"] == "async"

        job = wait_for_http_job(
            f"http://127.0.0.1:{port}", write_body["status_url"],
            {server_module.CONTROL_TOKEN_HEADER: "isolated-operator"},
        )
        assert job["status"] == "completed", job

        avm_root = Path(server_module.DATA_DIR) / "avm"
        receipt_path = avm_root / "manual_review_receipts.json"
        operations_path = avm_root / "manual_review_receipt_operations.jsonl"
        jobs_path = avm_root / "manual_review_receipt_jobs.json"
        assert receipt_path.exists()
        assert operations_path.exists()
        assert jobs_path.exists()

        receipt_backup = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt_backup["receipts"][0]["action"] == "manual_location_review"

        jobs_backup = json.loads(jobs_path.read_text(encoding="utf-8"))
        assert jobs_backup["jobs"] == []
        durable_path = Path(server_module.DATA_DIR) / "runtime" / "collection-jobs" / f"{write_body['job_id']}.json"
        durable_job = json.loads(durable_path.read_text(encoding="utf-8"))
        assert durable_job["job_id"] == write_body["maintenance_job_id"]
        assert durable_job["status"] == "completed"
        assert durable_job["result"]["receipt"]["action"] == "manual_location_review"

        operation_lines = operations_path.read_text(encoding="utf-8").splitlines()
        assert len(operation_lines) == 1
        assert json.loads(operation_lines[0])["operation"] == "created"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts") as resp:
            receipts_body = json.loads(resp.read().decode("utf-8"))
        assert receipts_body["receipt_count"] == 1
        assert receipts_body["receipts"][0]["action"] == "manual_location_review"
        backup_summary = receipts_body["manual_review_control_plane_backup"]
        assert backup_summary["backup_state"] == "in_sync"
        assert backup_summary["source_receipt_count"] == 1
        assert backup_summary["backup_receipt_count"] == 1
        assert backup_summary["all_backup_files_present"] is True

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipt_operations") as resp:
            operations_body = json.loads(resp.read().decode("utf-8"))
        assert operations_body["operation_count"] == 1
        assert operations_body["operations"][0]["operation"] == "created"
        assert operations_body["manual_review_control_plane_backup"]["backup_state"] == "in_sync"
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.RUNTIME.started_at = original_start_time

def test_http_receipt_control_plane_bootstraps_db_from_existing_json_files(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
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
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (avm_root / "manual_review_receipt_operations.jsonl").write_text(
        json.dumps(
            {
                "operation_id": "op-1",
                "operation": "created",
                "action": "manual_location_review",
                "ready_signal": "location_artifacts_complete",
                "status": "ready_for_reentry",
                "payload_fingerprint": "fp-1",
                "execution_mode": "async",
                "requested_at": "2026-05-15 10:00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_root))
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
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.RUNTIME.started_at
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.RUNTIME.started_at = 0
    server_module.RUNTIME.collection.seen_ids = {}
    server_module.RUNTIME.collection.pending_tasks = []
    server_module.RUNTIME.collection.dispatched_tasks = {}
    server_module.RUNTIME.control.paused = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts") as resp:
            receipts_body = json.loads(resp.read().decode("utf-8"))
        assert receipts_body["receipt_count"] == 1
        assert receipts_body["receipts"][0]["action"] == "manual_location_review"
        assert receipts_body["manual_review_control_plane_storage"]["state_source"] == "repository"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipt_operations") as resp:
            operations_body = json.loads(resp.read().decode("utf-8"))
        assert operations_body["operation_count"] == 1
        assert operations_body["manual_review_control_plane_storage"]["state_source"] == "repository"

        assert repo.manual_review_control_plane_counts()["receipt_count"] == 1
        assert repo.manual_review_control_plane_counts()["operation_count"] == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.RUNTIME.started_at = original_start_time
