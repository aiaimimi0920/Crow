"""A running caller loop must not permanently disable list browser fallback."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from tools import live_batch_smoke as smoke

TARGET = "https://sf.taobao.com/list/50025969__2.htm?page=1"
HTML = '<script id="sf-item-list-data">{"data":[]}</script>'


def test_running_loop_uses_isolated_capture_not_sync_playwright(monkeypatch):
    isolated = Mock(return_value=(HTML, TARGET))
    monkeypatch.setattr(
        "tools.list_browser_capture.capture_list_with_deadline", isolated
    )
    monkeypatch.setattr(
        smoke,
        "fetch_browser_navigation_list_page",
        lambda *a: pytest.fail("Sync API must not start in a running loop"),
    )

    async def invoke():
        return smoke.fetch_browser_list_page("http://fixture", TARGET)

    assert asyncio.run(invoke()) == (HTML, TARGET)
    isolated.assert_called_once_with(TARGET, cdp_endpoint="http://fixture")


def test_sync_caller_keeps_existing_capture_path(monkeypatch):
    direct = Mock(return_value=(HTML, TARGET))
    monkeypatch.setattr(smoke, "fetch_browser_navigation_list_page", direct)
    assert smoke.fetch_browser_list_page("http://fixture", TARGET) == (HTML, TARGET)
    direct.assert_called_once_with("http://fixture", TARGET)


@pytest.mark.parametrize("body", [HTML, "<html>x5secdata=fixture</html>"])
def test_isolated_capture_preserves_payload_and_positive_challenge(monkeypatch, body):
    from tools import list_browser_capture as boundary

    def run(command, request):
        value = json.loads(request)
        assert command[-1] == "tools.list_browser_capture"
        assert value["seed"] == {"url": TARGET}
        assert value["cdp_endpoint"] == "http://fixture"
        assert value["deadline_monotonic"] > 0
        return json.dumps(
            {"kind": "ok", "result": [body, TARGET, len(body), "browser_navigation"]}
        )

    monkeypatch.setattr(boundary, "run_capture_process", run)
    assert boundary.capture_list_with_deadline(
        TARGET, cdp_endpoint="http://fixture"
    ) == (body, TARGET)


def test_isolated_capture_keeps_capacity_type(monkeypatch):
    from tools import list_browser_capture as boundary
    from tools.cdp_background_page import BackgroundPageCapacityError

    monkeypatch.setattr(
        boundary, "run_capture_process", lambda *a: b'{"kind":"capacity"}'
    )
    with pytest.raises(BackgroundPageCapacityError):
        boundary.capture_list_with_deadline(TARGET, cdp_endpoint="http://fixture")


def test_real_child_starts_playwright_outside_callers_running_loop(monkeypatch):
    import sys

    from tools import list_browser_capture as boundary

    script = """
from tools import list_browser_capture as child
from playwright.sync_api import sync_playwright
def capture(seed, **kwargs):
    with sync_playwright() as driver:
        assert driver.chromium is not None
    return ('中文列表', seed['url'], 12, 'browser_navigation')
child._capture = capture
child.main()
"""
    real_run = boundary.run_capture_process

    def run(command, request):
        return real_run(
            [sys.executable, "-B", "-c", script], request, timeout_seconds=15
        )

    monkeypatch.setattr(boundary, "run_capture_process", run)

    async def invoke():
        return smoke.fetch_browser_list_page("http://fixture", TARGET)

    assert asyncio.run(invoke()) == ("中文列表", TARGET)
