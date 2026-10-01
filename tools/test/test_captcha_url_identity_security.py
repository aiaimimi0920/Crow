"""Host-specific CAPTCHA hints must not disable generic/local solver targets."""

import json
from types import SimpleNamespace

import pytest
import websocket

from src.captcha_cdp import _has_solver_url_flag
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_cdp as cdp
from tools.test.test_captcha_dom_evaluation import DocumentSolver

pytestmark = [pytest.mark.security, pytest.mark.unit]

LOGIN_DECOYS = [
    "https://login.taobao.com.attacker.test/",
    "https://evil-login.taobao.com/",
    "https://login.taobao.com@attacker.test/",
    "https://attacker.test/login.taobao.com/",
    "https://attacker.test/?next=https://login.taobao.com/",
    "https://attacker.test/#https://login.taobao.com/",
    "https://login.taobao.com:bad/",
    "https://login.taobao.com:65536/",
    "https://user:password@login.taobao.com/",
    "https://login.\ntaobao.com/",
    "https://attacker.test\\@login.taobao.com/",
    "//login.taobao.com/",
    "javascript://login.taobao.com/",
    "https://[bad",
]


@pytest.mark.parametrize("flag", ["__captcha_solver_bg", "__captcha_worker_master"])
@pytest.mark.parametrize(
    "query,expected",
    [
        ("?{flag}=1", True),
        ("?{flag}=1&{flag}=0", False),
        ("?{flag}=1&{flag}=1", False),
        ("?{flag}=10", False),
        ("?other={flag}=1", False),
        ("#{flag}=1", False),
    ],
)
def test_solver_flags_require_one_exact_top_level_value(flag, query, expected):
    assert (
        _has_solver_url_flag(
            "file:///tmp/mock_slider.html" + query.format(flag=flag), flag
        )
        is expected
    )


@pytest.mark.parametrize("url", LOGIN_DECOYS)
def test_login_classifiers_reject_unrelated_authority_text(url):
    solver = CaptchaSolver()
    assert solver._is_login_url(url) is False
    assert solver._looks_like_login_ui({"href": url}) is False


@pytest.mark.parametrize(
    "url",
    [
        "HTTP://LOGIN.TAOBAO.COM/member/login.jhtml",
        "https://example.test/passport/fixture",
        "http://127.0.0.1:9000/passport/fixture",
        "file:///tmp/passport/fixture.html",
        "https://example.test/_____tmd_____/page/login_jump",
    ],
)
def test_login_classifiers_keep_real_hosts_and_generic_local_paths(url):
    solver = CaptchaSolver()
    assert solver._is_login_url(url) is True
    assert solver._looks_like_login_ui({"href": url}) is True


def test_login_classifiers_preserve_independent_dom_and_title_evidence():
    solver = CaptchaSolver()
    assert solver._is_login_url("https://login.tmall.com/") is True
    assert solver._looks_like_login_ui({"href": LOGIN_DECOYS[0], "loginRequired": True})
    assert solver._looks_like_login_ui(
        {"href": "file:///tmp/mock.html", "title": "登录"}
    )


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.test/_____tmd_____/punish", True),
        ("file:///tmp/_____tmd_____/punish", True),
        ("http://localhost:9000/mock?x5secdata=", True),
        ("https://example.test/mock?x5step=1", True),
        ("https://example.test/?next=/_____tmd_____/punish", False),
        ("https://example.test/?next=x5step=1", False),
        ("https://example.test/#x5secdata=fixture", False),
        ("https://example.test/?next=https://login.taobao.com/passport/mock", False),
    ],
)
def test_manual_challenge_markers_use_components_without_site_allowlist(url, expected):
    assert CaptchaSolver._is_manual_challenge_url(url) is expected


def tab(name, url, title=""):
    return {
        "id": name,
        "type": "page",
        "url": url,
        "title": title,
        "webSocketDebuggerUrl": "ws://fixture/" + name,
    }


def connect_solver(tabs, target_url=None):
    solver = CaptchaSolver(target_url=target_url)
    connected = []
    solver._get_json = lambda _endpoint: tabs
    solver._compact_cdp_pages_if_needed = lambda *_args, **_kwargs: {}
    solver._prune_duplicate_challenge_tabs = lambda _tabs: {}
    solver._connect_to_target = lambda ws, _title: connected.append(ws) or True
    return solver, connected


@pytest.mark.parametrize(
    "url",
    [
        "https://sec.taobao.com.attacker.test/",
        "https://attacker.test/?next=https://login.taobao.com/",
        "https://attacker.test/taobao.com/",
        "https://attacker.test/#tmall.com",
        "https://attacker.test/?next=https://taobao.com/?__captcha_solver_bg=1",
        "https://attacker.test/#__captcha_worker_master=1",
    ],
)
def test_cdp_discovery_does_not_restore_spoofed_host_via_brand_fallback(url):
    solver, connected = connect_solver([tab("decoy", url)])
    assert solver.connect_tab() is False
    assert connected == []


