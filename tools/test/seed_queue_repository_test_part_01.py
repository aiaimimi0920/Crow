from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403


def test_seed_item_url_normalizes_duplicate_detail_path_slashes() -> None:
    assert PropertyRepository._seed_item_url(
        "570192626894",
        "https://sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
    ) == "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"

def test_detail_claim_overrides_legacy_duplicate_slash_payload_url(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": "570192626894",
                "url": "https://sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
            }
        ],
    )

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["url"] == "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"
    assert claimed["source_url"] == claimed["url"]

def test_detail_claim_does_not_use_worker_local_filesystem_inside_row_lock(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo, item_id="missing-artifact")
    missing_path = tmp_path / "worker-only" / "detail.html"
    repo.mark_seed_raw_detail_captured("missing-artifact", detail_html_path=str(missing_path))

    claimed = repo.claim_seed_raw_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["item_id"] == "missing-artifact"
    assert claimed["_raw_detail_artifacts"]["detail_html_path"] == str(missing_path)

def test_collection_observer_lists_seed_links_with_totals(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)

    payload = repo.collection_observer_items(stage="links", limit=20, offset=0)

    assert payload["stage"] == "links"
    assert payload["total"] == 1
    assert payload["items"][0]["item_id"] == "1001"
    assert payload["items"][0]["title"] == "广州市南沙区测试房产"
    assert payload["items"][0]["source_url"] == "https://sf-item.taobao.com/sf_item/1001.htm"
    assert payload["items"][0]["latest_occurrence"]["sort_name"] == "出价次数由高到低"
    assert payload["items"][0]["latest_occurrence"]["source_page_url"].startswith("https://sf-item.taobao.com/list/")

def test_collection_observer_lists_detail_and_analysis_stages(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>成交价 123 万元</body></html>", encoding="utf-8")
    selected_json.write_text('{"selected": true, "title": "广州市南沙区测试房产"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "transaction_price": 1230000}', encoding="utf-8")

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path=str(detail_html),
        description_json_path=None,
        selected_json_path=str(selected_json),
    )

    details = repo.collection_observer_items(stage="details", limit=20, offset=0)
    assert details["total"] == 1
    assert repo.collection_observer_items(stage="links")["total"] == 0
    assert repo.collection_observer_items(stage="analysis")["total"] == 0
    assert details["items"][0]["status"] == "raw_detail_captured"
    assert details["items"][0]["artifacts"]["detail_html_path"] == str(detail_html)

    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    analysis = repo.collection_observer_items(stage="analysis", limit=20, offset=0)
    assert analysis["total"] == 1
    assert analysis["items"][0]["status"] == "detail_completed"
    assert analysis["items"][0]["final_json_path"] == str(final_json)
    assert repo.collection_observer_items(stage="links")["total"] == 0
    assert repo.collection_observer_items(stage="details")["total"] == 0

    repo.requeue_seed_detail_analysis("1001")
    assert repo.collection_observer_items(stage="analysis")["total"] == 0
    reanalysis = repo.collection_observer_items(stage="details")
    assert reanalysis["total"] == 1
    assert reanalysis["items"][0]["final_json_path"] == str(final_json)

def test_collection_observer_item_detail_loads_collected_content(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>标的物详情文本</body></html>", encoding="utf-8")
    selected_json.write_text('{"raw_text": "标的物详情文本"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "community_name": "测试小区"}', encoding="utf-8")
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(detail_html), selected_json_path=str(selected_json))
    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["item"]["item_id"] == "1001"
    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "标的物详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["selected_json"]["json"]["raw_text"] == "标的物详情文本"
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "测试小区"
    assert payload["occurrences"][0]["source_page_url"].startswith("https://sf-item.taobao.com/list/")

