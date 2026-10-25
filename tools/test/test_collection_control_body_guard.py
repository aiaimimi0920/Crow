"""Real TLS control transport rejects invalid media, encoding and short bodies."""

import io
import json
import ssl
from http.client import HTTPSConnection
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from tools import collection_control_https as control_http
from tools.test.test_collection_control_https import (
    control as control,  # noqa: PLC0414 -- pytest fixture re-export
)

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    ("body", "headers", "status", "code"),
    [
        (b"{}", {"Content-Type": "text/plain"}, 415, "CONTROL_REJECTED"),
        (b"{}", {}, 415, "CONTROL_REJECTED"),
        (
            b"\xff\xfe{\x00}\x00",
            {"Content-Type": "application/json"},
            400,
            "CONTROL_INVALID",
        ),
        (b"\xff\xff", {"Content-Type": "application/json"}, 400, "CONTROL_INVALID"),
        (
            b"{}",
            {"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
            400,
            "CONTROL_REJECTED",
        ),
    ],
    ids=["plain-text", "missing-media", "utf16", "invalid-utf8", "transfer-encoding"],
)
def test_control_rejects_unsupported_transport(
    control, monkeypatch, body, headers, status, code
):
    base, ca, _, _ = control
    calls = []
    monkeypatch.setattr(
        control_http, "dispatch", lambda *args: calls.append(args) or {"ok": True}
    )
    parsed = urlsplit(base)
    connection = HTTPSConnection(
        parsed.hostname,
        parsed.port,
        context=ssl.create_default_context(cafile=str(ca)),
        timeout=3,
    )
    try:
        connection.request(
            "POST", "/api/collection/settings/apply", body=body, headers=headers
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        assert response.status == status
        assert result == {"ok": False, "code": code}
        assert calls == []
    finally:
        connection.close()


def test_control_rejects_incomplete_body_before_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        control_http, "dispatch", lambda *args: calls.append(args) or {"ok": True}
    )
    handler = object.__new__(control_http.Handler)
    handler.command = "POST"
    handler.path = "/api/collection/settings/apply"
    handler.headers = {"Content-Length": "12", "Content-Type": "application/json"}
    handler.rfile = io.BytesIO(b"{}")
    handler.connection = SimpleNamespace(
        shutdown=lambda *_: None, settimeout=lambda *_: None
    )
    handler.server = SimpleNamespace(runtime_root=None)
    handler.respond = lambda status, body: calls.append((status, body))
    handler.handle_control()
    assert calls == [(400, {"ok": False, "code": "CONTROL_INVALID"})]
