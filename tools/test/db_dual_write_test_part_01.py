from src.collection.publication import publish_record
from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_build_collection_record_normalizes_flat_json_into_template_record():
    record = build_collection_record(_make_flat_item())

    assert record["source"]["item_id"] == "9001"
    assert record["source"]["source_item_id"] == "9001"
    assert record["source"]["source_platform"] == "taobao_sf"
    assert record["source"]["source_title"] == "Test Listing"

    assert record["auction"]["auction_date"] == "2026-05-11 10:00:00"
    assert record["auction"]["transaction_price"] == pytest.approx(1_000_000.0)
    assert record["auction"]["starting_price"] == pytest.approx(800_000.0)
    assert record["auction"]["deposit"] == pytest.approx(50_000.0)
    assert record["auction"]["apply_count"] == 4
    assert record["auction"]["bid_count"] == 7
    assert record["auction"]["bidder_count"] == 3

    assert record["location"]["full_address"] == "Shanghai Pudong Test Rd 99"
    assert record["location"]["community_name"] == "Test Garden"
    assert record["location"]["latitude"] == pytest.approx(31.23)
    assert record["location"]["longitude"] == pytest.approx(121.56)

    assert record["property"]["area_sqm"] == pytest.approx(89.5)
    assert record["property"]["gross_area_sqm"] == pytest.approx(179.0)
    assert record["property"]["ownership_share_ratio"] == pytest.approx(0.5)
    assert record["property"]["has_elevator"] is False
    assert record["property"]["build_year"] == 2001

    assert record["legal_context"]["appraisal_report_urls"] == [
        "https://example.com/a.pdf",
        "https://example.com/b.pdf",
    ]
    assert record["legal_context"]["announcement_attachment_urls"] == ["https://example.com/c.pdf"]

    assert record["risk_flags"]["is_occupied"] is True
    assert record["risk_flags"]["is_fractional_share"] is True
    assert record["risk_flags"]["property_fee_owed"] is True
    assert record["audit"]["evidence_source"] == "llm"
    assert record["audit"]["evidence_span"] == "['line1', 'line2']"

def test_repository_upsert_flat_item_updates_existing_listing_without_duplicate_rows(tmp_path: Path):
    repo = _make_repo(tmp_path)

    repo.upsert_flat_item(_make_flat_item(), event_type="sniff_saved", event_payload={"seq": 1, "source_file": "datas/archive/2026/2026-05-11.json"})
    repo.upsert_flat_item(
        _make_flat_item(
            title="Updated Listing",
            currentPrice="1120000",
            bidCount="9",
            lat="31.231",
            announcement_attachment_urls="https://example.com/updated.pdf",
            avm_risk_features={"is_occupied": "no", "build_year": "2003"},
        ),
        event_type="detail_saved",
        event_payload={"seq": 2},
    )

    assert repo.count_listings() == 1

    with repo.session_factory() as session:
        listing = session.get(PropertyListing, "9001")
        risk_row = session.get(PropertyRiskFlags, "9001")
        legal_row = session.get(PropertyLegalContext, "9001")
        audit_row = session.get(PropertyAudit, "9001")
        events = session.scalars(
            select(PropertyIngestEvent)
            .where(PropertyIngestEvent.item_id == "9001")
            .order_by(PropertyIngestEvent.id.asc())
        ).all()

        assert listing is not None
        assert listing.source_title == "Updated Listing"
        assert float(listing.transaction_price) == pytest.approx(1_120_000.0)
        assert listing.bid_count == 9
        assert listing.latitude == pytest.approx(31.231)
        assert listing.build_year == 2003
        assert listing.is_deleted is False
        assert listing.deleted_reason is None

        assert risk_row is not None
        assert risk_row.is_occupied is False

        assert legal_row is not None
        assert legal_row.announcement_attachment_urls == ["https://example.com/updated.pdf"]

        assert audit_row is not None
        assert audit_row.detail_archive_path == "html_archive/2026/2026-05-11/item-9001.html"
        assert audit_row.source_json_path == "datas/archive/2026/2026-05-11.json"
        assert audit_row.evidence_source == "llm"

        assert session.scalar(select(func.count()).select_from(PropertyListing)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyRiskFlags)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyLegalContext)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyAudit)) == 1
        event_types = [event.event_type for event in events]
        assert "sniff_saved" in event_types
        assert "detail_saved" in event_types
        assert "seed_stage_transition" in event_types
        assert "detail_stage_transition" in event_types
        assert "analysis_stage_transition" in event_types
        assert "analysis_ready_transition" in event_types
        assert events[-1].event_payload == {"seq": 2}

    flat_item = repo.get_flat_item("9001")
    assert flat_item is not None
    assert flat_item["json_file"] == "datas/archive/2026/2026-05-11.json"
    assert flat_item["__file_path"] == "datas/archive/2026/2026-05-11.json"

