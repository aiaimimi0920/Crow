from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, Protocol

from .adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from .contracts import CollectionAdapter, DetailExtractor


@dataclass(frozen=True)
class CallableDetailExtractor:
    """Adapt an existing JSON-string extraction function to DetailExtractor."""

    callback: Callable[..., str]

    def extract(self, content: str, *, item_id: str | None = None) -> str:
        return self.callback(content, item_id=item_id)


class DetailGateway(Protocol):
    extract_auction_data: Callable[..., str]
    extract_product_data: Callable[..., str]


def resolve_detail_extractor(
    *,
    adapter: CollectionAdapter,
    gateway: DetailGateway,
    model: str | None = None,
) -> DetailExtractor:
    callback = (
        gateway.extract_auction_data
        if isinstance(adapter, TaobaoJudicialAuctionAdapter)
        else gateway.extract_product_data
    )
    return CallableDetailExtractor(
        partial(callback, model=model) if model else callback
    )
