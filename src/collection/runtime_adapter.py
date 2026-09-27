from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from .adapters.generic_product import GenericProductAdapter
from .adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from .contracts import CollectionAdapter, DetailExtractor
from .detail_extractors import resolve_detail_extractor

_TAOBAO_PLATFORMS = frozenset(
    {"taobao", "taobao_judicial", "taobao_sf", "sf.taobao.com"}
)


def resolve_record_adapter(
    record: Mapping[str, Any],
    *,
    configured: CollectionAdapter | None = None,
) -> CollectionAdapter:
    """Resolve domain behavior without treating every unlabelled source as Taobao."""

    declared = str(record.get("source_platform") or "").strip()
    if configured is not None:
        declared_platform = declared.lower()
        configured_platform = configured.source_platform.lower()
        aliases_match = (
            declared_platform in _TAOBAO_PLATFORMS
            and configured_platform in _TAOBAO_PLATFORMS
        )
        if declared and declared != configured.source_platform and not aliases_match:
            raise ValueError(
                "record source_platform does not match the configured collection adapter"
            )
        return configured

    if declared:
        if declared.lower() in _TAOBAO_PLATFORMS:
            return TaobaoJudicialAuctionAdapter()
        return GenericProductAdapter(source_platform=declared)

    source_url = str(
        record.get("source_url") or record.get("url") or record.get("detail_url") or ""
    ).strip()
    try:
        hostname = (urlsplit(source_url).hostname or "").lower()
    except ValueError:
        hostname = ""
    if hostname == "taobao.com" or hostname.endswith(".taobao.com"):
        return TaobaoJudicialAuctionAdapter()
    return GenericProductAdapter()


def extract_detail_payload(
    content: str,
    *,
    item_id: str,
    adapter: CollectionAdapter,
    detail_extractor: DetailExtractor | None = None,
    model: str | None = None,
) -> str:
    if detail_extractor is not None:
        if model is not None:
            raise ValueError("custom detail extractors do not support model override")
        return detail_extractor.extract(content, item_id=item_id)

    from src import llm_helper

    return resolve_detail_extractor(
        adapter=adapter, gateway=llm_helper, model=model
    ).extract(content, item_id=item_id)


__all__ = ["extract_detail_payload", "resolve_record_adapter"]
