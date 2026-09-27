"""Collection-only composition with owned, stoppable background workers."""

from __future__ import annotations

import importlib
import ssl
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self

from .collection.contracts import CollectionAdapter
from .collection_application_delegates import (
    bind_application_readers,
    bind_runtime_delegates,
)
from .collection_http_handler import build_collection_handler
from .collection_http_server import CollectionHTTPServer
from .collection_job_control import DEFAULT_TIMEOUT_SECONDS
from .collection_runtime_config import create_collection_host
from .server_native_bindings import (
    bind_collection_handler_owners,
    bind_collection_server_owners,
)
from .server_routes import GET_GROUPS, POST_GROUPS, build_routes
from .storage.repository import CollectionRepository

_COLLECTION_MODULES = (
    "server_http_responses",
    "server_request_guard",
    "server_collection_settings",
    "server_auto_tuning",
    "server_engine_control",
    "server_solver_scope",
    "server_collection_status",
)
_COLLECTION_GETS = {
    "_get_collection_index",
    "_get_collection_overview",
    "_get_collection_items",
    "_get_collection_regions",
    "_get_collection_item",
    "_get_collection_job",
    "_get_auth_recovery",
    "_get_auth_recovery_snapshot",
    "_get_status",
    "_get_item",
}
_POSTPROCESSING_POSTS = {
    "_post_drift_report",
    "_post_release_gate",
    "_post_recent_gap_audit",
    "_post_analysis_run",
    "_post_analysis_evaluate",
    "_post_analysis_screen",
    "_post_start_all_subtasks",
    "_post_run_all_subtasks_sync",
    "_post_infer_location",
    "_post_detail_maintenance",
    "_post_fetch_missing_detail_archives",
    "_post_archive_detail_replay",
    "_post_recent_detail_replay",
}


def _publish(host: ModuleType, owner: object) -> None:
    for name in getattr(owner, "__all__", ()):
        setattr(host, name, getattr(owner, name))


def create_application(
    *,
    data_root: str | Path | None = None,
    repository: CollectionRepository | None = None,
    adapter: CollectionAdapter | None = None,
) -> CollectionApplication:
    host = create_collection_host(
        data_root=data_root, repository=repository, adapter=adapter
    )
    for name in _COLLECTION_MODULES:
        _publish(host, importlib.import_module("src." + name))
    for owner in bind_collection_server_owners(host):
        _publish(host, owner)
    bind_runtime_delegates(host)
    for owner in (
        *bind_application_readers(host),
        *bind_collection_handler_owners(host),
    ):
        _publish(host, owner)
    routes = build_routes(
        {
            **{
                name: paths
                for name, paths in GET_GROUPS.items()
                if name in _COLLECTION_GETS
            },
            "_get_collection_settings": (host._settings_schema.PREFIX,),
        },
        {
            **{
                name: paths
                for name, paths in POST_GROUPS.items()
                if name not in _POSTPROCESSING_POSTS
            },
            "_post_engine_control": tuple(host._engine_control.ROUTES),
            "_post_collection_settings": tuple(host._settings_schema.ROLES),
        },
    )
    vars(host)["ROUTES"] = routes
    vars(host)["DataHandler"] = build_collection_handler(host)
    return CollectionApplication(host, stop_event=host.STOP_EVENT)


@dataclass
class CollectionApplication:
    host: ModuleType
    stop_event: threading.Event = field(default_factory=threading.Event)
    threads: list[threading.Thread] = field(default_factory=list)
    _started: bool = False
    _closed: bool = False

    def start(self) -> None:
        if self._closed:
            raise RuntimeError(
                "Collection application is closed; construct a new application"
            )
        if self._started:
            return
        host = self.host
        targets = [
            host.manual_solver_retry_thread,
            host.background_file_processor,
            host.auto_tuner_thread,
        ]
        if host.NAS_AUTH_RECOVERY.enabled:
            targets.append(host.nas_auth_recovery_watchdog_thread)
        try:
            host.DB_REPOSITORY.initialize()
            host.initialize_runtime(start_workers=False)
            for target in targets:
                thread = threading.Thread(
                    target=target,
                    args=(self.stop_event,),
                    name="crow-" + target.__name__,
                    daemon=True,
                )
                thread.start()
                self.threads.append(thread)
            self._started = True
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self.stop_event.set()
        snapshot_thread = (
            self.host._auth_cookie_snapshot_runtime_state().active_thread()
        )
        workers = self.threads + ([snapshot_thread] if snapshot_thread else [])
        for thread in workers:
            thread.join(timeout=10)
        remaining = [thread.name for thread in workers if thread.is_alive()]
        self.host.executor.shutdown(wait=True, cancel_futures=True)
        if remaining:
            raise RuntimeError(
                "Collection workers did not stop: " + ", ".join(remaining)
            )
        self._closed = True

    def http_server(
        self,
        address: tuple[str, int],
        *,
        tls: ssl.SSLContext | None = None,
        job_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> CollectionHTTPServer:
        return CollectionHTTPServer(
            address,
            self.host.DataHandler,
            tls=tls,
            job_timeout_seconds=job_timeout_seconds,
        )

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()
