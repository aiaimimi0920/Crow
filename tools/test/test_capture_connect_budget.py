"""A private capture deadline bounds reconnects, not unrelated CDP callers."""

from types import SimpleNamespace

import pytest

from tools import live_batch_smoke, live_smoke_cdp
from tools.detail_browser_capture_child import capture_reply


def setup_clock_and_browser(monkeypatch, module, *, recover=False):
    clock = SimpleNamespace(now=0.0)
    calls = []

    def connect(endpoint, *, timeout):
        calls.append(timeout)
        if recover:
            clock.now += 0.1
            if len(calls) == 2:
                return object()
        else:
            clock.now += timeout / 1000
        raise TimeoutError("private endpoint context")

    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds)
    )
    monkeypatch.setattr(module, "_cdp_reconnect_attempts", lambda: 3)
    monkeypatch.setattr(module, "_cdp_reconnect_backoff_seconds", lambda: 0.5)
    monkeypatch.setattr(
        module, "compact_cdp_page_targets_if_needed", lambda _: {"triggered": False}
    )
    monkeypatch.setattr(module, "resolve_playwright_cdp_endpoint", lambda value: value)
    monkeypatch.setattr(module, "_cdp_endpoint_healthy_for_reconnect", lambda _: True)
    browser = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))
    return clock, calls, browser


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_capture_reconnects_share_remaining_deadline(monkeypatch, module):
    clock, calls, browser = setup_clock_and_browser(monkeypatch, module)

    def capture(seed, *, cdp_endpoint):
        module.connect_browser_over_cdp(browser, cdp_endpoint)

    reply = capture_reply(
        capture,
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 175.0},
    )
    assert calls == [120000, 54500]
    assert clock.now == 175.0
    assert reply == {
        "kind": "cdp",
        "operation": "connect_over_cdp_capture_budget",
        "diagnostic": {"type": "TimeoutError", "message": "timeout"},
    }


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_legacy_capture_without_deadline_keeps_reconnect_contract(monkeypatch, module):
    _, calls, browser = setup_clock_and_browser(monkeypatch, module)

    def capture(seed, *, cdp_endpoint):
        module.connect_browser_over_cdp(browser, cdp_endpoint)

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    assert calls == [120000, 120000, 120000]
    assert reply["operation"] == "connect_over_cdp_bounded_reconnect"


def test_capture_still_recovers_from_a_quick_transient_connection_error(monkeypatch):
    clock, calls, browser = setup_clock_and_browser(
        monkeypatch, live_batch_smoke, recover=True
    )

    def capture(seed, *, cdp_endpoint):
        assert live_batch_smoke.connect_browser_over_cdp(browser, cdp_endpoint)
        return "固定回归", "http://fixture/item", 12, "browser_navigation"

    reply = capture_reply(
        capture,
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 175.0},
    )
    assert calls == [120000, 120000]
    assert clock.now == pytest.approx(0.7)
    assert reply["kind"] == "ok"


def test_resolution_overhead_is_subtracted_before_connect(monkeypatch):
    clock, calls, browser = setup_clock_and_browser(monkeypatch, live_batch_smoke)

    def resolve(endpoint):
        clock.now += 2
        return endpoint

    monkeypatch.setattr(live_batch_smoke, "resolve_playwright_cdp_endpoint", resolve)
    capture_reply(
        lambda seed, **kw: live_batch_smoke.connect_browser_over_cdp(
            browser, kw["cdp_endpoint"]
        ),
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 10.0},
    )
    assert calls == [8000]
    assert clock.now == 10


def test_expired_capture_budget_does_not_probe_or_connect(monkeypatch):
    _, calls, browser = setup_clock_and_browser(monkeypatch, live_batch_smoke)
    metadata = []
    monkeypatch.setattr(
        live_batch_smoke,
        "compact_cdp_page_targets_if_needed",
        lambda _: metadata.append(True),
    )
    reply = capture_reply(
        lambda seed, **kw: live_batch_smoke.connect_browser_over_cdp(
            browser, kw["cdp_endpoint"]
        ),
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 0.0},
    )
    assert calls == metadata == []
    assert reply["operation"] == "connect_over_cdp_capture_budget"


