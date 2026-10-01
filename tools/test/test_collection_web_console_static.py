from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest


@pytest.fixture(params=["native", "facade"])
def console(request, monkeypatch, tmp_path):
    dist = tmp_path / "collector-desktop" / "dist"
    if request.param == "facade":
        from src import server

        monkeypatch.setattr(server, "COLLECTOR_DESKTOP_DIST", dist)
        return server
    from src import collection_console_assets as assets

    return SimpleNamespace(
        _collection_observer_page_html=partial(assets.page_html, dist=dist),
        _collection_observer_static_asset=partial(assets.static_asset, dist=dist),
        _safe_collection_static_path=partial(assets.safe_static_path, dist=dist),
    )


def test_collection_page_serves_built_desktop_console_when_dist_exists(
    console, tmp_path
) -> None:
    server = console

    dist = tmp_path / "collector-desktop" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<div id="app">built console</div>', encoding="utf-8"
    )
    (assets / "index-test.js").write_text(
        'console.log("built console")', encoding="utf-8"
    )

    assert (
        server._collection_observer_page_html() == '<div id="app">built console</div>'
    )
    asset = server._collection_observer_static_asset("/collection/assets/index-test.js")
    assert asset is not None
    assert asset[0] == b'console.log("built console")'
    assert asset[1] == "application/javascript"
    root_asset = server._collection_observer_static_asset("/assets/index-test.js")
    assert root_asset is not None
    assert root_asset[0] == b'console.log("built console")'
    assert root_asset[1] == "application/javascript"


def test_collection_page_falls_back_to_inline_console_when_dist_missing(
    console,
) -> None:
    server = console

    html = server._collection_observer_page_html()

    assert "Crow 采集观察台" in html
    assert "/api/collection/overview" in html


@pytest.mark.parametrize(
    "request_path",
    [
        "/collection/../outside.txt",
        "/collection/%2e%2e/outside.txt",
        "/assets/../../outside.txt",
        "/collection/missing.js",
        "/collection/assets",
        "/outside.txt",
    ],
)
def test_static_asset_rejects_escape_missing_and_directory(
    console, tmp_path, request_path
):
    dist = tmp_path / "collector-desktop" / "dist"
    (dist / "assets").mkdir(parents=True)
    evidence = dist.parent / "outside.txt"
    evidence.write_bytes(b"private evidence")

    assert console._safe_collection_static_path(request_path) is None
    assert console._collection_observer_static_asset(request_path) is None
    assert evidence.read_bytes() == b"private evidence"


@pytest.mark.parametrize(
    "name, content_type",
    [
        ("index.html", "text/html; charset=utf-8"),
        ("style.css", "text/css"),
        ("opaque.crowunknown", "application/octet-stream"),
    ],
)
def test_static_asset_preserves_bytes_and_content_type(
    console, tmp_path, name, content_type
):
    dist = tmp_path / "collector-desktop" / "dist"
    dist.mkdir(parents=True)
    payload = bytes([0, 128, 255])
    (dist / name).write_bytes(payload)
    assert console._collection_observer_static_asset("/collection/" + name) == (
        payload,
        content_type,
    )


def test_facade_delegates_to_native_asset_reader(monkeypatch, tmp_path):
    from src import collection_console_assets, server

    calls = []

    def read_asset(path, *, dist):
        calls.append((path, dist))
        return b"native", "text/plain"

    monkeypatch.setattr(server, "COLLECTOR_DESKTOP_DIST", tmp_path)
    monkeypatch.setattr(collection_console_assets, "static_asset", read_asset)
    assert server._collection_observer_static_asset("/assets/native.txt") == (
        b"native",
        "text/plain",
    )
    assert calls == [("/assets/native.txt", tmp_path)]
