from __future__ import annotations

import base64
import hashlib
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src import server, server_request_guard


class FakeCoordinator:
    enabled = True
    stall_seconds = 1800

    def __init__(self):
        self.claims = []

    def snapshot(self):
        return {
            "enabled": True,
            "stall_seconds": 1800,
            "active": {
                "recovery_id": "auth-recovery-1",
                "status": "requested",
                "snapshot": None,
            },
        }

    def claim(self, role, recovery_id, node_id):
        self.claims.append((role, recovery_id, node_id))
        return {"ok": True, "recovery": self.snapshot()["active"]}


def _request_json(url, *, method="GET", payload=None, recovery_token=""):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Fapai-Recovery-Token": recovery_token,
        },
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def _request_error(url, *, method="GET", payload=None, raw_data=None, recovery_token=""):
    data = raw_data if raw_data is not None else (
        None if payload is None else json.dumps(payload).encode("utf-8")
    )
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Fapai-Recovery-Token": recovery_token,
        },
    )
    with pytest.raises(HTTPError) as caught:
        urlopen(request, timeout=5)
    return caught.value.code, json.load(caught.value)


def test_recovery_api_exposes_safe_state_and_accepts_exact_pc1_claim(monkeypatch, tmp_path):
    coordinator = FakeCoordinator()
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/collection/auth/recovery"
        forbidden_status, forbidden_body = _request_error(base, recovery_token="wrong-token")
        state = _request_json(base, recovery_token="test-recovery-token")
        claim = _request_json(
            f"{base}/claim",
            method="POST",
            payload={"recovery_id": "auth-recovery-1", "role": "pc1", "node_id": "pc1"},
            recovery_token="test-recovery-token",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert state["auth_recovery"]["active"]["status"] == "requested"
    assert forbidden_status == 403
    assert forbidden_body["error"]["code"] == "COLLECTION_AUTH_RECOVERY_FORBIDDEN"
    assert claim["ok"] is True
    assert coordinator.claims == [("pc1", "auth-recovery-1", "pc1")]
    assert "cookies" not in json.dumps(state)


def test_recovery_snapshot_endpoint_relays_only_the_active_digest_matched_file(monkeypatch, tmp_path):
    snapshot_path = tmp_path / "taobao-cookies.json"
    raw = json.dumps(
        [{"name": "session", "value": "secret", "domain": ".taobao.com", "path": "/"}]
    ).encode("utf-8")
    snapshot_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")

    class SnapshotCoordinator:
        enabled = True

        def snapshot(self):
            return {
                "enabled": True,
                "active": {
                    "recovery_id": "auth-recovery-1",
                    "status": "snapshot_ready",
                    "snapshot": {"sha256": digest, "cookie_count": 1},
                },
            }

    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SnapshotCoordinator())
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", lambda _payload: str(snapshot_path))
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/collection/auth/recovery"
        payload = _request_json(
            f"{base}/snapshot?recovery_id=auth-recovery-1",
            recovery_token="test-recovery-token",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert payload["sha256"] == digest
    assert payload["encoding"] == "base64"
    assert base64.b64decode(payload["snapshot"]) == raw


def test_recovery_snapshot_endpoint_reports_each_validation_failure(monkeypatch, tmp_path):
    class SnapshotCoordinator:
        enabled = True

        def __init__(self):
            self.active = None

        def snapshot(self):
            return {"enabled": True, "active": self.active}

    coordinator = SnapshotCoordinator()
    snapshot_path = tmp_path / "taobao-cookies.json"
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", lambda _payload: str(snapshot_path))
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = (
            f"http://127.0.0.1:{httpd.server_address[1]}"
            "/api/collection/auth/recovery/snapshot?recovery_id=auth-recovery-1"
        )
        cases = [
            (
                {"recovery_id": "other", "status": "requested", "snapshot": None},
                None,
                "COLLECTION_AUTH_RECOVERY_NOT_ACTIVE",
            ),
            (
                {"recovery_id": "auth-recovery-1", "status": "requested", "snapshot": None},
                None,
                "COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY",
            ),
            (
                {
                    "recovery_id": "auth-recovery-1",
                    "status": "snapshot_ready",
                    "snapshot": {"sha256": hashlib.sha256(b"missing").hexdigest()},
                },
                None,
                "COLLECTION_AUTH_RECOVERY_SNAPSHOT_MISSING",
            ),
            (
                {
                    "recovery_id": "auth-recovery-1",
                    "status": "snapshot_ready",
                    "snapshot": {"sha256": hashlib.sha256(b"").hexdigest()},
                },
                b"",
                "COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID",
            ),
            (
                {
                    "recovery_id": "auth-recovery-1",
                    "status": "snapshot_ready",
                    "snapshot": {"sha256": hashlib.sha256(b"expected").hexdigest()},
                },
                b"changed",
                "COLLECTION_AUTH_RECOVERY_SNAPSHOT_CHANGED",
            ),
        ]
        assert {case[2] for case in cases} == {
            "COLLECTION_AUTH_RECOVERY_NOT_ACTIVE",
            "COLLECTION_AUTH_RECOVERY_SNAPSHOT_CHANGED",
            "COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID",
            "COLLECTION_AUTH_RECOVERY_SNAPSHOT_MISSING",
            "COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY",
        }
        for active, contents, expected_code in cases:
            coordinator.active = active
            snapshot_path.unlink(missing_ok=True)
            if contents is not None:
                snapshot_path.write_bytes(contents)
            status, body = _request_error(endpoint, recovery_token="test-recovery-token")
            assert status in {404, 409}
            assert body["error"]["code"] == expected_code
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_recovery_post_routes_validate_authenticated_object_bodies(monkeypatch, tmp_path):
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", FakeCoordinator())
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{httpd.server_address[1]}"
        routes = (
            "/api/collection/auth/recovery/claim",
            "/api/collection/auth/recovery/snapshot_ready",
            "/api/collection/auth/recovery/pc2_restarting",
            "/api/collection/auth/recovery/result",
        )
        for route in routes:
            status, body = _request_error(
                origin + route,
                method="POST",
                raw_data=b"[",
                recovery_token="test-recovery-token",
            )
            assert status == 400
            assert body["error"]["code"] == "AVM_INVALID_JSON"
            status, body = _request_error(
                origin + route,
                method="POST",
                payload=[],
                recovery_token="test-recovery-token",
            )
            assert status == 400
            assert body["error"]["code"] == "AVM_INVALID_REQUEST_BODY"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_recovery_claim_and_force_reset_expose_structured_rejections(monkeypatch, tmp_path):
    coordinator = FakeCoordinator()
    coordinator.claim = lambda *_args: {"ok": False, "error": "rejected"}
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    monkeypatch.setattr(server, "_force_reset_solver_scope", lambda *_args: {"ok": False})
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{httpd.server_address[1]}"
        status, body = _request_error(
            origin + "/api/collection/auth/recovery/claim",
            method="POST",
            payload={"recovery_id": "auth-recovery-1", "role": "pc1", "node_id": "pc1"},
            recovery_token="test-recovery-token",
        )
        assert status == 400
        assert body["error"]["code"] == "COLLECTION_AUTH_RECOVERY_REJECTED"
        status, body = _request_error(
            origin + "/api/collection/auth/force_reset",
            method="POST",
            payload={"scope": "detail", "challenge_id": "challenge-1"},
        )
        assert status == 403
        assert body["error"]["code"] == "COLLECTION_AUTH_RECOVERY_FORBIDDEN"
        status, body = _request_error(
            origin + "/api/collection/auth/force_reset",
            method="POST",
            payload={"scope": "detail", "challenge_id": "challenge-1"},
            recovery_token="test-recovery-token",
        )
        assert status == 409
        assert body["error"]["code"] == "COLLECTION_CHALLENGE_FORCE_RESET_REJECTED"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_successful_pc2_result_clears_auth_pause_then_waits_for_real_progress(monkeypatch):
    calls = []

    class ResultCoordinator:
        def snapshot(self):
            return {"active": {"recovery_id": "auth-recovery-1"}}

        def result(self, recovery_id, *, success, reason=""):
            calls.append((recovery_id, success, reason))
            return {"ok": True, "status": "verifying"}

    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", ResultCoordinator())
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda: None)
    monkeypatch.setattr(server, "_remember_solver_auth_completion", lambda payload: calls.append(("remember", payload)))
    monkeypatch.setattr(server, "_collection_effectively_paused", lambda: False)
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": False})

    result = server._nas_auth_recovery_result(
        {
            "recovery_id": "auth-recovery-1",
            "success": True,
            "reason": "cookie_import_verified_after_restart",
        }
    )

    assert result["status"] == "verifying"
    assert result["paused"] is False
    assert calls[0] == (
        "auth-recovery-1",
        True,
        "cookie_import_verified_after_restart",
    )
    assert calls[1][0] == "remember"


