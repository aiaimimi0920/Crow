"""Crow collection engine: rough discovery, detail capture, and AI archiving."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapter_resolver import collection_adapter_from_env, create_collection_adapter
    from .adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
    from .detail_extractors import CallableDetailExtractor
    from .detail_service import DetailCollectionService
    from .readiness import generic_product_analysis_missing_fields
    from .seed_list_parser import (
        GenericJsonSeedListParser,
        SeedListParser,
        SeedListParseResult,
        TaobaoSeedListParser,
        normalize_source_item_id,
    )
    from .seed_scan_policy import (
        DEFAULT_SEED_SCAN_POLICY,
        GenericSeedScanPolicy,
        SeedScanPolicy,
        TaobaoJudicialSeedScanPolicy,
    )
    from .seed_service import SeedCollectionService
    from .stage_state import derive_stage_state

_EXPORT_MODULES = {
    "DetailCollectionService": ".detail_service",
    "CallableDetailExtractor": ".detail_extractors",
    "collection_adapter_from_env": ".adapter_resolver",
    "create_collection_adapter": ".adapter_resolver",
    "DEFAULT_SEED_SCAN_POLICY": ".seed_scan_policy",
    "GenericProductAdapter": ".adapters.generic_product",
    "GenericJsonSeedListParser": ".seed_list_parser",
    "GenericSeedScanPolicy": ".seed_scan_policy",
    "generic_product_analysis_missing_fields": ".readiness",
    "normalize_source_item_id": ".seed_list_parser",
    "SeedCollectionService": ".seed_service",
    "SeedListParseResult": ".seed_list_parser",
    "SeedListParser": ".seed_list_parser",
    "SeedScanPolicy": ".seed_scan_policy",
    "TaobaoJudicialAuctionAdapter": ".adapters.taobao_judicial",
    "TaobaoSeedListParser": ".seed_list_parser",
    "TaobaoJudicialSeedScanPolicy": ".seed_scan_policy",
    "derive_stage_state": ".stage_state",
}


def __getattr__(name: str) -> object:
    # URL policies must not initialize detail capture, AVM, or LLM dependencies.
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "DetailCollectionService",
    "CallableDetailExtractor",
    "collection_adapter_from_env",
    "create_collection_adapter",
    "DEFAULT_SEED_SCAN_POLICY",
    "GenericProductAdapter",
    "GenericJsonSeedListParser",
    "GenericSeedScanPolicy",
    "generic_product_analysis_missing_fields",
    "normalize_source_item_id",
    "SeedCollectionService",
    "SeedListParseResult",
    "SeedListParser",
    "SeedScanPolicy",
    "TaobaoJudicialAuctionAdapter",
    "TaobaoSeedListParser",
    "TaobaoJudicialSeedScanPolicy",
    "derive_stage_state",
]
