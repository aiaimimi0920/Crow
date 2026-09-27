from __future__ import annotations

import importlib
import logging
from pathlib import Path
import sys
import threading

from src.auth_cookie_snapshot_jobs import AuthCookieSnapshotJobs
from src.auth_recovery_progress import captured_detail_count, pending_detail_count
from src.collection_index_loader import load_collection_index
from src.server_collection_status import CollectionStatusReaders
from src.server_module_exports import ModuleExports
from src.server_native_bindings import (
    bind_native_handler_owners,
    bind_native_server_owners,
)

logger = logging.getLogger(__name__)


if __package__:
    _PACKAGE = __package__
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _PACKAGE = "src"
_CONTEXT = importlib.import_module(f"{_PACKAGE}.server_context")
_NATIVE_MODULES = (
    "server_http_responses",
    "server_request_guard",
    "server_collection_settings",
    "server_auto_tuning",
    "server_hybrid_history",
    "server_hybrid_lifecycle",
    "server_hybrid_events",
    "server_hybrid_escalation",
    "server_hybrid_operator_summary",
    "server_hybrid_policy",
    "server_hybrid_runtime",
    "server_hybrid_context",
    "server_manual_review",
    "server_desktop_auth",
    "server_engine_control",
    "server_solver_scope",
    "server_collection_status",
    "server_data_runtime",
    "server_collection_operations",
    "server_handler_core",
    "server_handler_task_control",
    "server_handler_get_collection",
    "server_handler_ingest",
    "server_handler_analysis",
)


_EXPORTS = ModuleExports(globals(), _CONTEXT)
_EXPORTS.publish(_CONTEXT)
_SOLVER_REQUEST_RUNTIME = importlib.import_module(f"{_PACKAGE}.solver_request_runtime")


def _refresh_solver_last_request(request_payload):
    return _SOLVER_REQUEST_RUNTIME.refresh_solver_last_request(
        request_payload,
        runtime=RUNTIME,
    )


def _build_solver_for_request(request_payload):
    return _SOLVER_REQUEST_RUNTIME.build_solver_for_request(
        request_payload,
        default_solver=solver,
        factory=CaptchaSolver,
    )


def _runtime_started_at() -> float:
    with RUNTIME.lock:
        return RUNTIME.started_at


for _runtime_delegate in (
    _refresh_solver_last_request,
    _build_solver_for_request,
    _runtime_started_at,
):
    setattr(_CONTEXT, _runtime_delegate.__name__, _runtime_delegate)
    _CONTEXT.__all__.append(_runtime_delegate.__name__)


for _module_name in _NATIVE_MODULES:
    _EXPORTS.publish(importlib.import_module(f"{_PACKAGE}.{_module_name}"))

for _owner in bind_native_server_owners(sys.modules[__name__]):
    _EXPORTS.publish(_owner)
_EXPORTS.publish(
    CollectionStatusReaders(
        repository=lambda: DB_REPOSITORY,
        env_flag=lambda name, default: _runtime_env_flag(name, default),
        prefer_db_reads=lambda: _prefer_db_task_reads(),
        statistics=lambda repository, loader: _collection_statistics.SNAPSHOTS.snapshot(
            repository, loader
        ),
        seed_counts=lambda: _load_collection_seed_queue_counts(),
        empty_counts=lambda: _empty_seed_queue_counts(),
        api_metrics=lambda: llm_helper.get_api_metrics(),
        runtime_snapshot=lambda: _collection_runtime_snapshot(),
        build_info=lambda: _build_info_payload(),
        runtime_state_label=lambda status: (
            _collection_runtime_state_label_from_status_payload(status)
        ),
        solver_status=lambda: _captcha_solver_runtime_status(),
        auth_recovery=lambda: NAS_AUTH_RECOVERY.snapshot(),
        status=lambda: _collection_api_lightweight_status_payload(),
        control=lambda: RUNTIME.control.snapshot(),
        data_root=lambda: Path(DATA_DIR),
        restart=lambda: _engine_restart_status(),
        challenge_metrics=lambda root: _hybrid_collection_challenge_metrics_summary(
            root
        ),
        auth_watcher=lambda root: _pc1_auth_auto_resume_state_summary(root),
    )
)
_EXPORTS.publish(
    AuthCookieSnapshotJobs(
        state=lambda: _auth_cookie_snapshot_runtime_state(),
        retry_attempts=lambda: _auth_cookie_snapshot_retry_attempts(),
        retry_backoff=lambda: _auth_cookie_snapshot_retry_backoff_seconds(),
        set_state=lambda **updates: _set_auth_cookie_snapshot_state(**updates),
        refresh=lambda request: _refresh_auth_cookie_snapshot(request),
        finalize=lambda current_id, **kwargs: (
            _finalize_auth_completion_after_cookie_snapshot(current_id, **kwargs)
        ),
        retry_runner=lambda: _run_auth_cookie_snapshot_retry,
        refresh_enabled=lambda payload: _payload_flag(
            payload, "refresh_cookie_snapshot", True
        ),
        clock=lambda: time.time(),
        sleep=lambda seconds: time.sleep(seconds),
        thread_factory=lambda **kwargs: threading.Thread(**kwargs),
    )
)


