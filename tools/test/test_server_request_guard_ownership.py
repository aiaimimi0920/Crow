"""Request policies must work at their owner, without facade-global injection."""

from io import BytesIO
from types import SimpleNamespace

import pytest

from src import server
from src import server_request_guard as guard

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    ("endpoint", "permitted"),
    [
        ("http://solver.example:9222", True),
        ("http://localhost:9222", True),
        ("https://secondary.example:9443/", True),
        ("http://localhost:9999", False),
        ("http://169.254.169.254", False),
        ("http://solver.example:9222#other", False),
        ("http://user:password@solver.example:9222", False),
    ],
)
def test_native_cdp_policy_uses_the_configured_allowlist(
    monkeypatch, endpoint, permitted
):
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://solver.example:9222")
    monkeypatch.setenv("FAPAI_CDP_ALLOWED_ENDPOINTS", "https://secondary.example:9443")

    assert guard._cdp_endpoint_permitted(endpoint) is permitted


@pytest.mark.parametrize("consumer", ["native", "facade"])
def test_node_auth_reads_rotated_credentials_from_its_owner(
    monkeypatch, tmp_path, consumer
):
    token_file = tmp_path / "recovery.token"
    token_file.write_text("first-token", encoding="utf-8")
    monkeypatch.setattr(guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_file)
    monkeypatch.delenv("FAPAI_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("FAPAI_ENGINE_OPERATOR_TOKEN_FILE", raising=False)
    owner = guard if consumer == "native" else server
    headers = {"X-Fapai-Recovery-Token": "first-token"}

    assert owner._verify_node_auth_token(headers) == (True, None)
    token_file.write_text("rotated-token", encoding="utf-8")
    authorized, error = owner._verify_node_auth_token(headers)
    assert authorized is False
    assert error["status"] == 403
    assert owner._verify_node_auth_token(
        {"X-Fapai-Recovery-Token": "rotated-token"}
    ) == (True, None)

    token_file.write_bytes(b"\xff")
    authorized, error = owner._verify_node_auth_token(headers)
    assert authorized is False
    assert error["status"] == 503


def test_recovery_coordinator_uses_the_same_credential_reader(monkeypatch, tmp_path):
    token_file = tmp_path / "recovery.token"
    token_file.write_text("recovery-token", encoding="utf-8")
    monkeypatch.setattr(guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_file)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(enabled=True))
    headers = {"X-Fapai-Recovery-Token": "recovery-token"}

    assert server._nas_auth_recovery_authorized(headers) == (True, "")
    token_file.write_text("rotated-token", encoding="utf-8")
    assert server._nas_auth_recovery_authorized(headers) == (
        False,
        "auth recovery token is invalid",
    )
    token_file.write_text("", encoding="utf-8")
    assert server._nas_auth_recovery_authorized(headers) == (
        False,
        "auth recovery token is not configured",
    )


def test_facade_body_reader_observes_owner_limit_before_reading(monkeypatch):
    errors = []
    body = BytesIO(b'{"x":1}')
    handler = SimpleNamespace(
        headers={"Content-Length": "7", "Content-Type": "application/json"},
        rfile=body,
        close_connection=False,
        send_error_json=lambda **error: errors.append(error),
    )
    monkeypatch.setattr(guard, "REQUEST_BODY_MAX_BYTES", 6)

    assert server._read_json_body(handler) == (False, None)
    assert handler.close_connection is True
    assert errors[0]["status"] == 413
    assert errors[0]["code"] == "AVM_REQUEST_BODY_TOO_LARGE"
    assert body.tell() == 0


def test_desktop_auth_server_entrypoint_delegates_to_native_owner(monkeypatch):
    from src import server_desktop_auth

    calls = []

    def fake_native(handler, **dependencies):
        calls.append((handler, dependencies))

    monkeypatch.setattr(
        server_desktop_auth, "_server_desktop_auth_request", fake_native
    )
    handler = object()
    server._server_desktop_auth_request(handler)

    assert calls == [
        (
            handler,
            {
                "authorize_recovery": server._nas_auth_recovery_authorized,
                "solver_scope_status": server._solver_scope_runtime_status,
                "solver_status": server._captcha_solver_runtime_status,
                "set_pause_state": server._set_collection_pause_state,
                "nas_auth_recovery": server.NAS_AUTH_RECOVERY,
                "runtime": server.RUNTIME,
            },
        )
    ]
