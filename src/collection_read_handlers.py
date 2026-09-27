"""Collection console resources and query HTTP adapters with live host callbacks."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol
from urllib.parse import unquote

Query = dict[str, list[str]]


class ResponseStream(Protocol):
    def write(self, data: bytes) -> object: ...


class CollectionReadHandler(Protocol):
    wfile: ResponseStream

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self,
        *,
        status: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None: ...
    def send_response(self, code: int) -> None: ...
    def send_header(self, keyword: str, value: str) -> None: ...
    def end_headers(self) -> None: ...


class ObserverRepository(Protocol):
    enabled: bool


class CollectionReadHost(Protocol):
    DB_REPOSITORY: ObserverRepository

    def _collection_observer_page_html(self) -> str: ...
    def _collection_observer_static_asset(
        self, request_path: str
    ) -> tuple[bytes, str] | None: ...
    def _collection_observer_overview_payload(self) -> object: ...
    def _collection_observer_items_payload(self, query: Query) -> object: ...
    def _collection_observer_regions_payload(self, query: Query) -> object: ...
    def _collection_observer_item_payload(self, query: Query) -> dict[str, object]: ...


GetHandler = Callable[[CollectionReadHandler, object, str, Query], None]


@dataclass(frozen=True)
class CollectionReadHandlers:
    _get_collection_index: GetHandler
    _get_collection_asset: GetHandler
    _get_collection_overview: GetHandler
    _get_collection_items: GetHandler
    _get_collection_regions: GetHandler
    _get_collection_item: GetHandler
    __all__: ClassVar[list[str]] = [
        "_get_collection_index",
        "_get_collection_asset",
        "_get_collection_overview",
        "_get_collection_items",
        "_get_collection_regions",
        "_get_collection_item",
    ]


def bind_collection_reads(host: CollectionReadHost) -> CollectionReadHandlers:
    def _get_collection_index(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        body = host._collection_observer_page_html().encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _get_collection_asset(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        asset = host._collection_observer_static_asset(request_path)
        if asset is None:
            handler.send_error_json(
                status=404,
                code="COLLECTION_STATIC_ASSET_NOT_FOUND",
                message="collection console 静态资源不存在",
                details={"path": request_path},
            )
            return
        body, content_type = asset
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _get_collection_overview(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            handler.send_json(host._collection_observer_overview_payload())
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_OVERVIEW_FAILED",
                message="collection observer overview 读取失败",
                details={"error": str(e)},
            )

    def _get_collection_items(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            handler.send_json(host._collection_observer_items_payload(query))
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_ITEMS_FAILED",
                message="collection observer item 列表读取失败",
                details={"error": str(e)},
            )

    def _get_collection_regions(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            handler.send_json(host._collection_observer_regions_payload(query))
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_REGIONS_FAILED",
                message="collection observer 地区状态读取失败",
                details={"error": str(e)},
            )

    def _get_collection_item(
        handler: CollectionReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            if request_path.startswith("/api/collection/items/"):
                query = dict(query)
                query["item_id"] = [unquote(request_path.rsplit("/", 1)[-1])]
            item_id = str((query.get("item_id") or [""])[0] or "").strip()
            if not item_id:
                handler.send_error_json(
                    status=400, code="AVM_INVALID_ID", message="item_id is required"
                )
                return
            observer_detail = getattr(
                host.DB_REPOSITORY, "collection_observer_item_detail", None
            )
            if not host.DB_REPOSITORY.enabled or not callable(observer_detail):
                handler.send_error_json(
                    status=503,
                    code="COLLECTION_OBSERVER_UNAVAILABLE",
                    message="Observer storage is unavailable",
                )
                return
            payload = host._collection_observer_item_payload(query)
            if payload.get("found") is False:
                handler.send_error_json(
                    status=404,
                    code="AVM_DETAIL_ITEM_NOT_FOUND",
                    message="Item not found",
                    details={"id": item_id},
                )
                return
            handler.send_json(payload)
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_ITEM_FAILED",
                message="collection observer item 详情读取失败",
                details={"error": str(e)},
            )

    return CollectionReadHandlers(
        _get_collection_index,
        _get_collection_asset,
        _get_collection_overview,
        _get_collection_items,
        _get_collection_regions,
        _get_collection_item,
    )
