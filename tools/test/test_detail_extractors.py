from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.collection.adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from src.collection.detail_extractors import (
    CallableDetailExtractor,
    resolve_detail_extractor,
)
from src.collection.runtime_adapter import extract_detail_payload


def test_callable_detail_extractor_forwards_item_id() -> None:
    calls: list[tuple[str, str | None]] = []
    extractor = CallableDetailExtractor(
        lambda content, item_id=None: calls.append((content, item_id)) or "{}"
    )

    assert extractor.extract("page", item_id="sku-7") == "{}"
    assert calls == [("page", "sku-7")]


@pytest.mark.parametrize("auction", [False, True])
@pytest.mark.parametrize("model", [None, "isolated-model"])
def test_resolve_detail_extractor_uses_source_policy(auction, model) -> None:
    calls = []

    def extract(kind, content, **options):
        calls.append((kind, content, options))
        return "{}"

    gateway = SimpleNamespace(
        extract_auction_data=lambda content, **options: extract(
            "auction", content, **options
        ),
        extract_product_data=lambda content, **options: extract(
            "product", content, **options
        ),
    )
    extractor = resolve_detail_extractor(
        adapter=TaobaoJudicialAuctionAdapter() if auction else GenericProductAdapter(),
        gateway=gateway,
        model=model,
    )

    assert extractor.extract("page", item_id="source-7") == "{}"
    options = {"item_id": "source-7", **({"model": model} if model else {})}
    assert calls == [("auction" if auction else "product", "page", options)]


def test_custom_detail_extractor_rejects_ambiguous_model_override() -> None:
    extractor = CallableDetailExtractor(lambda *_args, **_kwargs: "{}")
    with pytest.raises(ValueError, match="do not support model override"):
        extract_detail_payload(
            "page",
            item_id="source-7",
            adapter=GenericProductAdapter(),
            detail_extractor=extractor,
            model="ambiguous-model",
        )
