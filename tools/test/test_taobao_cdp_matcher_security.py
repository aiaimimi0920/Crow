"""Synthetic CDP page matching: preserve reuse without selecting unrelated tabs."""

from urllib.parse import quote

import pytest

from tools import taobao_health_cdp_transport, taobao_login_health

pytestmark = [pytest.mark.security, pytest.mark.unit]
SEED_URL = "https://sf.taobao.com/list/123.htm?__captcha_solver_bg=1"
DETAIL_URL = "https://sf-item.taobao.com/sf_item/456.htm?__captcha_solver_bg=1"
WORKER_URL = "https://sf.taobao.com/?__captcha_worker_master=1"
LOGIN_URL = "https://login.taobao.com/member/login.jhtml"


@pytest.fixture(params=[taobao_health_cdp_transport, taobao_login_health])
def matcher_factory(request):
    return request.param.build_cdp_verification_page_matcher


@pytest.mark.parametrize("requested", [SEED_URL, DETAIL_URL, WORKER_URL, LOGIN_URL])
@pytest.mark.parametrize(
    "candidate",
    [
        "https://login.taobao.com.attacker.test/havanaone/login/login.htm",
        "https://login.m.taobao.com.attacker.test/login.htm",
        "https://login.tmall.com.attacker.test/login.htm",
        "https://login.taobao.com@attacker.test/havanaone/login/login.htm",
        "https://attacker.test/?redirect=https://login.taobao.com/",
        "https://attacker.test/#login.taobao.com",
        "https://sf.taobao.com/?redirect=https%3A%2F%2Flogin.taobao.com%2F",
        "https://sf.taobao.com/#https://login.taobao.com/",
        "https://attacker.test/havanaone/login/login.htm",
        "https://sf.taobao.com.attacker.test/list/123.htm?__captcha_solver_bg=1",
        "https://sf.taobao.com.attacker.test/?__captcha_worker_master=1",
        "https://attacker.test/sf_item/123.htm?__captcha_manual_popup=1",
        "https://attacker.test/list/123.htm/_____tmd_____/punish?x5step=1",
        "javascript://login.taobao.com/havanaone/login/login.htm",
        "https://user:password@login.taobao.com/member/login.jhtml",
        "https://attacker.test\\@login.taobao.com/member/login.jhtml",
        "https://login.taobao.com:bad/member/login.jhtml",
        "https://login.taobao.com:65536/member/login.jhtml",
        "https://login.\ntaobao.com/member/login.jhtml",
        "https://[bad",
        "//login.taobao.com/member/login.jhtml",
        "about:blank#login.taobao.com",
    ],
)
def test_cdp_matcher_never_reuses_deceptive_or_malformed_tabs(
    matcher_factory, requested, candidate
):
    assert matcher_factory(requested)(candidate) is False


@pytest.mark.parametrize("requested", [SEED_URL, DETAIL_URL, LOGIN_URL])
@pytest.mark.parametrize(
    "candidate",
    [
        "https://login.taobao.com/havanaone/login/login.htm",
        "https://login.m.taobao.com/login.htm",
        "https://login.tmall.com/login.htm",
        "https://sf.taobao.com/havanaone/login/login.htm",
        "https://tmall.com/havanaone/login/login.htm",
        "HTTP://LOGIN.TAOBAO.COM/member/login.jhtml",
    ],
)
def test_cdp_matcher_preserves_shared_taobao_tmall_login_redirects(
    matcher_factory, requested, candidate
):
    redirect = "?redirectURL=" + quote(requested, safe="")
    assert matcher_factory(requested)(candidate + redirect) is True


@pytest.mark.parametrize(
    ("requested", "candidate", "expected"),
    [
        (SEED_URL, "https://sf.taobao.com/list/789.htm?__captcha_solver_bg=1", True),
        (SEED_URL, "https://sf.taobao.com/list/789.htm?__captcha_manual_popup=1", True),
        (SEED_URL, "https://sf.taobao.com//list/789.htm/_____tmd_____/punish", True),
        (SEED_URL, "https://sf.taobao.com/list/789.htm?x5step=1", True),
        (SEED_URL, "https://sf.taobao.com/list/789.htm?x5secdata=fixture", True),
        (SEED_URL, DETAIL_URL, False),
        (DETAIL_URL, SEED_URL, False),
        (
            DETAIL_URL,
            "https://sf-item.taobao.com/sf_item/789.htm?__captcha_solver_bg=1",
            True,
        ),
        (
            DETAIL_URL,
            "https://sf-item.taobao.com/sf_item/789.htm/_____tmd_____/punish",
            True,
        ),
        (WORKER_URL, "https://sf.taobao.com/?other=1&__captcha_worker_master=1", True),
        (
            WORKER_URL,
            "https://sf.taobao.com/list/123.htm?__captcha_worker_master=1",
            False,
        ),
        (WORKER_URL, "https://sf-item.taobao.com/?__captcha_worker_master=1", False),
        (WORKER_URL, "http://sf.taobao.com/?__captcha_worker_master=1", False),
        (WORKER_URL, LOGIN_URL, False),
        (LOGIN_URL, SEED_URL, False),
        (LOGIN_URL, "https://sf.taobao.com/list/123.htm/_____tmd_____/punish", False),
    ],
)
def test_cdp_matcher_keeps_worker_login_and_solver_scopes_separate(
    matcher_factory, requested, candidate, expected
):
    assert matcher_factory(requested)(candidate) is expected


