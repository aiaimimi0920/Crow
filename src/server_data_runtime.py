from __future__ import annotations

import datetime
import glob
import json
import os
import sys
import threading
import time
from typing import cast
from .collection_startup import CollectionStartup, CollectionStartupHost
from .collection_index_bootstrap import CollectionIndexBootstrap, CollectionIndexHost
from .collection_file_runtime import CollectionFileRuntime, CollectionFileHost

from .collection_archive_binding import CollectionArchiveHost, bind_collection_archives
from .collection_database_writes import (
    CollectionWriteHost,
    bind_collection_database_writes,
)

from .server_context import (
    DATA_DIR,
    DB_REPOSITORY,
    NAS_AUTH_RECOVERY,
    NAS_AUTH_RECOVERY_POLL_SECONDS,
    RUNTIME,
    _shared_extract_detail_artifacts,
    _shared_get_detail_archive_path,
    llm_helper,
    sync_collection_record,
)
from .runtime_json import load_json_file
from .collection_index_loader import load_collection_index

# Direct module callers and the legacy bootstrap still need archive entrypoints.
# They share native implementations, with this module's live dependencies.
_archive_paths, _archive_records = bind_collection_archives(
    cast(CollectionArchiveHost, sys.modules[__name__])
)
get_data_path = _archive_paths.get_data_path
get_detail_archive_path = _archive_paths.get_detail_archive_path
get_list_payload_archive_path = _archive_paths.get_list_payload_archive_path
archive_list_payload = _archive_paths.archive_list_payload
_extract_detail_artifacts = _archive_paths._extract_detail_artifacts
update_file_global = _archive_records.update_file_global
update_item_in_json = _archive_records.update_item_in_json
remove_item_from_json = _archive_records.remove_item_from_json

_database_writes = bind_collection_database_writes(
    cast(CollectionWriteHost, sys.modules[__name__])
)
persist_item_to_db = _database_writes.persist_item_to_db
mark_item_deleted_in_db = _database_writes.mark_item_deleted_in_db

_startup = CollectionStartup(cast(CollectionStartupHost, sys.modules[__name__]))
initialize_runtime = _startup.initialize_runtime

_index_bootstrap = CollectionIndexBootstrap(
    cast(CollectionIndexHost, sys.modules[__name__])
)
load_data = _index_bootstrap.load_data
cleanup_orphaned_files = _index_bootstrap.cleanup_orphaned_files

_file_runtime = CollectionFileRuntime(cast(CollectionFileHost, sys.modules[__name__]))
process_single_file = _file_runtime.process_single_file
background_file_processor = _file_runtime.background_file_processor


__all__ = [
    "load_json_file",
    "get_data_path",
    "get_detail_archive_path",
    "get_list_payload_archive_path",
    "archive_list_payload",
    "_extract_detail_artifacts",
    "load_data",
    "cleanup_orphaned_files",
    "initialize_runtime",
    "update_file_global",
    "persist_item_to_db",
    "mark_item_deleted_in_db",
    "process_single_file",
    "update_item_in_json",
    "remove_item_from_json",
    "background_file_processor",
]