def test_dual_write_keeps_json_snapshot_and_db_row_on_single_item_upsert(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)

    json_path = tmp_path / "2026-05-11.json"

    first_item = _make_flat_item()
    sync_collection_record(first_item)
    publish_record(str(json_path), "9001", first_item, "sniff_saved", {"seq": 1},
                   persist=server_module.persist_item_to_db, publish=server_module.update_item_in_json)

    second_item = _make_flat_item(
        title="Dual Write Updated",
        currentPrice="1135000",
        bidCount="10",
        source_platform="manual_test",
        avm_risk_features={"is_occupied": "no"},
    )
    sync_collection_record(second_item)
    publish_record(str(json_path), "9001", second_item, "detail_saved", {"seq": 2},
                   persist=server_module.persist_item_to_db, publish=server_module.update_item_in_json)

    stored_items = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(stored_items) == 1
    assert stored_items[0]["id"] == "9001"
    assert stored_items[0]["source"]["source_title"] == "Dual Write Updated"
    assert stored_items[0]["source"]["source_platform"] == "manual_test"
    assert stored_items[0]["auction"]["transaction_price"] == pytest.approx(1_135_000.0)
    assert stored_items[0]["auction"]["bid_count"] == 10

    with repo.session_factory() as session:
        listing = session.get(PropertyListing, "9001")
        events = session.scalars(
            select(PropertyIngestEvent)
            .where(PropertyIngestEvent.item_id == "9001")
            .order_by(PropertyIngestEvent.id.asc())
        ).all()

        assert listing is not None
        assert listing.source_title == "Dual Write Updated"
        assert listing.source_platform == "manual_test"
        assert float(listing.transaction_price) == pytest.approx(1_135_000.0)
        assert listing.bid_count == 10
        assert session.scalar(select(func.count()).select_from(PropertyListing)) == 1
        business_event_payloads = [event.event_payload for event in events if event.event_type in {"sniff_saved", "detail_saved"}]
        assert business_event_payloads == [{"seq": 1}, {"seq": 2}]

def test_sync_collection_record_applies_standardized_community_fields():
    item = {
        "id": "9201",
        "城市": "北京市",
        "区": "朝阳区",
        "所属小区": "远洋天地小区",
        "地点": "北京市朝阳区八里庄远洋天地小区7号楼",
    }

    sync_collection_record(item)

    assert item["所属小区"] == "远洋天地小区"
    assert item["community_name"] == "远洋天地小区"
    assert item["location"]["community_name"] == "远洋天地小区"
    assert item["community_name_source"] == "collector"
    assert item["community_name_confidence"] == pytest.approx(0.72)
    assert item["community_stable_key"] == "collector::北京市::朝阳区::远洋天地"

def test_build_collection_record_keeps_standardized_community_audit_fields():
    item = {
        "id": "9202",
        "城市": "北京市",
        "区": "朝阳区",
        "所属小区": "远洋天地",
        "community_name_source": "beike_alias",
        "community_name_confidence": 0.98,
        "community_stable_key": "beike::北京市::朝阳区::远洋天地",
        "community_raw_name": "远洋天地小区",
        "beike_community_id": "bj-test-002",
    }

    record = build_collection_record(item)

    assert record["location"]["community_name"] == "远洋天地"
    assert record["audit"]["community_name_source"] == "beike_alias"
    assert record["audit"]["community_name_confidence"] == pytest.approx(0.98)
    assert record["audit"]["community_stable_key"] == "beike::北京市::朝阳区::远洋天地"
    assert record["audit"]["community_raw_name"] == "远洋天地小区"
    assert record["audit"]["beike_community_id"] == "bj-test-002"

def test_repository_persists_standardized_community_audit_fields(tmp_path: Path):
    repo = _make_repo(tmp_path)

    repo.upsert_flat_item(
        _make_flat_item(
            id="9203",
            community_name="远洋天地",
            community_name_source="beike_alias",
            community_name_confidence=0.98,
            community_stable_key="beike::北京市::朝阳区::远洋天地",
            community_raw_name="远洋天地小区",
            beike_community_id="bj-test-002",
        ),
        event_type="community_standardized",
    )

    with repo.session_factory() as session:
        audit_row = session.get(PropertyAudit, "9203")
        assert audit_row.community_name_source == "beike_alias"
        assert float(audit_row.community_name_confidence) == pytest.approx(0.98)
        assert audit_row.community_stable_key == "beike::北京市::朝阳区::远洋天地"
        assert audit_row.community_raw_name == "远洋天地小区"
        assert audit_row.beike_community_id == "bj-test-002"

    flat_item = repo.get_flat_item("9203")
    assert flat_item["community_name_source"] == "beike_alias"
    assert flat_item["community_name_confidence"] == pytest.approx(0.98)
    assert flat_item["community_stable_key"] == "beike::北京市::朝阳区::远洋天地"
    assert flat_item["community_raw_name"] == "远洋天地小区"
    assert flat_item["beike_community_id"] == "bj-test-002"

