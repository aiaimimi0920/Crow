"""Native collection index loading and interrupted-file recovery."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol

from .collection_archive_paths import ArchiveDates
from .collection_index_loader import IndexRepository
from .collection_runtime_index import CollectionRuntimeIndex
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class IndexLoader(Protocol):
    def __call__(
        self,
        active_data_root: str | Path,
        *,
        collection: CollectionRuntimeIndex,
        repository: IndexRepository,
        prefer_db_index: Callable[[], bool],
        db_counts_snapshot: Callable[[], dict[str, int]],
        sync_record: Callable[[dict[str, object]], object],
        data_path: Callable[[object], str],
        now: Callable[[], datetime],
    ) -> None: ...


class BootstrapPaths(Protocol):
    def join(self, root: str | Path, suffix: str) -> str: ...


class BootstrapFilesystem(Protocol):
    path: BootstrapPaths

    def fspath(self, path: str | Path) -> str: ...
    def rename(self, source: str, target: str) -> None: ...


class BootstrapGlob(Protocol):
    def glob(self, pattern: str) -> list[str]: ...


class CollectionIndexHost(Protocol):
    DATA_DIR: str | Path
    RUNTIME: RuntimeState
    DB_REPOSITORY: IndexRepository
    os: BootstrapFilesystem
    glob: BootstrapGlob
    datetime: ArchiveDates
    load_collection_index: IndexLoader
    _runtime_env_flag: Callable[[str, bool], bool]
    _db_counts_snapshot: Callable[[], dict[str, int]]
    sync_collection_record: Callable[[dict[str, object]], object]
    get_data_path: Callable[[object], str]


@dataclass(frozen=True)
class CollectionIndexBootstrap:
    host: CollectionIndexHost

    __all__: ClassVar[list[str]] = ["load_data", "cleanup_orphaned_files"]

    def load_data(self, data_root: str | Path | None = None) -> None:
        host = self.host
        return host.load_collection_index(
            host.os.fspath(data_root or host.DATA_DIR),
            collection=host.RUNTIME.collection,
            repository=host.DB_REPOSITORY,
            prefer_db_index=lambda: host._runtime_env_flag(
                "FAPAI_DB_PREFER_RUNTIME_INDEX", True
            ),
            db_counts_snapshot=lambda: host._db_counts_snapshot(),
            sync_record=host.sync_collection_record,
            data_path=host.get_data_path,
            now=host.datetime.datetime.now,
        )

    def cleanup_orphaned_files(self) -> None:
        host = self.host
        failed_orphans = host.glob.glob(
            host.os.path.join(host.DATA_DIR, "*.processing.failed")
        )
        for path in failed_orphans:
            original = path.replace(".processing.failed", "")
            try:
                host.os.rename(path, original)
                with open(original + ".failed", "w") as marker:
                    marker.write("recovered")
            except Exception:
                logger.exception("Failed to reset orphan file=%s", path)

        orphans = host.glob.glob(host.os.path.join(host.DATA_DIR, "*.processing"))
        if orphans:
            logger.warning(
                "Found orphaned processing files=%s; resetting", len(orphans)
            )
            for path in orphans:
                original = path.replace(".processing", "")
                try:
                    host.os.rename(path, original)
                except Exception:
                    logger.exception("Failed to reset orphan file=%s", path)
