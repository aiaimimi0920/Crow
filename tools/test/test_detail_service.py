from __future__ import annotations

from pathlib import Path

from src.collection.adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from src.collection.detail_execution import DetailModels, DetailRuntime, DetailStorage
from src.collection.detail_extractors import CallableDetailExtractor
from src.collection.detail_service import DetailCollectionService


def _submit_detail_html(tmp_path: Path, *, status: str):
    item_id = "12345"
    state = {
        "pending_tasks": [item_id],
        "submitted": [],
        "persisted": [],
        "item": {
            "file_path": str(tmp_path / "seed.json"),
            "cached": True,
            "data": {
                "id": item_id,
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
            },
        },
    }

    service = DetailCollectionService(tmp_path, adapter=TaobaoJudicialAuctionAdapter())

    def get_working_item(candidate_id: str, include_processed: bool = False):
        return state["item"] if candidate_id == item_id else None

    def apply_flat_override_patch(data, patch):
        data.update(patch)

    def reset_structured_sections_for_resync(data):
        data["resync_reset"] = True

    def update_file_global(file_path, candidate_id, data):
        state["updated"] = {
            "file_path": file_path,
            "id": candidate_id,
            "data": dict(data),
        }

    def persist_item_to_db(data, event_type, meta):
        state["persisted"].append(
            {"event_type": event_type, "meta": meta, "data": dict(data)}
        )

    def evict_runtime_item(candidate_id):
        state.setdefault("evicted", []).append(candidate_id)

    def submit_task(path):
        state["submitted"].append(path)

    result = service.submit_html(
        item_id=item_id,
        html_content="<html><body>login/captcha page</body></html>",
        status=status,
        get_working_item=get_working_item,
        apply_flat_override_patch=apply_flat_override_patch,
        reset_structured_sections_for_resync=reset_structured_sections_for_resync,
        update_file_global=update_file_global,
        persist_item_to_db=persist_item_to_db,
        evict_runtime_item=evict_runtime_item,
        submit_task=submit_task,
        prefer_db_task_reads=lambda: False,
        remove_pending=lambda candidate_id: state["pending_tasks"].remove(candidate_id),
    )
    return result, state, tmp_path / "html" / f"item-{item_id}.html"


def test_failed_timeout_detail_html_persists_status_without_ai_queue(tmp_path: Path):
    result, state, html_path = _submit_detail_html(tmp_path, status="failed_timeout")

    assert result == {"status": "queued"}
    assert html_path.exists()
    assert state["submitted"] == []
    assert state["item"]["data"]["status"] == "failed_timeout"
    assert [event["event_type"] for event in state["persisted"]] == [
        "analyze_html_status"
    ]


def test_failed_captcha_detail_html_persists_status_without_ai_queue(tmp_path: Path):
    result, state, html_path = _submit_detail_html(tmp_path, status="failed_captcha")

    assert result == {"status": "queued"}
    assert html_path.exists()
    assert state["submitted"] == []
    assert state["item"]["data"]["status"] == "failed_captcha"
    assert [event["event_type"] for event in state["persisted"]] == [
        "analyze_html_status"
    ]


