import pytest

from tools import pc2_reference_browse as browse
from tools import pc2_solver_reference_tabs as tabs
from tools.pc2_reference_navigation import safe_navigation


@pytest.mark.parametrize(
    "url",
    [
        "https://accounts.google.com/",
        "https://www.google.com/url?q=https://external.test",
        "https://www.google.com/search?q=x&adurl=",
        "https://www.google.com/download",
        "https://www.google.com.evil.test/",
        "https://user@www.google.com/",
        "https://www.baidu.com/link?url=x",
        "https://www.baidu.com/passport",
        "http://www.google.com/",
        "javascript:alert(1)",
    ],
)
def test_disallowed_navigation(url):
    assert not safe_navigation(url)


def test_normal_navigation_requires_same_origin():
    assert safe_navigation(
        "https://www.google.com/search?q=test", "https://www.google.com/"
    )
    assert safe_navigation("https://www.baidu.com/s?wd=test", "https://www.baidu.com/")
    assert not safe_navigation(
        "https://www.baidu.com/s?wd=test", "https://www.google.com/"
    )


def test_page_navigation_depth_is_one_and_excludes_login(monkeypatch):
    from tools import pc2_reference_browser as browser

    page = object.__new__(browser.ReferencePage)
    page.origin, page.depth = "https://www.google.com/", 0
    snapshot = {
        "url": page.origin,
        "width": 800,
        "height": 600,
        "links": [
            {"url": "https://accounts.google.com/"},
            {"url": "https://www.google.com/search?q=test"},
        ],
    }
    monkeypatch.setattr(page, "evaluate", lambda _: snapshot)
    calls = []
    monkeypatch.setattr(
        page, "call", lambda method, params: calls.append((method, params))
    )
    monkeypatch.setattr(browser.random, "random", lambda: 0.1)
    page.step()
    page.step()
    navigation = [params for method, params in calls if method == "Page.navigate"]
    assert navigation == [{"url": "https://www.google.com/search?q=test"}]
    calls.clear()
    snapshot["url"] = "https://accounts.google.com/"
    assert page.step() is False
    assert calls == []


def test_two_subsequent_failure_rounds_and_success_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(tabs, "FALLBACK_STATE_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(tabs, "_load_fallback_state", lambda: {"challenge_id": "c"})
    monkeypatch.setattr(
        tabs,
        "list_cdp_targets",
        lambda _: [{"type": "page", "url": u} for _, u in tabs.SITES],
    )
    tabs.record_failed_drags("offline", 3)
    assert tabs.load_reference_state()["post_open_failures"] == 0
    tabs.record_failed_drags("offline", 2)
    assert tabs.load_reference_state()["post_open_failures"] == 1
    tabs.record_failed_drags("offline", 0)
    assert tabs.load_reference_state()["post_open_failures"] == 0
    tabs.record_failed_drags("offline", 1)
    tabs.record_failed_drags("offline", 1)
    assert tabs.load_reference_state()["post_open_failures"] == 2


@pytest.mark.parametrize("abort", [False, True])
def test_bounded_phase_returns_exact_target_and_never_replays(monkeypatch, abort):
    state = {"challenge_id": "c", "tabs_ready": True, "post_open_failures": 2}
    monkeypatch.setattr(browse, "load_reference_state", lambda: dict(state))
    monkeypatch.setattr(
        browse, "save_reference_state", lambda value: state.update(value)
    )
    monkeypatch.setattr(browse, "_load_fallback_state", lambda: {"challenge_id": "c"})
    now = [0.0]
    monkeypatch.setattr(browse.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        browse.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    monkeypatch.setattr(browse.random, "uniform", lambda a, b: a)
    monkeypatch.setattr(browse, "active_manual_window", lambda: None)
    monkeypatch.setattr(browse, "allowed", lambda *args: not abort or now[0] < 4)
    monkeypatch.setattr(browse, "write_solver_heartbeat", lambda _: None)
    monkeypatch.setattr(browse, "log_event", lambda _: None)
    targets = [{"id": "original", "type": "page", "url": "https://sf-item.taobao.com/"}]
    targets += [{"id": host, "type": "page", "url": url} for host, url in tabs.SITES]
    monkeypatch.setattr(browse, "list_cdp_targets", lambda _: targets)
    activated, closed = [], []
    monkeypatch.setattr(
        browse, "activate_cdp_target", lambda endpoint, t: activated.append(t["id"])
    )

    class Page:
        def __init__(self, target):
            self.target = target

        def step(self):
            return True

        def close(self):
            closed.append(self.target["id"])

    monkeypatch.setattr(browse, "ReferencePage", Page)
    browse.maybe_browse_reference_tabs("api", "endpoint", {"_target_id": "original"})
    assert state["browse_finished"]
    assert len(closed) == 2
    assert (activated[-1] == "original") is not abort
    assert now[0] == (4 if abort else 60)
    before = list(activated)
    browse.maybe_browse_reference_tabs("api", "endpoint", {"_target_id": "original"})
    assert activated == before
