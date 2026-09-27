"""Bind native auth completion to live, replaceable server dependencies."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

from .auth_cleanup_completion import AuthCleanupCompletion
from .auth_completion_contracts import CookieFinalizer, CookieScheduler
from .auth_completion_receipts import AuthCompletionReceipts
from .auth_cookie_binding import CookieClock, CookieEnvironment
from .collection.adapters import taobao_auth_target
from .runtime_state import RuntimeState
from .server_collection_console import AuthCompletion
from .solver_captcha_reports import PayloadFlag, ReportMarker
from .solver_pause_cleanup import PauseSetter
from .solver_recovery_state import SolverRecoveryState


class AuthCompletionHost(Protocol):
    RUNTIME: RuntimeState
    DATA_DIR: str
    os: CookieEnvironment
    time: CookieClock
    _auth_completion_confirmation_path: Callable[[], Path]
    _auth_completion_recovery_state: Callable[[], SolverRecoveryState]
    _normalize_auth_completion_id: Callable[[object], str | None]
    _normalize_challenge_scope: Callable[[object], str | None]
    _scope_for_challenge_id: Callable[[object], str | None]
    _solver_scope_runtime_status: Callable[[str | None], dict[str, object]]
    _captcha_solver_runtime_status: Callable[[], dict[str, object]]
    _node_auth_challenge_matches: Callable[[dict[str, object], str], bool]
    _auth_completion_was_confirmed: Callable[[str | None], bool]
    _challenge_scope_for_request: Callable[[object], str | None]
    _auth_state_is_confirmed: Callable[[dict[str, object], str | None], bool]
    _payload_flag: PayloadFlag
    _solver_target_requires_manual_only: Callable[[object], bool]
    _auth_cookie_snapshot_runtime_status: Callable[[], dict[str, object]]
    _read_solver_scope_state: Callable[[str | None], dict[str, object]]
    _solver_manual_flag_is_manual_only: Callable[[], bool]
    _solver_scope_state_root_path: Callable[[], Path]
    _clear_solver_manual_required_pause_compat: Callable[[str | None], str | None]
    _remember_auth_completion_confirmation: Callable[[str | None], str | None]
    _remember_solver_auth_completion: Callable[[object], None]
    _persist_solver_scope_state: Callable[[str, Mapping[str, object]], str | None]
    _persist_solver_challenge_state: Callable[[str, dict[str, str]], str | None]
    _write_solver_manual_required_flag: Callable[[float], str | None]
    _set_collection_pause_state: PauseSetter
    _schedule_auth_cookie_snapshot_refresh: CookieScheduler
    _finalize_auth_completion_after_cookie_snapshot: CookieFinalizer
    _solver_scope_manual_flag_path: Callable[[str | None], str]
    _collection_runtime_state_label: Callable[[], str]
    _refresh_solver_last_request: Callable[[dict[str, object]], object]
    _begin_solver_challenge: Callable[[object], str]
    _mark_solver_manual_required: ReportMarker
    _collection_effectively_paused: Callable[[], bool]
    _build_solver_request: Callable[[object], dict[str, str]]


def bind_auth_completion(
    host: AuthCompletionHost,
) -> tuple[AuthCompletionReceipts, AuthCleanupCompletion, AuthCompletion]:
    receipts = AuthCompletionReceipts(
        runtime=lambda: host.RUNTIME,
        data_dir=lambda: host.DATA_DIR,
        env=lambda name: host.os.getenv(name),
        path=lambda: host._auth_completion_confirmation_path(),
        recovery=lambda: host._auth_completion_recovery_state(),
        scope_root=lambda: host._solver_scope_state_root_path(),
        clock=lambda: host.time.time(),
    )
    completion = AuthCompletion(
        runtime=lambda: host.RUNTIME,
        normalize_completion=lambda value: host._normalize_auth_completion_id(value),
        normalize_scope=lambda value: host._normalize_challenge_scope(value),
        scope_for_id=lambda value: host._scope_for_challenge_id(value),
        scope_status=lambda scope: host._solver_scope_runtime_status(scope),
        status=lambda: host._captcha_solver_runtime_status(),
        node_matches=lambda payload, source: host._node_auth_challenge_matches(
            payload, source
        ),
        was_confirmed=lambda completion: host._auth_completion_was_confirmed(
            completion
        ),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        confirmed=lambda status, scope: host._auth_state_is_confirmed(status, scope),
        flag=lambda payload, key, default: host._payload_flag(payload, key, default),
        manual_only=lambda request: host._solver_target_requires_manual_only(request),
        cookie_status=lambda: host._auth_cookie_snapshot_runtime_status(),
        read_scope=lambda scope: host._read_solver_scope_state(scope),
        flag_manual_only=lambda: host._solver_manual_flag_is_manual_only(),
        state_root=lambda: host._solver_scope_state_root_path(),
        clear_pause=lambda scope: host._clear_solver_manual_required_pause_compat(
            scope
        ),
        remember_confirmation=lambda completion: (
            host._remember_auth_completion_confirmation(completion)
        ),
        remember_completion=lambda request: host._remember_solver_auth_completion(
            request
        ),
        persist_scope=lambda scope, state: host._persist_solver_scope_state(
            scope, state
        ),
        persist_legacy=lambda challenge, request: host._persist_solver_challenge_state(
            challenge, request
        ),
        write_manual_flag=lambda epoch: host._write_solver_manual_required_flag(epoch),
        set_pause=lambda paused, reason=None, **kwargs: (
            host._set_collection_pause_state(paused, reason, **kwargs)
        ),
        schedule=lambda payload, completion_id, **kwargs: (
            host._schedule_auth_cookie_snapshot_refresh(
                payload, completion_id, **kwargs
            )
        ),
        finalize=lambda completion_id, **kwargs: (
            host._finalize_auth_completion_after_cookie_snapshot(
                completion_id, **kwargs
            )
        ),
        scope_flag_path=lambda scope: host._solver_scope_manual_flag_path(scope),
        runtime_label=lambda: host._collection_runtime_state_label(),
        # The legacy adapter handles non-string targets internally; do not coerce them.
        matches_target=lambda scope, target, state: (
            taobao_auth_target.matches_challenge_target(scope, cast(str, target), state)
        ),
    )
    cleanup = AuthCleanupCompletion(
        runtime=completion.runtime,
        normalize_scope=completion.normalize_scope,
        scope_status=completion.scope_status,
        infer_scope=completion.infer_scope,
        scope_for_id=completion.scope_for_id,
        was_confirmed=completion.was_confirmed,
        status=completion.status,
        confirmed=completion.confirmed,
        read_scope=completion.read_scope,
        flag_manual_only=completion.flag_manual_only,
        state_root=completion.state_root,
        clear_pause=completion.clear_pause,
        remember_confirmation=completion.remember_confirmation,
        remember_completion=completion.remember_completion,
        persist_scope=completion.persist_scope,
        persist_legacy=completion.persist_legacy,
        write_manual_flag=completion.write_manual_flag,
        refresh_request=lambda request: host._refresh_solver_last_request(request),
        begin=lambda request: host._begin_solver_challenge(request),
        mark_manual=lambda **kwargs: host._mark_solver_manual_required(**kwargs),
        manual_only=completion.manual_only,
        set_pause=completion.set_pause,
        normalize_completion=completion.normalize_completion,
        paused=lambda: host._collection_effectively_paused(),
        node_matches=completion.node_matches,
        build_request=lambda payload: host._build_solver_request(payload),
        scope_flag_path=completion.scope_flag_path,
        runtime_label=completion.runtime_label,
    )
    return receipts, cleanup, completion