@pytest.mark.parametrize("flag", ["__captcha_solver_bg", "__captcha_manual_popup"])
@pytest.mark.parametrize(
    "query",
    [
        "?{flag}=10",
        "?{flag}=0",
        "?{flag}=1&{flag}=0",
        "?other={flag}=1",
        "?redirectURL=https%3A%2F%2Fsf.taobao.com%2F%3F{flag}%3D1",
        "#{flag}=1",
        "/{flag}=1",
    ],
)
def test_cdp_solver_markers_must_be_exact_top_level_query_parameters(
    matcher_factory, flag, query
):
    candidate = "https://sf.taobao.com/list/123.htm" + query.format(flag=flag)
    assert matcher_factory(SEED_URL)(candidate) is False


@pytest.mark.parametrize(
    "candidate",
    [
        "https://sf.taobao.com/?__captcha_worker_master=10",
        "https://sf.taobao.com/?other=__captcha_worker_master=1",
        "https://sf.taobao.com/#__captcha_worker_master=1",
        "https://sf.taobao.com/?__captcha_worker_master=1&__captcha_worker_master=0",
        "https://sf.taobao.com/list/123.htm?next=/_____tmd_____/punish",
        "https://sf.taobao.com/list/123.htm#x5secdata=fixture",
        "https://sf.taobao.com/list/123.htm?next=x5step=1",
        "https://sf.taobao.com/list/123.htm/unchallenged",
    ],
)
def test_cdp_matcher_does_not_confuse_values_fragments_or_partial_markers(
    matcher_factory, candidate
):
    assert matcher_factory(WORKER_URL)(candidate) is False
    assert matcher_factory(SEED_URL)(candidate) is False


@pytest.mark.parametrize(
    "requested",
    ["https://[bad", "javascript://sf.taobao.com/", "//sf.taobao.com/"],
)
def test_invalid_requests_do_not_reuse_any_tab(matcher_factory, requested):
    matcher = matcher_factory(requested)
    assert matcher(SEED_URL) is False
    assert matcher(WORKER_URL) is False
    assert matcher(LOGIN_URL) is False


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "https://contest.local"])
def test_explicit_local_targets_reuse_only_their_own_route(matcher_factory, origin):
    matcher = matcher_factory(origin + "/auth?__captcha_solver_bg=1")
    assert matcher(origin + "/auth?other=1&__captcha_solver_bg=1") is True
    assert matcher(origin + "/auth/_____tmd_____/punish?x5step=1") is True
    assert matcher(origin + "/other?__captcha_solver_bg=1") is False
    assert matcher("https://attacker.test/auth?__captcha_solver_bg=1") is False
    assert matcher(LOGIN_URL) is False
    assert matcher(SEED_URL) is False


def test_default_matcher_restricts_login_and_challenge_tabs_to_supported_hosts(
    matcher_factory,
):
    matcher = matcher_factory("https://sf.taobao.com/list/123.htm")
    assert matcher(LOGIN_URL) is True
    assert matcher("https://login.tmall.com/login.htm") is True
    assert matcher(SEED_URL) is True
    assert matcher("https://sf.taobao.com/challenge") is True
    assert matcher("https://attacker.test/challenge") is False
    assert matcher("https://attacker.test/?__captcha_solver_bg=1") is False
    assert matcher("https://sf.taobao.com/?next=/challenge") is False


def test_target_lookup_skips_deceptive_tab_before_reusing_real_login(monkeypatch):
    impostor = {"id": "fake", "url": "https://login.taobao.com.attacker.test/"}
    expected = {"id": "login", "url": LOGIN_URL}
    monkeypatch.setattr(
        taobao_login_health, "list_cdp_targets", lambda _endpoint: [impostor, expected]
    )
    assert (
        taobao_login_health.find_cdp_target("http://127.0.0.1:9223", SEED_URL)
        == expected
    )
