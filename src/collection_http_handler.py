"""Shared HTTP dispatch and authorization for collection application hosts."""

from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from threading import Event
from types import ModuleType
from urllib.parse import parse_qs, urlparse

from . import server_collection_jobs, server_route_access, server_routes


class CollectionRequestHandler(SimpleHTTPRequestHandler):
    application: ModuleType
    closing: Event | None = None
    timeout = 30

    def do_HEAD(self):
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.application._apply_cors_headers(self)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Crow-Control-Token, X-Crow-Recovery-Token, X-Crow-Collection-Token, X-FAPAI-Control-Token, X-Fapai-Recovery-Token, X-FAPAI-Collection-Token",
        )
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in server_routes.RETIRED_GET_ROUTES:
            self.send_error_json(
                status=405,
                code="API_METHOD_NOT_ALLOWED",
                message="This operation requires an authenticated POST",
                details={
                    "method": "POST",
                    "path": server_routes.RETIRED_GET_ROUTES[path],
                },
            )
            return
        handler = self.application.ROUTES.get(("GET", path))
        if handler is not None:
            return getattr(self, handler)(parsed, path, query)
        if path.startswith(("/collection/", "/assets/")):
            return self._get_collection_asset(parsed, path, query)
        if path.startswith("/api/collection/items/"):
            return self._get_collection_item(parsed, path, query)
        if path.startswith("/api/"):
            return self._get_api_not_found(parsed, path, query)
        return self._server_get_fallback(parsed, path, query)

    def do_POST(self):
        path = urlparse(self.path).path
        handler = self.application.ROUTES.get(("POST", path))
        if handler is not None:
            if self._authorize_write(handler, path):
                return getattr(self, handler)()
            return
        return self._server_post_fallback()

    def _authorize_write(self, handler, request_path):
        if self.closing is not None and self.closing.is_set():
            self.send_error_json(
                status=503,
                code="COLLECTION_STOPPING",
                message="Collection application is closing",
            )
            return False
        host = self.application
        access = server_route_access.required_access("POST", handler)
        if access == "worker":
            return host._require_collection_worker(self)
        if access == "node":
            return host._require_node_auth(self)
        if access == "recovery":
            authorized, _error = host._nas_auth_recovery_authorized(self.headers)
            if not authorized:
                host._send_guard_error(
                    self,
                    {
                        "status": 403,
                        "code": "AUTH_RECOVERY_FORBIDDEN"
                        if request_path == "/api/collection/auth/recovery/request"
                        else "COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                        "message": "Authentication recovery authorization rejected",
                        "details": {},
                    },
                )
            return authorized
        if access in {"engine", "settings"}:
            role = (
                host._settings_schema.ROLES.get(request_path)
                if access == "settings"
                else (
                    "operator"
                    if request_path == host._engine_control.PREFIX
                    else "agent"
                )
            )
            try:
                host._engine_control.authorize(self.headers, role)
            except host._engine_control.RestartError as error:
                host._send_guard_error(
                    self,
                    {
                        "status": error.status,
                        "code": "SETTINGS_REJECTED"
                        if access == "settings"
                        else "ENGINE_RESTART_REJECTED",
                        "message": str(error),
                        "details": {},
                    },
                )
                return False
            return True
        return host._require_control_plane(self)

    def _post_collection_start(self):
        host = self.application
        if not host._require_control_plane(self):
            return
        accepted, _payload = host._read_json_body(self)
        if accepted:
            self.send_json(host._collection_operator_start())

    def _post_desktop_auth_request(self):
        return self.application._server_desktop_auth_request(self)

    def _get_collection_settings(self, parsed, request_path, query):
        return self.application._server_collection_settings(self, read=True)

    def _post_engine_control(self):
        return self.application._server_engine_control(self)

    def _post_collection_settings(self):
        return self.application._server_collection_settings(self)

    def _enqueue_collection_job(self, operation, work, failure_code, **options):
        return server_collection_jobs.enqueue_job(
            self,
            operation,
            work,
            failure_code,
            data_root=Path(self.application.DATA_DIR),
            **options,
        )

    def _submit_maintenance_job(self, operation, failure_code):
        from .collection_maintenance_jobs import prepare_maintenance

        host = self.application
        if not host._require_control_plane(self):
            return
        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        root = Path(host.DATA_DIR)
        try:
            work = prepare_maintenance(
                operation,
                payload,
                root,
                host._detail_collection_service(root),
                host.load_data,
            )
        except Exception as error:  # noqa: BLE001 - preserve the HTTP failure boundary.
            self.send_error_json(
                status=500,
                code=failure_code,
                message="Unable to prepare collection operation",
                details={"error": str(error)},
            )
            return
        self._enqueue_collection_job(operation, work, failure_code)

    def _get_collection_job(self, parsed, request_path, query):
        return server_collection_jobs.get_job(
            self, query.get("id", [""])[0], data_root=Path(self.application.DATA_DIR)
        )

    def _post_collection_job_cancel(self):
        return server_collection_jobs.cancel_job(
            self, data_root=Path(self.application.DATA_DIR)
        )


def build_collection_handler(host: ModuleType) -> type[CollectionRequestHandler]:
    class Handler(CollectionRequestHandler):
        application = host
        closing = host.STOP_EVENT

    names = set(host.ROUTES.values()) | {
        "_get_collection_asset",
        "_get_collection_item",
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
    for name in names:
        if not hasattr(Handler, name) or name == "log_message":
            setattr(Handler, name, getattr(host, name))
    return Handler
