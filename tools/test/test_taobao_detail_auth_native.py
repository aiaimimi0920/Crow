"""Exact-item HTTP proof rejects authentication walls and redirects."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from src import auth_cookie_health
from src.collection.adapters import taobao_detail_auth as detail

TARGET = "https://sf-item.taobao.com/sf_item/864933660682.htm"
READY = '<div id="J_StartPrice">100</div>'


@pytest.mark.parametrize(
    "html,url,healthy",
    [
        (READY, TARGET, True),
        ("", TARGET, False),
        (READY, TARGET.replace("864933660682", "999"), False),
        (READY + "扫码登录", TARGET, False),
        (READY + "请完成验证", TARGET, False),
        (READY + "_____tmd_____/punish", TARGET, False),
        (READY, "https://login.taobao.com/", False),
        (READY, TARGET + "/_____tmd_____/slide", False),
    ],
)
def test_exact_detail_payload_predicate(html, url, healthy):
    assert detail.detail_payload_authenticated(html, url, TARGET) is healthy


@pytest.mark.parametrize(
    "status,healthy", [(200, True), (302, False), (403, False), (500, False)]
)
def test_http_status_and_transport_boundary(status, healthy):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(text=READY, url=TARGET, status_code=status)

    result = detail.probe_detail_page(
        TARGET, cookies=[], session=SimpleNamespace(get=get), user_agent="production-UA"
    )
    assert result["healthy"] is healthy
    assert calls[0][0] == TARGET
    assert calls[0][1]["headers"]["User-Agent"] == "production-UA"
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://sf-item.taobao.com/sf_item/1.htm",
        "https://127.0.0.1/",
        "https://example.invalid/",
    ],
)
def test_invalid_target_never_makes_http_request(url):
    def unexpected(*_args, **_kwargs):
        pytest.fail("invalid detail URL reached transport")

    with pytest.raises(ValueError):
        detail.probe_detail_page(
            url, cookies=[], session=SimpleNamespace(get=unexpected)
        )


@pytest.mark.parametrize("raises", [False, True])
def test_detail_health_keeps_legacy_seed_proof_false(monkeypatch, raises):
    monkeypatch.setattr(
        auth_cookie_health, "resolve_cdp_user_agent", lambda _: "production-UA"
    )

    def probe(url, **kwargs):
        assert url == TARGET and kwargs["user_agent"] == "production-UA"
        if raises:
            raise OSError("cookie2=synthetic-private-value")
        return {"healthy": True}

    monkeypatch.setattr(auth_cookie_health, "probe_detail_page", probe)
    result = auth_cookie_health.probe_cookie_snapshot_health(
        [], [], detail_target_url=TARGET
    )
    assert result["healthy"] is False and result["healthy_samples"] == 0
    assert result["scope"] == "detail" and result["scope_target_url"] == TARGET
    assert result["scope_healthy"] is (not raises)
    assert "synthetic-private-value" not in str(result)


def test_native_detail_import_has_no_tool_or_server_dependency():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import sys; import src.collection.adapters.taobao_detail_auth; "
                "assert not any(n == 'tools' or n.startswith('tools.') for n in sys.modules); "
                "assert 'src.server' not in sys.modules and 'src.server_context' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
