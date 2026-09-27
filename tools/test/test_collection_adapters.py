from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from src.analysis_ensemble import (
    GENERIC_ANALYSIS_PROFILE,
    build_field_consensus,
    compose_final_payload,
)
from src.collection import (
    CallableDetailExtractor,
    DetailCollectionService,
    GenericProductAdapter,
    SeedCollectionService,
    TaobaoJudicialAuctionAdapter,
    collection_adapter_from_env,
    create_collection_adapter,
    derive_stage_state,
)


def test_generic_adapter_collects_arbitrary_product_seed(tmp_path: Path) -> None:
    target = tmp_path / "products.json"
    persisted: list[dict[str, object]] = []
    service = SeedCollectionService(
        data_root=str(tmp_path),
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    )

    result = service.submit_batch(
        {
            "items": [
                {
                    "sku": "sku-7",
                    "name": "Reusable product",
                    "detail_url": "https://catalog.example/items/sku-7",
                    "inventory": 12,
                }
            ]
        },
        parse_price=lambda value: value,
        safe_int=lambda value: value,
        prefer_db_task_reads=lambda: False,
        get_seen_entry=lambda _item_id: None,
        get_flat_item=lambda _item_id: None,
        get_data_path=lambda _partition: str(target),
        update_file_global=lambda *_args: None,
        persist_item_to_db=lambda item, *_args: persisted.append(dict(item)),
        evict_runtime_item=lambda _item_id: None,
        archive_list_payload=lambda *_args: None,
        set_seen=lambda *_args: None,
        queue_pending=lambda _item_id: True,
    )

    assert result == {"status": "ok", "new": 1}
    record = persisted[0]
    assert record["id"] == GenericProductAdapter(source_platform="catalog_x").item_id(
        {"sku": "sku-7"}
    )
    assert record["item_id"] == record["id"]
    assert record["source_item_id"] == "sku-7"
    assert record["source_platform"] == "catalog_x"
    assert record["source_title"] == "Reusable product"
    assert record["source_url"] == "https://catalog.example/items/sku-7"
    assert record["inventory"] == 12


def test_collection_services_default_to_source_neutral_adapter(tmp_path: Path) -> None:
    seed_service = SeedCollectionService()
    detail_service = DetailCollectionService(tmp_path)

    assert type(seed_service.adapter) is GenericProductAdapter
    assert type(detail_service.adapter) is GenericProductAdapter


def test_generic_seed_service_does_not_bootstrap_legacy_search_tasks() -> None:
    class RepositoryProbe:
        enabled = True

        def count_search_tasks(self) -> int:
            raise AssertionError("generic service must not inspect legacy search tasks")

    SeedCollectionService(repository=RepositoryProbe())._bootstrap_db_search_tasks()


def test_collection_adapter_factory_supports_runtime_compatibility_default() -> None:
    adapter = collection_adapter_from_env(
        default="taobao_judicial",
        environ={},
    )

    assert type(adapter) is TaobaoJudicialAuctionAdapter


def test_collection_adapter_factory_configures_generic_source_platform() -> None:
    adapter = collection_adapter_from_env(
        environ={
            "CROW_COLLECTION_ADAPTER": "generic",
            "CROW_COLLECTION_SOURCE_PLATFORM": "catalog_x",
        }
    )

    assert type(adapter) is GenericProductAdapter
    assert adapter.source_platform == "catalog_x"


def test_collection_adapter_factory_rejects_unknown_adapter() -> None:
    with pytest.raises(ValueError, match="unsupported collection adapter"):
        create_collection_adapter("typoed-adapter")


def test_generic_adapter_rejects_item_from_another_source_platform() -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")

    with pytest.raises(ValueError, match="does not match"):
        adapter.build_seed_record(
            {
                "id": "shared-1",
                "source_platform": "catalog_y",
                "url": "https://catalog.example/items/shared-1",
            },
            parse_number=lambda value: value,
            safe_int=lambda value: value,
        )


def test_server_collection_factories_keep_explicit_legacy_default(monkeypatch) -> None:
    monkeypatch.delenv("CROW_COLLECTION_ADAPTER", raising=False)
    monkeypatch.delenv("CROW_COLLECTION_SOURCE_PLATFORM", raising=False)
    server = importlib.import_module("src.server")

    assert type(server._seed_collection_service().adapter) is TaobaoJudicialAuctionAdapter
    assert type(server._detail_collection_service().adapter) is TaobaoJudicialAuctionAdapter


def test_server_collection_factories_honor_generic_runtime_config(monkeypatch) -> None:
    monkeypatch.setenv("CROW_COLLECTION_ADAPTER", "generic")
    monkeypatch.setenv("CROW_COLLECTION_SOURCE_PLATFORM", "catalog_x")
    server = importlib.import_module("src.server")

    seed_adapter = server._seed_collection_service().adapter
    detail_adapter = server._detail_collection_service().adapter
    assert type(seed_adapter) is GenericProductAdapter
    assert type(detail_adapter) is GenericProductAdapter
    assert seed_adapter.source_platform == "catalog_x"
    assert detail_adapter.source_platform == "catalog_x"