def test_process_html_file_preserves_seed_values_when_ai_returns_null_fields(
    tmp_path: Path,
):
    item_id = "747988656830"
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    html_path = html_dir / f"item-{item_id}.html"
    html_path.write_text(
        "<html><body>loaded detail page</body></html>", encoding="utf-8"
    )

    seed_data = {
        "id": int(item_id),
        "title": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
        "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
        "status": "done",
        "currentPrice": 13554680.0,
        "initialPrice": 13554680.0,
        "auction_date": "2023-12-13 15:45:41",
        "bidCount": 945,
        "applyCount": 11,
    }
    state = {
        "pending_tasks": [item_id],
        "persisted": [],
        "updated": None,
        "item": {
            "file_path": str(tmp_path / "seed.json"),
            "cached": True,
            "data": dict(seed_data),
        },
    }

    service = DetailCollectionService(tmp_path, adapter=TaobaoJudicialAuctionAdapter())

    def get_working_item(candidate_id: str, include_processed: bool = False):
        return state["item"] if candidate_id == item_id else None

    def update_item_in_json(file_path, candidate_id, data):
        state["updated"] = {
            "file_path": file_path,
            "id": candidate_id,
            "data": dict(data),
        }

    def persist_item_to_db(data, event_type, meta):
        state["persisted"].append(
            {"event_type": event_type, "meta": meta, "data": dict(data)}
        )

    def extract_auction_data(_content, item_id=None):
        return """
        {
          "id": 33007244168,
          "市场评估价": 9001680,
          "标题": null,
          "是否成交": false,
          "交易时间": null,
          "成交价格": null,
          "起拍价格": 9001680,
          "竞拍人数": null,
          "出价次数": null,
          "建筑面积": 117.06,
          "单价": 115792.59,
          "is_processed": true
        }
        """

    def extract_avm_risk_features(_content, item_id=None):
        state.setdefault("risk_extractions", []).append(item_id)
        return {"is_occupied": True}

    def sync_avm_risk_aliases(item):
        state.setdefault("risk_syncs", []).append(item_id)
        return item

    service.process_html_file(
        str(html_path),
        storage=DetailStorage(
            get_working_item=get_working_item,
            update_item_in_json=update_item_in_json,
            remove_item_from_json=lambda *_args: None,
            persist_item_to_db=persist_item_to_db,
            mark_item_deleted_in_db=lambda *_args: None,
        ),
        runtime=DetailRuntime(
            evict_runtime_item=lambda *_args: None,
            prefer_db_task_reads=lambda: False,
            queue_pending=lambda _item_id: True,
            set_seen=lambda *_args: None,
            remove_pending=lambda candidate_id: state["pending_tasks"].remove(
                candidate_id
            ),
        ),
        models=DetailModels(
            extractor=CallableDetailExtractor(extract_auction_data),
            sync_risk=sync_avm_risk_aliases,
            extract_risk=extract_avm_risk_features,
            report=lambda **_kwargs: None,
        ),
    )

    updated = state["updated"]["data"]
    assert updated["title"] == seed_data["title"]
    assert updated["id"] == int(item_id)
    assert updated["标题"] == seed_data["title"]
    assert updated["是否成交"] is True
    assert updated["交易时间"] == seed_data["auction_date"]
    assert updated["成交价格"] == seed_data["currentPrice"]
    assert updated["起拍价格"] == seed_data["initialPrice"]
    assert updated["市场评估价"] == 9001680
    assert updated["竞拍人数"] == seed_data["applyCount"]
    assert updated["出价次数"] == seed_data["bidCount"]
    assert updated["建筑面积"] == 117.06
    assert updated["单价"] == 115792.59
    assert updated["avm_risk_features"]["is_occupied"] is True
    assert state["risk_extractions"] == [item_id]
    assert state["risk_syncs"] == [item_id]


def test_generic_seed_preservation_entrypoint_uses_the_configured_adapter():
    record = {"source_item_id": "sku-1", "source_platform": "catalog_x", "price": None}
    seed = {
        "source_item_id": "sku-1",
        "source_platform": "catalog_x",
        "price": 42,
        "name": "Seed",
    }

    DetailCollectionService._preserve_seed_values(
        record,
        seed,
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    )

    assert record == {
        "source_item_id": "sku-1",
        "source_platform": "catalog_x",
        "price": 42,
        "name": "Seed",
    }


def test_legacy_seed_preservation_entrypoint_delegates_to_auction_adapter():
    record = {
        "id": "legacy-1",
        "source_item_id": "legacy-1",
        "建筑面积": 80,
        "成交价格": None,
    }
    seed = {
        "id": "legacy-1",
        "title": "Seed title",
        "currentPrice": 1_000_000,
        "url": "https://example.test/items/legacy-1",
        "status": "done",
    }

    DetailCollectionService._preserve_seed_values(record, seed)

    assert record["标题"] == "Seed title"
    assert record["成交价格"] == 1_000_000
    assert record["建筑面积"] == 80


def test_run_maintenance_forwards_reconcile_limit(tmp_path, monkeypatch):
    import tools.run_recent_enrich_maintenance as maintenance_module

    calls = {}

    def fake_run(**options):
        calls.update(options)
        return {"reconcile_limit": options["reconcile_limit"]}

    monkeypatch.setattr(maintenance_module, "run_recent_enrich_maintenance", fake_run)
    service = DetailCollectionService(tmp_path)

    assert service.run_maintenance(reconcile_limit=7) == {"reconcile_limit": 7}
    assert calls["reconcile_limit"] == 7
