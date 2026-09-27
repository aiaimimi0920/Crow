"""Auction patch precedence and structured-record rebuild publication boundary."""

from types import SimpleNamespace

import pytest


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


def test_alias_priority_is_mapping_order_not_patch_order(host):
    patch = {
        "transaction_price": 3,
        "currentPrice": 2,
        "成交价格": 1,
        "status": "done",
        "状态": "pending",
        "deposit": 0,
        "starting_price": "",
        "initialPrice": 7,
        "city": None,
    }
    item = {"city": "kept"}
    assert host._apply_flat_override_patch(item, patch) is None
    assert item == {
        "transaction_price": 3,
        "status": "pending",
        "deposit": 0,
        "starting_price": 7,
        "city": "kept",
    }


def test_reset_removes_only_structured_sections(host):
    sections = (
        "source",
        "archive",
        "auction",
        "location",
        "property",
        "legal_context",
        "risk_flags",
        "audit",
    )
    preserved = {
        "id": "item",
        "title": "kept",
        "avm_risk_features": {"risk": True},
        "custom": [],
    }
    item = {**preserved, **{key: {"stale": True} for key in sections}}
    assert host._reset_structured_sections_for_resync(item) is None
    assert item == preserved
    assert item["avm_risk_features"] is preserved["avm_risk_features"]


def test_saved_patch_uses_replaced_alias_table(host, monkeypatch):
    from src.collection.adapters.auction_record_patch import AuctionRecordPatch

    for name in AuctionRecordPatch.__all__:
        assert isinstance(getattr(host, name).__self__, AuctionRecordPatch)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)
    apply = host._apply_flat_override_patch
    monkeypatch.setattr(host, "_FLAT_OVERRIDE_ALIAS_MAP", {"custom_alias": "custom"})
    item = {}
    apply(item, {"custom_alias": False, "status": "ignored"})
    assert item == {"custom": False}


def test_detail_patch_rebuilds_structure_before_publication(tmp_path):
    from src import server
    from src.collection.detail_service import DetailCollectionService

    original = {"id": "item", "transaction_price": 1, "auction": {"stale": True}}
    working = {"data": original, "file_path": "archive.json", "cached": True}
    stages = []

    def sync(item):
        assert "auction" not in item
        assert item["transaction_price"] == 2
        stages.append("sync")
        item["auction"] = {"transaction_price": item["transaction_price"]}

    def archive(_path, _item_id, item):
        assert original["transaction_price"] == 1
        assert item["auction"] == {"transaction_price": 2}
        stages.append("archive")

    def persist(_item, _event, _payload):
        assert original["transaction_price"] == 1
        stages.append("database")

    def removed(_item_id):
        assert original["auction"] == {"transaction_price": 2}
        stages.append("runtime")

    service = DetailCollectionService(
        tmp_path, adapter=SimpleNamespace(sync_record=sync)
    )
    result = service.apply_working_item_patch(
        item_id="item",
        patch_data={"currentPrice": 2},
        event_type="test",
        get_working_item=lambda *_args, **_kwargs: working,
        apply_flat_override_patch=server._apply_flat_override_patch,
        reset_structured_sections_for_resync=server._reset_structured_sections_for_resync,
        update_file_global=archive,
        persist_item_to_db=persist,
        evict_runtime_item=lambda _id: None,
        prefer_db_task_reads=lambda: False,
        remove_pending=removed,
    )
    assert result == {"status": "ok"}
    assert stages == ["sync", "archive", "database", "runtime"]
