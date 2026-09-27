from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import llm_helper, llm_product_extraction
from src.collection import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from src.collection.runtime_adapter import resolve_record_adapter
from tools import detail_worker, live_batch_smoke, seed_collector


def test_unlabelled_non_taobao_record_uses_source_neutral_adapter() -> None:
    adapter = resolve_record_adapter({"url": "https://catalog.example/items/sku-1"})

    assert type(adapter) is GenericProductAdapter
    assert adapter.source_platform == "generic"


@pytest.mark.parametrize("legacy_platform", ["taobao", "taobao_judicial", "sf.taobao.com"])
def test_configured_taobao_adapter_accepts_legacy_platform_aliases(
    legacy_platform: str,
) -> None:
    configured = TaobaoJudicialAuctionAdapter()

    assert resolve_record_adapter(
        {"source_platform": legacy_platform},
        configured=configured,
    ) is configured


def test_generic_detail_record_requires_raw_source_identity() -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")

    with pytest.raises(ValueError, match="missing its source_item_id"):
        adapter.prepare_detail_record({}, existing={}, item_id="src-storage-hash")


def test_seed_config_derives_policy_from_explicit_adapter(tmp_path: Path) -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")

    config = seed_collector.SeedCollectorConfig(
        job_key="catalog-x",
        province="",
        city="",
        district="",
        location_code="source",
        category="catalog_x",
        sort_specs=(seed_collector.SeedSortSpec("source", "source", "default", 0),),
        max_page=1,
        cdp_endpoint="",
        output_dir=tmp_path,
        worker_id="worker-x",
        collection_adapter=adapter,
    )

    assert config.seed_scan_policy is not None
    assert config.seed_scan_policy.source_platform == "catalog_x"


def test_generic_detail_target_uses_explicit_source_url() -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")
    seed = {
        "item_id": adapter.item_id({"id": "sku-1"}),
        "source_item_id": "sku-1",
        "source_platform": "catalog_x",
        "url": "https://catalog.example/items/sku-1",
    }

    assert detail_worker._detail_seed_target_url(
        seed,
        str(seed["item_id"]),
        adapter=adapter,
    ) == seed["url"]

    with pytest.raises(ValueError, match="requires source URL"):
        detail_worker._detail_seed_target_url(
            {key: value for key, value in seed.items() if key != "url"},
            str(seed["item_id"]),
            adapter=adapter,
        )


def test_generic_product_extractor_rejects_non_object_json(monkeypatch) -> None:
    monkeypatch.setattr(llm_product_extraction, "chat_with_glm", lambda _prompt: "[]")

    with pytest.raises(ValueError, match="must return a JSON object"):
        llm_helper.extract_product_data("name: reusable item", item_id="sku-1")


def test_live_detail_runtime_uses_generic_extractor_and_preserves_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")
    item_id = adapter.item_id({"id": "sku-1"})
    seed = {
        "id": "sku-1",
        "item_id": item_id,
        "source_item_id": "sku-1",
        "source_platform": "catalog_x",
        "title": "Reusable item",
        "url": "https://catalog.example/items/sku-1",
    }
    html = "<html><body>Reusable item inventory 12</body></html>"

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_detail_html",
        lambda *_args, **_kwargs: (html, seed["url"], len(html), "unit-test"),
    )
    monkeypatch.setattr(
        llm_helper,
        "extract_product_data",
        lambda *_args, **_kwargs: json.dumps({"name": "Reusable item", "inventory": 12}),
    )
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic runtime must not use the auction extractor")
        ),
    )
    monkeypatch.setattr(
        llm_helper,
        "extract_avm_risk_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic runtime must not run AVM risk extraction")
        ),
    )

    selected = live_batch_smoke.process_item(
        object(),
        seed,
        {},
        config=live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="",
            target_url=seed["url"],
            target_success=1,
            max_attempts=1,
            do_risk=True,
            collection_adapter=adapter,
        ),
    )

    final_item = json.loads((tmp_path / item_id / "final.json").read_text(encoding="utf-8"))
    assert final_item["id"] == item_id
    assert final_item["source_item_id"] == "sku-1"
    assert final_item["source_platform"] == "catalog_x"
    assert final_item["source_url"] == seed["url"]
    assert final_item["inventory"] == 12
    assert final_item["detail_captured"] is True
    assert "auction" not in final_item
    assert selected["final_core"]["source_item_id"] == "sku-1"


def test_live_detail_runtime_preserves_seed_url_when_fetch_has_no_final_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")
    item_id = adapter.item_id({"id": "sku-2"})
    seed = {
        "item_id": item_id,
        "source_item_id": "sku-2",
        "source_platform": "catalog_x",
        "source_url": "https://catalog.example/items/sku-2",
    }
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_detail_html",
        lambda *_args, **_kwargs: ("<html>item</html>", "", 17, "unit-test"),
    )
    monkeypatch.setattr(
        llm_helper,
        "extract_product_data",
        lambda *_args, **_kwargs: json.dumps({"name": "item"}),
    )

    live_batch_smoke.process_item(
        object(),
        seed,
        {},
        config=live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="",
            target_url=seed["source_url"],
            target_success=1,
            max_attempts=1,
            do_risk=False,
            collection_adapter=adapter,
        ),
    )

    final_item = json.loads((tmp_path / item_id / "final.json").read_text(encoding="utf-8"))
    assert final_item["source_url"] == seed["source_url"]


def test_live_detail_runtime_normalizes_sparse_generic_seed_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = GenericProductAdapter(source_platform="catalog_x")
    seed = {
        "id": "sku-3",
        "source_platform": "catalog_x",
        "source_url": "https://catalog.example/items/sku-3",
    }
    expected_item_id = adapter.item_id(seed)
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_detail_html",
        lambda *_args, **_kwargs: ("<html>item</html>", seed["source_url"], 17, "unit-test"),
    )
    monkeypatch.setattr(
        llm_helper,
        "extract_product_data",
        lambda *_args, **_kwargs: json.dumps({"name": "item"}),
    )

    live_batch_smoke.process_item(
        object(),
        seed,
        {},
        config=live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="",
            target_url=seed["source_url"],
            target_success=1,
            max_attempts=1,
            do_risk=False,
            collection_adapter=adapter,
        ),
    )

    final_item = json.loads(
        (tmp_path / expected_item_id / "final.json").read_text(encoding="utf-8")
    )
    assert final_item["id"] == expected_item_id
    assert final_item["source_item_id"] == "sku-3"


def test_raw_analysis_normalizes_legacy_generic_seed_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    item_id = "src-existing-storage-id"
    item_dir = tmp_path / item_id
    item_dir.mkdir()
    seed = {
        "id": "legacy-sku-4",
        "source_platform": "catalog_x",
        "source_url": "https://catalog.example/items/legacy-sku-4",
    }
    live_batch_smoke.write_json(item_dir / "seed.json", seed)
    (item_dir / "detail.html").write_text("<html>legacy item</html>", encoding="utf-8")
    monkeypatch.setattr(
        llm_helper,
        "extract_product_data",
        lambda *_args, **_kwargs: json.dumps({"name": "legacy item"}),
    )

    live_batch_smoke.analyze_raw_item(item_id, output_dir=tmp_path)

    final_item = live_batch_smoke.load_json(item_dir / "final.json")
    assert final_item["id"] == item_id
    assert final_item["source_item_id"] == "legacy-sku-4"
    assert final_item["source_platform"] == "catalog_x"