def test_unhealthy_cookie_signal_requires_an_active_solver_pause(monkeypatch):
    monkeypatch.setattr(
        server,
        "_auth_cookie_snapshot_runtime_status",
        lambda: {
            "status": "failed",
            "result": {"reason": "cookie_snapshot_candidate_unhealthy"},
        },
    )
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": False})
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": True})
    assert server._nas_auth_recovery_signal() == "cookie_snapshot_candidate_unhealthy"

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "manual_required": True},
    )
    assert server._nas_auth_recovery_signal() == "captcha_manual_required"


def test_stalled_stage_challenges_are_independent_auth_recovery_signals(monkeypatch):
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS", 300)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {"status": "idle"})

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "seed": {"paused": True, "challenge_age_seconds": 900},
                "detail": {"paused": True, "challenge_age_seconds": 299},
            },
        },
    )
    assert server._nas_auth_recovery_signal() == "seed_challenge_stalled"

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "seed": {"paused": False, "challenge_age_seconds": 0},
                "detail": {"paused": True, "challenge_age_seconds": 300},
            },
        },
    )
    assert server._nas_auth_recovery_signal() == "detail_challenge_stalled"


def test_node_solver_blocked_report_persists_strong_recovery_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server.RUNTIME.control, "scope_root", None)
    monkeypatch.setattr(
        server.RUNTIME.control,
        "scopes",
        {scope: server._new_solver_scope_state() for scope in server.CHALLENGE_SCOPES},
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "challenge_id", None)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "pending_token", None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)

    request = {
        "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "scope": "detail",
        "node_solver_blocked": True,
        "node_solver_blocked_reason": "repeated_solver_failures",
        "node_solver_blocked_attempts": 10,
    }
    first = server._node_solver_blocked_report_payload(request)
    blocked_at = first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_at_epoch"
    ]
    second = server._node_solver_blocked_report_payload(request)

    assert first["status"] == "node_solver_blocked"
    assert first["scope"] == "detail"
    assert first["captcha_solver"]["manual_required"] is True
    assert first["captcha_solver"]["scopes"]["detail"]["node_solver_blocked"] is True
    assert first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_reason"
    ] == "repeated_solver_failures"
    assert first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_attempts"
    ] == 10
    assert second["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_at_epoch"
    ] == blocked_at
    assert server._nas_auth_recovery_signal() == "captcha_manual_required"

    assert server._clear_solver_challenge_state(scope="detail") is None
    assert server._nas_auth_recovery_signal() is None


def test_node_solver_blocked_signal_requires_paused_scoped_failure(monkeypatch):
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {"status": "idle"})
    base_scope = {
        "paused": True,
        "node_solver_blocked": True,
        "node_solver_blocked_reason": "repeated_solver_failures",
    }

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "scopes": {"detail": {**base_scope, "paused": False}}},
    )
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server.RUNTIME.control, "reason", "operator")
    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "scopes": {"detail": base_scope}},
    )
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "detail": {**base_scope, "node_solver_blocked_reason": "transient_failure"}
            },
        },
    )
    assert server._nas_auth_recovery_signal() is None
