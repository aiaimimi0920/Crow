from contextlib import closing
from http.client import HTTPConnection
import json
from threading import Thread
from types import SimpleNamespace

import pytest

from src import server, server_request_guard


pytestmark = pytest.mark.security
WORKER_TOKEN = "quality-worker-credential-" * 2
WORKER_HEADERS = {"X-FAPAI-Collection-Token": WORKER_TOKEN}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server_request_guard, "_engine_tokens", SimpleNamespace(token=lambda _role: ""))
    monkeypatch.setenv("FAPAI_CONTROL_PLANE_TOKEN", "test-operator")
    token_file = tmp_path / "worker.token"
    token_file.write_text(WORKER_TOKEN, encoding="utf-8")
    monkeypatch.setenv("FAPAI_COLLECTION_WORKER_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", tmp_path / "missing-token")
    with server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler) as httpd:
        thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()

        def request(method, path, body=None, headers=None):
            with closing(HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3)) as connection:
                request_headers = {"Content-Type": "application/json", **(headers or {})}
                connection.request(method, path, body=body, headers=request_headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()

        try:
            yield request
        finally:
            httpd.shutdown()
            thread.join(timeout=3)


def test_head_never_uses_static_file_handler(api, monkeypatch):
    monkeypatch.setattr(server.DataHandler, "send_head", lambda _self: pytest.fail("filesystem HEAD leak"))
    assert api("HEAD", "/AGENTS.md")[0] == 404


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "https://localhost.evil.example", "http://localhost:8765"])
def test_untrusted_origin_does_not_receive_cors_permission(api, origin):
    status, headers, _body = api("OPTIONS", "/api/upload", headers={"Origin": origin})
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers


def test_cors_requires_exact_configured_origin(api, monkeypatch):
    monkeypatch.setenv("FAPAI_CORS_ALLOWED_ORIGINS", "http://localhost:8765")
    assert api("OPTIONS", "/api/status", headers={"Origin": "http://localhost:8765"})[1]["Access-Control-Allow-Origin"] == "http://localhost:8765"
    assert "Access-Control-Allow-Origin" not in api("OPTIONS", "/api/status", headers={"Origin": "http://localhost:8766"})[1]


@pytest.mark.parametrize("authorized", [False, True])
def test_status_only_shares_recovery_details_with_authorized_callers(api, monkeypatch, authorized):
    recovery = {"enabled": True, "active": {"status": "requested", "recovery_id": "private-id", "snapshot": {"value_fingerprint": "private-digest"}}, "private_future_field": "hidden"}
    monkeypatch.setattr(server.DataHandler, "_get_status", lambda handler, *_: handler.send_json({"total_ids": 42, "auth_recovery": recovery}))
    headers = {"X-FAPAI-Control-Token": "test-operator"} if authorized else {}
    status, response_headers, raw = api("GET", "/api/status?test=1", headers=headers)
    assert status == 200
    assert int(response_headers["Content-Length"]) == len(raw)
    payload = json.loads(raw)
    assert payload["total_ids"] == 42
    if authorized:
        assert payload["auth_recovery"] == recovery
    else:
        assert payload["auth_recovery"] == {"enabled": True, "active": {"status": "requested"}, "last_result": None}
        assert b"private" not in raw

def test_real_status_handler_redacts_recovery_snapshot(api, monkeypatch):
    recovery = {
        "enabled": True,
        "status": "active",
        "phase": "waiting",
        "active": {
            "status": "requested",
            "phase": "awaiting_pc2",
            "recovery_id": "private-recovery-id",
            "manual_request_id": "private-manual-request-id",
            "target_url": "https://private.example/auth",
            "challenge_id": "private-challenge-id",
            "snapshot": {
                "sha256": "private-sha256",
                "snapshot_sha256": "private-snapshot-sha256",
                "value_fingerprint": "private-fingerprint",
            },
        },
        "last_result": {
            "status": "completed",
            "phase": "done",
            "recovery_id": "private-last-recovery-id",
            "manual_request_id": "private-last-manual-request-id",
            "target_url": "https://private.example/last",
            "challenge_id": "private-last-challenge-id",
            "snapshot_sha256": "private-last-snapshot-sha256",
            "value_fingerprint": "private-last-fingerprint",
        },
    }
    monkeypatch.setattr(server, "_collection_api_lightweight_status_enabled", lambda: False)
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", [])
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", {})
    monkeypatch.setattr(server.RUNTIME.collection, "dispatched_tasks", {})
    monkeypatch.setattr(
        server,
        "_seed_collection_service",
        lambda: SimpleNamespace(counts_snapshot=lambda: {"search_pending": 0, "search_done": 0}),
    )
    monkeypatch.setattr(
        server.llm_helper,
        "get_api_metrics",
        lambda: {"success_rate": 0.0, "avg_response_time_ms": 0.0, "total_calls": 0, "success_calls": 0},
    )
    monkeypatch.setattr(server, "_db_collection_stage_snapshot", lambda: {})
    monkeypatch.setattr(server, "_collection_runtime_snapshot", lambda: {
        "paused": False,
        "captcha_solver": {},
        "auth_recovery": recovery,
        "collection_scopes": {},
    })
    monkeypatch.setattr(server.AVM_SERVICE, "health_snapshot", lambda lightweight=True: {})
    monkeypatch.setattr(server, "_avm_operator_eval_summary", lambda *_args, **_kwargs: {})

    status, _headers, raw = api("GET", "/api/status")
    assert status == 200
    payload = json.loads(raw)
    assert payload["auth_recovery"] == {
        "enabled": True,
        "status": "active",
        "phase": "waiting",
        "active": {"status": "requested", "phase": "awaiting_pc2"},
        "last_result": {"status": "completed", "phase": "done"},
    }
    for secret in (
        "private-recovery-id",
        "private-manual-request-id",
        "https://private.example/auth",
        "private-challenge-id",
        "private-snapshot-sha256",
        "private-fingerprint",
    ):
        assert secret.encode("utf-8") not in raw

    status, _headers, raw = api("GET", "/api/status", headers={"X-FAPAI-Control-Token": "test-operator"})
    assert status == 200
    assert json.loads(raw)["auth_recovery"] == recovery


