"""Credential binding tests use temporary tokens and fake transports only."""

import pytest

from src import collection_api_credentials as credentials
from tools import internal_api_http


@pytest.fixture
def configured(monkeypatch, tmp_path):
    token = tmp_path / "worker.token"
    token.write_text("fixture_worker_token_" + "a" * 32, encoding="utf-8")
    monkeypatch.setenv(credentials.TOKEN_FILE_ENV, str(token))
    monkeypatch.setenv(credentials.ORIGIN_ENV, "https://crow.test:8443/api")
    ca = tmp_path / "api-ca.pem"
    ca.write_text("fixture CA", encoding="utf-8")
    monkeypatch.setenv(credentials.CA_FILE_ENV, str(ca))
    return token


def test_token_is_read_on_demand_and_existing_role_header_is_preserved(configured):
    url = "https://crow.test:8443/api/report_captcha?scope=seed"
    assert (
        credentials.request_headers(url)[credentials.WORKER_TOKEN_HEADER]
        == configured.read_text()
    )
    configured.write_text("fixture_worker_token_" + "b" * 32, encoding="utf-8")
    assert (
        credentials.request_headers(url)[credentials.WORKER_TOKEN_HEADER]
        == configured.read_text()
    )
    operator = {
        "x-fapai-control-token": "explicit_operator",
        "Accept": "application/json",
    }
    assert credentials.request_headers(url, operator) == operator


@pytest.mark.parametrize(
    "url",
    [
        "https://provider.test:8443/api/report_captcha",
        "https://crow.test:8444/api/report_captcha",
        "http://crow.test:8443/api/report_captcha",
        "https://crow.test:8443/json/list",
        "https://crow.test:8443/api-other/report_captcha",
        "https://crow.test:0/api/report_captcha",
    ],
)
def test_other_destinations_never_receive_or_read_worker_token(
    configured, monkeypatch, url
):
    monkeypatch.setattr(credentials, "worker_token", lambda: pytest.fail("secret read"))
    assert credentials.request_headers(url) == {}


@pytest.mark.parametrize(
    "suffix", ["/../external", "/%2e%2e/external", "/%252e%252e/external"]
)
def test_path_normalization_cannot_escape_bound_api(configured, suffix):
    with pytest.raises(OSError, match="canonical"):
        credentials.request_headers("https://crow.test:8443/api" + suffix)


@pytest.mark.parametrize(
    "origin", ["http://192.0.2.10:8001/api", "http://crow.test:8001/api"]
)
def test_remote_plaintext_is_rejected_before_reading_token(
    configured, monkeypatch, origin
):
    monkeypatch.setenv(credentials.ORIGIN_ENV, origin)
    monkeypatch.setattr(credentials, "worker_token", lambda: pytest.fail("secret read"))
    with pytest.raises(OSError, match="HTTPS"):
        credentials.request_headers(origin + "/log")


def test_remote_https_requires_private_ca_before_reading_worker_token(
    configured, monkeypatch
):
    monkeypatch.delenv(credentials.CA_FILE_ENV)
    monkeypatch.setattr(credentials, "worker_token", lambda: pytest.fail("secret read"))
    with pytest.raises(OSError, match="CA file is required"):
        credentials.request_headers("https://crow.test:8443/api/log")


def test_loopback_https_does_not_require_private_ca(configured, monkeypatch):
    monkeypatch.delenv(credentials.CA_FILE_ENV)
    monkeypatch.setenv(credentials.ORIGIN_ENV, "https://127.0.0.1:8443/api")
    headers = credentials.request_headers("https://127.0.0.1:8443/api/log")
    assert headers[credentials.WORKER_TOKEN_HEADER] == configured.read_text()


@pytest.mark.parametrize("host", ["127.0.0.1", "[::1]", "localhost"])
def test_loopback_tunnels_can_carry_worker_credentials(configured, monkeypatch, host):
    origin = f"http://{host}:8001/api"
    monkeypatch.setenv(credentials.ORIGIN_ENV, origin)
    assert credentials.WORKER_TOKEN_HEADER in credentials.request_headers(
        origin + "/log"
    )


def test_invalid_configuration_fails_without_leaking_file_contents(
    configured, monkeypatch
):
    configured.write_text("bad fixture credential\ncontent", encoding="utf-8")
    with pytest.raises(OSError, match="credential is invalid") as error:
        credentials.request_headers("https://crow.test:8443/api/log")
    assert configured.read_text() not in str(error.value)
    monkeypatch.delenv(credentials.ORIGIN_ENV)
    with pytest.raises(OSError, match="requires CROW_API_BASE_URL"):
        credentials.request_headers("https://crow.test:8443/api/log")


@pytest.mark.parametrize(
    "base", ["https://crow.test:8443", "https://crow.test:8443/root"]
)
def test_api_base_requires_explicit_api_prefix(configured, monkeypatch, base):
    monkeypatch.setenv(credentials.ORIGIN_ENV, base)
    with pytest.raises(OSError, match="/api prefix"):
        credentials.request_headers("https://crow.test:8443/api/log")


def test_internal_post_binds_worker_header_and_rejects_redirect(configured):
    calls = []

    class Response:
        status_code = 302

        def raise_for_status(self):
            pytest.fail("redirect reached HTTP success handling")

    class Session:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    with pytest.raises(OSError, match="redirects"):
        internal_api_http.post_json(
            "https://crow.test:8443/api/report_captcha",
            {"scope": "seed"},
            timeout=1,
            session=Session(),
        )
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["headers"] == {
        credentials.WORKER_TOKEN_HEADER: configured.read_text()
    }
