"""Health checks own and close their HTTP session without changing validation."""

from types import SimpleNamespace

import pytest

from src import auth_cookie_health as owner


@pytest.fixture
def session(monkeypatch):
    state = SimpleNamespace(close_calls=0)

    def close():
        state.close_calls += 1

    state.close = close
    monkeypatch.setattr(owner, "build_session_from_playwright_cookies", lambda _: state)
    monkeypatch.setattr(owner, "resolve_cdp_user_agent", lambda _: "test-UA")
    monkeypatch.setattr(owner, "probe_seed_page", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        owner, "classify_taobao_health", lambda *_args, **_kwargs: {"healthy": True}
    )
    monkeypatch.setattr(
        owner, "probe_detail_page", lambda *_args, **_kwargs: {"healthy": True}
    )
    return state


@pytest.mark.parametrize("detail", [False, True])
def test_successful_probe_closes_owned_session_once(session, detail):
    result = owner.probe_cookie_snapshot_health(
        [],
        ["https://example.invalid/list"],
        detail_target_url="https://example.invalid/item" if detail else "",
    )
    assert result["scope_healthy" if detail else "healthy"] is True
    if detail:
        assert result["healthy"] is False
    assert session.close_calls == 1


@pytest.mark.parametrize("detail", [False, True])
def test_failed_probe_remains_unhealthy_and_closes_session(
    session, monkeypatch, detail
):
    def fail(*_args, **_kwargs):
        raise TimeoutError("synthetic probe timeout")

    monkeypatch.setattr(
        owner, "probe_detail_page" if detail else "probe_seed_page", fail
    )
    result = owner.probe_cookie_snapshot_health(
        [],
        ["https://example.invalid/list"],
        detail_target_url="https://example.invalid/item" if detail else "",
    )
    assert result["healthy"] is False
    assert result["sample_results"][0]["status"] == "probe_error"
    assert session.close_calls == 1


def test_empty_samples_close_session_without_assuming_health(session):
    result = owner.probe_cookie_snapshot_health([], [])
    assert result == {
        "healthy": False,
        "healthy_samples": 0,
        "sample_count": 0,
        "sample_results": [],
    }
    assert session.close_calls == 1


def test_setup_exception_is_preserved_but_session_is_closed(session, monkeypatch):
    def fail(*_args):
        raise OSError("synthetic setup failure")

    monkeypatch.setattr(owner, "resolve_cdp_user_agent", fail)
    with pytest.raises(OSError, match="synthetic setup failure"):
        owner.probe_cookie_snapshot_health([], [])
    assert session.close_calls == 1


@pytest.mark.parametrize("detail", [False, True])
def test_cancellation_propagates_after_session_cleanup(session, monkeypatch, detail):
    class Cancelled(BaseException):
        pass

    def fail(*_args, **_kwargs):
        raise Cancelled

    monkeypatch.setattr(
        owner, "probe_detail_page" if detail else "probe_seed_page", fail
    )
    with pytest.raises(Cancelled):
        owner.probe_cookie_snapshot_health(
            [],
            ["https://example.invalid/list"],
            detail_target_url="https://example.invalid/item" if detail else "",
        )
    assert session.close_calls == 1


def test_session_stays_open_and_is_reused_until_all_samples_finish(
    session, monkeypatch
):
    calls = []

    def probe(url, **options):
        assert options["session"] is session
        assert session.close_calls == 0
        calls.append(url)
        if len(calls) == 1:
            raise OSError("synthetic first sample failure")
        return {}

    monkeypatch.setattr(owner, "probe_seed_page", probe)
    urls = ["https://example.invalid/first", "https://example.invalid/second"]
    result = owner.probe_cookie_snapshot_health([], urls)
    assert calls == urls
    assert result["healthy"] is True
    assert result["healthy_samples"] == 1
    assert session.close_calls == 1
