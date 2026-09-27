"""Native detail-file dispatch and background discovery orchestration."""

import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

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
    get_data_path: Callable[[object], str]
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
        host._detail_collection_service().process_html_file(
            file_path,
            get_working_item=host._get_working_item,
            get_data_path=host.get_data_path,
            update_item_in_json=host.update_item_in_json,
            remove_item_from_json=host.remove_item_from_json,
            persist_item_to_db=host.persist_item_to_db,
            mark_item_deleted_in_db=host.mark_item_deleted_in_db,
            evict_runtime_item=host._evict_runtime_item,
            prefer_db_task_reads=host._prefer_db_task_reads,
            sync_avm_risk_aliases=host.sync_avm_risk_aliases,
            extract_auction_data=host.llm_helper.extract_auction_data,
            extract_avm_risk_features=host.llm_helper.extract_avm_risk_features,
            log_prediction_event=host.llm_helper.log_prediction_event,
            queue_pending=collection.queue_pending,
            set_seen=collection.set_seen,
            remove_pending=collection.remove_pending,
        )

    def background_file_processor(self) -> None:
        host = self.host
        logger.info("Background AI processor started using global executor")
        while True:
            try:
                files = host.glob.glob(host.os.path.join(host.DATA_DIR, "item-*.txt"))
                files += host.glob.glob(
                    host.os.path.join(host.DATA_DIR, "html", "item-*.html")
                )
                files += host.glob.glob(host.os.path.join(host.DATA_DIR, "item-*.html"))
                if not files:
                    host.time.sleep(1)
                    continue
                submitted_count = 0
                for path in files:
                    if path in host.RUNTIME.processing:
                        continue
                    host.submit_task(path)
                    submitted_count += 1
                if submitted_count > 0:
                    logger.info(
                        "Background scanner submitted tasks=%s", submitted_count
                    )
                host.time.sleep(1)
            except Exception:
                logger.exception("Background scanner loop failed")
                host.time.sleep(5)
