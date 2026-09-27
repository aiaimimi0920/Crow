"""Real dispatcher checks: no writes or task claims before role authorization."""

import json
from types import SimpleNamespace

import pytest

from src import server, server_request_guard
from src.server_route_access import required_access
from src.server_routes import RETIRED_GET_ROUTES
from tools.test.test_quality_http_guards import WORKER_HEADERS, WORKER_TOKEN, api

pytestmark = pytest.mark.security
OPERATOR = "quality-operator-credential-" * 2
AGENT = "quality-agent-credential-" * 2
RECOVERY = "quality-recovery-credential-" * 2


@pytest.fixture
def configured_api(api, tmp_path, monkeypatch):
    for role, token in (("OPERATOR", OPERATOR), ("AGENT", AGENT)):
        path = tmp_path / f"{role}.token"
        path.write_text(token, encoding="utf-8")
        monkeypatch.setenv(f"FAPAI_ENGINE_{role}_TOKEN_FILE", str(path))
    monkeypatch.setenv("FAPAI_CONTROL_PLANE_TOKEN", OPERATOR)
    path = tmp_path / "recovery.token"
    path.write_text(RECOVERY, encoding="utf-8")
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", path)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(enabled=True))
    return api


def credentials(path, handler):
    role = required_access("POST", handler)
    if role == "worker":
        return WORKER_HEADERS
    if role in {"node", "recovery"}:
        return {"X-Fapai-Recovery-Token": RECOVERY}
    if role == "engine" and path != server._engine_control.PREFIX:
        return {"X-FAPAI-Control-Token": AGENT}
    if role == "settings" and server._settings_schema.ROLES[path] == "agent":
        return {"X-FAPAI-Control-Token": AGENT}
    return {"X-FAPAI-Control-Token": OPERATOR}


def test_every_post_route_rejects_missing_and_wrong_credentials(configured_api, monkeypatch):
    calls = []
    for (method, path), handler in server.ROUTES.items():
        if method != "POST":
            continue
        monkeypatch.setattr(server.DataHandler, handler, lambda *_: calls.append(True))
        for headers in ({}, {"X-FAPAI-Collection-Token": "wrong", "X-FAPAI-Control-Token": "wrong", "X-Fapai-Recovery-Token": "wrong"}):
            status, _, raw = configured_api("POST", path + "?trace=auth", b"not json", headers)
            assert status == 403, (path, status, raw)
            assert "error" in json.loads(raw)
    assert calls == []


def test_real_route_policy_accepts_only_its_role(configured_api, monkeypatch):
    def respond(handler):
        handler.rfile.read(int(handler.headers["Content-Length"]))
        handler.send_json({"accepted": True})

    for (method, path), handler in server.ROUTES.items():
        if method != "POST":
            continue
        monkeypatch.setattr(server.DataHandler, handler, respond)
        status, _, raw = configured_api("POST", path, b"{}", credentials(path, handler))
        assert status == 200 and json.loads(raw) == {"accepted": True}, (path, raw)
        if required_access(method, handler) != "worker":
            assert configured_api("POST", path, b"{}", WORKER_HEADERS)[0] == 403, path


@pytest.mark.parametrize("path", ["/api/collection/control/restart/poll", "/api/collection/settings/poll"])
def test_operator_does_not_acquire_agent_privileges(configured_api, path):
    assert configured_api("POST", path, b"{}", {"X-FAPAI-Control-Token": OPERATOR})[0] == 403


def test_worker_missing_invalid_rotated_and_operator_reused_credentials_fail_closed(api, tmp_path, monkeypatch):
    path = tmp_path / "worker.token"
    path.write_text("invalid", encoding="utf-8")
    assert api("POST", "/api/log", b"{}", WORKER_HEADERS)[0] == 503
    path.write_text(OPERATOR, encoding="utf-8")
    monkeypatch.setenv("FAPAI_CONTROL_PLANE_TOKEN", OPERATOR)
    assert api("POST", "/api/log", b"{}", {"X-FAPAI-Collection-Token": OPERATOR})[0] == 503
    path.write_text(WORKER_TOKEN + "rotated", encoding="utf-8")
    assert api("POST", "/api/log", b"{}", WORKER_HEADERS)[0] == 403
    assert api("POST", "/api/log", b"{}", {"X-FAPAI-Collection-Token": WORKER_TOKEN + "rotated"})[0] == 200
    monkeypatch.delenv("FAPAI_COLLECTION_WORKER_TOKEN_FILE")
    assert api("POST", "/api/log", b"{}", WORKER_HEADERS)[0] == 503


def test_retired_get_routes_cannot_claim_resume_or_write_reports(configured_api, tmp_path, monkeypatch):
    evidence = tmp_path / "organized.json"
    evidence.write_bytes(b"preserve this evidence")
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", ["pending-item"])
    monkeypatch.setattr(server.RUNTIME.collection, "dispatched_tasks", {})
    before = set(tmp_path.rglob("*"))
    for path, replacement in RETIRED_GET_ROUTES.items():
        status, headers, raw = configured_api("GET", path + "?dry_run=false", headers={"X-FAPAI-Control-Token": OPERATOR})
        assert status == 405 and headers["Allow"] == "POST", path
        assert json.loads(raw)["error"]["code"] == "API_METHOD_NOT_ALLOWED"
        assert json.loads(raw)["error"]["details"]["path"] == replacement
    assert RETIRED_GET_ROUTES["/api/resume"] == "/api/collection/control/resume"
    assert server.RUNTIME.control.paused is True and server.RUNTIME.collection.pending_tasks == ["pending-item"]
    assert server.RUNTIME.collection.dispatched_tasks == {}
    assert set(tmp_path.rglob("*")) == before
    assert evidence.read_bytes() == b"preserve this evidence"


def test_read_only_get_does_not_change_runtime_lifecycle(configured_api, monkeypatch):
    sentinel = 123.0
    monkeypatch.setattr(server.RUNTIME, "started_at", sentinel)
    initialized = server.RUNTIME.initialized
    assert configured_api("GET", "/api/unknown-status")[0] == 404
    assert server.RUNTIME.started_at == sentinel
    assert server.RUNTIME.initialized is initialized


def test_post_seed_claim_uses_body_not_query_and_validates_before_claim(api, monkeypatch):
    claims = []
    monkeypatch.setattr(server, "_seed_collection_service", lambda: SimpleNamespace(
        next_task=lambda session, **_: claims.append(session) or {"task": None}))
    monkeypatch.setattr(server, "_collection_scope_effectively_paused", lambda _: False)
    assert api("POST", "/api/collection/seeds/next_task?session_id=untrusted", b'{"session_id":"actual"}', WORKER_HEADERS)[0] == 200
    for invalid in ([], {}, None, "", "x" * 129):
        status, _, raw = api("POST", "/api/collection/seeds/next_task", json.dumps({"session_id": invalid}), WORKER_HEADERS)
        assert status == 400
        assert json.loads(raw)["error"]["code"] == "AVM_INVALID_SESSION_ID"
    assert claims == ["actual"]
