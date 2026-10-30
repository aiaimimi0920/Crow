"""Keep outage evidence typed, private and distinct from a page attach timeout."""

import json
from types import SimpleNamespace

import pytest
import requests

from tools import cdp_reconnect_health as owner
from tools import live_batch_smoke, live_smoke_cdp
from tools.capture_failure_diagnostics import (
    _safe_diagnostic,
    capture_error_diagnostic,
    capture_failure_summary,
)
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply

PRIVATE = "SECRET_ENDPOINT_CREDENTIALS"


@pytest.mark.parametrize("module", [live_smoke_cdp, live_batch_smoke])
def test_failed_reconnect_health_marker_survives_private_protocol(monkeypatch, module):
    monkeypatch.setattr(module, "compact_cdp_page_targets_if_needed", lambda _: {})
    monkeypatch.setattr(module, "resolve_playwright_cdp_endpoint", lambda value: value)
    monkeypatch.setattr(module, "_cdp_reconnect_attempts", lambda: 2)
    monkeypatch.setattr(module, "_cdp_reconnect_backoff_seconds", lambda: 0)
    monkeypatch.setattr(module, "_cdp_endpoint_healthy_for_reconnect", lambda _: False)

    def connect(*args, **kwargs):
        raise ConnectionResetError(PRIVATE)

    browser = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))
    reply = capture_reply(
        lambda seed, **kw: module.connect_browser_over_cdp(browser, kw["cdp_endpoint"]),
        {"seed": {}, "cdp_endpoint": PRIVATE},
    )
    assert reply["diagnostic"] == {
        "type": "RuntimeError",
        "message": "runtime_error",
        "endpoint_unhealthy": True,
    }
    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as raised:
        decode_capture_reply(json.dumps(reply), cdp_endpoint=PRIVATE)
    summary = capture_failure_summary(raised.value)
    assert summary["cause"] == reply["diagnostic"]
    assert PRIVATE not in json.dumps(reply) + json.dumps(summary)


@pytest.mark.parametrize("error", [RuntimeError(PRIVATE), TimeoutError(PRIVATE)])
def test_untyped_errors_do_not_claim_endpoint_outage(error):
    assert "endpoint_unhealthy" not in capture_error_diagnostic(error)


@pytest.mark.parametrize("kind", ["TimeoutError", "BrowserError", "ValueError"])
def test_invalid_marker_types_are_discarded(kind):
    category = {
        "TimeoutError": "timeout",
        "BrowserError": "browser_error",
        "ValueError": "invalid_value",
    }[kind]
    assert "endpoint_unhealthy" not in _safe_diagnostic(
        {"type": kind, "message": category, "endpoint_unhealthy": True}
    )
    assert "endpoint_unhealthy" not in _safe_diagnostic(
        {"type": "RuntimeError", "message": "runtime_error", "endpoint_unhealthy": 1}
    )


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (
            200,
            {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/fixture"},
            True,
        ),
        (
            200,
            {"webSocketDebuggerUrl": "wss://cdp.invalid/devtools/browser/fixture"},
            True,
        ),
        (
            200,
            {"webSocketDebuggerUrl": "ws://cdp.invalid/devtools/page/fixture"},
            False,
        ),
        (200, {"webSocketDebuggerUrl": "ws://cdp.invalid/devtools/browser/"}, False),
        (
            200,
            {"webSocketDebuggerUrl": "https://cdp.invalid/devtools/browser/fixture"},
            False,
        ),
        (200, {"webSocketDebuggerUrl": []}, False),
        (200, [], False),
        (200, {}, False),
        (302, {}, False),
        (401, {}, False),
        (503, {}, False),
    ],
)
def test_metadata_probe_is_bounded_read_only_without_proxy_or_redirects(
    monkeypatch, status, payload, expected
):
    calls = []

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("closed")

        def get(self, url, **kwargs):
            assert self.trust_env is False
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=status, json=lambda: payload)

    monkeypatch.setattr(owner.requests, "Session", Session)
    assert (
        owner.cdp_metadata_recovered("http://cdp.invalid:9224/", timeout_seconds=2)
        is expected
    )
    assert calls == [
        (
            "http://cdp.invalid:9224/json/version",
            {"timeout": 2, "allow_redirects": False},
        ),
        "closed",
    ]


@pytest.mark.parametrize(
    "error",
    [requests.ConnectionError(PRIVATE), requests.Timeout(PRIVATE), ValueError(PRIVATE)],
)
def test_metadata_failure_is_not_success_or_sensitive_output(
    monkeypatch, error, capsys
):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            raise error

    monkeypatch.setattr(owner.requests, "Session", Session)
    assert not owner.cdp_metadata_recovered("http://cdp.invalid", timeout_seconds=1)
    assert PRIVATE not in capsys.readouterr().out
