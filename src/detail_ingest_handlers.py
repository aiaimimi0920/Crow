"""Detail patch and HTML HTTP adapters preserving persistence ordering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

if TYPE_CHECKING:
    from .collection.detail_service import DetailCollectionService
    from .collection_runtime_index import CollectionRuntimeIndex

Record = dict[str, object]


class DetailIngestHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record | None = None
    ) -> None: ...


class DetailIngestHost(Protocol):
    REQUEST_BODY_HTML_MAX_BYTES: int
    logger: Logger

    def _collection_runtime_index(self) -> CollectionRuntimeIndex: ...
    def _read_json_body(
        self, handler: DetailIngestHandler, *, max_bytes: int | None = None
    ) -> tuple[bool, Record]: ...
    def _detail_collection_service(self) -> DetailCollectionService: ...
    def _get_working_item(
        self, item_id: str, include_processed: bool = False
    ) -> Record | None: ...
    def _apply_flat_override_patch(self, data: Record, patch: Record) -> None: ...
    def _reset_structured_sections_for_resync(self, data: Record) -> None: ...
    def update_file_global(self, path: str, item_id: str, data: Record) -> None: ...
    def persist_item_to_db(
        self, data: Record, event_type: str, payload: Record | None = None
    ) -> None: ...
    def _evict_runtime_item(self, item_id: str) -> None: ...
    def _prefer_db_task_reads(self) -> bool: ...
    def submit_task(self, path: str) -> None: ...


@dataclass(frozen=True)
class DetailIngestHandlers:
    _post_detail_update_item: Callable[[DetailIngestHandler], None]
    _post_detail_html: Callable[[DetailIngestHandler], None]
    _post_area_result: Callable[[DetailIngestHandler], None]
    _post_approve_area: Callable[[DetailIngestHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_detail_update_item",
        "_post_detail_html",
        "_post_area_result",
        "_post_approve_area",
    ]


def bind_detail_ingest(host: DetailIngestHost) -> DetailIngestHandlers:
    def _post_detail_update_item(handler: DetailIngestHandler) -> None:
        runtime_index = host._collection_runtime_index()
        accepted, data = host._read_json_body(handler)
        if not accepted:
            return
        try:
            item_id = str(data.get("id") or "").strip()
            if not item_id:
                handler.send_error_json(
                    status=400, code="AVM_INVALID_ID", message="id is required"
                )
                return
            force_status = (
                "failed_timeout" if data.get("status") == "failed_timeout" else None
            )
            result = cast(
                Record,
                host._detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="update_item",
                    get_working_item=host._get_working_item,
                    apply_flat_override_patch=host._apply_flat_override_patch,
                    reset_structured_sections_for_resync=host._reset_structured_sections_for_resync,
                    update_file_global=host.update_file_global,
                    persist_item_to_db=host.persist_item_to_db,
                    evict_runtime_item=host._evict_runtime_item,
                    prefer_db_task_reads=host._prefer_db_task_reads,
                    remove_pending=runtime_index.remove_pending,
                    force_status=force_status,
                ),
            )
            if result["status"] == "ok":
                if force_status == "failed_timeout":
                    host.logger.info("Item %s TIMED OUT.", item_id)
                handler.send_json({"status": "updated"})
            elif result["status"] == "id_not_found":
                handler.send_error_json(
                    status=404,
                    code="AVM_DETAIL_ITEM_NOT_FOUND",
                    message="Item not found",
                    details={"id": item_id},
                )
            else:
                handler.send_error_json(
                    status=500,
                    code="AVM_DETAIL_UPDATE_ITEM_FAILED",
                    message="Unexpected update result",
                )
        except Exception as error:  # noqa: BLE001 - preserve HTTP patch error boundary
            handler.send_error_json(
                status=500,
                code="AVM_DETAIL_UPDATE_ITEM_FAILED",
                message="条目更新失败",
                details={"error": str(error)},
            )

    def _post_detail_html(handler: DetailIngestHandler) -> None:
        runtime_index = host._collection_runtime_index()
        accepted, data = host._read_json_body(
            handler, max_bytes=host.REQUEST_BODY_HTML_MAX_BYTES
        )
        if not accepted:
            return
        try:
            item_id = str(data.get("id") or "").strip()
            if not item_id:
                handler.send_error_json(
                    status=400, code="AVM_INVALID_ID", message="id is required"
                )
                return
            html_content = data.get("html", "")
            status = data.get("status")
            result = cast(
                Record,
                host._detail_collection_service().submit_html(
                    item_id=item_id,
                    html_content=html_content,
                    status=status,
                    get_working_item=host._get_working_item,
                    apply_flat_override_patch=host._apply_flat_override_patch,
                    reset_structured_sections_for_resync=host._reset_structured_sections_for_resync,
                    update_file_global=host.update_file_global,
                    persist_item_to_db=host.persist_item_to_db,
                    evict_runtime_item=host._evict_runtime_item,
                    submit_task=host.submit_task,
                    prefer_db_task_reads=host._prefer_db_task_reads,
                    remove_pending=runtime_index.remove_pending,
                ),
            )
            if result.get("status") == "id_not_found":
                handler.send_error_json(
                    status=404,
                    code="AVM_DETAIL_ITEM_NOT_FOUND",
                    message="Item not found",
                    details={"id": item_id},
                )
                return
            handler.send_json(result)
        except Exception as error:
            host.logger.exception("Error saving HTML content")
            handler.send_error_json(
                status=500,
                code="AVM_DETAIL_ANALYZE_HTML_FAILED",
                message="HTML 分析结果提交失败",
                details={"error": str(error)},
            )

    def _post_area_result(handler: DetailIngestHandler) -> None:
        accepted, data = host._read_json_body(handler)
        if not accepted:
            return
        try:
            runtime_index = host._collection_runtime_index()
            item_id = str(data.get("id"))
            result = cast(
                Record,
                host._detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="area_result",
                    get_working_item=host._get_working_item,
                    apply_flat_override_patch=host._apply_flat_override_patch,
                    reset_structured_sections_for_resync=host._reset_structured_sections_for_resync,
                    update_file_global=host.update_file_global,
                    persist_item_to_db=host.persist_item_to_db,
                    evict_runtime_item=host._evict_runtime_item,
                    prefer_db_task_reads=host._prefer_db_task_reads,
                    remove_pending=runtime_index.remove_pending,
                    mark_processed=True,
                ),
            )
            if result["status"] == "ok":
                host.logger.info(
                    "[AREA RESULT] Updated %s | Area: %s",
                    item_id,
                    data.get("建筑面积", 0),
                )
                handler.send_json(result)
            else:
                host.logger.warning("[AREA RESULT] Item %s not found in index", item_id)
                handler.send_error_json(
                    status=404,
                    code="AVM_DETAIL_ITEM_NOT_FOUND",
                    message="未找到目标条目",
                    details={"id": item_id},
                )
        except Exception as error:
            host.logger.exception("Error processing area result")
            handler.send_error_json(
                status=500,
                code="AVM_DETAIL_AREA_RESULT_FAILED",
                message="面积结果回写失败",
                details={"error": str(error)},
            )

    def _post_approve_area(handler: DetailIngestHandler) -> None:
        accepted, data = host._read_json_body(handler)
        if not accepted:
            return
        try:
            runtime_index = host._collection_runtime_index()
            item_id = str(data.get("id"))
            result = cast(
                Record,
                host._detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="manual_approve_area",
                    get_working_item=host._get_working_item,
                    apply_flat_override_patch=host._apply_flat_override_patch,
                    reset_structured_sections_for_resync=host._reset_structured_sections_for_resync,
                    update_file_global=host.update_file_global,
                    persist_item_to_db=host.persist_item_to_db,
                    evict_runtime_item=host._evict_runtime_item,
                    prefer_db_task_reads=host._prefer_db_task_reads,
                    remove_pending=runtime_index.remove_pending,
                    mark_processed=True,
                    force_status="done",
                ),
            )
            if result["status"] == "ok":
                host.logger.info(
                    "[APPROVE AREA] Manually Approved %s | Area: %s",
                    item_id,
                    data.get("建筑面积", 0),
                )
                handler.send_json(result)
            else:
                host.logger.warning(
                    "[APPROVE AREA] Item %s not found in index", item_id
                )
                handler.send_error_json(
                    status=404,
                    code="AVM_DETAIL_ITEM_NOT_FOUND",
                    message="未找到目标条目",
                    details={"id": item_id},
                )
        except Exception as error:
            host.logger.exception("Error processing area approval")
            handler.send_error_json(
                status=500,
                code="AVM_DETAIL_APPROVE_AREA_FAILED",
                message="面积人工确认失败",
                details={"error": str(error)},
            )

    return DetailIngestHandlers(
        _post_detail_update_item,
        _post_detail_html,
        _post_area_result,
        _post_approve_area,
    )
