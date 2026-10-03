from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_collect_list_union_stops_remaining_pages_after_fetch_error(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"has_script": True, "item_count": 1, "body_has_challenge": False}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"data": []}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "first"}]}

    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        if "page=2" in target_url:
            raise RuntimeError("browser challenge timeout")
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            list_st_params=("2",),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=4,
            list_stop_on_empty=True,
        ),
    )

    assert len(fetched_urls) == 2
    assert result["list_union"]["sources"][1]["error"] == "RuntimeError: runtime_error"
    assert result["list_union"]["sources"][2]["skipped"] is True
    assert result["list_union"]["sources"][3]["skipped"] is True

def test_collect_list_union_preserves_first_fetch_status_method_and_metadata(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "has_script": True,
                "item_count": 2,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "final_url": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"data": [{"id": "first"}, {"id": "second"}]}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "first", "url": "https://sf-item.taobao.com/sf_item/first.htm"},
                    {"id": "second", "url": "https://sf-item.taobao.com/sf_item/second.htm"},
                ],
            }

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list-html",
            "https://sf.taobao.com/list/page=1&redirected=1",
            206,
            "browser_page_after_http_challenge",
        ),
    )

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
        ),
    )

    assert result["first_fetch"] == {
        "url": "https://sf.taobao.com/list/page=1?st_param=2&page=1",
        "location_code": "",
        "category": "",
        "st_param": "2",
        "page": 1,
        "list_status": 206,
        "list_final_url": "https://sf.taobao.com/list/page=1&redirected=1",
        "list_fetch_method": "browser_page_after_http_challenge",
        "list_item_count": 2,
        "body_has_challenge": False,
        "body_has_login": False,
        "body_has_punish": False,
        "payload_present": True,
    }
    assert result["list_union"]["sources"][0]["list_status"] == 206
    assert result["list_union"]["sources"][0]["list_fetch_method"] == "browser_page_after_http_challenge"
    assert result["list_union"]["sources"][0]["eligible_item_count"] == 2

def test_collect_list_union_raises_when_first_page_fetch_error_leaves_no_successful_payload(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            raise AssertionError("summary should not run when fetch fails")

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            raise AssertionError("payload extraction should not run when fetch fails")

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (_ for _ in ()).throw(
            RuntimeError("browser challenge timeout")
        ),
    )

    with pytest.raises(RuntimeError, match="list payload missing for all list sources"):
        live_batch_smoke.collect_list_union(
            _FakeProbe,
            object(),
            live_batch_smoke.LiveSmokeConfig(
                output_dir=Path("out"),
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page=1",
                target_success=1,
                max_attempts=1,
                do_risk=False,
            ),
        )

def test_collect_list_union_challenge_stops_all_sort_keys(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            is_challenge = html == "challenge"
            return {
                "has_script": not is_challenge,
                "item_count": 1 if not is_challenge else None,
                "body_has_challenge": is_challenge,
                "body_has_login": False,
                "body_has_punish": is_challenge,
                "final_url": final_url,
            }

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object] | None:
            return None if html == "challenge" else {"data": [{"id": html}]}

        @staticmethod
        def build_userscript_like_batch_payload(payload, *, source_page_url: str) -> dict[str, object]:
            item_id = payload["data"][0]["id"]
            return {
                "source_page_url": source_page_url,
                "items": [{"id": item_id, "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm"}],
            }

    fetched: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched.append(target_url)
        query = parse_qs(urlparse(target_url).query)
        page = int(query.get("page", ["1"])[0])
        st_param = query.get("st_param", ["2"])[0]
        if st_param == "2" and page == 1:
            return "st2-page1", target_url, 200, "http_cookie"
        if st_param == "2" and page == 2:
            return "challenge", target_url, 200, "http_cookie_challenge"
        return f"st{st_param}-page{page}", target_url, 200, "http_cookie"

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            list_st_params=("2", "1"),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=3,
            list_stop_on_empty=True,
        ),
    )

    assert len(fetched) == 2
    assert "st_param=2&page=3" not in "".join(fetched)
    assert not any("st_param=1" in url for url in fetched)
    sources = result["list_union"]["sources"]
    assert len(sources) == 2
    assert sources[1]["body_has_challenge"] is True
    assert result["challenge_break"]["scope"] == "list"
    assert [item["id"] for item in result["items"]] == ["st2-page1"]

def test_build_area_followup_queue_includes_only_area_missing_items(tmp_path: Path) -> None:
    summary = {
        "summary_path": str(tmp_path / "summary.json"),
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        "results": [
            _result("has-area", area_sqm=117.06, unit_price=115792.59, desc_area=117.06),
            _result("missing-area", area_sqm=None, unit_price=0, desc_area=None),
        ],
    }
    existing_item_dir = tmp_path / "missing-area"
    existing_item_dir.mkdir()
    (existing_item_dir / "detail.html").write_text("<html></html>", encoding="utf-8")
    (existing_item_dir / "description-data.json").write_text(
        '{"area_sqm": null, "text_len": 48, "has_area_marker": false, "text_path": "desc.txt"}',
        encoding="utf-8",
    )

    queue = live_batch_smoke.build_area_followup_queue(summary, artifact_root=tmp_path)

    assert queue["schema_version"] == "area_followup_queue_v1"
    assert queue["source_summary"] == str(tmp_path / "summary.json")
    assert queue["job_count"] == 1
    job = queue["jobs"][0]
    assert job["item_id"] == "missing-area"
    assert job["reason"] == "area_missing_after_detail_and_description_data"
    assert job["missing_fields"] == ["area_sqm", "gross_area_sqm", "unit_price"]
    assert job["priority"] == "P1"
    assert job["source_url"] == "https://sf-item.taobao.com/sf_item/missing-area.htm"
    assert job["community_name"] == "贡院西街片区"
    assert job["community_stable_key"] == "collector::北京市::东城区::贡院西街片区"
    assert job["transaction_price"] == 11632000
    assert job["current_unit_price"] == 0
    assert job["desc_text_len"] == 48
    assert job["desc_has_area_marker"] is False
    assert job["description_data_path"] == str(existing_item_dir / "description-data.json")
    assert job["detail_html_path"] == str(existing_item_dir / "detail.html")
    assert job["next_attempts"] == [
        "announcement_attachment",
        "appraisal_report_attachment",
        "detail_page_images_ocr",
        "external_property_or_community_index",
    ]

