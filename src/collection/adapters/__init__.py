"""Load adapter implementations only when their public exports are requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generic_product import GenericProductAdapter, GenericProductAnalysisProfile
    from .taobao_judicial import (
        TaobaoJudicialAnalysisProfile,
        TaobaoJudicialAuctionAdapter,
    )

_EXPORT_MODULES = {
    "GenericProductAdapter": ".generic_product",
    "GenericProductAnalysisProfile": ".generic_product",
    "TaobaoJudicialAuctionAdapter": ".taobao_judicial",
    "TaobaoJudicialAnalysisProfile": ".taobao_judicial",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "GenericProductAdapter",
    "GenericProductAnalysisProfile",
    "TaobaoJudicialAuctionAdapter",
    "TaobaoJudicialAnalysisProfile",
]