def test_seed_stub_uses_the_configured_adapter() -> None:
    service = SeedCollectionService(
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    )

    record = service.build_seed_stub(
        {
            "sku": "sku-8",
            "name": "Portable seed",
            "detail_url": "https://catalog.example/items/sku-8",
        },
        parse_price=lambda value: value,
        safe_int=lambda value: value,
    )

    assert record["source_item_id"] == "sku-8"
    assert record["item_id"] == GenericProductAdapter(source_platform="catalog_x").item_id(
        {"sku": "sku-8"}
    )
    assert record["source_platform"] == "catalog_x"
    assert record["source_title"] == "Portable seed"
    assert "auction_date" not in record


def test_generic_adapter_processes_alphanumeric_detail_id(tmp_path: Path) -> None:
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    html_path = html_dir / "item-sku-7.html"
    html_path.write_text("<html><body>price 99</body></html>", encoding="utf-8")
    updated: list[dict[str, object]] = []
    seed = {
        "source_item_id": "sku-7",
        "source_platform": "catalog_x",
        "inventory": 12,
        "url": "https://catalog.example/items/sku-7",
    }

    def reject_avm_callback(*_args, **_kwargs):
        raise AssertionError("generic detail collection must not invoke AVM callbacks")

    DetailCollectionService(
        tmp_path,
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    ).process_html_file(
        str(html_path),
        get_working_item=lambda *_args, **_kwargs: {
            "file_path": str(tmp_path / "products.json"),
            "data": seed,
        },
        get_data_path=lambda _partition: str(tmp_path / "products.json"),
        update_item_in_json=lambda _path, _item_id, record: updated.append(dict(record)),
        remove_item_from_json=lambda *_args: None,
        persist_item_to_db=lambda *_args: None,
        mark_item_deleted_in_db=lambda *_args: None,
        evict_runtime_item=lambda *_args: None,
        prefer_db_task_reads=lambda: False,
        sync_avm_risk_aliases=reject_avm_callback,
        extract_avm_risk_features=reject_avm_callback,
        log_prediction_event=lambda **_kwargs: None,
        queue_pending=lambda _item_id: True,
        set_seen=lambda *_args: None,
        remove_pending=lambda _item_id: None,
        detail_extractor=CallableDetailExtractor(
            lambda *_args, **_kwargs: json.dumps({"name": "Updated", "price": 99})
        ),
    )

    assert updated[0]["source_item_id"] == "sku-7"
    assert updated[0]["inventory"] == 12
    assert updated[0]["price"] == 99
    assert updated[0]["detail_captured"] is True
    assert updated[0]["is_processed"] is True


def test_generic_analysis_profile_has_no_auction_derived_fields() -> None:
    candidates = [{"price": "10"}, {"price": "10"}, {"price": "10"}]
    consensus = build_field_consensus(
        candidates,
        source_text="price 10",
        profile=GENERIC_ANALYSIS_PROFILE,
    )

    payload = compose_final_payload(
        consensus=consensus,
        adjudication=None,
        profile=GENERIC_ANALYSIS_PROFILE,
    )

    assert payload == {"price": "10", "is_processed": True}
    assert "单价" not in payload


def test_default_auction_analysis_profile_keeps_unit_aware_price_derivation() -> None:
    payload = compose_final_payload(
        consensus={
            "locked_fields": {
                "成交价格": {"value": "125万元"},
                "建筑面积": {"value": "100㎡"},
            }
        },
        adjudication=None,
    )

    assert payload["单价"] == 12_500.0


def test_generic_stage_state_does_not_require_auction_or_property_fields() -> None:
    state = derive_stage_state(
        {
            "source_item_id": "sku-7",
            "source_platform": "catalog_x",
            "source_url": "https://catalog.example/items/sku-7",
            "detail_archive_path": "html/sku-7.html",
            "detail_captured": True,
        },
    )

    assert state["seed_status"] == "stored"
    assert state["detail_status"] == "archived"
    assert state["analysis_ready"] is True
    assert state["analysis_missing_fields"] == []
    assert state["analysis_model_version"] == "generic_product_v1"


def test_stage_state_preserves_taobao_readiness_for_legacy_and_explicit_sources() -> None:
    for source_platform in (None, "taobao_sf", "https://sf.taobao.com/"):
        record = {
            "source_item_id": "legacy-7",
            "source_url": "https://sf.taobao.com/item/legacy-7",
            "detail_archive_path": "html/legacy-7.html",
            "detail_captured": True,
        }
        if source_platform is not None:
            record["source_platform"] = source_platform

        state = derive_stage_state(record)

        assert state["analysis_ready"] is False
        assert "auction_date" in state["analysis_missing_fields"]
        assert "status" in state["analysis_missing_fields"]
