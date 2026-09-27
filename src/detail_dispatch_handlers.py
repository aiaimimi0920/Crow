"""Native POST detail-task dispatch using the current server dependencies."""

from __future__ import annotations

from collections.abc import Callable, Sized
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

if TYPE_CHECKING:
    from .collection.detail_service import DetailCollectionService
    from .collection_runtime_index import CollectionRuntimeIndex


class DetailDispatchHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...


class DetailDispatchHost(Protocol):
    DISPATCH_COOLDOWN_SECONDS: int
    logger: Logger

    def _collection_runtime_index(self) -> CollectionRuntimeIndex: ...
    def _read_json_body(
        self, handler: DetailDispatchHandler
    ) -> tuple[bool, object]: ...
    def _collection_scope_effectively_paused(self, scope: str) -> bool: ...
    def _prefer_db_task_reads(self) -> bool: ...
    def _detail_collection_service(self) -> DetailCollectionService: ...
    def _utc_now(self) -> datetime: ...


@dataclass(frozen=True)
class DetailDispatchHandlers:
    _post_detail_tasks: Callable[[DetailDispatchHandler], None]
    _post_detail_next_task: Callable[[DetailDispatchHandler], None]
    _post_detail_next_visit: Callable[[DetailDispatchHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_detail_tasks",
        "_post_detail_next_task",
        "_post_detail_next_visit",
    ]


def bind_detail_dispatch(host: DetailDispatchHost) -> DetailDispatchHandlers:
    def _post_detail_tasks(handler: DetailDispatchHandler) -> None:
        runtime_index = host._collection_runtime_index()
        accepted, _payload = host._read_json_body(handler)
        if not accepted:
            return
        if host._collection_scope_effectively_paused("detail"):
            handler.send_json({"tasks": []})
            return
        batch_size = 300
        if host._prefer_db_task_reads():
            try:
                _, _, dispatched_snapshot = runtime_index.state_snapshot()
                result = cast(
                    dict[str, object],
                    host._detail_collection_service().batch_tasks(
                        dispatched_tasks=dispatched_snapshot,
                        cooldown_seconds=host.DISPATCH_COOLDOWN_SECONDS,
                        batch_size=batch_size,
                        mark_dispatched=runtime_index.mark_dispatched,
                        get_dispatched=runtime_index.get_dispatched,
                        prune_dispatched=runtime_index.prune_dispatched,
                    ),
                )
            except Exception as error:  # noqa: BLE001 - preserve HTTP service error boundary
                handler.send_error_json(
                    status=500,
                    code="AVM_DETAIL_BATCH_TASKS_FAILED",
                    message="详情批量任务分发失败",
                    details={"error": str(error)},
                )
                return
            handler.send_json(
                {
                    "tasks": result["tasks"],
                    "total": result["total"],
                    "done": result["done"],
                }
            )
            if len(cast(Sized, result["tasks"])) > 0:
                host.logger.info(
                    "Dispatched detail tasks count=%s batch_limit=%s pending=%s",
                    len(cast(Sized, result["tasks"])),
                    batch_size,
                    result["pending"],
                )
            else:
                host.logger.debug("Returned zero detail tasks")
            return
        tasks, total_count, done_count, pending_count = (
            runtime_index.claim_pending_batch(
                host._utc_now(), host.DISPATCH_COOLDOWN_SECONDS, batch_size
            )
        )
        handler.send_json({"tasks": tasks, "total": total_count, "done": done_count})
        host.logger.info(
            "Dispatched detail tasks count=%s batch_limit=%s pending=%s",
            len(tasks),
            batch_size,
            pending_count,
        )

    def _post_detail_next_task(handler: DetailDispatchHandler) -> None:
        runtime_index = host._collection_runtime_index()
        _, _, dispatched_snapshot = runtime_index.state_snapshot()
        accepted, _payload = host._read_json_body(handler)
        if not accepted:
            return
        if host._prefer_db_task_reads():
            try:
                next_task = host._detail_collection_service().next_task(
                    dispatched_tasks=dispatched_snapshot,
                    cooldown_seconds=host.DISPATCH_COOLDOWN_SECONDS,
                    dispatch_lock=runtime_index.lock,
                    mark_dispatched=runtime_index.mark_dispatched,
                    get_dispatched=runtime_index.get_dispatched,
                    prune_dispatched=runtime_index.prune_dispatched,
                )
            except Exception as error:  # noqa: BLE001 - preserve HTTP service error boundary
                handler.send_error_json(
                    status=500,
                    code="AVM_DETAIL_NEXT_TASK_FAILED",
                    message="详情任务分发失败",
                    details={"error": str(error)},
                )
                return
            handler.send_json(next_task if next_task else {})
            return
        now = host._utc_now()
        item = runtime_index.claim_next_pending(now, host.DISPATCH_COOLDOWN_SECONDS)
        next_task = {"url": item.get("url")} if item is not None else None
        handler.send_json(next_task if next_task else {})

    def _post_detail_next_visit(handler: DetailDispatchHandler) -> None:
        runtime_index = host._collection_runtime_index()
        accepted, _payload = host._read_json_body(handler)
        if not accepted:
            return
        if hasattr(runtime_index, "state_snapshot"):
            seen_ids, _pending, dispatched_snapshot = runtime_index.state_snapshot()
        else:
            with runtime_index.lock:
                seen_ids = dict(runtime_index.seen_ids)
                dispatched_snapshot = dict(runtime_index.dispatched_tasks)
        legacy_entries = None
        if not host._prefer_db_task_reads():
            legacy_entries = list(seen_ids.items())
        try:
            result = host._detail_collection_service().next_visit_task(
                dispatched_tasks=dispatched_snapshot,
                cooldown_seconds=host.DISPATCH_COOLDOWN_SECONDS,
                legacy_entries=legacy_entries,
                dispatch_lock=runtime_index.lock,
                mark_dispatched=getattr(runtime_index, "mark_dispatched", None),
                get_dispatched=getattr(runtime_index, "get_dispatched", None),
                prune_dispatched=getattr(runtime_index, "prune_dispatched", None),
            )
        except Exception as error:  # noqa: BLE001 - preserve visit dispatch error boundary
            handler.send_error_json(
                status=500,
                code="AVM_NEXT_VISIT_TASK_FAILED",
                message="下一条访问任务分发失败",
                details={"error": str(error)},
            )
            return
        handler.send_json(result)

    return DetailDispatchHandlers(
        _post_detail_tasks, _post_detail_next_task, _post_detail_next_visit
    )
