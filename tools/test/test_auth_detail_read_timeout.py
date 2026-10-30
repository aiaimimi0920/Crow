"""A site ReadTimeout is not auth proof and releases both owned transports."""

import json
from types import SimpleNamespace

from requests import ReadTimeout

from src import auth_cookie_health as health
from src import cdp_cookie_transport as cdp


def test_detail_read_timeout_retains_proof_boundary_and_closes_sessions(monkeypatch):
    target = "https://sf-item.taobao.com/sf_item/123456789012.htm"
    site = SimpleNamespace(close_calls=0, calls=[])
    metadata = SimpleNamespace(close_calls=0, calls=[], trust_env=True)

    def site_get(url, **options):
        assert url == target
        assert options["timeout"] == 15 and options["allow_redirects"] is False
        assert options["headers"]["User-Agent"] == "fixture-UA"
        assert site.close_calls == 0 and metadata.close_calls == 1
        site.calls.append(url)
        raise ReadTimeout("cookie2=synthetic-private-value")

    def metadata_get(url, **options):
        assert url == "http://fixture.invalid/json/version"
        assert options == {"timeout": 10} and metadata.trust_env is False
        metadata.calls.append(url)
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"User-Agent": "fixture-UA"}
        )

    site.get = site_get
    site.close = lambda: setattr(site, "close_calls", site.close_calls + 1)
    metadata.get = metadata_get
    metadata.close = lambda: setattr(metadata, "close_calls", metadata.close_calls + 1)
    monkeypatch.setattr(health, "build_session_from_playwright_cookies", lambda _: site)
    monkeypatch.setattr(cdp.requests, "Session", lambda: metadata)
    result = health.probe_cookie_snapshot_health(
        [], [], cdp_endpoint="http://fixture.invalid", detail_target_url=target
    )
    assert result["healthy"] is False and result["scope_healthy"] is False
    assert result["sample_count"] == 1 and result["scope_target_url"] == target
    assert result["sample_results"] == [
        {"healthy": False, "status": "probe_error", "error": "ReadTimeout"}
    ]
    assert "synthetic-private-value" not in json.dumps(result)
    assert site.calls == [target] and len(metadata.calls) == 1
    assert site.close_calls == metadata.close_calls == 1
