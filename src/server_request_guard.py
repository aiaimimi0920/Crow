"""Request guards shared by every public handler: body limits, CORS, tokens."""

from __future__ import annotations

import hmac
import json
import os
import socket
from pathlib import Path
from typing import BinaryIO, Protocol, TypedDict
from urllib.parse import urlsplit

from src import collection_api_credentials as _worker_credentials
from src import collection_engine_restart as _engine_tokens
from src.server_runtime_paths import NAS_AUTH_RECOVERY_TOKEN_FILE
from src.solver_request_payload import _normalize_solver_cdp_endpoint

REQUEST_BODY_MAX_BYTES = max(
    65536, int(os.getenv("FAPAI_MAX_REQUEST_BODY_BYTES") or 16 * 1024 * 1024)
)
REQUEST_BODY_HTML_MAX_BYTES = max(
    REQUEST_BODY_MAX_BYTES,
    int(os.getenv("FAPAI_MAX_HTML_REQUEST_BODY_BYTES") or 64 * 1024 * 1024),
)
UPLOAD_MAX_BYTES = max(
    65536, int(os.getenv("FAPAI_MAX_UPLOAD_BYTES") or 64 * 1024 * 1024)
)
CORS_DEFAULT_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
CONTROL_TOKEN_HEADER = "X-FAPAI-Control-Token"
RECOVERY_TOKEN_HEADER = "X-Fapai-Recovery-Token"
_TRUTHY = {"1", "true", "yes", "on"}