@pytest.mark.parametrize("query", ["id=../escape&name=a", "id=ok&name=../escape", "id=ok&name=/escape", "id=ok&name=C%3Afile", "id=ok%0A&name=a"])
def test_upload_rejects_unsafe_paths_without_writing(api, tmp_path, query):
    assert api("POST", "/api/upload?" + query, b"evidence", WORKER_HEADERS)[0] == 400
    assert not (tmp_path / "downloads").exists()


def test_upload_preserves_existing_archive(api, tmp_path):
    path = "/api/upload?id=ok&name=detail.html"
    assert api("POST", path, b"original", WORKER_HEADERS)[0] == 200
    status, _headers, raw = api("POST", path, b"replacement", WORKER_HEADERS)
    assert status == 409
    assert json.loads(raw)["error"]["code"] == "AVM_UPLOAD_EXISTS"
    assert (tmp_path / "downloads" / "ok" / "detail.html").read_bytes() == b"original"


@pytest.mark.parametrize("length, status", [("bad", 400), ("-1", 400), ("999999999", 413)])
def test_json_body_rejects_invalid_or_excessive_lengths(api, length, status):
    assert api("POST", "/api/log", headers={**WORKER_HEADERS, "Content-Length": length})[0] == status


@pytest.mark.parametrize("size", [2, 4096, 65536])
def test_json_endpoint_rejects_simple_cross_origin_form_body(api, size):
    status, _headers, raw = api("POST", "/api/log", b"x" * size, {**WORKER_HEADERS, "Content-Type": "text/plain"})
    assert status == 415
    assert json.loads(raw)["error"]["code"] == "AVM_UNSUPPORTED_CONTENT_TYPE"


def test_excessive_body_reports_stable_error_without_reading(api):
    status, _headers, raw = api("POST", "/api/log", headers={**WORKER_HEADERS, "Content-Length": "999999999"})
    assert status == 413
    assert json.loads(raw)["error"]["code"] == "AVM_REQUEST_BODY_TOO_LARGE"


@pytest.mark.parametrize("path", ["/api/collection/auth/complete", "/api/collection/auth/force_reset"])
def test_auth_mutations_reject_wrong_token(api, path):
    status, _headers, _body = api("POST", path, b"{}", {"X-Fapai-Recovery-Token": "wrong"})
    assert status == 403


def test_unconfigured_control_plane_fails_closed(api, monkeypatch):
    monkeypatch.delenv("FAPAI_CONTROL_PLANE_TOKEN")
    assert api("POST", "/api/avm/run", b"{}")[0] == 503


def test_pipeline_rejects_data_directory_escape(api, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    body = json.dumps({"data_dir": str(tmp_path.parent)})
    assert api("POST", "/api/avm/run", body, {"X-FAPAI-Control-Token": "test-operator"})[0] == 400


def test_error_response_does_not_expose_exception_details(api, monkeypatch):
    monkeypatch.delenv("FAPAI_EXPOSE_ERROR_DETAILS", raising=False)
    monkeypatch.setattr(server.DataHandler, "_post_client_log", lambda handler: handler.send_error_json(
        500, "TEST_FAILURE", "Operation failed", {"error": "database credentials and private path"}))
    status, _headers, raw = api("POST", "/api/log", b"", WORKER_HEADERS)
    assert status == 500
    assert b"database credentials" not in raw
    assert json.loads(raw)["error"]["details"]["error_id"]


@pytest.mark.parametrize("payload", [
    {"cdp_endpoint": "http://169.254.169.254"},
    {"cdp_endpoint": "http://127.0.0.1:9999"},
    {"node_id": "pc2", "cookie_snapshot_path": "../outside.json"},
    {"node_id": "..", "cookie_snapshot_path": "../outside.json"},
])
def test_auth_completion_rejects_untrusted_targets_before_state_change(api, monkeypatch, payload):
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9222")
    monkeypatch.setattr(server, "_collection_observer_auth_complete_payload", lambda _: pytest.fail("state mutated"))
    status, _headers, raw = api("POST", "/api/collection/auth/complete", json.dumps(payload), {"X-FAPAI-Control-Token": "test-operator"})
    assert status == 400
    assert json.loads(raw)["error"]["code"] == "COLLECTION_AUTH_TARGET_REJECTED"


def test_cookie_snapshot_ignores_untrusted_solver_report(tmp_path, monkeypatch):
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {"cookie_snapshot_path": str(tmp_path / "outside.json")})
    monkeypatch.setattr(server, "_auth_cookie_snapshot_root_candidates", lambda: [tmp_path])
    actual = server._resolve_auth_cookie_snapshot_path({"node_id": "pc2"})
    assert actual == str(tmp_path / "secrets" / "nodes" / "pc2" / "taobao-cookies.json")


def test_recovery_authorization_rejects_non_ascii_header_without_type_error(tmp_path, monkeypatch):
    token_file = tmp_path / "recovery.token"
    token_file.write_text("ascii-recovery-token", encoding="utf-8")
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_file)
    monkeypatch.setattr(server.NAS_AUTH_RECOVERY, "enabled", True)

    authorized, reason = server._nas_auth_recovery_authorized(
        {"X-Fapai-Recovery-Token": "☃"}
    )

    assert authorized is False
    assert reason == "auth recovery token is invalid"
