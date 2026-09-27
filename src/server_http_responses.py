"""HTTP response serialization without collection runtime initialization."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import BinaryIO, Protocol
from urllib.parse import urlparse

from src.server_request_guard import (
    GuardRequest,
    _apply_cors_headers,
    _env_flag,
    _public_auth_recovery_snapshot,
    _verify_node_auth_token,
)

logger = logging.getLogger(__name__)


class JsonResponseHandler(GuardRequest, Protocol):
    path: str
    wfile: BinaryIO

    def send_response(self, code: int, message: str | None = None) -> None: ...

    def end_headers(self) -> None: ...


def _is_client_disconnect_error(error: BaseException) -> bool:
    return isinstance(
        error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
    ) or getattr(error, "errno", None) in {32, 104, 10053, 10054}


def _json_payload_type_name(payload: object) -> str:
    if payload is None:
        return "null"
    if isinstance(payload, dict):
        return "object"
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, bool):
        return "boolean"
    if isinstance(payload, (int, float)):
        return "number"
    if isinstance(payload, str):
        return "string"
    return type(payload).__name__


def _write_json_response(
    handler: JsonResponseHandler, status: int, payload: object
) -> None:
    try:
        raw = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        _apply_cors_headers(handler)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(raw)))
        if status == 405:
            handler.send_header("Allow", "POST")
        handler.end_headers()
        handler.wfile.write(raw)
    except Exception as error:
        if _is_client_disconnect_error(error):
            return
        raise


def send_json(handler: JsonResponseHandler, data: object) -> None:
    if urlparse(handler.path).path == "/api/status" and isinstance(data, dict):
        authorized, _error = _verify_node_auth_token(handler.headers)
        if not authorized and "auth_recovery" in data:
            data = {
                **data,
                "auth_recovery": _public_auth_recovery_snapshot(data["auth_recovery"]),
            }
    _write_json_response(handler, 200, data)


def _redact_error_details(
    status: int, code: str, details: Mapping[str, object] | None
) -> dict[str, object]:
    """Keep exception text out of 5xx responses unless explicitly configured."""
    result = dict(details or {})
    if status < 500 or _env_flag("FAPAI_EXPOSE_ERROR_DETAILS", "0"):
        return result
    error_text = result.pop("error", None)
    if error_text is None:
        return result
    error_id = uuid.uuid4().hex[:16]
    logger.error("%s error_id=%s: %s", code, error_id, error_text)
    result["error_id"] = error_id
    return result


def send_error_json(
    handler: JsonResponseHandler,
    status: int,
    code: str,
    message: str,
    details: Mapping[str, object] | None = None,
) -> None:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": _redact_error_details(status, code, details),
        }
    }
    _write_json_response(handler, status, payload)


def send_invalid_request_body(handler: JsonResponseHandler, payload: object) -> None:
    handler.send_error_json(
        status=400,
        code="AVM_INVALID_REQUEST_BODY",
        message="请求体必须是 JSON 对象",
        details={
            "expected_type": "object",
            "received_type": _json_payload_type_name(payload),
        },
    )


__all__ = [
    "_is_client_disconnect_error",
    "_json_payload_type_name",
    "_write_json_response",
    "_redact_error_details",
    "send_json",
    "send_error_json",
    "send_invalid_request_body",
]
