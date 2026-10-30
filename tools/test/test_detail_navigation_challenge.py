"""An interrupted navigation may already have loaded the requested challenge."""

import json

import pytest

from tools import live_batch_smoke as smoke
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply
from tools.test.detail_navigation_challenge_fixtures import navigation_fixture
from tools.test.test_detail_capture_diagnostics import worker_failure
from tools.test.test_detail_http_error_challenge import URL


@pytest.mark.parametrize(
    "code",
    [
        "ERR_TIMED_OUT",
        "ERR_CONNECTION_CLOSED",
        "ERR_CONNECTION_TIMED_OUT",
        "operation_timeout",
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_loaded_challenge_survives_navigation_error_and_private_protocol(
    monkeypatch, code, existing
):
    fixture = navigation_fixture(monkeypatch, code=code, existing=existing)
    reply = capture_reply(
        lambda *_, **__: fixture.capture(),
        {"seed": {}, "cdp_endpoint": "http://fixture"},
    )
    assert reply == {
        "kind": "challenge",
        "operation": "browser detail request",
        "challenge_url": URL,
    }
    with pytest.raises(smoke.DetailChallengeError):
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    assert fixture.events.count("navigate") == fixture.events.count("read_owned") == 1
    assert ("close_owned" in fixture.events) is existing
    assert fixture.events.count("session_detach") == 1
    assert fixture.events[-2:] == ["browser_detach", "driver_stop"]
    assert fixture.timeouts == [2000]


def test_navigation_challenge_reaches_worker_without_spending_item_retry(
    monkeypatch, tmp_path
):
    from src.storage.models import FapaiSeedItem

    fixture = navigation_fixture(monkeypatch)
    reply = capture_reply(
        lambda *_, **__: fixture.capture(),
        {"seed": {}, "cdp_endpoint": "http://fixture"},
    )
    with pytest.raises(smoke.DetailChallengeError) as caught:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary, repository = worker_failure(tmp_path, caught.value)
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row.status == "pending_detail" and row.detail_attempt_count == 0
