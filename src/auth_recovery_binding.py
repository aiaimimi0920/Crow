"""Compose native authentication recovery owners against the live server facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .auth_recovery_progress import ProgressRepository
from .collection.adapters import taobao_auth_target
from .runtime_state import RuntimeState
from .server_auth_recovery import AuthRecovery, RecoveryCoordinator
from .server_solver_state import PauseCleaner
from .solver_auth_history import SolverAuthHistory
from .solver_status_reader import ScopeStatus, SolverStatusReader


class RecoveryClock(Protocol):
    time: Callable[[], float]
    sleep: Callable[[float], None]


class AuthRecoveryHost(Protocol):
    RUNTIME: RuntimeState
    DB_REPOSITORY: ProgressRepository
    NAS_AUTH_RECOVERY: RecoveryCoordinator
    DATA_DIR: str
    time: RecoveryClock
    NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS: float
    NAS_AUTH_RECOVERY_POLL_SECONDS: float
    SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS: float
    SOLVER_AUTH_REPORT_GRACE_SECONDS: float
    SOLVER_DETAIL_PROGRESS_GRACE_SECONDS: float
    SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS: int
    _solver_force_unlock_flag_exists: Callable[[], bool]
    _solver_manual_flag_request: Callable[[], dict[str, object]]
    _solver_scope_runtime_status: ScopeStatus
    _challenge_scope_for_request: Callable[[object], str | None]
    _solver_manual_flag_is_manual_only: Callable[[], bool]
    _solver_target_requires_manual_only: Callable[[object], bool]
    _solver_request_delegated_to_node: Callable[[object], bool]
    _manual_solver_retry_next_epoch: Callable[[float], float | None]
    _real_taobao_auto_solver_enabled: Callable[[], bool]
    _collection_effectively_paused: Callable[[], bool]
    _manual_solver_retry_enabled: Callable[[], bool]
    _manual_solver_retry_interval_seconds: Callable[[], int]
    _solver_max_runtime_seconds: Callable[[], int]
    _auth_cookie_snapshot_runtime_status: Callable[[], dict[str, object]]
    _solver_challenge_state_path: Callable[[], Path]
    _normalize_solver_target_url: Callable[[object], str]
    _solver_challenge_request_key: Callable[[object], tuple[str, str, str]]
    _build_solver_request: Callable[[object], dict[str, str]]
    _solver_detail_captured_count: Callable[[], int | None]
    _normalize_challenge_scope: Callable[[object], str | None]
    _solver_request_matches_auth_source: Callable[[object, object], bool]
    _solver_auth_report_suppression: Callable[..., dict[str, object] | None]
    _recovery_expected_token: Callable[[], str]
    _captcha_solver_runtime_status: Callable[[], dict[str, object]]
    _nas_auth_recovery_pending_detail_count: Callable[[], int]
    _nas_auth_recovery_signal: Callable[[], str | None]
    _sample_nas_auth_recovery: Callable[[], dict[str, object]]
    _clear_solver_manual_required_pause: PauseCleaner
    _remember_solver_auth_completion: Callable[[dict[str, str]], None]


def bind_auth_recovery(
    host: AuthRecoveryHost,
) -> tuple[SolverStatusReader, SolverAuthHistory, AuthRecovery]:
    status = SolverStatusReader(
        runtime=lambda: host.RUNTIME,
        clock=lambda: host.time.time(),
        flag_exists=lambda: host._solver_force_unlock_flag_exists(),
        flag_request=lambda: host._solver_manual_flag_request(),
        scope_status=lambda scope, **kwargs: host._solver_scope_runtime_status(
            scope, **kwargs
        ),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        flag_manual_only=lambda: host._solver_manual_flag_is_manual_only(),
        target_manual_only=lambda request: host._solver_target_requires_manual_only(
            request
        ),
        delegated=lambda request: host._solver_request_delegated_to_node(request),
        next_retry=lambda now: host._manual_solver_retry_next_epoch(now),
        auto_enabled=lambda: host._real_taobao_auto_solver_enabled(),
        paused=lambda: host._collection_effectively_paused(),
        retry_enabled=lambda: host._manual_solver_retry_enabled(),
        retry_interval=lambda: host._manual_solver_retry_interval_seconds(),
        max_runtime=lambda: host._solver_max_runtime_seconds(),
        cookie_status=lambda: host._auth_cookie_snapshot_runtime_status(),
    )
    history = SolverAuthHistory(
        runtime=lambda: host.RUNTIME,
        clock=lambda: host.time.time(),
        data_dir=lambda: host.DATA_DIR,
        state_path=lambda: host._solver_challenge_state_path(),
        normalize_target=lambda target: host._normalize_solver_target_url(target),
        request_key=lambda request: host._solver_challenge_request_key(request),
        build_request=lambda request: host._build_solver_request(request),
        captured_count=lambda: host._solver_detail_captured_count(),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        normalize_scope=lambda scope: host._normalize_challenge_scope(scope),
        matches_source=lambda completed, incoming: (
            host._solver_request_matches_auth_source(completed, incoming)
        ),
        reset_grace=lambda: host.SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
        auth_grace=lambda: host.SOLVER_AUTH_REPORT_GRACE_SECONDS,
        progress_grace=lambda: host.SOLVER_DETAIL_PROGRESS_GRACE_SECONDS,
        progress_min_items=lambda: host.SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS,
        same_target=lambda scope, left, right: taobao_auth_target.same_auth_target(
            scope, left, right
        ),
        suppression=lambda *args, **kwargs: host._solver_auth_report_suppression(
            *args, **kwargs
        ),
    )
    recovery = AuthRecovery(
        runtime=lambda: host.RUNTIME,
        repository=lambda: host.DB_REPOSITORY,
        coordinator=lambda: host.NAS_AUTH_RECOVERY,
        blocked_seconds=lambda: host.NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS,
        poll_seconds=lambda: host.NAS_AUTH_RECOVERY_POLL_SECONDS,
        sleep=lambda seconds: host.time.sleep(seconds),
        expected_token=lambda: host._recovery_expected_token(),
        solver_status=lambda: host._captcha_solver_runtime_status(),
        cookie_status=lambda: host._auth_cookie_snapshot_runtime_status(),
        scope_status=lambda scope, **kwargs: host._solver_scope_runtime_status(
            scope, **kwargs
        ),
        captured_count=lambda: host._solver_detail_captured_count(),
        pending_count=lambda: host._nas_auth_recovery_pending_detail_count(),
        signal=lambda: host._nas_auth_recovery_signal(),
        sample=lambda: host._sample_nas_auth_recovery(),
        clear_pause=lambda **kwargs: host._clear_solver_manual_required_pause(**kwargs),
        matches_target=lambda scope, target, state: (
            taobao_auth_target.matches_challenge_target(scope, target, state)
        ),
        remember_completion=lambda request: host._remember_solver_auth_completion(
            request
        ),
        paused=lambda: host._collection_effectively_paused(),
    )
    return status, history, recovery
