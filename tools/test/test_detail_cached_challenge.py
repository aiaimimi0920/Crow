from types import SimpleNamespace

import pytest

from tools import live_batch_smoke as smoke

URL = "https://sf-item.taobao.com/sf_item/610925725633.htm"
CHALLENGE = "<html>x5secdata=old-challenge</html>"
HEALTHY = '<html><input id="J_StartPrice" value="123"></html>'


@pytest.mark.parametrize("http_challenge", [False, True])
def test_cached_challenge_must_not_block_fresh_authenticated_request(
    monkeypatch, http_challenge
):
    calls = []
    response = SimpleNamespace(
        text=CHALLENGE if http_challenge else HEALTHY,
        url=URL,
        content=HEALTHY.encode(),
        raise_for_status=lambda: None,
    )

    def get(*args, **kwargs):
        calls.append("http")
        return response

    monkeypatch.setattr(smoke, "detail_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        smoke,
        "fetch_detail_with_browser",
        lambda *a, **k: (HEALTHY, URL, len(HEALTHY), "fresh_browser"),
    )
    result = smoke.fetch_detail_html(
        SimpleNamespace(get=get),
        {"id": "610925725633", "url": URL},
        {"610925725633": (CHALLENGE, URL)},
        cdp_endpoint="http://fixture",
        referer_url="",
    )
    assert calls == ["http"]
    assert result[0] == HEALTHY
    assert result[3] == ("fresh_browser" if http_challenge else "http_cookie")


def test_current_challenge_still_fails_closed(monkeypatch):
    response = SimpleNamespace(text=CHALLENGE, url=URL, raise_for_status=lambda: None)
    monkeypatch.setattr(smoke, "detail_browser_fallback_enabled", lambda: False)
    with pytest.raises(smoke.DetailChallengeError, match="HTTP detail request"):
        smoke.fetch_detail_html(
            SimpleNamespace(get=lambda *a, **k: response),
            {"id": "610925725633", "url": URL},
            {"610925725633": (CHALLENGE, URL)},
            cdp_endpoint="http://fixture",
            referer_url="",
        )