_CONSOLE_ASSETS = importlib.import_module(f"{_PACKAGE}.collection_console_assets")


def _safe_collection_static_path(request_path):
    return _CONSOLE_ASSETS.safe_static_path(request_path, dist=COLLECTOR_DESKTOP_DIST)


def _collection_observer_static_asset(request_path):
    return _CONSOLE_ASSETS.static_asset(request_path, dist=COLLECTOR_DESKTOP_DIST)


def _collection_observer_page_html():
    return _CONSOLE_ASSETS.page_html(dist=COLLECTOR_DESKTOP_DIST)


for _console_delegate in (
    _safe_collection_static_path,
    _collection_observer_static_asset,
    _collection_observer_page_html,
):
    setattr(_CONTEXT, _console_delegate.__name__, _console_delegate)
    _CONTEXT.__all__.append(_console_delegate.__name__)


_DESKTOP_AUTH = importlib.import_module(f"{_PACKAGE}.server_desktop_auth")


def _server_desktop_auth_request(handler):
    return _DESKTOP_AUTH._server_desktop_auth_request(
        handler,
        authorize_recovery=_nas_auth_recovery_authorized,
        solver_scope_status=_solver_scope_runtime_status,
        solver_status=_captcha_solver_runtime_status,
        set_pause_state=_set_collection_pause_state,
        nas_auth_recovery=NAS_AUTH_RECOVERY,
        runtime=RUNTIME,
    )


_CONTEXT._server_desktop_auth_request = _server_desktop_auth_request


_ENGINE_CONTROL = importlib.import_module(f"{_PACKAGE}.server_engine_control")


def _collection_operator_start():
    return _ENGINE_CONTROL._collection_operator_start(
        runtime=RUNTIME,
        set_pause_state=_set_collection_pause_state,
        scope_status=_solver_scope_runtime_status,
        runtime_state_label=_collection_runtime_state_label,
    )


def _server_engine_control(handler):
    return _ENGINE_CONTROL._server_engine_control(
        handler,
        collection_operator_start=_collection_operator_start,
        mailbox_factory=_engine_restart_mailbox,
    )


def _engine_restart_status():
    return _ENGINE_CONTROL._engine_restart_status(
        mailbox_factory=_engine_restart_mailbox,
    )


_CONTEXT._engine_restart_mailbox = _ENGINE_CONTROL._engine_restart_mailbox
_CONTEXT._engine_restart_status = _engine_restart_status
_CONTEXT._collection_operator_start = _collection_operator_start
_CONTEXT._server_engine_control = _server_engine_control

_SCOPE_POLICY = importlib.import_module(f"{_PACKAGE}.server_solver_scope")


def _solver_scopes():
    return SolverScopeRuntime(
        RUNTIME,
        Path(DATA_DIR),
        _solver_challenge_state_path,
        CHALLENGE_FORCE_RESET_SECONDS,
    )


def _solver_scope_state_root_path():
    return _solver_scopes().state_root_path()


def _solver_scope_state_path(scope):
    return _solver_scopes().state_path(scope)


def _read_solver_scope_state(scope):
    return _solver_scopes().read(scope)


def _persist_solver_scope_state(scope, state):
    return _solver_scopes().persist(scope, state)


def _scope_challenge_age(scope, now=None):
    return _solver_scopes().age(scope, now)


def _solver_force_unlock_flag_path():
    return _solver_scopes().manual_flag_path()


def _solver_scope_manual_flag_path(scope):
    return _solver_scopes().manual_flag_path(scope)


def _solver_force_unlock_flag_exists():
    return _solver_scopes().manual_flag_exists()


def _collection_effectively_paused():
    return _solver_scopes().effectively_paused()


def _collection_scope_effectively_paused(scope):
    if _solver_force_unlock_flag_exists():
        return True
    return _solver_scopes().scope_effectively_paused(scope, check_manual_flag=False)


def _set_collection_pause_state(paused, reason=None, *, scope=None):
    return _solver_scopes().set_pause(paused, reason, scope=scope)


def _solver_transient_pause_active():
    return _solver_scopes().transient_pause_active()


