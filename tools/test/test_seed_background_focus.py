"""Collector DOM reads must not take the shared browser's input focus."""

import pytest

from tools import live_batch_smoke, live_smoke_cdp, taobao_login_health


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_read_list_html_does_not_activate_target(monkeypatch, module):
    target = {
        "id": "background-seed",
        "url": "https://sf.taobao.com/list/50025969__2.htm",
        "webSocketDebuggerUrl": "ws://fixture/seed",
    }
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda *_: pytest.fail("a collector read stole the solver foreground"),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda *_: {
            "result": {
                "result": {
                    "value": {
                        "html": '<script id="sf-item-list-data">{}</script>',
                        "url": target["url"],
                    }
                }
            }
        },
    )
    html, url = module._read_cdp_list_target_html("http://fixture", target)
    assert "sf-item-list-data" in html
    assert url == target["url"]


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_capacity_stays_retryable_instead_of_cdp_unreachable(monkeypatch, module):
    from tools import cdp_background_page, live_smoke_browser
    from tools.test.test_browser_target_capture import capture_fixture
    browser_module = live_smoke_browser if module is live_smoke_cdp else module
    capture, events, _ = capture_fixture(monkeypatch, browser_module, 'seed')
    def full(*args):
        raise cdp_background_page.BackgroundPageCapacityError('capacity reached')
    monkeypatch.setattr('tools.browser_target_capture.owned_background_page', full)
    with pytest.raises(cdp_background_page.BackgroundPageCapacityError):
        capture()
    assert 'fresh_request' not in events and 'close_owned' not in events
