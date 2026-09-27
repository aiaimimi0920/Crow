"""Error contracts exercise real handlers without persistent control mailboxes."""

import json
from types import SimpleNamespace

import pytest

from src import server, server_collection_settings
from tools.test.test_quality_http_guards import api as api


def code(api, path, body=b"{}"):
    status, _headers, raw = api("POST", path, body)
    assert status >= 400
    return json.loads(raw)["error"]["code"]


@pytest.fixture
def controls(monkeypatch):
    monkeypatch.setattr(server._engine_control, "authorize", lambda *_: None)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _: (True, None))
    monkeypatch.setattr(
        server_collection_settings,
        "_collection_settings_store",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(server, "_engine_restart_mailbox", lambda: SimpleNamespace())


def unavailable():
    raise OSError("synthetic storage failure")


def test_settings_invalid_json(api, controls):
    assert (
        code(api, server._settings_schema.PREFIX + "/apply", b"{broken")
        == "SETTINGS_INVALID"
    )


def test_settings_rejects_non_object(api, controls):
    assert (
        code(api, server._settings_schema.PREFIX + "/apply", b"[]")
        == "SETTINGS_REJECTED"
    )


def test_settings_storage_unavailable(api, controls, monkeypatch):
    monkeypatch.setattr(
        server_collection_settings, "_collection_settings_store", unavailable
    )
    assert (
        code(api, server._settings_schema.PREFIX + "/apply") == "SETTINGS_UNAVAILABLE"
    )


def test_restart_invalid_json(api, controls):
    assert (
        code(api, server._engine_control.PREFIX, b"{broken")
        == "ENGINE_RESTART_INVALID_JSON"
    )


def test_restart_rejects_unexpected_fields(api, controls):
    assert code(api, server._engine_control.PREFIX) == "ENGINE_RESTART_REJECTED"


def test_restart_storage_unavailable(api, controls, monkeypatch):
    monkeypatch.setattr(server, "_engine_restart_mailbox", unavailable)
    assert (
        code(api, server._engine_control.PREFIX, b'{"request_id":"test"}')
        == "ENGINE_RESTART_STORAGE_UNAVAILABLE"
    )


AUTH_PATH = "/api/collection/auth/recovery/request"


def test_auth_recovery_rejects_invalid_fields(api, controls):
    assert code(api, AUTH_PATH) == "AUTH_RECOVERY_INVALID"


def test_auth_recovery_rejects_missing_token(api, monkeypatch):
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _: (False, {}))
    assert code(api, AUTH_PATH) == "AUTH_RECOVERY_FORBIDDEN"


def test_auth_recovery_rejects_changed_challenge(api, controls, monkeypatch):
    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda: {"challenge_id": "current"}
    )
    assert (
        code(api, AUTH_PATH, b'{"request_id":"test","challenge_id":"old"}')
        == "AUTH_CHALLENGE_CHANGED"
    )


def test_auth_recovery_reports_unavailable(api, controls, monkeypatch):
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", unavailable)
    assert (
        code(api, AUTH_PATH, b'{"request_id":"test","challenge_id":"current"}')
        == "AUTH_RECOVERY_UNAVAILABLE"
    )


def test_auth_recovery_rejects_busy_coordinator(api, controls, monkeypatch):
    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda: {"challenge_id": "current"}
    )
    monkeypatch.setattr(
        server,
        "NAS_AUTH_RECOVERY",
        SimpleNamespace(request_manual=lambda *_, **__: {"ok": False, "busy": True}),
    )
    assert (
        code(api, AUTH_PATH, b'{"request_id":"test","challenge_id":"current"}')
        == "AUTH_RECOVERY_REJECTED"
    )


def test_auth_recovery_requires_stage_capability(api, controls, monkeypatch):
    monkeypatch.setattr(
        server, "NAS_AUTH_RECOVERY", SimpleNamespace(snapshot=lambda: {})
    )
    body = json.dumps(
        {
            "request_id": "test",
            "challenge_id": "current",
            "scope": "detail",
            "target_url": "https://sf-item.taobao.com/sf_item/1001.htm",
            "protocol_version": 2,
        }
    )
    assert code(api, AUTH_PATH, body) == "AUTH_PC2_UPGRADE_REQUIRED"
