"""Compose state entrypoints with current facade callbacks and source policy."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from .collection.adapters.taobao_solver_target import (
    _solver_request_scope_from_target_url,
)
from .runtime_state import RuntimeState
from .server_solver_state import PauseCleaner, SolverState
from .solver_manual_pause import ManualFlagWriter
from .solver_pause_cleanup import PauseSetter


class StateClock(Protocol):
    time: Callable[[], float]
    time_ns: Callable[[], int]


class SolverStateHost(Protocol):
    RUNTIME: RuntimeState
    time: StateClock
    logger: logging.Logger
    _build_solver_request: Callable[[object], dict[str, str]]
    _solver_request_matches_auth_source: Callable[[object, object], bool]
    _challenge_scope_for_request: Callable[[object], str | None]
    _solver_scope_runtime_status: Callable[[str], Mapping[str, object]]
    _solver_challenge_state_path: Callable[[], Path]
    _read_solver_challenge_state: Callable[[], Mapping[str, object]]
    _solver_scope_state_root_path: Callable[[], Path]
    _normalize_challenge_scope: Callable[[object], str | None]
    _read_solver_scope_state: Callable[[str], Mapping[str, object]]
    _clear_solver_challenge_state_locked: Callable[[str | None], str | None]
    _solver_scope_state_path: Callable[[str], Path]
    _solver_force_unlock_flag_path: Callable[[], str]
    _set_collection_pause_state: PauseSetter
    _begin_solver_challenge_locked: Callable[[object], str]
    _persist_solver_scope_state: Callable[[str, Mapping[str, object]], str | None]
    _persist_solver_challenge_state: Callable[[str, dict[str, str]], str | None]
    _solver_challenge_owner_key: Callable[[object], tuple[str, str]]
    _solver_challenge_request_key: Callable[[object], tuple[str, str, str]]
    _collection_effectively_paused: Callable[[], bool]
    _captcha_solver_runtime_status: Callable[[], dict[str, object]]
    _solver_last_request_target_url: Callable[[object], str]
    _solver_request_scope_from_target_url: Callable[[str], str]
    _solver_last_request_scope: Callable[[object], str]
    _seed_stage_has_remaining_work: Callable[[dict[str, object]], bool]
    _solver_manual_flag_scope: Callable[[], str | None]
    _solver_scope_manual_flag_path: Callable[[str], str]
    _clear_solver_manual_required_pause: PauseCleaner
    _clear_solver_challenge_state: Callable[[str | None], str | None]
    _remember_solver_auth_completion: Callable[[dict[str, str]], None]
    _clear_solver_running_state: Callable[[], None]
    _clear_solver_manual_required_state: Callable[[], None]
    _request_solver_cancel: Callable[[], None]
    _write_solver_manual_required_flag: ManualFlagWriter


def bind_solver_state(host: SolverStateHost) -> SolverState:
    return SolverState(
        runtime=lambda: host.RUNTIME,
        clock=lambda: host.time.time(),
        new_id=lambda: f"captcha-{host.time.time_ns()}",
        source_scope=_solver_request_scope_from_target_url,
        logger=lambda: host.logger,
        build_request=lambda request: host._build_solver_request(request),
        matches_source=lambda completed, incoming: (
            host._solver_request_matches_auth_source(completed, incoming)
        ),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        scope_status=lambda scope: host._solver_scope_runtime_status(scope),
        legacy_path=lambda: host._solver_challenge_state_path(),
        read_legacy=lambda: host._read_solver_challenge_state(),
        root_path=lambda: host._solver_scope_state_root_path(),
        normalize_scope=lambda scope: host._normalize_challenge_scope(scope),
        read_scope=lambda scope: host._read_solver_scope_state(scope),
        clear_locked=lambda scope: host._clear_solver_challenge_state_locked(scope),
        scope_path=lambda scope: host._solver_scope_state_path(scope),
        flag_path=lambda: host._solver_force_unlock_flag_path(),
        set_pause=lambda *args, **kwargs: host._set_collection_pause_state(
            *args, **kwargs
        ),
        begin_locked=lambda request: host._begin_solver_challenge_locked(request),
        persist_scope=lambda scope, state: host._persist_solver_scope_state(
            scope, state
        ),
        persist_legacy=lambda challenge, request: host._persist_solver_challenge_state(
            challenge, request
        ),
        owner_key=lambda request: host._solver_challenge_owner_key(request),
        request_key=lambda request: host._solver_challenge_request_key(request),
        effectively_paused=lambda: host._collection_effectively_paused(),
        runtime_status=lambda: host._captcha_solver_runtime_status(),
        last_target=lambda status: host._solver_last_request_target_url(status),
        classify_target=lambda url: host._solver_request_scope_from_target_url(url),
        last_scope=lambda status: host._solver_last_request_scope(status),
        seed_pending=lambda status: host._seed_stage_has_remaining_work(status),
        flag_scope=lambda: host._solver_manual_flag_scope(),
        scope_flag_path=lambda scope: host._solver_scope_manual_flag_path(scope),
        clear_pause=lambda **kwargs: host._clear_solver_manual_required_pause(**kwargs),
        clear_challenge=lambda scope: host._clear_solver_challenge_state(scope),
        remember_completion=lambda request: host._remember_solver_auth_completion(
            request
        ),
        clear_running=lambda: host._clear_solver_running_state(),
        clear_manual=lambda: host._clear_solver_manual_required_state(),
        cancel=lambda: host._request_solver_cancel(),
        write_flag=lambda created_at_epoch, **kwargs: (
            host._write_solver_manual_required_flag(created_at_epoch, **kwargs)
        ),
    )
