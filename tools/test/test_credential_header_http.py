"""Exercise actual loopback TLS/header parsing with synthetic role credentials."""

import http.client
import ssl
from urllib.parse import urlsplit

import pytest

from src import collection_api_credentials as credentials
from tools.test import test_collection_api_credentials as credential_fixtures
from tools.test import test_collection_control_https as control_fixtures

pytestmark = pytest.mark.security

configured = credential_fixtures.configured
control = control_fixtures.control


def test_tls_control_accepts_each_namespace_and_rejects_ambiguous_fields(control):
    origin, ca, tokens, _root = control
    target = urlsplit(origin)
    operator = tokens["operator"].read_text()
    agent = tokens["agent"].read_text()
    new, old = "X-Crow-Control-Token", "X-FAPAI-Control-Token"
    cases = [
        ([(new, operator)], 200),
        ([(old, operator)], 200),
        ([(new.lower(), operator), (old.upper(), operator)], 200),
        ([(new, agent)], 403),
        ([(new, operator), (old, agent)], 403),
        ([(old, operator), (old.lower(), agent)], 403),
        ([(old, operator), (old.lower(), operator)], 403),
        ([(new, operator + "," + agent)], 403),
        (
            [
                (new, operator),
                ("X-Crow-Recovery-Token", "one"),
                ("X-Fapai-Recovery-Token", "two"),
            ],
            403,
        ),
    ]
    for headers, expected in cases:
        connection = http.client.HTTPSConnection(
            target.hostname,
            target.port,
            context=ssl.create_default_context(cafile=str(ca)),
            timeout=5,
        )
        try:
            connection.putrequest("GET", "/api/collection/settings")
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            body = response.read().decode()
            assert response.status == expected
            assert operator not in body and agent not in body
        finally:
            connection.close()


@pytest.mark.parametrize("name", sorted(credentials.CREDENTIAL_HEADERS))
def test_new_and_old_explicit_credentials_keep_transport_guards(configured, name):
    with pytest.raises(OSError, match="HTTPS"):
        credentials.request_headers(
            "http://remote.invalid/api/log", {name: "synthetic"}
        )
    supplied = {name: "synthetic"}
    assert (
        credentials.request_headers("https://crow.test:8443/api/log", supplied)
        == supplied
    )


def test_supplied_alias_conflict_is_rejected_before_destination_or_token_read(
    configured, monkeypatch
):
    monkeypatch.setattr(
        credentials, "worker_token", lambda: pytest.fail("must not read token")
    )
    with pytest.raises(OSError, match="Conflicting") as error:
        credentials.request_headers(
            "https://crow.test:8443/api/log",
            {
                "X-Crow-Collection-Token": "private-one",
                "X-FAPAI-Collection-Token": "private-two",
            },
        )
    assert "private" not in str(error.value)


def test_recovery_http_names_and_cors_preserve_origin_boundary(monkeypatch, tmp_path):
    import threading

    from src import server, server_request_guard
    from tools.test.test_server_nas_auth_recovery_api import FakeCoordinator

    token = "synthetic-recovery-fixture"
    path = tmp_path / "recovery.token"
    path.write_text(token)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", FakeCoordinator())
    monkeypatch.setattr(server_request_guard, "NAS_AUTH_RECOVERY_TOKEN_FILE", path)
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        for fields, expected in [
            ([("X-Crow-Recovery-Token", token)], 200),
            ([("x-fapai-recovery-token", token)], 200),
            (
                [("X-Crow-Recovery-Token", token), ("X-Fapai-Recovery-Token", token)],
                200,
            ),
            (
                [
                    ("X-Crow-Recovery-Token", token),
                    ("X-Fapai-Recovery-Token", "different"),
                ],
                403,
            ),
            (
                [
                    ("X-Crow-Recovery-Token", token),
                    ("x-crow-recovery-token", "different"),
                ],
                403,
            ),
        ]:
            connection = http.client.HTTPConnection(*httpd.server_address, timeout=5)
            try:
                connection.putrequest("GET", "/api/collection/auth/recovery")
                for key, value in fields:
                    connection.putheader(key, value)
                connection.endheaders()
                response = connection.getresponse()
                assert response.status == expected
                assert token not in response.read().decode()
            finally:
                connection.close()
        for origin, allowed in [
            ("tauri://localhost", True),
            ("https://untrusted.invalid", False),
        ]:
            connection = http.client.HTTPConnection(*httpd.server_address, timeout=5)
            try:
                connection.request(
                    "OPTIONS",
                    "/api/collection/auth/recovery",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Headers": "X-Crow-Recovery-Token,X-Fapai-Recovery-Token",
                    },
                )
                response = connection.getresponse()
                assert (
                    response.getheader("Access-Control-Allow-Origin") == origin
                ) is allowed
                names = response.getheader("Access-Control-Allow-Headers", "").lower()
                assert (
                    "x-crow-recovery-token" in names
                    and "x-fapai-recovery-token" in names
                )
                response.read()
            finally:
                connection.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_worker_guard_keeps_roles_and_rejects_cross_role_conflicts(monkeypatch):
    from types import SimpleNamespace

    from src import server_request_guard as guard

    worker, operator = "synthetic-worker", "synthetic-operator"
    monkeypatch.setattr(
        guard, "_control_plane_expected_tokens", lambda: [operator.encode()]
    )
    monkeypatch.setattr(credentials, "worker_token", lambda: worker)
    for fields, accepted in [
        ({"X-Crow-Collection-Token": worker}, True),
        ({"X-FAPAI-Collection-Token": worker}, True),
        ({"X-Crow-Collection-Token": worker, "X-FAPAI-Collection-Token": worker}, True),
        ({"X-Crow-Control-Token": operator}, True),
        ({"X-Crow-Recovery-Token": worker}, False),
        (
            {
                "X-Crow-Control-Token": operator,
                "X-Crow-Collection-Token": worker,
                "X-FAPAI-Collection-Token": "different",
            },
            False,
        ),
    ]:
        errors = []
        request = SimpleNamespace(
            headers=fields,
            connection=SimpleNamespace(shutdown=lambda _how: None),
            send_error_json=lambda _errors=errors, **payload: _errors.append(payload),
        )
        assert guard._require_collection_worker(request) is accepted
        assert bool(errors) is not accepted