@pytest.mark.parametrize("deadline", [True, "SECRET", float("nan"), float("inf")])
def test_malformed_deadline_is_rejected_without_capture_or_private_text(deadline):
    calls = []
    reply = capture_reply(
        lambda *a, **kw: calls.append(True),
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": deadline},
    )
    assert not calls
    assert reply == {
        "kind": "error",
        "diagnostic": {"type": "ValueError", "message": "invalid_value"},
    }


def test_capture_budget_is_restored_after_success_failure_and_nested_scope(monkeypatch):
    from tools.capture_budget import bounded_connect_timeout, capture_budget

    monkeypatch.setattr(live_batch_smoke.time, "monotonic", lambda: 0)
    with capture_budget(10):
        assert bounded_connect_timeout(120000) == 10000
        for fails in (False, True):

            def capture(*args, fails=fails, **kwargs):
                assert bounded_connect_timeout(120000) == 2000
                if fails:
                    raise ValueError("private context")
                return ("", "", 0, "fixture")

            capture_reply(
                capture,
                {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 2},
            )
            assert bounded_connect_timeout(120000) == 10000
    assert bounded_connect_timeout(120000) == 120000


def test_retry_backoff_cannot_outlive_capture_budget(monkeypatch):
    from tools.capture_budget import (
        CaptureBudgetExceeded,
        capture_budget,
        wait_for_cdp_retry,
    )

    clock, _, _ = setup_clock_and_browser(monkeypatch, live_batch_smoke)
    with capture_budget(0.25), pytest.raises(CaptureBudgetExceeded):
        wait_for_cdp_retry(20)
    assert clock.now == 0.25


def test_zero_playwright_timeout_is_bounded_only_inside_capture(monkeypatch):
    from tools.capture_budget import bounded_connect_timeout, capture_budget

    monkeypatch.setattr(live_batch_smoke.time, "monotonic", lambda: 0)
    assert bounded_connect_timeout(0) == 0
    with capture_budget(2):
        assert bounded_connect_timeout(0) == 2000


def test_cancellation_propagates_and_restores_budget(monkeypatch):
    from tools.capture_budget import bounded_connect_timeout

    monkeypatch.setattr(live_batch_smoke.time, "monotonic", lambda: 0)

    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        capture_reply(
            cancelled,
            {"seed": {}, "cdp_endpoint": "fixture", "deadline_monotonic": 2},
        )
    assert bounded_connect_timeout(120000) == 120000


def test_parent_transfers_absolute_budget_and_preserves_hard_deadline(monkeypatch):
    import json

    from tools import detail_browser_capture as boundary

    requests = []

    def run(command, request):
        requests.append(json.loads(request))
        return b'{"kind":"ok","result":["","",0,"fixture"]}'

    monkeypatch.setattr(boundary.time, "monotonic", lambda: 1000)
    monkeypatch.setattr(boundary, "run_capture_process", run)
    boundary.capture_detail_with_deadline({"url": "fixture"}, cdp_endpoint="fixture")
    assert requests == [
        {
            "seed": {"url": "fixture"},
            "cdp_endpoint": "fixture",
            "deadline_monotonic": 1175.0,
        }
    ]
    assert boundary.DEFAULT_CAPTURE_SECONDS == 180
    assert boundary.CLEANUP_SECONDS == 5


def test_budget_diagnostic_survives_private_reply_round_trip(monkeypatch):
    import json

    from tools.capture_failure_diagnostics import capture_failure_summary
    from tools.detail_browser_capture import decode_capture_reply

    _, _, browser = setup_clock_and_browser(monkeypatch, live_batch_smoke)
    reply = capture_reply(
        lambda seed, **kw: live_batch_smoke.connect_browser_over_cdp(
            browser, kw["cdp_endpoint"]
        ),
        {"seed": {}, "cdp_endpoint": "http://fixture", "deadline_monotonic": 0},
    )
    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as raised:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    assert capture_failure_summary(raised.value) == {
        "operation": "connect_over_cdp_capture_budget",
        "deadline_exceeded": False,
        "cause": {"type": "TimeoutError", "message": "timeout"},
    }
