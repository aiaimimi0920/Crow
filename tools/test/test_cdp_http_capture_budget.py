"""CDP metadata and page-management requests share the private capture budget."""

from types import SimpleNamespace

import pytest

from tools import capture_budget as budget
from tools import live_batch_smoke, live_smoke_auth, live_smoke_cdp


def transport(monkeypatch, *, elapsed=0):
    clock = SimpleNamespace(now=0.0)
    calls = []

    class Session:
        def __init__(self):
            self.headers = {}
            calls.append("session")

        def request(self, url, *, timeout):
            assert self.trust_env is False
            assert self.headers == {"Connection": "close"}
            calls.append((url.rsplit("/", 1)[-1], timeout))
            clock.now += elapsed
            targets = [{"id": str(i), "type": "page"} for i in range(2)]
            return SimpleNamespace(
                status_code=200,
                json=lambda: targets,
                raise_for_status=lambda: None,
            )

        get = put = request

        def close(self):
            calls.append("close")

    monkeypatch.setattr(budget.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(live_smoke_auth.requests, "Session", Session)
    return clock, calls


@pytest.mark.parametrize("module", [live_smoke_auth, live_batch_smoke])
@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("remaining,expected", [(0.25, 0.25), (10, 3)])
def test_http_timeout_is_capped_by_remaining_private_budget(
    monkeypatch, module, method, remaining, expected
):
    _, calls = transport(monkeypatch)
    with budget.capture_budget(remaining):
        getattr(module, "_cdp_http_" + method)(
            "http://fixture", "/json/version", timeout_seconds=3
        )
    assert calls == ["session", ("version", expected), "close"]


@pytest.mark.parametrize("method", ["get", "put"])
def test_expired_budget_does_not_create_a_session_or_send_a_request(
    monkeypatch, method
):
    _, calls = transport(monkeypatch)
    with budget.capture_budget(0), pytest.raises(budget.CaptureBudgetExceeded):
        getattr(live_smoke_auth, "_cdp_http_" + method)(
            "http://fixture", "/json/version", timeout_seconds=3
        )
    assert calls == []


@pytest.mark.parametrize("method", ["get", "put"])
def test_late_reply_is_not_accepted_as_in_budget_work(monkeypatch, method):
    _, calls = transport(monkeypatch, elapsed=2)
    with budget.capture_budget(1), pytest.raises(budget.CaptureBudgetExceeded):
        getattr(live_smoke_auth, "_cdp_http_" + method)(
            "http://fixture", "/json/version", timeout_seconds=3
        )
    assert calls == ["session", ("version", 1), "close"]


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_slow_target_list_does_not_start_new_page_management_after_deadline(
    monkeypatch, module
):
    _, calls = transport(monkeypatch, elapsed=2)
    with budget.capture_budget(1):
        summary = module.compact_cdp_page_targets_if_needed("http://fixture", limit=2)
    assert summary["closed"] == 0
    assert calls == ["session", ("list", 1), "close"]


def test_legacy_caller_without_private_budget_keeps_original_timeout(monkeypatch):
    _, calls = transport(monkeypatch, elapsed=10)
    live_smoke_auth._cdp_http_get("http://fixture", "/json/version", timeout_seconds=3)
    assert calls == ["session", ("version", 3), "close"]


def test_each_request_recomputes_remaining_time_instead_of_restarting_budget(
    monkeypatch,
):
    clock, calls = transport(monkeypatch)
    with budget.capture_budget(1):
        live_smoke_auth._cdp_http_get(
            "http://fixture", "/json/version", timeout_seconds=3
        )
        clock.now = 0.75
        live_smoke_auth._cdp_http_put("http://fixture", "/json/new", timeout_seconds=3)
    assert calls == [
        "session",
        ("version", 1),
        "close",
        "session",
        ("new", 0.25),
        "close",
    ]


def test_request_cancellation_closes_session_and_restores_budget(monkeypatch):
    from tools.cdp_http_session import request_cdp

    calls = []

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            raise KeyboardInterrupt()

        def close(self):
            calls.append("close")

    monkeypatch.setattr(budget.time, "monotonic", lambda: 0)
    with pytest.raises(KeyboardInterrupt), budget.capture_budget(1):
        request_cdp(Session, "get", "http://fixture", timeout_seconds=3)
    assert calls == ["close"]
    assert budget.bounded_capture_timeout(3000) == 3000