def _solver_scope_runtime_status(scope, now=None):
    return _solver_scopes().status(scope, now)


def _force_reset_solver_scope(scope, challenge_id=None):
    return _SCOPE_POLICY._force_reset_solver_scope(
        scope,
        challenge_id,
        scopes=_solver_scopes(),
        clear_challenge=_clear_solver_challenge_state,
        remember_reset=_remember_solver_force_reset_recovery,
        solver_status=_captcha_solver_runtime_status,
        report_grace_seconds=SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
    )


from src.manual_review_readers import ManualReviewReaders

_MANUAL_REVIEW_READERS = ManualReviewReaders(
    repository=lambda: DB_REPOSITORY,
    data_root=lambda: Path(DATA_DIR),
)

_EXPORTS.publish(_MANUAL_REVIEW_READERS)

for _owner in bind_native_handler_owners(sys.modules[__name__]):
    _EXPORTS.publish(_owner)

_route_definitions = importlib.import_module(f"{_PACKAGE}.server_routes")
_route_access = importlib.import_module(f"{_PACKAGE}.server_route_access")
_JOB_ROUTES = importlib.import_module(f"{_PACKAGE}.server_collection_jobs")
_MANUAL_REVIEW_DELETE = importlib.import_module(
    f"{_PACKAGE}.server_manual_review_delete"
)
ROUTES = _route_definitions.build_routes(
    {
        **_route_definitions.GET_GROUPS,
        "_get_collection_settings": (_settings_schema.PREFIX,),
        **MANUAL_REVIEW_GET_GROUPS,
    },
    {
        **_route_definitions.POST_GROUPS,
        "_post_manual_review_receipt": tuple(MANUAL_REVIEW_RECEIPT_ENDPOINTS),
        "_post_engine_control": tuple(_engine_control.ROUTES),
        "_post_collection_settings": tuple(_settings_schema.ROLES),
    },
)