def test_load_data_db_first_keeps_runtime_cache_empty_until_items_are_requested(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9101", currentPrice="980000"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.RUNTIME.collection.seen_ids == {}
    assert server_module.RUNTIME.collection.pending_tasks == []

def test_repository_counts_snapshot_and_coordinate_centroids(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="centroid-1",
            city="上海市",
            district="浦东新区",
            community_name="测试花园",
            lat="31.2000",
            lng="121.5000",
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )
    repo.upsert_flat_item(
        _make_flat_item(
            id="centroid-2",
            city="上海市",
            district="浦东新区",
            community_name="测试花园",
            lat="31.3000",
            lng="121.7000",
            avm_risk_features={"is_occupied": "no"},
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-12.json"},
    )

    counts = repo.counts_snapshot()
    centroids = repo.build_coordinate_centroids()

    assert counts["db_total_ids"] == 2
    assert counts["db_pending_ids"] == 2
    assert centroids["community::测试花园"] == (31.25, 121.6)

def test_repository_analysis_readiness_snapshot_counts_blockers(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="blocker-1",
            city="上海市",
            district="浦东新区",
            business_area_name="",
            community_name="",
            lat="",
            lng="",
            area_sqm="",
            currentPrice="",
            initialPrice="",
            detail_archive_path=None,
            status="pending",
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )

    snapshot = repo.analysis_readiness_snapshot()

    assert snapshot["ready"] == 0
    assert snapshot["not_ready"] == 1
    assert snapshot["invalid"] == 0
    assert snapshot["blockers"]["area_sqm"] == 1
    assert snapshot["blockers"]["business_area"] == 1
    assert snapshot["blockers"]["price_anchor"] == 1
    assert snapshot["blockers"]["detail_stage"] == 1
    assert snapshot["blockers"]["status"] == 1
    assert snapshot["blockers"]["location_precision"] == 1

def test_repository_event_type_counts_and_detail_fetch_candidate_block_cooldown(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="cooldown-1", detail_archive_path=None, url="https://example.com/item/cooldown-1"),
        event_type="detail_archive_fetch_blocked",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )

    counts = repo.event_type_counts(("detail_archive_fetch_blocked",), hours=24)
    blocked_ids = repo.recent_event_item_ids(("detail_archive_fetch_blocked",), hours=24)
    candidates = repo.iter_detail_fetch_candidates(limit=10)

    assert counts["detail_archive_fetch_blocked"] == 1
    assert "cooldown-1" in blocked_ids
    assert all(row["item_id"] != "cooldown-1" for row in candidates)

def test_load_data_prefers_database_over_stale_json_when_db_is_enabled(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9201", title="DB Title", currentPrice="980000"), event_type="seed")

    data_dir = tmp_path / "datas"
    data_dir.mkdir(parents=True, exist_ok=True)
    stale_file = data_dir / "2026-05-11.json"
    stale_file.write_text(
        json.dumps(
            [
                {
                    "id": "9201",
                    "title": "Stale JSON Title",
                    "成交价格": "1万",
                    "交易时间": "2026-05-11 10:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.RUNTIME.collection.seen_ids == {}
    working = server_module._get_working_item("9201", include_processed=True)
    assert working["data"]["source_title"] == "DB Title"
    assert server_module.RUNTIME.collection.seen_ids == {}

def test_repository_pending_task_queries_and_processed_counts(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9301", title="Pending", url="https://x/9301"), event_type="seed")
    repo.upsert_flat_item(
        _make_flat_item(id="9302", title="Processed", url="https://x/9302", avm_risk_features={"is_occupied": "no"}),
        event_type="seed",
    )

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9302")
        audit_row.is_processed = True

    pending = repo.iter_pending_task_items(limit=10)
    pending_ids = [row["id"] for row in pending]

    assert "9301" in pending_ids
    assert "9302" not in pending_ids
    assert repo.count_pending_task_items() == 1

def test_repository_manual_review_receipt_persistence_and_audit(tmp_path: Path):
    repo = _make_repo(tmp_path)

    upsert = repo.upsert_manual_review_receipt(
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
            "source": "operator_api",
        }
    )
    repo.append_manual_review_receipt_operation(
        operation="created",
        receipt=upsert["receipt"],
        execution_mode="async",
        maintenance_job_id="job-1",
    )
    job = repo.create_manual_review_receipt_job(
        receipt_key={"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
        maintenance_options={"window_days": 7},
    )
    repo.update_manual_review_receipt_job(
        job["job_id"],
        status="completed",
        result_summary={"generated_at": "x", "reentry_applied": True},
        finished_at="2026-05-15 10:00:00",
    )

    receipts = repo.list_manual_review_receipts()
    assert receipts["receipts"][0]["action"] == "manual_location_review"

    operations = repo.list_manual_review_receipt_operations(action="manual_location_review")
    assert len(operations) == 1
    assert operations[0]["maintenance_job_id"] == "job-1"

    jobs_snapshot = repo.manual_review_receipt_jobs_snapshot()
    assert jobs_snapshot["jobs"][0]["job_id"] == job["job_id"]
    assert jobs_snapshot["jobs"][0]["status"] == "completed"

    deleted = repo.delete_manual_review_receipt("manual_location_review", "location_artifacts_complete")
    assert deleted["deleted"] is True
    assert deleted["receipt_count"] == 0

    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ManualReviewReceipt)) == 0
        assert session.scalar(select(func.count()).select_from(ManualReviewReceiptOperation)) == 1
        assert session.scalar(select(func.count()).select_from(ManualReviewReceiptJob)) == 1
