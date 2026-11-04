"""A detail challenge must not be reused as evidence that seed collection is blocked."""

import pytest

from tools import (
    cdp_background_page,
    live_batch_smoke,
    live_smoke_browser,
    taobao_login_health,
)


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    "detail_url",
    [
        "https://sf-item.taobao.com/sf_item/123.htm/_____tmd_____/punish?x5step=1",
        "https://susong-item.taobao.com/auction/123.htm/_____tmd_____/punish?x5step=1",
    ],
)
def test_seed_navigation_ignores_detail_challenge_without_reading_or_closing_it(monkeypatch, module, detail_url):
    from tools.test.test_browser_target_capture import capture_fixture, PAYLOADS
    capture, actions, _ = capture_fixture(monkeypatch, module, 'seed', old_url=detail_url)
    assert capture()[0] == PAYLOADS['seed']
    assert 'old_read' not in actions
    assert actions.count('fresh_request') == actions.count('close_owned') == 1


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


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    "other_url",
    [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=371603&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=445302&page=15",
        "https://sf.taobao.com/list/200782003__2.htm?location_code=445302&page=1",
    ],
)
def test_seed_navigation_does_not_recycle_another_jobs_challenge(monkeypatch, module, other_url):
    from tools.test.test_browser_target_capture import capture_fixture, PAYLOADS
    capture, actions, _ = capture_fixture(monkeypatch, module, 'seed', old_url=other_url)
    assert capture()[0] == PAYLOADS['seed']
    assert 'old_read' not in actions
    assert actions.count('fresh_request') == 1


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
def test_current_job_challenge_is_revalidated_without_touching_borrowed_page(monkeypatch, module):
    from tools.test.test_browser_target_capture import capture_fixture, TARGETS, PAYLOADS
    redirected = TARGETS['seed'].replace('.htm?', '.htm/_____tmd_____/punish?') + '&x5step=1'
    capture, actions, _ = capture_fixture(monkeypatch, module, 'seed', old_url=redirected)
    assert capture()[0] == PAYLOADS['seed']
    assert actions.count('old_read') == actions.count('fresh_request') == 1