def test_attach_area_stats_and_queue_paths_returns_new_summary(tmp_path: Path) -> None:
    summary = {
        "results": [
            _result("missing-area", area_sqm=None, unit_price=None, desc_area=None),
        ],
    }

    enriched = live_batch_smoke.attach_area_artifacts(summary, output_dir=tmp_path)

    assert "area_stats" in enriched
    assert enriched["area_stats"]["area_missing_count"] == 1
    assert enriched["area_followup_queue_path"] == str(tmp_path / "area_followup_queue.json")
    assert "area_followup_queue" not in enriched
    assert summary.get("area_stats") is None

def test_resume_state_persists_completed_items_and_skips_them(tmp_path: Path) -> None:
    state_path = tmp_path / "resume_state.json"
    state = live_batch_smoke.load_resume_state(state_path)

    live_batch_smoke.mark_resume_item(
        state,
        "a",
        status="completed",
        metadata={"selected_json_path": "a/selected.json"},
    )
    live_batch_smoke.save_resume_state(state_path, state)

    loaded = live_batch_smoke.load_resume_state(state_path)
    candidates, skipped = live_batch_smoke.select_resume_candidates(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        loaded,
        limit=2,
    )

    assert live_batch_smoke.is_resume_completed(loaded, "a") is True
    assert [item["id"] for item in candidates] == ["b", "c"]
    assert skipped == ["a"]

def test_resume_state_retries_non_completed_items(tmp_path: Path) -> None:
    state = live_batch_smoke.load_resume_state(tmp_path / "missing.json")
    live_batch_smoke.mark_resume_item(state, "a", status="completed")
    live_batch_smoke.mark_resume_item(state, "b", status="failed", metadata={"error": "timeout"})
    live_batch_smoke.mark_resume_item(state, "c", status="in_progress")

    candidates, skipped = live_batch_smoke.select_resume_candidates(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        state,
        limit=3,
    )

    assert [item["id"] for item in candidates] == ["b", "c", "d"]
    assert skipped == ["a"]

def test_load_resume_state_recovers_invalid_json_and_non_mapping_payload(tmp_path: Path) -> None:
    invalid_json_path = tmp_path / "invalid-resume.json"
    invalid_json_path.write_text("{", encoding="utf-8")

    invalid_json_state = live_batch_smoke.load_resume_state(invalid_json_path)
    assert invalid_json_state["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert invalid_json_state["items"] == {}

    list_payload_path = tmp_path / "list-resume.json"
    list_payload_path.write_text(json.dumps(["not-a-dict"]), encoding="utf-8")

    list_payload_state = live_batch_smoke.load_resume_state(list_payload_path)
    assert list_payload_state["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert list_payload_state["items"] == {}

def test_load_resume_state_normalizes_missing_schema_and_non_mapping_items(tmp_path: Path) -> None:
    state_path = tmp_path / "resume_state.json"
    state_path.write_text(
        json.dumps({"schema_version": "", "items": [], "updated_at": "2026-08-13T00:00:00Z"}),
        encoding="utf-8",
    )

    loaded = live_batch_smoke.load_resume_state(state_path)

    assert loaded["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert loaded["items"] == {}
    assert loaded["updated_at"] == "2026-08-13T00:00:00Z"

def test_hydrate_resume_state_requires_both_final_and_selected_artifacts(tmp_path: Path) -> None:
    state = live_batch_smoke.new_resume_state()
    (tmp_path / "final-only").mkdir()
    (tmp_path / "selected-only").mkdir()
    (tmp_path / "complete").mkdir()
    (tmp_path / "final-only" / "final.json").write_text("{}", encoding="utf-8")
    (tmp_path / "selected-only" / "selected.json").write_text("{}", encoding="utf-8")
    (tmp_path / "complete" / "final.json").write_text("{}", encoding="utf-8")
    (tmp_path / "complete" / "selected.json").write_text("{}", encoding="utf-8")

    hydrated = live_batch_smoke.hydrate_resume_state_from_artifacts(
        state,
        [
            {"id": "final-only", "url": "https://example.test/final-only", "title": "final only"},
            {"id": "selected-only", "url": "https://example.test/selected-only", "title": "selected only"},
            {"id": "complete", "url": "https://example.test/complete", "title": "complete"},
        ],
        output_dir=tmp_path,
    )

    assert hydrated == ["complete"]
    assert live_batch_smoke.is_resume_completed(state, "final-only") is False
    assert live_batch_smoke.is_resume_completed(state, "selected-only") is False
    assert live_batch_smoke.is_resume_completed(state, "complete") is True
