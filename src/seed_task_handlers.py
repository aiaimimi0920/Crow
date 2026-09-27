"""Native seed admission, task claim and progress-report HTTP handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from .collection.seed_service import SeedCollectionService


class SeedTaskHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...
    def _enqueue_collection_job(
        self,
        kind: str,
        work: Callable[[], object],
        error_code: str,
        *,
        response_extra: dict[str, object],
    ) -> object: ...


class SeedTaskHost(Protocol):
    logger: Logger

    def _read_json_body(
        self, handler: SeedTaskHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _seed_collection_service(self) -> SeedCollectionService: ...
    def _collection_scope_effectively_paused(self, scope: str) -> bool: ...
    def _require_control_plane(self, handler: SeedTaskHandler) -> bool: ...
    def handle_seed_batch_submission(self, payload: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class SeedTaskHandlers:
    _post_seed_next_task: Callable[[SeedTaskHandler], None]
    _post_seed_progress: Callable[[SeedTaskHandler], None]
    _post_seed_batch: Callable[[SeedTaskHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_seed_next_task",
        "_post_seed_progress",
        "_post_seed_batch",
    ]


def bind_seed_tasks(host: SeedTaskHost) -> SeedTaskHandlers:
    def _post_seed_next_task(handler: SeedTaskHandler) -> None:
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        session_id = payload.get("session_id", "default")
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 128
        ):
            handler.send_error_json(
                status=400,
                code="AVM_INVALID_SESSION_ID",
                message="Invalid collection session ID",
                details={},
            )
            return
        try:
            handler.send_json(
                host._seed_collection_service().next_task(
                    session_id, paused=host._collection_scope_effectively_paused("seed")
                )
            )
        except Exception as error:  # noqa: BLE001 - preserve HTTP service error boundary
            handler.send_error_json(
                status=500,
                code="AVM_SEED_NEXT_TASK_FAILED",
                message="种子任务分发失败",
                details={"error": str(error)},
            )

    def _post_seed_progress(handler: SeedTaskHandler) -> None:
        accepted, data = host._read_json_body(handler)
        if not accepted:
            return
        try:
            url = data.get("url")
            task_key = data.get("task_key")
            has_next = data.get("has_next", True)
            is_empty = data.get("is_empty", False)
            page_num = data.get("page_num", 1)
            total_pages = data.get("total_pages")
            zero_bid_detected = data.get("zero_bid_detected", False)
            log_msg = f"[SNIFF REPORT] Page {page_num} | Next: {has_next} | Empty: {is_empty} | TotalPages: {total_pages}"
            if zero_bid_detected:
                log_msg += " | [ZERO-BID EARLY TERMINATION]"
            host.logger.info("%s | URL: %s", log_msg, url)
            if url or task_key:
                handler.send_json(host._seed_collection_service().report_progress(data))
            else:
                handler.send_error_json(
                    status=400,
                    code="AVM_SEED_PROGRESS_MISSING_URL",
                    message="缺少 URL 或 task_key",
                    details={"required_any": ["url", "task_key"]},
                )
        except ValueError as error:
            host.logger.warning("Invalid report_sniff_status payload: %s", error)
            handler.send_error_json(
                status=400,
                code="AVM_SEED_PROGRESS_INVALID",
                message="种子进度参数无效",
                details={"error": str(error)},
            )
        except Exception as error:
            host.logger.exception("Error in report_sniff_status")
            handler.send_error_json(
                status=500,
                code="AVM_SEED_PROGRESS_FAILED",
                message="种子进度回报失败",
                details={"error": str(error)},
            )

    def _post_seed_batch(self: SeedTaskHandler) -> None:
        accepted, data = host._read_json_body(self)
        if not accepted:
            return
        mode = str(data.get("mode", "sync") or "sync").lower()
        if mode == "async":
            if not host._require_control_plane(self):
                return
            submission_data = {
                key: value for key, value in data.items() if key != "mode"
            }

            def run() -> object:
                return host.handle_seed_batch_submission(submission_data)

            self._enqueue_collection_job(
                "seed_batch",
                run,
                "AVM_SEED_BATCH_ASYNC_FAILED",
                response_extra={"execution_mode": "async"},
            )
            return
        try:
            self.send_json(host.handle_seed_batch_submission(data))
        except Exception as error:
            host.logger.exception("Error processing save")
            self.send_error_json(
                status=500,
                code="AVM_SEED_BATCH_FAILED",
                message="种子批量提交失败",
                details={"error": str(error)},
            )

    return SeedTaskHandlers(_post_seed_next_task, _post_seed_progress, _post_seed_batch)
