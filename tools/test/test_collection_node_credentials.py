"""Exercise node role routing without reading installed credentials or sending writes."""

import os

import pytest
import requests

from src import collection_api_credentials as credentials
from tools import internal_api_http
from tools.test.test_collection_api_credentials import configured as configured
from tools.test.test_collection_control_https import control as control


@pytest.fixture
def recovery(configured, monkeypatch, tmp_path):
    path = tmp_path / "node.token"
    path.write_text("recovery_fixture_" + "r" * 40, encoding="utf-8")
    monkeypatch.setenv(credentials.RECOVERY_TOKEN_FILE_ENV, str(path))
    return path


@pytest.mark.parametrize("path", sorted(credentials.NODE_AUTH_PATHS))
def test_node_posts_use_recovery_role_and_observe_rotation(recovery, path):
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class Session:
        def post(self, url, **options):
            calls.append((url, options))
            return Response()

    url = "https://crow.test:8443" + path
    for token in (recovery.read_text(), "rotated_fixture_" + "b" * 40):
        recovery.write_text(token, encoding="utf-8")
        assert internal_api_http.post_json(url, {}, timeout=1, session=Session()) == {
            "ok": True
        }
        assert calls[-1][1]["headers"] == {credentials.RECOVERY_TOKEN_HEADER: token}
        assert calls[-1][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "url,method",
    [
        ("https://other.test:8443/api/collection/auth/complete", "POST"),
        ("https://crow.test:8444/api/collection/auth/complete", "POST"),
        ("https://crow.test:8443/api/collection/auth/complete_extra", "POST"),
        ("https://crow.test:8443/api/collection/auth/complete", "GET"),
        ("https://crow.test:8443/api/log", "POST"),
        ("https://crow.test:8443/json/list", "GET"),
    ],
)
def test_recovery_secret_is_not_read_for_other_routes(recovery, url, method):
    recovery.write_text("invalid secret", encoding="utf-8")
    assert credentials.RECOVERY_TOKEN_HEADER not in credentials.request_headers(
        url, method=method
    )


@pytest.mark.parametrize("failure", ["missing", "invalid", "same_as_worker"])
def test_node_credentials_fail_closed(configured, recovery, monkeypatch, failure):
    if failure == "missing":
        monkeypatch.delenv(credentials.RECOVERY_TOKEN_FILE_ENV)
    elif failure == "invalid":
        recovery.write_text("invalid fixture", encoding="utf-8")
    else:
        recovery.write_text(configured.read_text(), encoding="utf-8")
    with pytest.raises(OSError):
        credentials.request_headers(
            "https://crow.test:8443/api/collection/auth/complete", method="POST"
        )


def test_recovery_configuration_does_not_change_unrelated_clients(
    recovery, monkeypatch
):
    monkeypatch.delenv(credentials.TOKEN_FILE_ENV)
    monkeypatch.delenv(credentials.ORIGIN_ENV)
    assert credentials.request_headers("http://127.0.0.1:9222/json/list") == {}
    supplied = {credentials.RECOVERY_TOKEN_HEADER: "explicit_fixture"}
    assert (
        credentials.request_headers(
            "https://explicit.test/api/collection/auth/complete",
            supplied,
            method="POST",
        )
        == supplied
    )


def test_private_ca_is_bound_to_api_and_never_disables_verification(
    configured, monkeypatch, tmp_path
):
    ca = tmp_path / "ca.pem"
    ca.write_text("fixture CA", encoding="utf-8")
    monkeypatch.setenv(credentials.CA_FILE_ENV, str(ca))
    assert credentials.request_verify("https://crow.test:8443/api/status") == str(ca)
    assert credentials.request_verify("https://other.test/api/status") is True
    assert credentials.request_verify("https://crow.test:8443/json/list") is True
    monkeypatch.setenv(credentials.CA_FILE_ENV, str(tmp_path / "missing.pem"))
    with pytest.raises(OSError, match="CA file"):
        credentials.request_verify("https://crow.test:8443/api/status")


def test_private_ca_roundtrip_and_untrusted_certificate_rejection(
    control, configured, recovery, monkeypatch
):
    origin, ca, _, _ = control
    received = []

    def dispatch(_root, method, path, headers, body):
        received.append((method, path, dict(headers), body))
        return {"ok": True}

    monkeypatch.setattr("tools.collection_control_https.dispatch", dispatch)
    monkeypatch.setenv(credentials.ORIGIN_ENV, origin + "/api")
    monkeypatch.setenv(credentials.CA_FILE_ENV, str(ca))
    assert internal_api_http.fetch_json(origin + "/api/status", timeout=2) == {
        "ok": True
    }
    assert internal_api_http.post_json(
        origin + "/api/collection/auth/complete", {"node_id": "fixture"}, timeout=2
    ) == {"ok": True}
    assert received[1][2][credentials.RECOVERY_TOKEN_HEADER] == recovery.read_text()
    assert credentials.WORKER_TOKEN_HEADER not in received[1][2]
    monkeypatch.delenv(credentials.CA_FILE_ENV)
    with pytest.raises(OSError):
        internal_api_http.fetch_json(origin + "/api/status", timeout=2)
    assert len(received) == 2


def test_reused_session_cannot_add_stale_roles_or_disable_tls(recovery):
    calls = []

    class Capture(requests.adapters.BaseAdapter):
        def send(self, request, **options):
            calls.append((request, options))
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"ok": true}'
            return response

        def close(self):
            pass

    with requests.Session() as session:
        session.trust_env = False
        session.verify = False
        session.headers[credentials.WORKER_TOKEN_HEADER] = "stale-worker-fixture"
        session.headers["X-FAPAI-Control-Token"] = "stale-operator-fixture"
        session.mount("https://", Capture())
        internal_api_http.post_json(
            "https://crow.test:8443/api/collection/auth/complete",
            {},
            timeout=1,
            session=session,
        )
        request, options = calls[0]
        assert (
            request.headers[credentials.RECOVERY_TOKEN_HEADER] == recovery.read_text()
        )
        assert credentials.WORKER_TOKEN_HEADER not in request.headers
        assert "X-FAPAI-Control-Token" not in request.headers
        assert options["verify"] == os.environ[credentials.CA_FILE_ENV]
        assert session.verify is False
        assert (
            session.headers[credentials.WORKER_TOKEN_HEADER] == "stale-worker-fixture"
        )
