"""Seed selection must agree with the existing target-bound success contract."""

import pytest

from src.captcha_solver import CaptchaSolver

REQUESTED = (
    "https://sf.taobao.com/list/123.htm"
    "?location_code=110100&page=4&st_param=5&auction_start_seg=-1"
)
SOLVER_TARGET = REQUESTED + "&__captcha_solver_bg=1"
REDIRECTED = REQUESTED.replace(".htm?", ".htm/_____tmd_____/punish?")
FOREIGN = (
    REDIRECTED.replace("110100", "310100"),
    REDIRECTED.replace("page=4", "page=5"),
    REDIRECTED.replace("123.htm", "456.htm"),
    REDIRECTED.replace("st_param=5", "st_param=1"),
    REDIRECTED.replace("auction_start_seg=-1", "auction_start_seg=1"),
    "https://sf.taobao.com/list/123.htm/_____tmd_____/punish?x5step=1",
)


def tab(identity, url, title="CAPTCHA Verification"):
    return {
        "id": identity,
        "type": "page",
        "url": url,
        "title": title,
        "webSocketDebuggerUrl": "ws://fixture/" + identity,
    }


def selection(tabs, *, open_succeeds=True):
    solver = CaptchaSolver(target_url=SOLVER_TARGET)
    actions = {"connected": [], "opened": 0, "closed": []}
    solver._get_json = lambda _endpoint: tabs
    solver._close_cdp_target = lambda key: actions["closed"].append(key) or True
    solver._connect_to_target = lambda endpoint, _title: (
        actions["connected"].append(endpoint) or True
    )

    def open_requested():
        actions["opened"] += 1
        if not open_succeeds:
            return None
        opened = tab("requested", SOLVER_TARGET, "司法拍卖")
        solver._remember_target_tab(opened)
        return opened

    solver._open_target_tab = open_requested
    return solver, actions


@pytest.mark.parametrize("foreign", FOREIGN)
def test_foreign_seed_challenge_is_not_reused_for_another_job(foreign):
    solver, actions = selection([tab("foreign", foreign)])
    assert solver.connect_tab() is True
    assert actions["opened"] == 1
    assert actions["connected"] == ["ws://fixture/requested"]


@pytest.mark.parametrize(
    "foreign",
    (*FOREIGN, REQUESTED.replace("page=4", "page=8") + "&__captcha_worker_master=1"),
)
def test_open_failure_cannot_restore_foreign_seed_via_heuristics(foreign):
    solver, actions = selection([tab("foreign", foreign)], open_succeeds=False)
    assert solver.connect_tab() is False
    assert actions["connected"] == []
    assert actions["opened"] == 1


@pytest.mark.parametrize(
    "url",
    (
        REDIRECTED + "&x5step=1&x5secdata=opaque",
        (
            "https://sf.taobao.com//list/123.htm/_____tmd_____/punish"
            "?auction_start_seg=-1&st_param=5&page=4&location_code=110100"
        ),
        REQUESTED + "&spm=tracking",
    ),
)
def test_same_seed_identity_is_reused_without_opening_another_page(url):
    solver, actions = selection([tab("matching", url)])
    assert solver.connect_tab() is True
    assert actions["opened"] == 0
    assert actions["connected"] == ["ws://fixture/matching"]


@pytest.mark.parametrize("remembered_matches", [False, True])
def test_cached_socket_cannot_override_current_seed_page_identity(remembered_matches):
    foreign = tab("cached", FOREIGN[0])
    solver, actions = selection([foreign])
    solver._remember_target_tab(foreign)
    if remembered_matches:
        solver.current_target_url = REQUESTED
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/requested"]


@pytest.mark.parametrize("cached_url", (None, *FOREIGN))
def test_failed_directory_read_only_reuses_a_bound_cached_seed(cached_url):
    solver, actions = selection(None)
    solver.target_id = "cached"
    solver.target_ws_url = "ws://fixture/cached"
    solver.current_target_url = cached_url
    assert solver.connect_tab() is False
    assert actions["connected"] == [] and actions["opened"] == 0


def test_bound_cached_seed_remains_usable_when_directory_read_fails():
    solver, actions = selection(None)
    solver._remember_target_tab(tab("cached", REDIRECTED))
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/cached"]
    assert actions["opened"] == 0


def test_directory_refresh_updates_the_remembered_seed_identity():
    pages = [tab("cached", REDIRECTED)]
    solver, actions = selection(pages)
    solver._remember_target_tab(tab("cached", FOREIGN[0]))
    assert solver.connect_tab() is True
    assert solver.current_target_url == REDIRECTED
    solver._get_json = lambda _endpoint: None
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/cached"] * 2
    assert actions["opened"] == 0


def test_seed_selection_preserves_other_scope_and_reference_pages():
    pages = [
        tab("foreign", FOREIGN[0]),
        tab(
            "detail", "https://sf-item.taobao.com/sf_item/123.htm/_____tmd_____/punish"
        ),
        tab("reference", "https://www.baidu.com/", "reference"),
    ]
    solver, actions = selection(pages)
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/requested"]
    assert actions["closed"] == []


def test_login_page_still_uses_existing_manual_authentication_path():
    solver, actions = selection(
        [tab("login", "https://login.taobao.com/havanaone/login/login.htm", "登录")]
    )
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/login"]
    assert actions["opened"] == 0


@pytest.mark.parametrize(
    "target",
    (None, "https://sf-item.taobao.com/sf_item/123.htm?__captcha_solver_bg=1"),
)
def test_generic_or_bound_detail_cache_remains_usable(target):
    solver, actions = selection(None)
    solver.target_url = target
    solver.current_target_url = target
    solver.target_ws_url = "ws://fixture/cached"
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/cached"]


def test_unbound_seed_does_not_consume_a_drag_attempt(monkeypatch):
    solver, actions = selection([tab("foreign", FOREIGN[0])], open_succeeds=False)
    monkeypatch.setattr(solver, "_headed_playwright_enabled", lambda: False)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _seconds: None)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: 0)
    monkeypatch.setattr(
        solver, "_page_challenge_summary", lambda: pytest.fail("foreign DOM read")
    )
    monkeypatch.setattr(solver, "_do_drag", lambda *args: pytest.fail("foreign drag"))
    assert solver.solve(max_attempts=1) is False
    assert actions["connected"] == []
