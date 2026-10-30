"""Classify existing redirect responses without following or exposing Location."""

import json
from types import SimpleNamespace

import pytest

from src import auth_cookie_health
from src.collection.adapters import taobao_detail_auth as detail

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
SECRET = "synthetic-redirect-secret"


@pytest.mark.parametrize(
    "location,kind",
    [
        (None, "missing_location"),
        ("", "missing_location"),
        (
            f"https://login.taobao.com/member/login.jhtml?token={SECRET}",
            "login_required",
        ),
        (f"//login.m.taobao.com/?token={SECRET}", "login_required"),
        (f"/havanaone/login?token={SECRET}", "login_required"),
        (
            f"/sf_item/123.htm/_____tmd_____/punish?x5secdata={SECRET}",
            "challenge_required",
        ),
        (f"/sf_item/123.htm?x5secdata={SECRET}", "challenge_required"),
        ("/sf_item/123.htm?x5sec=", "challenge_required"),
        ("/sf_item/123.htm?X5SECDATA", "challenge_required"),
        ("/sf_item/123.htm?%785sec=", "challenge_required"),
        (f"/sf_item/123.htm?trace={SECRET}", "same_detail"),
        ("https://susong-item.taobao.com/auction/123.htm", "same_detail"),
        ("/sf_item/456.htm", "other_detail"),
        ("https://sf.taobao.com/list/other.htm", "other_taobao"),
        (f"https://example.invalid/?next={SECRET}", "external_target"),
        ("https://taobao.com.example.invalid/_____tmd_____/punish", "external_target"),
        ("https://127.0.0.1/private", "external_target"),
        ("http://sf-item.taobao.com/sf_item/123.htm", "non_https_target"),
        ("https://sf-item.taobao.com:9443/sf_item/123.htm", "invalid_location"),
        (f"https://{SECRET}@sf-item.taobao.com/sf_item/123.htm", "invalid_location"),
        ("https://[invalid", "invalid_location"),
        ("javascript:alert(1)", "invalid_location"),
        ("https://login.taobao.com/\r\nCookie: synthetic", "invalid_location"),
        ("https://login.taobao.com/\tpath", "invalid_location"),
        (r"https://login.taobao.com\@example.invalid/", "invalid_location"),
        pytest.param("/" + "x" * 8193, "invalid_location", id="overlong-location"),
        pytest.param(
            "/?" + "a=1&" * 129, "invalid_location", id="too-many-query-fields"
        ),
        (123, "invalid_location"),
    ],
)
def test_redirect_diagnostic_is_enum_only_and_never_a_health_proof(location, kind):
    calls = []

    def get(url, **options):
        calls.append((url, options))
        return SimpleNamespace(
            url=TARGET,
            text=f'<div id="J_StartPrice">{SECRET}</div>',
            status_code=302,
            headers={} if location is None else {"lOcAtIoN": location},
        )

    result = detail.probe_detail_page(
        TARGET, cookies=[], session=SimpleNamespace(get=get), timeout=7
    )
    assert result["redirect_kind"] == kind
    assert result["healthy"] is False
    assert result["status"] == "detail_auth_unverified"
    assert len(calls) == 1 and calls[0][0] == TARGET
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["timeout"] == 7
    assert SECRET not in json.dumps(result)
    assert set(result) == {
        "scope",
        "check_url",
        "final_url",
        "http_status",
        "healthy",
        "status",
        "redirect_kind",
    }


@pytest.mark.parametrize("status", [200, 301, 302, 303, 304, 307, 308, 403, 500])
def test_classification_only_for_navigation_redirects_and_legacy_responses(status):
    response = SimpleNamespace(url=TARGET, text="", status_code=status)
    result = detail.probe_detail_page(
        TARGET, cookies=[], session=SimpleNamespace(get=lambda *_a, **_k: response)
    )
    if status in {301, 302, 303, 307, 308}:
        assert result["redirect_kind"] == "missing_location"
    else:
        assert "redirect_kind" not in result
    assert result["healthy"] is False


def test_redirect_classification_survives_scope_health_without_upgrading_proof(
    monkeypatch,
):
    response = SimpleNamespace(
        url=TARGET,
        text="",
        status_code=302,
        headers={"Location": f"https://login.taobao.com/?ticket={SECRET}"},
    )
    session = SimpleNamespace(get=lambda *_a, **_k: response, close=lambda: None)
    monkeypatch.setattr(
        auth_cookie_health, "build_session_from_playwright_cookies", lambda _: session
    )
    monkeypatch.setattr(
        auth_cookie_health, "resolve_cdp_user_agent", lambda _: "test-UA"
    )
    result = auth_cookie_health.probe_cookie_snapshot_health(
        [], [], detail_target_url=TARGET
    )
    assert result["scope_healthy"] is False and result["healthy"] is False
    assert result["sample_results"][0]["redirect_kind"] == "login_required"
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("headers", [None, [], {"Other": SECRET}])
def test_missing_or_non_mapping_headers_remain_compatible(headers):
    response = SimpleNamespace(url=TARGET, text="", status_code=302, headers=headers)
    result = detail.probe_detail_page(
        TARGET, cookies=[], session=SimpleNamespace(get=lambda *_a, **_k: response)
    )
    assert result["redirect_kind"] == "missing_location"
    assert result["healthy"] is False
    assert SECRET not in json.dumps(result)


def test_non_redirect_success_keeps_existing_health_contract():
    response = SimpleNamespace(
        url=TARGET,
        text='<div id="J_StartPrice">100</div>',
        status_code=200,
        headers={"Location": f"https://login.taobao.com/?token={SECRET}"},
    )
    result = detail.probe_detail_page(
        TARGET, cookies=[], session=SimpleNamespace(get=lambda *_a, **_k: response)
    )
    assert result["healthy"] is True
    assert result["status"] == "healthy_detail_payload"
    assert "redirect_kind" not in result and SECRET not in json.dumps(result)
