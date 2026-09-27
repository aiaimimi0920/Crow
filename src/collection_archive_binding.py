"""Bind archive paths and record mutations to current facade resources."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .collection_archive_paths import (
    ArchiveDates,
    ArchiveFilesystem,
    CollectionArchivePaths,
    DetailArtifacts,
)
from .collection_archive_records import CollectionArchiveRecords
from .runtime_state import RuntimeState


class ArchiveJSON(Protocol):
    dump: Callable[..., None]


class CollectionArchiveHost(Protocol):
    RUNTIME: RuntimeState
    DATA_DIR: str
    datetime: ArchiveDates
    os: ArchiveFilesystem
    json: ArchiveJSON
    load_json_file: Callable[[str | Path], object]
    get_list_payload_archive_path: Callable[[object, str], str]
    _shared_get_detail_archive_path: Callable[[str, object, object, str], Path]
    _shared_extract_detail_artifacts: DetailArtifacts


def bind_collection_archives(
    host: CollectionArchiveHost,
) -> tuple[CollectionArchivePaths, CollectionArchiveRecords]:
    return (
        CollectionArchivePaths(
            data_root=lambda: host.DATA_DIR,
            dates=lambda: host.datetime,
            filesystem=lambda: host.os,
            dump=lambda *args, **kwargs: host.json.dump(*args, **kwargs),
            list_path=lambda value, suffix: host.get_list_payload_archive_path(
                value, suffix
            ),
            detail_path=lambda root, value, item, extension: (
                host._shared_get_detail_archive_path(root, value, item, extension)
            ),
            extract=lambda **kwargs: host._shared_extract_detail_artifacts(**kwargs),
        ),
        CollectionArchiveRecords(
            runtime=lambda: host.RUNTIME,
            exists=lambda path: host.os.path.exists(path),
            load=lambda path: host.load_json_file(path),
        ),
    )
