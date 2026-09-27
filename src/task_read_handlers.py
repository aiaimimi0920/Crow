"""Task item and pipeline reads plus HTTP fallback/maintenance adapters."""

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast
from urllib.parse import parse_qs, urlparse


class TaskReadHandler(Protocol):
    path: str

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
    def end_headers(self) -> None: ...
    def _submit_maintenance_job(self, action: str, code: str) -> None: ...


class ItemRepository(Protocol):
    enabled: bool

    def get_flat_item(self, item_id: str) -> object: ...


class ItemIndex(Protocol):
    lock: AbstractContextManager[object]
    seen_ids: Mapping[str, dict[str, object]]


class TaskPipeline(Protocol):
    def status(self) -> object: ...
    def verify_merge_completeness(self) -> object: ...


class TaskReadHost(Protocol):
    AVM_PIPELINE: TaskPipeline
    DB_REPOSITORY: ItemRepository
    logger: logging.Logger

    def _collection_runtime_index(self) -> ItemIndex: ...


GetHandler = Callable[[TaskReadHandler, object, str, object], None]


@dataclass(frozen=True)
class TaskReadHandlers:
    _get_pipeline_status: GetHandler
    _get_merge_check: GetHandler
    _get_item: GetHandler
    _get_api_not_found: GetHandler
    _server_get_fallback: GetHandler
    _post_recent_detail_replay: Callable[[TaskReadHandler], None]
    __all__: ClassVar[list[str]] = [
        "_get_pipeline_status",
        "_get_merge_check",
        "_get_item",
        "_get_api_not_found",
        "_server_get_fallback",
        "_post_recent_detail_replay",
    ]


def bind_task_reads(host: TaskReadHost) -> TaskReadHandlers:
    def _get_pipeline_status(
        handler: TaskReadHandler, parsed: object, request_path: str, query: object
    ) -> None:
        try:
            handler.send_json(host.AVM_PIPELINE.status())
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_PIPELINE_STATUS_FAILED",
                message="pipeline 状态查询失败",
                details={"error": str(e)},
            )

    def _get_merge_check(
        handler: TaskReadHandler, parsed: object, request_path: str, query: object
    ) -> None:
        try:
            handler.send_json(host.AVM_PIPELINE.verify_merge_completeness())
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MERGE_CHECK_FAILED",
                message="merge completeness 校验失败",
                details={"error": str(e)},
            )

    def _get_item(
        handler: TaskReadHandler, parsed: object, request_path: str, query: object
    ) -> None:
        runtime_index = host._collection_runtime_index()
        params = parse_qs(urlparse(handler.path).query)
        item_id = params.get("id", [""])[0].strip()
        if not item_id:
            handler.send_error_json(
                status=400, code="AVM_INVALID_ID", message="id is required"
            )
            return
        lookup_failed = False
        if item_id and host.DB_REPOSITORY.enabled:
            try:
                db_item = host.DB_REPOSITORY.get_flat_item(item_id)
                if db_item:
                    handler.send_json(db_item)
                    return
            except Exception:
                lookup_failed = True
                host.logger.exception(
                    "/api/get_item database lookup failed item=%s", item_id
                )
        get_seen = cast(
            Callable[[str], dict[str, object] | None] | None,
            getattr(runtime_index, "get_seen", None),
        )
        if get_seen is not None:
            runtime_entry = get_seen(item_id)
        else:
            with runtime_index.lock:
                runtime_entry = runtime_index.seen_ids.get(item_id)
        if runtime_entry is not None:
            handler.send_json(runtime_entry["data"])
        elif lookup_failed:
            handler.send_error_json(
                status=503,
                code="AVM_ITEM_LOOKUP_UNAVAILABLE",
                message="Item storage is unavailable",
            )
        else:
            handler.send_error_json(
                status=404,
                code="AVM_DETAIL_ITEM_NOT_FOUND",
                message="Item not found",
                details={"id": item_id},
            )

    def _get_api_not_found(
        handler: TaskReadHandler, parsed: object, request_path: str, query: object
    ) -> None:
        handler.send_error_json(
            status=404,
            code="AVM_ENDPOINT_NOT_FOUND",
            message="未找到接口",
            details={"path": request_path},
        )

    def _server_get_fallback(
        handler: TaskReadHandler, parsed: object, request_path: str, query: object
    ) -> None:
        handler.send_response(404)
        handler.end_headers()

    def _post_recent_detail_replay(self: TaskReadHandler) -> None:
        self._submit_maintenance_job(
            "recent_detail_replay", "AVM_RECENT_DETAIL_REPLAY_FAILED"
        )

    return TaskReadHandlers(
        _get_pipeline_status,
        _get_merge_check,
        _get_item,
        _get_api_not_found,
        _server_get_fallback,
        _post_recent_detail_replay,
    )