@pytest.mark.parametrize(
    "url",
    [
        "HTTP://SEC.TAOBAO.COM/",
        "https://login.taobao.com/",
        "https://sf.taobao.com/",
        "https://paimai.tmall.com/",
    ],
)
def test_cdp_discovery_recognizes_real_site_identity(url):
    solver, connected = connect_solver(
        [
            tab("decoy", "https://sec.taobao.com.attacker.test/"),
            tab("real", url),
        ]
    )
    assert solver.connect_tab() is True
    assert connected == ["ws://fixture/real"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/mock",
        "http://127.0.0.1:9000/mock",
        "file:///tmp/mock_slider.html",
    ],
)
def test_exact_generic_and_local_targets_keep_priority(url):
    solver, connected = connect_solver([tab("exact", url)], target_url=url)
    assert solver.connect_tab() is True
    assert connected == ["ws://fixture/exact"]


@pytest.mark.parametrize(
    "url",
    [
        "https://sec.taobao.com.attacker.test/punish",
        "https://attacker.test/?next=https://sec.taobao.com/punish",
        "https://example.test/?next=/_____tmd_____/punish",
        "https://example.test/#x5secdata=fixture",
    ],
)
def test_pc2_metadata_does_not_substitute_spoofed_url_for_dom_evidence(
    monkeypatch, url
):
    monkeypatch.setattr(
        cdp, "fetch_json", lambda *_args, **_kwargs: [tab("decoy", url)]
    )
    probe = SimpleNamespace(
        _remember_target_tab=lambda _tab: None,
        _connect_to_target=lambda *_args: True,
        _page_challenge_summary=lambda: {},
        _close_solver_ws=lambda: None,
    )
    monkeypatch.setattr(cdp, "_create_probe_solver", lambda **_kwargs: probe)
    assert cdp.check_cdp_browser_for_challenge_page("http://fixture") is None


@pytest.mark.parametrize(
    "url",
    [
        "HTTP://SEC.TAOBAO.COM/punish",
        "https://example.test/_____tmd_____/punish",
        "file:///tmp/_____tmd_____/punish",
        "http://localhost/mock?x5secdata=",
    ],
)
def test_pc2_metadata_preserves_real_and_generic_challenge_routes(monkeypatch, url):
    monkeypatch.setattr(cdp, "fetch_json", lambda *_args, **_kwargs: [tab("real", url)])
    assert (
        cdp.check_cdp_browser_for_challenge_page("http://fixture")["_target_id"]
        == "real"
    )


@pytest.mark.parametrize(
    "real_url",
    [
        "https://sec.taobao.com/",
        "HTTP://LOGIN.TAOBAO.COM/",
        "file:///tmp/_____tmd_____/punish",
    ],
)
def test_pc2_slider_priority_uses_authority_while_retaining_dom_probe(
    monkeypatch, real_url
):
    class Socket:
        def settimeout(self, _timeout):
            pass

        def send(self, payload):
            self.message = json.loads(payload)

        def recv(self):
            return json.dumps(
                {
                    "id": self.message["id"],
                    "result": {"result": {"value": {"found": True}}},
                }
            )

        def close(self):
            pass

    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: Socket()
    )
    monkeypatch.setattr(
        cdp,
        "fetch_json",
        lambda *_args, **_kwargs: [
            tab("decoy", "https://sec.taobao.com.attacker.test/"),
            tab("real", real_url),
        ],
    )
    assert cdp.check_cdp_browser_for_slider("http://fixture")["_target_id"] == "real"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://login.taobao.com/", True),
        ("HTTP://LOGIN.TMALL.COM/", True),
        ("https://login.taobao.com.attacker.test/", False),
        ("https://attacker.test/?next=https://login.taobao.com/", False),
        ("https://attacker.test/#https://login.tmall.com/", False),
        ("https://example.test/passport/fixture", True),
        ("http://localhost:9000/login", True),
        ("file:///tmp/passport/fixture.html", True),
    ],
)
def test_actual_preflight_javascript_uses_login_authority_and_generic_paths(
    url, expected
):
    summary = DocumentSolver({"url": url})._page_challenge_summary()
    assert summary["loginRequired"] is expected


def test_actual_preflight_javascript_preserves_independent_login_evidence():
    summary = DocumentSolver(
        {"url": "https://example.test/", "title": "登录"}
    )._page_challenge_summary()
    assert summary["loginRequired"] is True
