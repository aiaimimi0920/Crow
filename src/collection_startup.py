"""Serialized collection startup with explicit live dependencies."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class StartupRepository(Protocol):
    enabled: bool

    def initialize(self) -> None: ...


class StartupThread(Protocol):
    def start(self) -> None: ...


class StartupThreads(Protocol):
    def Thread(
        self, *, target: Callable[[], object], daemon: bool
    ) -> StartupThread: ...


class StartupClock(Protocol):
    def time(self) -> float: ...


class StartupRecovery(Protocol):
    enabled: bool
    stall_seconds: float


class StartupSeedService(Protocol):
    def _bootstrap_db_search_tasks(self) -> object: ...


class CollectionStartupHost(Protocol):
    RUNTIME: RuntimeState
    DB_REPOSITORY: StartupRepository
    NAS_AUTH_RECOVERY: StartupRecovery
    NAS_AUTH_RECOVERY_POLL_SECONDS: float
    threading: StartupThreads
    time: StartupClock
    _solver_scope_state_root_path: Callable[[], Path]
    _read_solver_scope_state: Callable[[str], Mapping[str, object]]
    _persist_solver_scope_state: Callable[[str, Mapping[str, object]], str | None]
    _read_solver_challenge_state: Callable[[], Mapping[str, object]]
    _persist_solver_challenge_state: Callable[[str, dict[str, str]], str | None]
    _write_solver_manual_required_flag: Callable[[float], str | None]
    _restore_solver_challenge_state: Callable[[], object]
    _restore_solver_scope_states: Callable[[], object]
    cleanup_orphaned_files: Callable[[], object]
    load_data: Callable[[], object]
    _seed_collection_service: Callable[[], StartupSeedService]
    manual_solver_retry_thread: Callable[[], object]
    _manual_solver_retry_interval_seconds: Callable[[], float]
    _manual_solver_retry_poll_seconds: Callable[[], float]
    _sample_nas_auth_recovery: Callable[[], object]
    nas_auth_recovery_watchdog_thread: Callable[[], object]


@dataclass(frozen=True)
class CollectionStartup:
    host: CollectionStartupHost

    __all__: ClassVar[list[str]] = ["initialize_runtime"]

    def initialize_runtime(self, *, start_workers: bool = True) -> None:
        from .auth_cleanup_journal import recover_pending_cleanups
        from .auth_cleanup_recovery import restore_legacy_cleanup

        host = self.host
        with host.RUNTIME.initialization_lock:
            if host.RUNTIME.initialized:
                return
            with host.RUNTIME.lock:
                recover_pending_cleanups(
                    host._solver_scope_state_root_path(),
                    read_scope=host._read_solver_scope_state,
                    persist_scope=host._persist_solver_scope_state,
                    read_legacy=host._read_solver_challenge_state,
                    restore_legacy=lambda state: restore_legacy_cleanup(
                        state,
                        runtime=host.RUNTIME,
                        persist_legacy=host._persist_solver_challenge_state,
                        write_manual_flag=host._write_solver_manual_required_flag,
                    ),
                )
            if host._restore_solver_challenge_state():
                logger.info(
                    "[SOLVER] Restored persisted challenge %s; "
                    "collection remains paused until node confirmation.",
                    host.RUNTIME.recovery.snapshot().challenge_id,
                )
            if host._restore_solver_scope_states():
                logger.info("Restored independent list/detail challenge latches")

            host.cleanup_orphaned_files()
            host.load_data()
            try:
                host.DB_REPOSITORY.initialize()
                if host.DB_REPOSITORY.enabled:
                    logger.info("Repository initialized for dual-write")
                    try:
                        host._seed_collection_service()._bootstrap_db_search_tasks()
                        logger.info("Search task bootstrap completed")
                    except Exception:
                        logger.exception("Search task bootstrap failed")
                else:
                    logger.info(
                        "Repository disabled; set FAPAI_DB_URL to enable database dual-write"
                    )
            except Exception:
                logger.exception("Database initialization failed")

            if start_workers:
                host.threading.Thread(
                    target=host.manual_solver_retry_thread, daemon=True
                ).start()
                logger.info(
                    "[SOLVER] Manual-required auto retry monitor started "
                    "(interval: %ss, poll: %ss).",
                    host._manual_solver_retry_interval_seconds(),
                    host._manual_solver_retry_poll_seconds(),
                )
            try:
                host._sample_nas_auth_recovery()
            except Exception:
                logger.exception(
                    "Initial authentication recovery progress sample failed"
                )
            if start_workers and host.NAS_AUTH_RECOVERY.enabled:
                host.threading.Thread(
                    target=host.nas_auth_recovery_watchdog_thread, daemon=True
                ).start()
                logger.info(
                    "[AUTH-RECOVERY] NAS stall recovery watchdog started "
                    "(stall: %.0fs, poll: %.0fs).",
                    host.NAS_AUTH_RECOVERY.stall_seconds,
                    host.NAS_AUTH_RECOVERY_POLL_SECONDS,
                )
            with host.RUNTIME.lock:
                host.RUNTIME.started_at = host.time.time()
                host.RUNTIME.initialized = True
