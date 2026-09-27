"""Compose observer and runtime control owners against current facade resources."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from .runtime_state import RuntimeState
from .server_collection_control import CollectionObserver, CollectionRuntimeControl
from .solver_pause_cleanup import PauseSetter

if TYPE_CHECKING:
    from .storage.repository import PropertyRepository


class ControlClock(Protocol):
    time: Callable[[], float]


class ControlPaths(Protocol):
    exists: Callable[[str], bool]


class ControlFilesystem(Protocol):
    path: ControlPaths
    remove: Callable[[str], None]


class CollectionControlHost(Protocol):
    RUNTIME: RuntimeState
    DB_REPOSITORY: PropertyRepository
    os: ControlFilesystem
    time: ControlClock
    _collection_api_lightweight_status_payload: Callable[[], dict[str, object]]
    _collection_effectively_paused: Callable[[], bool]
    _set_collection_pause_state: PauseSetter
    _solver_force_unlock_flag_path: Callable[[], str]
    _clear_solver_challenge_state: Callable[[], str | None]
    _clear_solver_running_state: Callable[[], None]
    _clear_solver_manual_required_state: Callable[[], None]
    _captcha_solver_runtime_status: Callable[[], dict[str, object]]
    _collection_runtime_state_label: Callable[[], str]


def bind_collection_control(
    host: CollectionControlHost,
) -> tuple[CollectionObserver, CollectionRuntimeControl]:
    return (
        CollectionObserver(repository=lambda: host.DB_REPOSITORY),
        CollectionRuntimeControl(
            runtime=lambda: host.RUNTIME,
            status=lambda: host._collection_api_lightweight_status_payload(),
            paused=lambda: host._collection_effectively_paused(),
            set_pause=lambda paused, reason=None, **kwargs: (
                host._set_collection_pause_state(paused, reason, **kwargs)
            ),
            flag_path=lambda: host._solver_force_unlock_flag_path(),
            exists=lambda path: host.os.path.exists(path),
            remove=lambda path: host.os.remove(path),
            clear_challenge=lambda: host._clear_solver_challenge_state(),
            clear_running=lambda: host._clear_solver_running_state(),
            clear_manual=lambda: host._clear_solver_manual_required_state(),
            solver_status=lambda: host._captcha_solver_runtime_status(),
            clock=lambda: host.time.time(),
            label=lambda: host._collection_runtime_state_label(),
        ),
    )