class RequestHeaders(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...


class GuardRequest(Protocol):
    headers: RequestHeaders
    rfile: BinaryIO
    connection: socket.socket
    close_connection: bool

    def send_header(self, keyword: str, value: str) -> None: ...

    def send_error_json(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None: ...

    def send_invalid_request_body(self, payload: object) -> None: ...


class GuardError(TypedDict):
    status: int
    code: str
    message: str
    details: dict[str, object]


def _env_flag(name: str, default: str) -> bool:
    return str(os.getenv(name) or default).strip().lower() in _TRUTHY


def _read_json_body(
    self: GuardRequest, *, max_bytes: int | None = None
) -> tuple[bool, dict[str, object] | None]:
    """Return (accepted, payload). On rejection the error response was already sent."""
    limit = int(max_bytes or REQUEST_BODY_MAX_BYTES)
    if self.headers.get("Transfer-Encoding"):
        self.close_connection = True
        self.send_error_json(
            status=400,
            code="AVM_INVALID_JSON",
            message="Unsupported transfer encoding",
            details={},
        )
        return (False, None)
    try:
        content_length = int(str(self.headers.get("Content-Length") or "0").strip())
    except ValueError:
        content_length = -1
    if content_length < 0:
        self.close_connection = True
        self.send_error_json(
            status=400,
            code="AVM_INVALID_JSON",
            message="请求体不是合法 JSON",
            details={"reason": "invalid_content_length"},
        )
        return (False, None)
    if content_length > limit:
        self.close_connection = True
        self.send_error_json(
            status=413,
            code="AVM_REQUEST_BODY_TOO_LARGE",
            message="请求体超过大小上限",
            details={"max_bytes": limit, "content_length": content_length},
        )
        return (False, None)
    content_type = (
        str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    )
    if content_length and content_type != "application/json":
        _send_guard_error(
            self,
            {
                "status": 415,
                "code": "AVM_UNSUPPORTED_CONTENT_TYPE",
                "message": "Content-Type must be application/json",
                "details": {},
            },
        )
        return (False, None)
    try:
        raw = self.rfile.read(content_length)
        if len(raw) != content_length:
            raise ValueError("incomplete request body")
        payload = json.loads(raw.decode("utf-8")) if content_length > 0 else {}
    except Exception:
        self.send_error_json(
            status=400,
            code="AVM_INVALID_JSON",
            message="请求体不是合法 JSON",
            details={},
        )
        return (False, None)
    if not isinstance(payload, dict):
        self.send_invalid_request_body(payload)
        return (False, None)
    return (True, payload)


def _read_limited_body(
    self: GuardRequest, *, max_bytes: int, min_bytes: int = 0
) -> bytes:
    """Read a bounded request body and reject malformed length headers uniformly."""
    try:
        content_length = int(str(self.headers.get("Content-Length") or "0").strip())
    except (TypeError, ValueError) as error:
        raise ValueError("invalid content length") from error
    if content_length < min_bytes or content_length > max_bytes:
        raise ValueError("invalid request body length")
    body = self.rfile.read(content_length)
    if len(body) != content_length:
        raise ValueError("incomplete request body")
    return body


def _cors_allowed_origins() -> set[str]:
    configured = str(os.getenv("FAPAI_CORS_ALLOWED_ORIGINS") or "")
    origins = {
        item.strip().rstrip("/") for item in configured.split(",") if item.strip()
    }
    origins.update(CORS_DEFAULT_ORIGINS)
    return origins


def _cors_origin_permitted(origin: object) -> bool:
    candidate = str(origin or "").strip().rstrip("/")
    if not candidate or candidate.lower() == "null":
        return False
    return candidate in _cors_allowed_origins()


def _apply_cors_headers(self: GuardRequest) -> None:
    origin = str(self.headers.get("Origin") or "").strip()
    if origin and _cors_origin_permitted(origin):
        self.send_header("Access-Control-Allow-Origin", origin.rstrip("/"))
        self.send_header("Vary", "Origin")


def _control_plane_expected_tokens() -> list[bytes]:
    tokens: list[bytes] = []
    env_token = str(os.getenv("FAPAI_CONTROL_PLANE_TOKEN") or "").strip()
    if env_token:
        tokens.append(env_token.encode("utf-8"))
    file_token = _engine_tokens.token("operator")
    if file_token:
        tokens.append(file_token.encode("utf-8"))
    return tokens


def _token_matches(supplied: object, expected: list[bytes]) -> bool:
    candidate = str(supplied or "").strip().encode("utf-8")
    if not candidate:
        return False
    matched = False
    for token in expected:
        if hmac.compare_digest(candidate, token):
            matched = True
    return matched


def _control_plane_unconfigured_error() -> GuardError:
    return {
        "code": "AVM_CONTROL_PLANE_UNCONFIGURED",
        "message": "control-plane token 未配置，操作类接口已拒绝",
        "status": 503,
        "details": {
            "expected": [
                "FAPAI_ENGINE_OPERATOR_TOKEN_FILE",
                "FAPAI_CONTROL_PLANE_TOKEN",
            ]
        },
    }


def _verify_control_plane_token(
    headers: RequestHeaders,
) -> tuple[bool, GuardError | None]:
    expected = _control_plane_expected_tokens()
    if not expected:
        return False, _control_plane_unconfigured_error()
    if _token_matches(headers.get(CONTROL_TOKEN_HEADER), expected):
        return True, None
    return False, {
        "code": "AVM_CONTROL_PLANE_FORBIDDEN",
        "message": "control-plane token 校验失败",
        "status": 403,
        "details": {},
    }


def _recovery_expected_token() -> str:
    try:
        token_file: Path = NAS_AUTH_RECOVERY_TOKEN_FILE
        return token_file.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _verify_node_auth_token(
    headers: RequestHeaders,
) -> tuple[bool, GuardError | None]:
    """Solver-node auth routes accept the recovery token or the operator token."""
    recovery = _recovery_expected_token()
    control = _control_plane_expected_tokens()
    if not recovery and not control:
        return False, _control_plane_unconfigured_error()
    if recovery and _token_matches(
        headers.get(RECOVERY_TOKEN_HEADER), [recovery.encode("utf-8")]
    ):
        return True, None
    if control and _token_matches(headers.get(CONTROL_TOKEN_HEADER), control):
        return True, None
    return False, {
        "code": "COLLECTION_AUTH_RECOVERY_FORBIDDEN",
        "message": "跨设备认证恢复凭据无效",
        "status": 403,
        "details": {"error": "auth recovery token is invalid"},
    }


def _send_guard_error(self: GuardRequest, error: GuardError) -> None:
    self.close_connection = True
    self.send_error_json(
        status=int(error.get("status") or 403),
        code=error["code"],
        message=error["message"],
        details=error.get("details", {}),
    )
    # Half-close before a bounded drain: closing with unread upload bytes can
    # reset the connection and discard the rejection response on Windows.
    try:
        self.connection.shutdown(socket.SHUT_WR)
        length = int(self.headers.get("Content-Length") or "0")
        if 0 < length <= 65536:
            self.connection.settimeout(0.1)
            self.rfile.read(length)
    except (OSError, ValueError):
        pass


def _require_control_plane(self: GuardRequest) -> bool:
    (authorized, error) = _verify_control_plane_token(self.headers)
    if not authorized:
        assert error is not None
        _send_guard_error(self, error)
    return authorized


def _require_node_auth(self: GuardRequest) -> bool:
    (authorized, error) = _verify_node_auth_token(self.headers)
    if not authorized:
        assert error is not None
        _send_guard_error(self, error)
    return authorized


def _require_collection_worker(self: GuardRequest) -> bool:
    control = _control_plane_expected_tokens()
    if _token_matches(self.headers.get(CONTROL_TOKEN_HEADER), control):
        return True
    try:
        expected = _worker_credentials.worker_token()
    except OSError:
        expected = ""
    if not expected or _token_matches(expected, control):
        _send_guard_error(
            self,
            {
                "status": 503,
                "code": "COLLECTION_WORKER_UNCONFIGURED",
                "message": "A distinct collection-worker credential is required",
                "details": {},
            },
        )
        return False
    if _token_matches(
        self.headers.get(_worker_credentials.WORKER_TOKEN_HEADER),
        [expected.encode("utf-8")],
    ):
        return True
    _send_guard_error(
        self,
        {
            "status": 403,
            "code": "COLLECTION_WORKER_FORBIDDEN",
            "message": "Collection-worker authorization rejected",
            "details": {},
        },
    )
    return False


def _cdp_endpoint_permitted(value: object) -> bool:
    endpoint = str(value or "").strip()
    if not endpoint:
        return False
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https", "ws", "wss"}
        or parsed.username
        or parsed.password
    ):
        return False
    if not parsed.hostname or parsed.fragment:
        return False
    configured = [os.getenv("FAPAI_CDP_ENDPOINT") or ""]
    configured.extend(str(os.getenv("FAPAI_CDP_ALLOWED_ENDPOINTS") or "").split(","))
    allowed = {
        _normalize_solver_cdp_endpoint(item.strip()).rstrip("/")
        for item in configured
        if item.strip()
    }
    return _normalize_solver_cdp_endpoint(endpoint).rstrip("/") in allowed


def _public_auth_recovery_snapshot(snapshot: object) -> dict[str, object]:
    """The unauthenticated status view never exposes recovery identifiers or targets."""
    data = snapshot if isinstance(snapshot, dict) else {}
    # ``enabled`` is a non-sensitive deployment/readiness fact.  Keep it in the
    # public projection so health checks can verify the recovery subsystem
    # without requiring a token, while all identifiers and targets stay private.
    public = {
        name: data[name] for name in ("enabled", "status", "phase") if name in data
    }
    for key in ("active", "last_result"):
        section = data.get(key)
        public[key] = (
            {name: section[name] for name in ("status", "phase") if name in section}
            if isinstance(section, dict)
            else None
        )
    return public


__all__ = [
    "CORS_DEFAULT_ORIGINS",
    "_TRUTHY",
    "REQUEST_BODY_MAX_BYTES",
    "REQUEST_BODY_HTML_MAX_BYTES",
    "UPLOAD_MAX_BYTES",
    "CONTROL_TOKEN_HEADER",
    "RECOVERY_TOKEN_HEADER",
    "_env_flag",
    "_read_json_body",
    "_read_limited_body",
    "_cors_allowed_origins",
    "_cors_origin_permitted",
    "_apply_cors_headers",
    "_control_plane_expected_tokens",
    "_token_matches",
    "_verify_control_plane_token",
    "_control_plane_unconfigured_error",
    "_recovery_expected_token",
    "_verify_node_auth_token",
    "_send_guard_error",
    "_require_control_plane",
    "_require_node_auth",
    "_require_collection_worker",
    "_cdp_endpoint_permitted",
    "_public_auth_recovery_snapshot",
    "_engine_tokens",
    "_worker_credentials",
]