class DataHandler(http.server.SimpleHTTPRequestHandler):
    timeout = 30

    def do_HEAD(self):
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        _apply_cors_headers(self)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-FAPAI-Control-Token, X-Fapai-Recovery-Token, X-FAPAI-Collection-Token",
        )
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)
        if request_path in _route_definitions.RETIRED_GET_ROUTES:
            self.send_error_json(
                status=405,
                code="API_METHOD_NOT_ALLOWED",
                message="This operation requires an authenticated POST",
                details={
                    "method": "POST",
                    "path": _route_definitions.RETIRED_GET_ROUTES[request_path],
                },
            )
            return
        handler = ROUTES.get(("GET", request_path))
        if handler is not None:
            return getattr(self, handler)(parsed, request_path, query)
        if request_path.startswith("/collection/") or request_path.startswith(
            "/assets/"
        ):
            return self._get_collection_asset(parsed, request_path, query)
        if request_path.startswith("/api/collection/items/"):
            return self._get_collection_item(parsed, request_path, query)
        if request_path.startswith("/api/"):
            return self._get_api_not_found(parsed, request_path, query)
        return self._server_get_fallback(parsed, request_path, query)

    def do_POST(self):
        request_path = urlparse(self.path).path
        handler = ROUTES.get(("POST", request_path))
        if handler is not None:
            if not self._authorize_write(handler, request_path):
                return
            return getattr(self, handler)()
        return self._server_post_fallback()

    def _authorize_write(self, handler, request_path):
        access = _route_access.required_access("POST", handler)
        if access == "worker":
            return _require_collection_worker(self)
        if access == "node":
            return _require_node_auth(self)
        if access == "recovery":
            authorized, _error = _nas_auth_recovery_authorized(self.headers)
            if not authorized:
                code = (
                    "AUTH_RECOVERY_FORBIDDEN"
                    if request_path == "/api/collection/auth/recovery/request"
                    else "COLLECTION_AUTH_RECOVERY_FORBIDDEN"
                )
                _send_guard_error(
                    self,
                    {
                        "status": 403,
                        "code": code,
                        "message": "Authentication recovery authorization rejected",
                        "details": {},
                    },
                )
            return authorized
        if access in {"engine", "settings"}:
            role = (
                _settings_schema.ROLES.get(request_path)
                if access == "settings"
                else ("operator" if request_path == _engine_control.PREFIX else "agent")
            )
            try:
                _engine_control.authorize(self.headers, role)
            except _engine_control.RestartError as error:
                code = (
                    "SETTINGS_REJECTED"
                    if access == "settings"
                    else "ENGINE_RESTART_REJECTED"
                )
                _send_guard_error(
                    self,
                    {
                        "status": error.status,
                        "code": code,
                        "message": str(error),
                        "details": {},
                    },
                )
                return False
            return True
        return _require_control_plane(self)

    def _post_collection_start(self):
        if not _require_control_plane(self):
            return
        accepted, _payload = _read_json_body(self)
        if accepted:
            self.send_json(_collection_operator_start())

    def _post_desktop_auth_request(self):
        return _server_desktop_auth_request(self)

    def _get_collection_settings(self, parsed, request_path, query):
        return _server_collection_settings(self, read=True)

    def _post_engine_control(self):
        return _server_engine_control(self)

    def _post_collection_settings(self):
        return _server_collection_settings(self)

    def _enqueue_collection_job(
        self,
        operation,
        work,
        failure_code,
        *,
        job_id=None,
        response_status=202,
        response_extra=None,
    ):
        return _JOB_ROUTES.enqueue_job(
            self,
            operation,
            work,
            failure_code,
            data_root=Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR)),
            job_id=job_id,
            response_status=response_status,
            response_extra=response_extra,
        )

    def _submit_maintenance_job(self, operation, failure_code):
        from src.collection_maintenance_jobs import prepare_maintenance

        if not _require_control_plane(self):
            return
        accepted, payload = _read_json_body(self)
        if not accepted:
            return
        active_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
        try:
            work = prepare_maintenance(
                operation,
                payload,
                active_root,
                _detail_collection_service(active_root),
                load_data,
            )
        except Exception as error:
            self.send_error_json(
                status=500,
                code=failure_code,
                message="Unable to prepare collection operation",
                details={"error": str(error)},
            )
            return
        self._enqueue_collection_job(operation, work, failure_code)

    def _submit_pipeline_job(self, config, failure_code):
        pipeline = AVM_PIPELINE

        def run():
            result = pipeline.run(async_mode=False, config=config)
            if result.get("status") != "completed":
                raise RuntimeError(
                    "Pipeline did not complete this request; inspect the pipeline log"
                )
            return result

        self._enqueue_collection_job("pipeline", run, failure_code)

    def _get_collection_job(self, parsed, request_path, query):
        return _JOB_ROUTES.get_job(
            self,
            query.get("id", [""])[0],
            data_root=Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR)),
        )

    def _post_collection_job_cancel(self):
        return _JOB_ROUTES.cancel_job(
            self,
            data_root=Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR)),
        )

    def do_DELETE(self):
        return _MANUAL_REVIEW_DELETE.delete_receipt(
            self,
            endpoints=MANUAL_REVIEW_RECEIPT_ENDPOINTS,
            authorize=_require_control_plane,
            read_body=_read_json_body,
            validate=_validate_manual_review_receipt_delete_payload,
            data_root=lambda: Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR)),
            repository=lambda: DB_REPOSITORY if DB_REPOSITORY.enabled else None,
            delete=delete_manual_review_receipt,
            append_operation=append_manual_review_receipt_operation,
            receipt_context=_manual_review_receipt_context,
            store_path=_manual_review_receipt_store_path,
            operations_path=_manual_review_receipt_operations_path,
        )


_method_names = set(ROUTES.values()) | {
    "_get_collection_asset",
    "_get_api_not_found",
    "_server_get_fallback",
    "_server_post_fallback",
    "send_json",
    "send_error_json",
    "send_invalid_request_body",
    "update_file",
    "run_solver",
    "log_message",
}
for _method_name in sorted(_method_names):
    if _method_name in DataHandler.__dict__:
        continue
    _method = globals()[_method_name]
    _method.__qualname__ = f"DataHandler.{_method_name}"
    setattr(DataHandler, _method_name, _method)


from src.collection_http_server import CollectionHTTPServer, tls_context_from_env


class ReusableTCPServer(CollectionHTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    _listener_tls = tls_context_from_env(os.environ)
    print(f"Starting Data Receiver on port {PORT}...")
    print(f"Serving Pending Tasks from: {os.path.abspath(DATA_DIR)}")
    initialize_runtime()
    AVM_CONFIG_MANAGER.load_on_startup()
    AVM_CONFIG_MANAGER.start_hot_reload_watcher()
    print(f"[AVM-CONFIG] Active config: {AVM_CONFIG_MANAGER.get_config()}")
    threading.Thread(target=background_file_processor, daemon=True).start()
    threading.Thread(target=auto_tuner_thread, daemon=True).start()
    try:
        with ReusableTCPServer(("", PORT), DataHandler, tls=_listener_tls) as httpd:
            print("Server running. Press Ctrl+C to stop.")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServer stopped by user.")
            except Exception as e:
                print(f"\nServer crashed: {e}")
                import traceback

                traceback.print_exc()
    except OSError as e:
        print(f"Error binding to port {PORT}: {e}")
