"""Detail discovery must obey the same item identity as success verification."""

import pytest

from src.captcha_solver import CaptchaSolver

REQUESTED = "https://sf-item.taobao.com/sf_item/123.htm"
SOLVER_TARGET = REQUESTED + "?__captcha_solver_bg=1"
CHALLENGE = REQUESTED + "/_____tmd_____/punish?x5secdata=fixture"
FOREIGN = (
    CHALLENGE.replace("123.htm", "456.htm"),
    "https://sf-item.taobao.com/sf_item/456.htm?__captcha_solver_bg=1",
    "https://sf-item.taobao.com/sf_item/456.htm?__captcha_worker_master=1",
    "https://example.test/sf_item/123.htm/_____tmd_____/punish",
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
        opened = tab("requested", solver.target_url, "detail fixture")
        solver._remember_target_tab(opened)
        return opened

    solver._open_target_tab = open_requested
    return solver, actions


@pytest.mark.parametrize("foreign", FOREIGN)
def test_other_detail_item_is_not_reused_for_this_request(foreign):
    solver, actions = selection([tab("foreign", foreign)])
    assert solver.connect_tab() is True
    assert actions["opened"] == 1
    assert actions["connected"] == ["ws://fixture/requested"]
    assert actions["closed"] == []


@pytest.mark.parametrize("foreign", FOREIGN)
def test_failed_open_does_not_restore_foreign_detail_by_heuristic(foreign):
    solver, actions = selection([tab("foreign", foreign)], open_succeeds=False)
    assert solver.connect_tab() is False
    assert actions == {"connected": [], "opened": 1, "closed": []}


@pytest.mark.parametrize(
    "url",
    (
        CHALLENGE,
        REQUESTED + "?spm=fixture&tracking=fixture",
        "https://sf-item.taobao.com//sf_item/123.htm/_____tmd_____/punish?x5step=1",
        "https://susong-item.taobao.com/auction/123.htm/_____tmd_____/punish",
    ),
)
def test_same_canonical_detail_identity_reuses_existing_page(url):
    solver, actions = selection([tab("matching", url)])
    assert solver.connect_tab() is True
    assert actions == {
        "connected": ["ws://fixture/matching"],
        "opened": 0,
        "closed": [],
    }


@pytest.mark.parametrize("remembered_matches", [False, True])
def test_detail_cache_cannot_override_current_directory_identity(remembered_matches):
    foreign = tab("cached", FOREIGN[0])
    solver, actions = selection([foreign])
    solver._remember_target_tab(foreign)
    if remembered_matches:
        solver.current_target_url = REQUESTED
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/requested"]
    assert actions["closed"] == []


@pytest.mark.parametrize("cached_url", (None, *FOREIGN))
def test_missing_directory_only_reuses_a_bound_detail_cache(cached_url):
    solver, actions = selection(None)
    solver.target_id = "cached"
    solver.target_ws_url = "ws://fixture/cached"
    solver.current_target_url = cached_url
    assert solver.connect_tab() is False
    assert actions == {"connected": [], "opened": 0, "closed": []}


def test_matching_detail_cache_remains_usable_without_directory():
    solver, actions = selection(None)
    solver._remember_target_tab(tab("cached", CHALLENGE))
    assert solver.connect_tab() is True
    assert actions == {"connected": ["ws://fixture/cached"], "opened": 0, "closed": []}


def test_detail_deduplication_preserves_other_item_challenges():
    solver, actions = selection(
        [
            tab("other-one", FOREIGN[0]),
            tab("other-two", FOREIGN[0].replace("456.htm", "789.htm")),
            tab("matching", CHALLENGE),
            tab("same-item-duplicate", CHALLENGE + "&x5step=1"),
            tab("seed", "https://sf.taobao.com/list/123.htm/_____tmd_____/punish"),
            tab("reference", "https://example.test/reference", "reference"),
        ]
    )
    assert solver.connect_tab() is True
    assert actions["connected"] == ["ws://fixture/matching"]
    assert actions["closed"] == ["same-item-duplicate"]
    assert actions["opened"] == 0


def test_detail_login_handoff_stays_on_the_manual_authentication_path():
    solver, actions = selection(
        [tab("login", "https://login.taobao.com/havanaone/login/login.htm")]
    )
    assert solver.connect_tab() is True
    assert actions == {"connected": ["ws://fixture/login"], "opened": 0, "closed": []}


def test_unbound_detail_never_reads_foreign_dom_or_drags(monkeypatch):
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


def test_compaction_refresh_cannot_reintroduce_foreign_detail_fallback():
    solver, actions = selection([tab("foreign", FOREIGN[1])], open_succeeds=False)
    calls = []

    def compact(*_args, **_kwargs):
        calls.append(True)
        return {"triggered": len(calls) == 2}

    solver._compact_cdp_pages_if_needed = compact
    assert solver.connect_tab() is False
    assert actions == {"connected": [], "opened": 1, "closed": []}


@pytest.mark.parametrize("scope", ["detail", "seed"])
@pytest.mark.parametrize("refresh", ["same", "foreign", "missing"])
@pytest.mark.parametrize("open_succeeds", [False, True])
def test_cached_identity_is_rechecked_after_pruning_refresh(
    scope, refresh, open_succeeds
):
    solver, actions = selection(None, open_succeeds=open_succeeds)
    target = (
        REQUESTED if scope == "detail" else "https://sf.taobao.com/list/123.htm?page=2"
    )
    solver.target_url = target
    cached = tab("cached", target)
    solver._remember_target_tab(cached)
    changed = target.replace("123.htm", "456.htm")
    refreshed = (
        [cached]
        if refresh == "same"
        else [tab("cached", changed)]
        if refresh == "foreign"
        else []
    )
    calls = []

    def directory(_endpoint):
        calls.append(True)
        return [cached, tab("duplicate", target)] if len(calls) == 1 else refreshed

    solver._get_json = directory
    expected = refresh == "same" or open_succeeds
    assert solver.connect_tab() is expected
    assert actions["closed"] == ["duplicate"]
    if refresh == "same":
        assert actions["connected"] == ["ws://fixture/cached"]
        assert actions["opened"] == 0
        assert len(calls) == 2
    else:
        assert actions["connected"] == (
            ["ws://fixture/requested"] if open_succeeds else []
        )
        assert actions["opened"] == 1
