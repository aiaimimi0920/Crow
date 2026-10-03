"""Bounded exception diagnostics for collection artifacts and console reports.

Exception messages, arguments, URLs, causes and source lines are deliberately
not serialized. Keep raw exceptions in memory for existing retry decisions.
"""

from __future__ import annotations

import errno
import ipaddress
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit

import requests

_ERROR_CATEGORIES = (
    ((requests.Timeout, TimeoutError), "TimeoutError", "timeout"),
    ((requests.HTTPError, HTTPError), "HTTPError", "http_error"),
    (
        (requests.ConnectionError, ConnectionError),
        "ConnectionError",
        "connection_error",
    ),
    ((json.JSONDecodeError,), "JSONDecodeError", "invalid_json"),
    ((requests.RequestException, URLError), "RequestError", "request_error"),
    ((OSError,), "OSError", "io_error"),
    ((ValueError,), "ValueError", "invalid_value"),
    ((TypeError,), "TypeError", "invalid_type"),
    ((LookupError,), "LookupError", "lookup_error"),
    ((RuntimeError,), "RuntimeError", "runtime_error"),
)

# Only fixed repository labels are exposed, never arbitrary co_filename values
# (which may include user paths or be provided by dynamically compiled code).
_STACK_FILES = (
    "tools/live_smoke_runtime.py",
    "tools/live_smoke_analysis_config.py",
    "tools/live_smoke_analysis.py",
    "tools/live_smoke_browser.py",
    "tools/live_smoke_list.py",
    "tools/live_smoke_cdp.py",
    "tools/detail_worker_execution.py",
    "tools/detail_worker_loop.py",
    "tools/detail_worker_artifacts.py",
    "tools/detail_worker_config.py",
    "tools/seed_collector_cycle.py",
    "tools/seed_collector_loop.py",
    "tools/seed_collector_auth.py",
    "src/llm_helper.py",
    "src/llm_openai_compatible.py",
    "src/llm_websocket.py",
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_STACK_LABELS = {str(_REPO_ROOT / name): name for name in _STACK_FILES}


def safe_cdp_endpoint(value: object) -> str:
    """Display only a validated origin; connection paths may also be credentials."""
    unavailable = "<configured CDP endpoint>"
    if type(value) is not str or len(value) > 8192:
        return unavailable
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        return unavailable
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
        if parsed.scheme not in {"http", "https", "ws", "wss"} or port == 0:
            return unavailable
        if ":" in host:
            if "%" in host:
                return unavailable
            host = "[" + str(ipaddress.IPv6Address(host)) + "]"
        elif not re.fullmatch(r"[A-Za-z0-9._-]{1,253}", host):
            return unavailable
        authority = host if port is None else f"{host}:{port}"
        return urlunsplit((parsed.scheme, authority, "", "", ""))
    except ValueError:
        return unavailable


def safe_exception_details(exc: BaseException) -> dict[str, str]:
    """Preserve the receipt type/message shape using fixed diagnostic categories."""
    error_type, message = "Exception", "unexpected_error"
    for classes, candidate_type, category in _ERROR_CATEGORIES:
        if isinstance(exc, classes):
            error_type, message = candidate_type, category
            break
    if isinstance(exc, (requests.HTTPError, HTTPError)):
        status = (
            getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(exc, requests.HTTPError)
            else exc.code
        )
        if type(status) is int and 100 <= status <= 599:
            message += f" status={status}"
    if isinstance(exc, OSError):
        code = exc.errno
        if type(code) is int and code in errno.errorcode:
            message += f" errno={errno.errorcode[code]}"
    return {"type": error_type, "message": message}


def safe_exception_text(exc: BaseException) -> str:
    details = safe_exception_details(exc)
    return f"{details['type']}: {details['message']}"


def safe_exception_traceback(exc: BaseException) -> str:
    """Return up to 20 file/line frames, excluding source, locals and chains."""
    frames: list[str] = []
    current = exc.__traceback__
    while current is not None and len(frames) < 20:
        filename = current.tb_frame.f_code.co_filename
        label = _STACK_LABELS.get(filename, "external")
        line = current.tb_lineno
        safe_line = line if type(line) is int and 1 <= line <= 1_000_000 else 0
        frames.append(f"{label}:{safe_line}")
        current = current.tb_next
    if current is not None:
        frames.append("[truncated]")
    return "\n".join(frames)
