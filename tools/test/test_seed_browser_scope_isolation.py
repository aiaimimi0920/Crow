"""A detail challenge must not be reused as evidence that seed collection is blocked."""

import pytest

from tools import live_batch_smoke, live_smoke_browser, taobao_login_health


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    "detail_url",
    [
        "https://sf-item.taobao.com/sf_item/123.htm/_____tmd_____/punish?x5step=1",
        "https://susong-item.taobao.com/auction/123.htm/_____tmd_____/punish?x5step=1",
    ],
)
def test_seed_navigation_ignores_detail_challenge_without_reading_or_closing_it(
    monkeypatch, module, detail_url
):
    detail = {"id": "detail-challenge", "type": "page", "url": detail_url}
    list_url = "https://sf.taobao.com/list/50025969__2.htm?page=1"
    seed = {
        "id": "seed-page",
        "type": "page",
        "url": list_url,
        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/seed-page",
    }
    actions = []
    monkeypatch.setattr(module, "_reuse_existing_taobao_login_page", lambda _: None)
    monkeypatch.setattr(taobao_login_health, "list_cdp_targets", lambda _: [detail])
    monkeypatch.setattr(
        taobao_login_health, "compact_cdp_pages_if_needed", lambda *a, **k: None
    )

    def open_seed(_endpoint, path, *, method):
        assert method == "PUT" and path.startswith("/json/new?")
        actions.append("open-seed")
        return seed

    def read_seed(_endpoint, target):
        assert target["id"] == "seed-page", "seed must not read another stage's target"
        return '<script id="sf-item-list-data">{"data":[]}</script>', list_url

    monkeypatch.setattr(taobao_login_health, "read_cdp_json", open_seed)
    monkeypatch.setattr(module, "_read_cdp_list_target_html", read_seed)
    monkeypatch.setattr(
        taobao_login_health,
        "close_cdp_target",
        lambda _endpoint, target_id: actions.append("close:" + target_id),
    )

    html, final_url = module.fetch_browser_navigation_list_page(
        "http://127.0.0.1:9224", list_url
    )

    assert "sf-item-list-data" in html
    assert final_url == list_url
    assert actions == ["open-seed", "close:seed-page"]


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    "url",
    [
        "https://sf.taobao.com/list/50025969__2.htm?page=4&x5step=1",
        "https://sec.taobao.com/_____tmd_____/punish?x5step=1",
    ],
)
def test_seed_and_unattributed_challenges_still_preserve_authentication(
    monkeypatch, module, url
):
    target = {"id": "existing-challenge", "type": "page", "url": url}
    page = ("<html>_____tmd_____/punish challenge</html>", url)
    monkeypatch.setattr(taobao_login_health, "list_cdp_targets", lambda _: [target])
    monkeypatch.setattr(module, "_read_cdp_list_target_html", lambda *args: page)

    assert module._reuse_existing_taobao_challenge_page("http://127.0.0.1:9224") == page