def test_collection_observer_item_detail_reads_linux_data_artifact_paths_from_shared_host_root(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>共享详情文本</body></html>", encoding="utf-8")
    (artifact_dir / "selected.json").write_text('{"raw_text": "共享详情文本"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "共享小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_DATA_ROOT_HOST", str(shared_root))

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path="/data/output/1001/detail.html",
        selected_json_path="/data/output/1001/selected.json",
    )
    repo.mark_seed_detail_completed(
        "1001",
        final_json_path="/data/output/1001/final.json",
        selected_json_path="/data/output/1001/selected.json",
    )

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert payload["artifacts"]["detail_html"]["resolved_path"] == str(artifact_dir / "detail.html")
    assert "共享详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["selected_json"]["json"]["raw_text"] == "共享详情文本"
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "共享小区"

def test_collection_observer_item_detail_reads_unc_fpfdata_artifact_paths_from_shared_root(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "nodes" / "pc2-real" / "detail_analysis_worker_3" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>UNC 详情文本</body></html>", encoding="utf-8")
    (artifact_dir / "selected.json").write_text('{"raw_text": "UNC 详情文本"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "UNC 小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_ARTIFACT_ROOT", str(shared_root))

    unc_root = r"\\192.168.15.200\home\project\project\FPFData"
    detail_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\detail.html"
    selected_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\selected.json"
    final_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\final.json"
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=detail_path, selected_json_path=selected_path)
    repo.mark_seed_detail_completed("1001", final_json_path=final_path, selected_json_path=selected_path)

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "UNC 详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "UNC 小区"

def test_collection_observer_derives_missing_raw_paths_from_completed_analysis_path(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "nodes" / "pc2-real" / "detail_analysis_worker_3" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>推导详情</body></html>", encoding="utf-8")
    (artifact_dir / "description-data.json").write_text('{"text": "推导描述"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "推导小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_ARTIFACT_ROOT", str(shared_root))

    final_path = r"\\192.168.15.200\home\project\project\FPFData\output\nodes\pc2-real\detail_analysis_worker_3\1001\final.json"
    repo.mark_seed_detail_completed("1001", final_json_path=final_path, selected_json_path=None)

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "推导详情" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["description_json"]["exists"] is True

def test_collection_observer_can_requeue_completed_item_for_ai_reanalysis(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>旧分析输入</body></html>", encoding="utf-8")
    selected_json.write_text('{"raw_text": "旧分析输入"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "community_name": "旧小区"}', encoding="utf-8")
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(detail_html), selected_json_path=str(selected_json))
    first_claim = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)
    assert first_claim is not None
    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    result = repo.requeue_seed_detail_analysis("1001", reason="operator_requested")

    assert result["ok"] is True
    assert result["item_id"] == "1001"
    assert result["status"] == "raw_detail_captured"
    assert result["analysis_attempt_count"] == 1
    next_claim = repo.claim_seed_raw_detail_item("analysis-worker-2", lease_seconds=30)
    assert next_claim is not None
    assert next_claim["item_id"] == "1001"
    assert next_claim["_raw_detail_artifacts"]["detail_html_path"] == str(detail_html)

def test_collection_observer_manual_update_merges_standardized_fields_into_flat_item(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": "1001",
            "title": "旧标题",
            "url": "https://example.com/old",
            "currentPrice": "1000000",
            "location": "旧地址",
            "city": "旧城市",
            "district": "旧区",
            "area_sqm": "80",
        },
        event_type="seed",
    )

    result = repo.manual_update_flat_item(
        "1001",
        {
            "title": "新标题",
            "transaction_price": "1234567",
            "full_address": "新地址",
            "city": "新城市",
            "district": "新区",
            "area_sqm": "92.5",
            "court_name": "测试法院",
        },
    )

    assert result["ok"] is True
    updated = repo.get_flat_item("1001")
    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["成交价格"] == 1234567.0
    assert updated["完整地址"] == "新地址"
    assert updated["城市"] == "新城市"
    assert updated["区"] == "新区"
    assert updated["建筑面积"] == 92.5
    assert updated["法院名称"] == "测试法院"

def test_collection_observer_regions_report_stage_specific_completion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, item_id="1001")

    links_initial = repo.collection_observer_regions(stage="links")
    nansha_initial = links_initial["regions"][0]
    assert nansha_initial["location_code"] == "440115"
    assert nansha_initial["completed"] is False
    assert nansha_initial["status_label"] == "待采集"

    with repo.session_factory.begin() as session:
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            progress.status = "exhausted"
            progress.completed_at = datetime.now()
            progress.next_page = 83
            session.add(progress)
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        job.status = "completed"
        job.completed_at = datetime.now()
        session.add(job)

    links_done = repo.collection_observer_regions(stage="links")
    assert links_done["regions"][0]["completed"] is True
    assert links_done["regions"][0]["status_label"] == "本轮完成"

    details_before = repo.collection_observer_regions(stage="details")
    assert details_before["regions"][0]["completed"] is False
    assert details_before["regions"][0]["counts"]["pending"] == 1

    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(tmp_path / "detail.html"))
    details_done = repo.collection_observer_regions(stage="details")
    assert details_done["regions"][0]["completed"] is True
    assert details_done["regions"][0]["status_label"] == "本轮完成"

    analysis_before = repo.collection_observer_regions(stage="analysis")
    assert analysis_before["regions"][0]["completed"] is False
    assert analysis_before["regions"][0]["counts"]["pending"] == 1

    repo.mark_seed_detail_completed("1001", final_json_path=str(tmp_path / "final.json"))
    analysis_done = repo.collection_observer_regions(stage="analysis")
    assert analysis_done["regions"][0]["completed"] is True
    assert analysis_done["regions"][0]["status_label"] == "本轮完成"

