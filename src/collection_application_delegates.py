"""Bind request-scoped policy and resources to one collection application."""

from pathlib import Path
from types import ModuleType

from . import (
    collection_console_assets,
    server_desktop_auth,
    server_engine_control,
    server_solver_scope,
    solver_request_runtime,
)
from .auth_cookie_snapshot_jobs import AuthCookieSnapshotJobs
from .collection_status_snapshots import (
    _hybrid_collection_challenge_metrics_summary,
    _pc1_auth_auto_resume_state_summary,
)
from .server_collection_status import CollectionStatusReaders
from .solver_scope_runtime import SolverScopeRuntime


def bind_runtime_delegates(host: ModuleType) -> None:
    scopes = SolverScopeRuntime(
        host.RUNTIME,
        Path(host.DATA_DIR),
        lambda: host._solver_challenge_state_path(),
        host.CHALLENGE_FORCE_RESET_SECONDS,
    )
    delegates = {
        "_solver_scope_state_root_path": scopes.state_root_path,
        "_solver_scope_state_path": scopes.state_path,
        "_read_solver_scope_state": scopes.read,
        "_persist_solver_scope_state": scopes.persist,
        "_scope_challenge_age": scopes.age,
        "_solver_force_unlock_flag_path": scopes.manual_flag_path,
        "_solver_scope_manual_flag_path": scopes.manual_flag_path,
        "_solver_force_unlock_flag_exists": scopes.manual_flag_exists,
        "_collection_effectively_paused": scopes.effectively_paused,
        "_collection_scope_effectively_paused": lambda scope: (
            scopes.manual_flag_exists()
            or scopes.scope_effectively_paused(scope, check_manual_flag=False)
        ),
        "_set_collection_pause_state": scopes.set_pause,
        "_solver_transient_pause_active": scopes.transient_pause_active,
        "_solver_scope_runtime_status": scopes.status,
        "_runtime_started_at": lambda: host.RUNTIME.started_at,
        "_refresh_solver_last_request": lambda request: (
            solver_request_runtime.refresh_solver_last_request(
                request, runtime=host.RUNTIME
            )
        ),
        "_build_solver_for_request": lambda request: (
            solver_request_runtime.build_solver_for_request(
                request, default_solver=host.solver, factory=host.CaptchaSolver
            )
        ),
        "_collection_observer_page_html": lambda: collection_console_assets.page_html(
            dist=host.COLLECTOR_DESKTOP_DIST
        ),
        "_collection_observer_static_asset": lambda path: (
            collection_console_assets.static_asset(
                path, dist=host.COLLECTOR_DESKTOP_DIST
            )
        ),
        "_safe_collection_static_path": lambda path: (
            collection_console_assets.safe_static_path(
                path, dist=host.COLLECTOR_DESKTOP_DIST
            )
        ),
        "_engine_restart_status": lambda: server_engine_control._engine_restart_status(
            mailbox_factory=host._engine_restart_mailbox
        ),
    }

    def force_reset(scope: str, challenge_id: str | None = None) -> dict[str, object]:
        return server_solver_scope._force_reset_solver_scope(
            scope,
            challenge_id,
            scopes=scopes,
            clear_challenge=host._clear_solver_challenge_state,
            remember_reset=host._remember_solver_force_reset_recovery,
            solver_status=host._captcha_solver_runtime_status,
            report_grace_seconds=host.SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
        )

    def operator_start() -> dict[str, object]:
        return server_engine_control._collection_operator_start(
            runtime=host.RUNTIME,
            set_pause_state=host._set_collection_pause_state,
            scope_status=host._solver_scope_runtime_status,
            runtime_state_label=host._collection_runtime_state_label,
        )

    def desktop_auth(handler: object) -> None:
        server_desktop_auth._server_desktop_auth_request(
            handler,
            authorize_recovery=host._nas_auth_recovery_authorized,
            solver_scope_status=host._solver_scope_runtime_status,
            solver_status=host._captcha_solver_runtime_status,
            set_pause_state=host._set_collection_pause_state,
            nas_auth_recovery=host.NAS_AUTH_RECOVERY,
            runtime=host.RUNTIME,
        )

    delegates.update(
        {
            "_force_reset_solver_scope": force_reset,
            "_collection_operator_start": operator_start,
            "_server_desktop_auth_request": desktop_auth,
            "_server_engine_control": lambda handler: (
                server_engine_control._server_engine_control(
                    handler,
                    collection_operator_start=operator_start,
                    mailbox_factory=host._engine_restart_mailbox,
                )
            ),
        }
    )
    vars(host).update(delegates)


def bind_application_readers(host: ModuleType) -> tuple[object, ...]:
    def finalize(
        completion_id: str | None,
        *,
        expected_challenge_id: str | None,
        completion_request: dict[str, object] | None,
    ) -> dict[str, object]:
        return host._finalize_auth_completion_after_cookie_snapshot(
            completion_id,
            expected_challenge_id=expected_challenge_id,
            completion_request=completion_request,
        )

    return (
        CollectionStatusReaders(
            repository=lambda: host.DB_REPOSITORY,
            env_flag=lambda name, default: host._runtime_env_flag(name, default),
            prefer_db_reads=lambda: host._prefer_db_task_reads(),
            statistics=lambda repository, loader: (
                host._collection_statistics.SNAPSHOTS.snapshot(repository, loader)
            ),
            seed_counts=lambda: host._load_collection_seed_queue_counts(),
            empty_counts=lambda: host._empty_seed_queue_counts(),
            api_metrics=lambda: host.llm_helper.get_api_metrics(),
            runtime_snapshot=lambda: host._collection_runtime_snapshot(),
            build_info=lambda: host._build_info_payload(),
            runtime_state_label=lambda status: (
                host._collection_runtime_state_label_from_status_payload(status)
            ),
            solver_status=lambda: host._captcha_solver_runtime_status(),
            auth_recovery=lambda: host.NAS_AUTH_RECOVERY.snapshot(),
            status=lambda: host._collection_api_lightweight_status_payload(),
            control=lambda: host.RUNTIME.control.snapshot(),
            data_root=lambda: Path(host.DATA_DIR),
            restart=lambda: host._engine_restart_status(),
            challenge_metrics=_hybrid_collection_challenge_metrics_summary,
            auth_watcher=_pc1_auth_auto_resume_state_summary,
        ),
        AuthCookieSnapshotJobs(
            state=lambda: host._auth_cookie_snapshot_runtime_state(),
            retry_attempts=lambda: host._auth_cookie_snapshot_retry_attempts(),
            retry_backoff=lambda: host._auth_cookie_snapshot_retry_backoff_seconds(),
            set_state=lambda **updates: host._set_auth_cookie_snapshot_state(**updates),
            refresh=lambda request: host._refresh_auth_cookie_snapshot(request),
            finalize=finalize,
            retry_runner=lambda: host._run_auth_cookie_snapshot_retry,
            refresh_enabled=lambda payload: host._payload_flag(
                payload, "refresh_cookie_snapshot", True
            ),
            clock=lambda: host.time.time(),
            sleep=lambda seconds: host.time.sleep(seconds),
            thread_factory=lambda **kwargs: host.threading.Thread(**kwargs),
            stop_event=host.STOP_EVENT,
        ),
    )
