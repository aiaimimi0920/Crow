"""Regression tests for Slice 3 storage batching, manual-review split, and HTTP/pool options."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.collection_http_server import tls_context_from_env
from src.collection_runtime_index import CollectionRuntimeIndex
from src.storage.connection_policy import engine_connection_options
from tools.test.test_detail_worker import _make_repo


def test_batched_upsert_seed_items_preserves_counts_and_duplicates(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.ensure_seed_scan_job(
        {
            "job_key": "gd-gz-440106-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "天河区",
            "location_code": "440106",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价降序"}],
        max_page=10,
    )
    first = repo.upsert_seed_items(
        job_key="gd-gz-440106-50025969",
        progress_key="gd-gz-440106-50025969:bid_desc",
        sort_key="bid_desc",
        sort_name="出价降序",
        st_param="2",
        page=1,
        source_page_url="https://sf.taobao.com/list/1",
        items=[
            {"id": "9003", "title": "C"},
            {"id": "9001", "title": "A"},
            {"id": "9003", "title": "C-updated"},
            {"id": "9002", "title": "B"},
        ],
    )
    assert first == {
        "seen": 4,
        "new_items": 3,
        "existing_items": 1,
        "new_occurrences": 4,
    }

    second = repo.upsert_seed_items(
        job_key="gd-gz-440106-50025969",
        progress_key="gd-gz-440106-50025969:bid_desc",
        sort_key="bid_desc",
        sort_name="出价降序",
        st_param="2",
        page=1,
        source_page_url="https://sf.taobao.com/list/1",
        items=[
            {"id": "9003", "title": "C"},
            {"id": "9004", "title": "D"},
        ],
    )
    assert second == {
        "seen": 2,
        "new_items": 1,
        "existing_items": 1,
        "new_occurrences": 1,
    }


def test_manual_review_operations_limit_and_stage_status_counts(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    for idx in range(5):
        repo.append_manual_review_receipt_operation(
            operation="upsert",
            receipt={
                "action": "verify",
                "ready_signal": f"sig-{idx}",
                "status": "ready",
                "payload": {"idx": idx},
            },
            execution_mode="sync",
        )
    assert repo.list_manual_review_receipt_operations(limit=0) == []
    limited = repo.list_manual_review_receipt_operations(limit=2)
    assert [row["ready_signal"] for row in limited] == ["sig-3", "sig-4"]

    repo.upsert_flat_item(
        {
            "id": "5001",
            "标题": "天河房产",
            "原始网站": "https://sf-item.taobao.com/sf_item/5001.htm",
            "成交价格": 2000000,
            "建筑面积": 100.0,
            "完整地址": "广州市天河区测试路",
            "城市": "广州市",
            "区": "天河区",
            "is_processed": True,
        },
        event_type="detail_analysis_completed",
        return_committed=False,
    )
    counts = repo.stage_status_counts()
    assert counts["seed_stored"] >= 1
    assert sum(counts.values()) > 0


def test_upsert_flat_item_without_return_committed_skips_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        repo,
        "get_flat_item",
        lambda *_a, **_kw: pytest.fail("return_committed=False must skip get_flat_item"),
    )
    out = repo.upsert_flat_item(
        {
            "id": "5002",
            "标题": "越秀房产",
            "原始网站": "https://sf-item.taobao.com/sf_item/5002.htm",
        },
        event_type="sniff_saved",
        return_committed=False,
    )
    assert out is None


def test_crow_tls_env_and_db_pool_options(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="both"):
        tls_context_from_env({"CROW_API_TLS_CERT_FILE": "only-cert.pem"})

    monkeypatch.setenv("CROW_DB_POOL_SIZE", "16")
    monkeypatch.setenv("CROW_DB_MAX_OVERFLOW", "24")
    monkeypatch.setenv("CROW_DB_POOL_TIMEOUT", "45")
    opts = engine_connection_options("postgresql+psycopg://u:p@127.0.0.1:5432/crow")
    assert opts["pool_size"] == 16
    assert opts["max_overflow"] == 24
    assert opts["pool_timeout"] == 45

    index = CollectionRuntimeIndex()
    assert index.queue_pending("a") is True
    assert index.queue_pending("a") is False
    index.remove_pending("missing")
    index.remove_pending("a")
    assert index.counts_snapshot() == (0, 0)


def test_pending_list_same_length_replacement_is_authoritative():
    index = CollectionRuntimeIndex()
    index.queue_pending("a")
    index.pending_tasks[:] = ["b"]
    assert index.queue_pending("a")
    assert not index.queue_pending("b")
    index.remove_pending("b")
    assert index.pending_tasks == ["a"]


def test_conflicting_tls_aliases_fail_before_loading_files():
    with pytest.raises(ValueError, match="Conflicting environment aliases"):
        tls_context_from_env({"CROW_API_TLS_CERT_FILE": "", "FAPAI_API_TLS_CERT_FILE": "a"})
