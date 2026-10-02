"""Raw capture must not scan every shared browser tab before claiming work."""

from types import SimpleNamespace

from tools import detail_worker as worker


def test_browser_page_snapshot_is_opt_in(monkeypatch):
    monkeypatch.delenv("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", raising=False)
    monkeypatch.delenv("CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES", raising=False)
    monkeypatch.setattr(worker, "export_cookies", lambda endpoint: ["cookie"])
    monkeypatch.setattr(worker, "build_http", lambda cookies: ("http", cookies))

    def forbidden(endpoint):
        raise AssertionError(
            "Shared browser tabs must not block normal capture startup"
        )

    monkeypatch.setattr(worker, "load_open_browser_pages", forbidden)
    assert worker._build_runtime_context(
        SimpleNamespace(cdp_endpoint="http://cdp")
    ) == (
        ("http", ["cookie"]),
        {},
    )


def test_explicit_browser_page_snapshot_keeps_manual_reuse(monkeypatch):
    monkeypatch.setenv("CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES", "1")
    monkeypatch.delenv("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", raising=False)
    monkeypatch.setattr(worker, "export_cookies", lambda endpoint: [])
    monkeypatch.setattr(worker, "build_http", lambda cookies: "http")
    pages = {"123": ("detail evidence", "https://example/item/123")}
    monkeypatch.setattr(worker, "load_open_browser_pages", lambda endpoint: pages)
    assert worker._build_runtime_context(
        SimpleNamespace(cdp_endpoint="http://cdp")
    ) == (
        "http",
        pages,
    )
