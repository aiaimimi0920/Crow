"""Regression tests for Slice 2 LLM pool resilience, HTML filtering, and archive propagation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import llm_avm_risk, llm_helper, llm_qualification_pool
from src.llm_qualification_pool import EmptyModelResponseError
from tools import detail_worker, worker_lifecycle
from tools.test.test_detail_worker import _make_repo, _seed_one_item
from tools.test.test_llm_qualification_pool import Response, make_pool


def test_worker_stopping_cancels_pool_without_disabling_healthy_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_pool = make_pool(tmp_path, {"model-a": 5, "model-b": 5})
    seed_pool.ensure()
    monkeypatch.setenv("CROW_ANALYSIS_MODEL_POOL_ENABLED", "1")
    monkeypatch.setenv("CROW_ANALYSIS_MODEL_POOL_PATH", str(seed_pool.store.path))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "model-a")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "model-b")

    lifecycle = worker_lifecycle.WorkerLifecycle("analysis-1", lambda _wid: None)
    token = worker_lifecycle._active.set(lifecycle)
    try:
        def interrupted_post(*_args, **_kwargs):
            lifecycle.stopping.set()
            import requests

            raise requests.ConnectionError("gateway interrupted by SIGTERM")

        seed_pool.session.post = interrupted_post
        pool = llm_qualification_pool.QualifiedModelPool(
            seed_pool.config,
            store=seed_pool.store,
            session=seed_pool.session,
            cancel_event=worker_lifecycle.stopping_event(),
        )
        with pytest.raises(llm_helper.LLMBackendUnavailableError, match="cancelled"):
            pool.chat("real item")
        assert seed_pool.available() == ["model-a", "model-b"]
    finally:
        worker_lifecycle._active.reset(token)


def test_empty_model_response_does_not_disable_models_or_revert_item_attempts(
    tmp_path: Path,
) -> None:
    pool = make_pool(tmp_path, {"model-a": 5, "model-b": 5})
    pool.ensure()
    pool.session.post = lambda *_a, **_kw: Response(
        {"choices": [{"message": {"content": "   "}}]}
    )
    with pytest.raises(EmptyModelResponseError):
        pool.chat("poison html item")
    assert pool.available() == ["model-a", "model-b"]
    assert (
        detail_worker._is_llm_backend_unavailable_error(
            EmptyModelResponseError("LLM backend unavailable: empty chat response")
        )
        is False
    )


def test_pool_retries_once_without_reasoning_effort_on_http_400(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, {"gemini-2.5-flash": 5}, reasoning_effort="none")
    payloads: list[dict[str, object]] = []
    original = pool.session.post

    def post_rejecting_reasoning(url: str, **kwargs):
        body = dict(kwargs["json"])
        payloads.append(body)
        if "reasoning_effort" in body:
            bad = Response({"error": {"message": "Unknown field reasoning_effort"}})
            bad.status_code = 400
            return bad
        return original(url, **kwargs)

    pool.session.post = post_rejecting_reasoning
    assert pool.ensure() == ["gemini-2.5-flash"]
    assert pool.chat("real item") == "production"
    assert payloads[-2].get("reasoning_effort") == "none"
    assert "reasoning_effort" not in payloads[-1]


def test_extract_avm_risk_features_filters_script_noise_before_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    payload = {key: None for key in llm_helper.AVM_RISK_KEYS}
    payload.update(
        {
            "community_name": "星河湾花园",
            "is_occupied": True,
            "clear_delivery": False,
            "housing_type": "住宅",
        }
    )

    def fake_chat(prompt: str, **_kwargs) -> str:
        captured.append(str(prompt))
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(llm_avm_risk, "chat_with_glm", fake_chat)
    huge_html = (
        "<html><head><script>"
        + ("var junk = '1234567890';\n" * 6000)
        + "</script></head><body>"
        + "<div id='J_NoticeDetail'>特别提醒：星河湾花园房屋目前有人居住，买受人自行腾退。</div>"
        + "</body></html>"
    )
    features = llm_helper.extract_avm_risk_features(huge_html, item_id="9001")
    assert features is not None
    assert features["community_name"] == "星河湾花园"
    assert "星河湾花园房屋目前有人居住" in captured[0]
    assert "var junk" not in captured[0]


def test_analysis_only_runtime_context_skips_cdp_cookie_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        detail_worker,
        "export_cookies",
        lambda *_a, **_kw: pytest.fail("analysis_only must never contact CDP"),
    )
    cfg = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9224",
        target_success=1,
        max_attempts=1,
        worker_id="analysis-1",
        do_risk=False,
        analysis_only=True,
    )
    assert detail_worker._build_runtime_context(cfg) == (None, {})


def test_raw_capture_archive_path_propagates_to_persisted_audit_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    archive_root = tmp_path / "archive"
    raw_html = "<html><head><title>测试房产</title></head><body><div id='J_NoticeDetail'>建筑面积（平方米）：108.50</div></body></html>"

    def _write_raw(_http, seed, _pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "detail.html").write_text(raw_html, encoding="utf-8")
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"], "detail_capture_mode": "raw"}),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    capture_summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path / "capture_work",
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-1",
            do_risk=False,
            raw_only=True,
            detail_archive_root=archive_root,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_write_raw,
    )
    archived_path = capture_summary["detail_archive_path"]
    assert Path(archived_path).is_file()

    monkeypatch.setattr(
        "src.collection.runtime_adapter.extract_detail_payload",
        lambda *_a, **_kw: json.dumps(
            {
                "id": 3001,
                "标题": "测试房产",
                "成交价格": 1085000,
                "建筑面积": 108.5,
                "完整地址": "广州市天河区测试路1号",
                "城市": "广州市",
                "区": "天河区",
                "is_processed": True,
            },
            ensure_ascii=False,
        ),
    )

    analysis_work = tmp_path / "analysis_work"
    analysis_summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=analysis_work,
            cdp_endpoint="",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-1",
            analysis_only=True,
            do_risk=False,
        ),
        repository=repo,
    )
    assert analysis_summary["decision"] == "detail_analysis_completed"
    persisted = repo.get_flat_item("3001")
    assert persisted is not None
    assert persisted["detail_archive_path"] == archived_path
    assert not (analysis_work / "3001" / "detail.html").exists()
    assert analysis_summary["staged_html_retained"] is False


def test_retry_requires_another_slot_and_cannot_outlive_first_send(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, {"model-a": 5}, reasoning_effort="none")
    now = [10.0]
    monkeypatch.setattr(llm_qualification_pool.time, "monotonic", lambda: now[0])
    calls = []
    reservations = []
    pool.store.reserve_request_slot = lambda: reservations.append(True) or 0

    def post(_url, **kw):
        calls.append(kw["timeout"])
        if len(calls) == 1:
            now[0] += 7
            response = Response({})
            response.status_code = 400
            return response
        return Response({"choices": [{"message": {"content": "ok"}}]})

    pool.session.post = post
    assert pool.request("model-a", "fixture") == "ok"
    assert calls == [10, 3]
    assert len(reservations) == 2


def test_empty_fence_uses_next_qualified_model(tmp_path):
    pool = make_pool(tmp_path, {"a": 5, "b": 5})
    pool.ensure()
    original = pool.session.post
    pool.session.post = lambda url, **kw: (
        Response({"choices": [{"message": {"content": "```json\n```"}}]})
        if kw["json"]["model"] == "a" else original(url, **kw)
    )
    assert pool.chat("test") == "production"
    assert pool.config["last_successful_model"] == "b"
    assert pool.available() == ["a", "b"]


def test_large_page_keeps_truncated_description_and_notice_tails(monkeypatch):
    from src import llm_auction_extraction as owner

    prompts = []
    monkeypatch.setattr(owner, "chat_with_glm", lambda p: prompts.append(str(p)) or "{}")
    owner.extract_auction_data("<div id='J_desc'>" + "字" * 20000 + "实测地址</div>"
                               "<div id='J_NoticeDetail'>公告前段竞买人条件另附法院名称</div>")
    assert "实测地址" in prompts[0] and "另附法院名称" in prompts[0]


def test_description_denies_local_hosts_and_redirects(monkeypatch):
    from src import llm_text_extraction as owner
    from unittest.mock import Mock

    session = Mock()
    monkeypatch.setattr(owner.requests, "Session", lambda: session)
    html = '<script id="description-data">{\"link\":\"%s\"}</script>'
    assert owner.fetch_description_data_text(html % "http://localhost/path") is None
    session.get.assert_not_called()
    session.get.return_value.status_code = 302
    assert owner.fetch_description_data_text(html % "https://itemcdn.tmall.com/path") is None
    assert session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("invalid", ["12345", "123.45678", "1,234.5"])
def test_unit_first_area_never_truncates_a_number(invalid):
    assert llm_helper.extract_area_from_text(f"建筑面积（平方米）：{invalid}") is None


def test_slow_body_does_not_retain_session_cookies(monkeypatch):
    from src import llm_qualification_transport as transport
    from types import SimpleNamespace

    now = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    session = SimpleNamespace(cookies={"previous": "fixture"})
    response = Response({})

    def stream(chunk_size):
        # This peer only yields when the requested read size has arrived.
        now[0] += chunk_size * 2
        yield b"x" * chunk_size

    def get(*_args, **_kw):
        assert not session.cookies
        session.cookies["new"] = "fixture"
        return response

    response.iter_content = stream
    session.get = get
    with pytest.raises(llm_helper.LLMBackendUnavailableError, match="response limit"):
        transport.request_json(session, "get", "https://example.invalid", timeout=1, max_bytes=8192)
    assert now[0] == 2 and not session.cookies


def test_disappeared_pool_row_never_grants_unrecorded_slot(tmp_path):
    import sqlite3
    from contextlib import closing

    pool = make_pool(tmp_path, {"model-a": 5})
    with closing(sqlite3.connect(pool.store.path)) as db:
        db.execute("DELETE FROM pools WHERE id=?", (pool.store.key,))
        db.commit()
    with pytest.raises(sqlite3.DatabaseError, match="state is missing"):
        type(pool.store).reserve_request_slot(pool.store)
