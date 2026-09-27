"""Native transport ownership and failure-path contracts."""

import json
import subprocess
import sys

import pytest

from src import cdp_cookie_transport as transport


def test_native_transport_import_does_not_load_tools_or_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import src.cdp_cookie_transport; "
                "assert not any(n == 'tools' or n.startswith('tools.') for n in sys.modules); "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules; "
                "assert 'playwright.sync_api' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_websocket_is_closed_when_cookie_response_is_malformed(monkeypatch):
    closed = []

    class Socket:
        def send(self, message):
            assert json.loads(message) == {"id": 1, "method": "Storage.getCookies"}

        def recv(self):
            return "not-json"

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        transport,
        "_resolve_cdp_websocket_for_cookie_export",
        lambda _session, _endpoint: "ws://example.invalid/devtools/browser/test",
    )
    monkeypatch.setattr(
        transport.websocket, "create_connection", lambda *_a, **_kw: Socket()
    )
    with pytest.raises(json.JSONDecodeError):
        transport._export_cdp_cookies_via_websocket("http://example.invalid", ())
    assert closed == [True]


@pytest.mark.parametrize("contents", [b"\xff", b"{invalid", b"[]"])
def test_unusable_cache_does_not_supply_a_websocket(tmp_path, monkeypatch, contents):
    cache = tmp_path / "cdp.json"
    cache.write_bytes(contents)
    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(cache))
    assert transport._load_cached_cdp_websocket("http://example.invalid") == ""


def test_saved_tool_export_observes_later_transport_replacement(monkeypatch):
    from tools import browserless_seed_probe

    export = browserless_seed_probe.export_cdp_cookies
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "1")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")

    def unavailable(_endpoint, _origins):
        raise OSError("synthetic websocket failure")

    monkeypatch.setattr(
        browserless_seed_probe, "_export_cdp_cookies_via_websocket", unavailable
    )
    monkeypatch.setattr(
        browserless_seed_probe,
        "_export_cdp_cookies_via_playwright",
        lambda endpoint, origins: [{"endpoint": endpoint, "origins": list(origins)}],
    )
    assert export("http://example.invalid", iter(["https://sf.taobao.com"])) == [
        {"endpoint": "http://example.invalid", "origins": ["https://sf.taobao.com"]}
    ]
