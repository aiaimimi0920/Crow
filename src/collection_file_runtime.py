"""Native detail-file dispatch and background discovery orchestration."""

import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, ClassVar, Protocol

from .collection.detail_execution import DetailModels, DetailRuntime, DetailStorage
from .collection.detail_extractors import resolve_detail_extractor
from .collection.detail_failures import DetailFailures
from .collection_index_bootstrap import BootstrapGlob
from .collection_runtime_index import CollectionRuntimeIndex
from .runtime_state import RuntimeState

if TYPE_CHECKING:
    from .collection.detail_service import DetailCollectionService

logger = logging.getLogger(__name__)


class FilePaths(Protocol):
    join: Callable[..., str]


class FileFilesystem(Protocol):
    path: FilePaths


class FileClock(Protocol):
    def sleep(self, seconds: float) -> None: ...


class FileModel(Protocol):
    extract_auction_data: Callable[..., str]
    extract_product_data: Callable[..., str]
    extract_avm_risk_features: Callable[[str, str | None], dict[str, object]]
    log_prediction_event: Callable[..., None]


class FileExecutor(Protocol):
    def submit(self, worker: Callable[[str], None], path: str) -> Future[None]: ...


class CollectionFileHost(Protocol):
    DATA_DIR: str
    RUNTIME: RuntimeState
    glob: BootstrapGlob
    os: FileFilesystem
    time: FileClock
    llm_helper: FileModel
    executor: FileExecutor
    process_single_file: Callable[[str], None]
    _collection_runtime_index: Callable[[], CollectionRuntimeIndex]
    _detail_collection_service: Callable[[], "DetailCollectionService"]
    _get_working_item: Callable[[str, bool], dict[str, object] | None]
    update_item_in_json: Callable[[str, str, dict[str, object]], None]
    remove_item_from_json: Callable[[str, str], None]
    persist_item_to_db: Callable[
        [dict[str, object], str, dict[str, object] | None], None
    ]
    mark_item_deleted_in_db: Callable[[str, str, dict[str, object] | None], None]
    _evict_runtime_item: Callable[[str], None]
    _prefer_db_task_reads: Callable[[], bool]
    sync_avm_risk_aliases: Callable[[dict[str, object]], dict[str, object]]
    submit_task: Callable[[str], None]


@dataclass(frozen=True)
class CollectionFileRuntime:
    host: CollectionFileHost

    __all__: ClassVar[list[str]] = [
        "process_single_file",
        "background_file_processor",
        "submit_task",
    ]

    def submit_task(self, file_path: str) -> None:
        host = self.host
        if not DetailFailures(Path(host.DATA_DIR)).ready(file_path):
            return
        processing = host.RUNTIME.processing
        if not processing.claim(file_path):
            return
        try:
            future = host.executor.submit(host.process_single_file, file_path)
            future.add_done_callback(lambda _future: processing.release(file_path))
        except Exception:
            logger.exception("Failed to submit task file=%s", file_path)
            processing.release(file_path)

    def process_single_file(self, file_path: str) -> None:
        host = self.host
        collection = host._collection_runtime_index()
        service = host._detail_collection_service()
        service.process_html_file(
            file_path,
            storage=DetailStorage(
                get_working_item=host._get_working_item,
                update_item_in_json=host.update_item_in_json,
                remove_item_from_json=host.remove_item_from_json,
                persist_item_to_db=host.persist_item_to_db,
                mark_item_deleted_in_db=host.mark_item_deleted_in_db,
            ),
            runtime=DetailRuntime(
                evict_runtime_item=host._evict_runtime_item,
                prefer_db_task_reads=host._prefer_db_task_reads,
                queue_pending=collection.queue_pending,
                set_seen=collection.set_seen,
                remove_pending=collection.remove_pending,
            ),
            models=DetailModels(
                extractor=resolve_detail_extractor(
                    adapter=service.adapter, gateway=host.llm_helper
                ),
                extract_risk=host.llm_helper.extract_avm_risk_features,
                sync_risk=host.sync_avm_risk_aliases,
                report=host.llm_helper.log_prediction_event,
            ),
        )

    def background_file_processor(self, stop_event: Event | None = None) -> None:
        host = self.host
        logger.info("Background AI processor started using global executor")

        def wait(seconds: float) -> None:
            if stop_event is None:
                host.time.sleep(seconds)
            else:
                stop_event.wait(seconds)

        while stop_event is None or not stop_event.is_set():
            try:
                files = host.glob.glob(host.os.path.join(host.DATA_DIR, "item-*.txt"))
                files += host.glob.glob(
                    host.os.path.join(host.DATA_DIR, "html", "item-*.html")
                )
                files += host.glob.glob(host.os.path.join(host.DATA_DIR, "item-*.html"))
                if not files:
                    wait(1)
                    continue
                submitted_count = 0
                for path in files:
                    if stop_event is not None and stop_event.is_set():
                        return
                    if path in host.RUNTIME.processing:
                        continue
                    host.submit_task(path)
                    submitted_count += 1
                if submitted_count > 0:
                    logger.info(
                        "Background scanner submitted tasks=%s", submitted_count
                    )
                wait(1)
            except Exception:
                logger.exception("Background scanner loop failed")
                wait(5)