def test_collection_observer_regions_hides_admin_legacy_rows_for_replaced_taobao_province(
    tmp_path: Path,
    monkeypatch,
) -> None:
    overrides_path = tmp_path / "taobao_sf_location_overrides.json"
    overrides_path.write_text(
        '{"replace_admin_provinces":["上海市"],"locations":[{"province":"上海市","city":"市辖区","district":"崇明","location_code":"310230"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_TAOBAO_LOCATIONS_FILE", str(overrides_path))
    repo = _make_repo(tmp_path)
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-admin-chongming-50025969",
            "province": "上海市",
            "city": "市辖区",
            "district": "崇明区",
            "location_code": "310151",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}],
        max_page=83,
    )
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-taobao-chongming-50025969",
            "province": "上海市",
            "city": "市辖区",
            "district": "崇明",
            "location_code": "310230",
            "category": "50025969",
            "metadata": {"location_source": "taobao_sf_location_overrides"},
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}],
        max_page=83,
    )

    payload = repo.collection_observer_regions(stage="links")

    assert [region["location_code"] for region in payload["regions"]] == ["310230"]
    assert payload["regions"][0]["district"] == "崇明"

def test_collection_observer_regions_orders_taobao_locations_by_code_with_other_last(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sort_specs = [{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}]
    for district, code in [
        ("其它", "500385"),
        ("南川", "500384"),
        ("云阳", "500235"),
    ]:
        repo.ensure_seed_scan_job(
            {
                "job_key": f"{code}-50025969",
                "province": "重庆市",
                "city": "市辖区",
                "district": district,
                "location_code": code,
                "category": "50025969",
                "metadata": {"location_source": "taobao_sf_location_overrides"},
            },
            sort_specs=sort_specs,
            max_page=83,
        )

    payload = repo.collection_observer_regions(stage="links")

    assert [region["location_code"] for region in payload["regions"]] == ["500235", "500384", "500385"]
    assert payload["regions"][-1]["district"] == "其它"

def test_collection_observer_regions_batches_link_counts_without_per_region_queries(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    for index in range(8):
        code = f"99010{index}"
        repo.ensure_seed_scan_job(
            {
                "job_key": f"batch-region-{index}-50025969",
                "province": "测试省",
                "city": "测试市",
                "district": f"测试区{index}",
                "location_code": code,
                "category": "50025969",
            },
            sort_specs=[
                {"sort_key": "default", "sort_name": "默认排序", "st_param": "0"},
                {"sort_key": "price_desc", "sort_name": "价格由高到低", "st_param": "3"},
            ],
            max_page=83,
        )

    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", record_statement)
    try:
        payload = repo.collection_observer_regions(stage="links")
    finally:
        event.remove(repo.engine, "before_cursor_execute", record_statement)

    assert len(payload["regions"]) == 8
    assert len(statements) <= 4

def test_collection_observer_items_can_filter_by_location_code(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, item_id="1001")
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-shanghai-fengxian-50025969",
            "province": "上海市",
            "city": "上海市",
            "district": "奉贤区",
            "location_code": "310120",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "4"}],
        max_page=10,
    )
    repo.upsert_seed_items(
        job_key="shanghai-shanghai-fengxian-50025969",
        progress_key="shanghai-shanghai-fengxian-50025969::default",
        sort_key="default",
        sort_name="默认排序",
        st_param="4",
        page=1,
        source_page_url="https://sf-item.taobao.com/list/shanghai?page=1",
        source_final_url="https://sf-item.taobao.com/list/shanghai?page=1&st=4",
        items=[{"id": "2001", "title": "上海市奉贤区测试房产", "url": "https://sf-item.taobao.com/sf_item/2001.htm"}],
    )

    payload = repo.collection_observer_items(stage="links", limit=20, offset=0, location_code="440115")

    assert payload["total"] == 1
    assert [item["item_id"] for item in payload["items"]] == ["1001"]
    assert payload["location_code"] == "440115"
