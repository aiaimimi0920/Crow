"""URL identity classification must not trust another URL component."""

import pytest

from src.collection.adapters.taobao_list_probe import (
    _looks_like_login_page,
    summarize_list_page,
)
from src.collection.adapters.taobao_solver_target import (
    _normalize_solver_target_url,
    _solver_request_scope_from_target_url,
)

pytestmark = [pytest.mark.security, pytest.mark.unit]


@pytest.mark.parametrize(
    ("url", "scope"),
    [
        ("https://sf-item.taobao.com/sf_item/123.htm", "detail"),
        ("HTTP://SF-ITEM.TAOBAO.COM/sf_item/123.htm?other=1", "detail"),
        ("https://sf.taobao.com/list/123.htm", "seed"),
        ("https://sf.taobao.com//list/123.htm/_____tmd_____/punish", "seed"),
        ("https://sf.taobao.com///list/123.htm?x5secdata=fixture", "seed"),
        ("https://paimai.tmall.com/sf_item/123.htm", "detail"),
        ("https://paimai.tmall.com/list/123.htm/_____tmd_____/punish", "seed"),
        ("https://taobao.com/sf_item/123.htm", "detail"),
    ],
)
def test_solver_scope_accepts_verified_hosts_and_paths(url, scope):
    assert _solver_request_scope_from_target_url(url) == scope


@pytest.mark.parametrize(
    "url",
    [
        "https://sf-item.taobao.com.attacker.test/sf_item/123.htm",
        "https://evil-sf-item.taobao.com.attacker.test/sf_item/123.htm",
        "https://evil-sf.taobao.com/list/123.htm",
        "https://sf.taobao.com.attacker.test/list/123.htm/_____tmd_____/punish",
        "https://sf-item.taobao.com@attacker.test/sf_item/123.htm",
        "https://attacker.test/sf_item/123.htm",
        "https://attacker.test/list/123.htm/_____tmd_____/punish",
        "https://attacker.test/?next=https://sf-item.taobao.com/sf_item/123.htm",
        "https://attacker.test/#https://sf.taobao.com/list/123.htm",
        "https://sf.taobao.com/?next=/sf_item/123.htm",
        "https://sf.taobao.com/?next=/list/123.htm&x5secdata=fixture",
        "https://sf.taobao.com/#/list/123.htm/_____tmd_____/punish",
        "https://taobao.com.attacker.test/sf_item/123.htm",
        "https://tmall.com.attacker.test/sf_item/123.htm",
        "https://evil-taobao.com/sf_item/123.htm",
        "https://evil-tmall.com/sf_item/123.htm",
        "https://.taobao.com/sf_item/123.htm",
        "https://bad..taobao.com/sf_item/123.htm",
    ],
)
def test_solver_scope_rejects_untrusted_hosts_and_embedded_routes(url):
    assert _solver_request_scope_from_target_url(url) == "unknown"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://[bad",
        "https://sf.taobao.com:bad/list/123.htm",
        "https://sf.taobao.com:65536/list/123.htm",
        "https:///sf.taobao.com/list/123.htm",
        "//sf.taobao.com/list/123.htm",
        "sf.taobao.com/list/123.htm",
        "ftp://sf.taobao.com/list/123.htm",
        "javascript://sf.taobao.com/list/123.htm",
        "https://attacker.test\\@sf.taobao.com/list/123.htm",
        "https://sf.taobao.com\\.attacker.test/list/123.htm",
        "https://sf.taobao.com\n.attacker.test/list/123.htm",
        "https://sf.\ttaobao.com/list/123.htm",
        "https://user:password@sf.taobao.com/list/123.htm",
        "https://sf%2etaobao.com/list/123.htm",
    ],
)
def test_malformed_targets_fail_closed_and_are_not_rewritten(url):
    assert _solver_request_scope_from_target_url(url) == "unknown"
    assert _normalize_solver_target_url(url) == url
    assert _looks_like_login_page("", url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://login.taobao.com/member/login.jhtml",
        "HTTP://LOGIN.TAOBAO.COM/havanaone/login/login.htm",
        "https://login.m.taobao.com/login.htm",
        "https://login.tmall.com/login.htm",
        "https://sf.taobao.com/havanaone/login/login.htm",
        "https://tmall.com/havanaone/login",
        "https://login.taobao.com/member/login.jhtml?redirectURL="
        "https%3A%2F%2Fsf.taobao.com%2Flist%2F123.htm",
    ],
)
def test_login_summary_recognizes_supported_login_redirects(url):
    assert _looks_like_login_page("", url) is True
    assert summarize_list_page("<html></html>", final_url=url)["body_has_login"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://login.taobao.com.attacker.test/login",
        "https://evil-login.taobao.com/login",
        "https://login.m.taobao.com.attacker.test/login",
        "https://login.tmall.com.attacker.test/login",
        "https://login.taobao.com@attacker.test/login",
        "https://attacker.test/login.taobao.com/",
        "https://attacker.test/?next=https://login.taobao.com/",
        "https://attacker.test/#https://login.taobao.com/",
        "https://sf.taobao.com/?next=https://login.taobao.com/",
        "https://attacker.test/havanaone/login/login.htm",
        "https://sf.taobao.com/?next=/havanaone/login/login.htm",
        "https://sf.taobao.com/#/havanaone/login/login.htm",
        "https://sf.taobao.com/havanaone/login-malicious",
    ],
)
def test_login_summary_does_not_trust_domain_text_in_other_components(url):
    assert _looks_like_login_page("", url) is False
    assert (
        summarize_list_page("<html></html>", final_url=url)["body_has_login"] is False
    )


def test_login_summary_preserves_strong_body_marker_detection():
    assert _looks_like_login_page("扫码登录", "https://sf.taobao.com/") is True


def test_normalization_preserves_identity_and_drops_stale_challenge_data():
    assert _normalize_solver_target_url(
        "https://sf.taobao.com//list/123.htm/_____tmd_____/punish"
        "?page=4&x5secdata=fixture&location_code=310120#challenge"
    ) == (
        "https://sf.taobao.com/list/123.htm?location_code=310120"
        "&page=4&__captcha_solver_bg=1"
    )
    assert (
        _normalize_solver_target_url(
            "https://sf-item.taobao.com//sf_item/456.htm/_____tmd_____/punish"
            "?x5secdata=fixture#challenge"
        )
        == "https://sf-item.taobao.com/sf_item/456.htm"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://tmall.com//list/123.htm/_____tmd_____/punish"
        "?page=4&x5secdata=fixture&__captcha_solver_bg=1#challenge",
        "https://paimai.tmall.com//sf_item/456.htm/_____tmd_____/punish"
        "?x5secdata=fixture&keep=visible#challenge",
        "https://login.tmall.com/havanaone/login/login.htm"
        "?redirectURL=https%3A%2F%2Fsf.taobao.com%2Flist%2F123.htm#login",
    ],
)
def test_normalization_leaves_tmall_urls_unchanged(url):
    assert _normalize_solver_target_url(url) == url
