"""Configuration aliases only: no browser, pointer, network, or runtime data."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_cdp
from src import cdp_cookie_transport as transport
from src.captcha_budget import SolveBudget
from src.captcha_nc_retry import CaptchaNCRetryMixin
from src.captcha_os_input import CaptchaOSInputMixin
from src.captcha_os_windows import CaptchaOSWindowsMixin
from src.captcha_preflight import CaptchaPreflightMixin
from src.captcha_target import CaptchaTargetMixin
from src.project_environment import EnvironmentAliasConflict


def configure(monkeypatch, prefix, key, value):
    for spelling in ("CROW_", "FAPAI_"):
        monkeypatch.delenv(spelling + key, raising=False)
    for spelling in ["CROW", "FAPAI"] if prefix == "BOTH" else [prefix]:
        monkeypatch.setenv(spelling + "_" + key, value)


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
@pytest.mark.parametrize(
    "value, expected", [("12.5", 12.5), ("", 180), ("bad", 180), ("nan", 180)]
)
def test_deadline_aliases_preserve_numeric_fallback(
    monkeypatch, prefix, value, expected
):
    configure(monkeypatch, prefix, "SOLVER_MAX_RUNTIME_SECONDS", value)
    assert SolveBudget(clock=lambda: 100).deadline == 100 + expected


def test_deadline_conflict_is_not_a_numeric_parse_failure(monkeypatch):
    monkeypatch.setenv("CROW_SOLVER_MAX_RUNTIME_SECONDS", "12")
    monkeypatch.setenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", "13")
    with pytest.raises(EnvironmentAliasConflict):
        SolveBudget()
    assert SolveBudget(deadline=10).deadline == 10  # Explicit argument wins.


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_endpoint_flags_retry_and_cookie_cache_aliases(monkeypatch, tmp_path, prefix):
    configure(monkeypatch, prefix, "CDP_ENDPOINT", "http://example.invalid:9223/")
    assert CaptchaTargetMixin().cdp_endpoint == "http://example.invalid:9223"
    configure(monkeypatch, prefix, "CDP_MAX_PAGE_TARGETS", "7")
    assert CaptchaTargetMixin()._page_target_limit() == 7
    configure(monkeypatch, prefix, "SOLVER_OS_MOUSE", "on")
    target = SimpleNamespace(_is_local_mock_slider_target=lambda: False)
    assert CaptchaOSWindowsMixin._os_mouse_enabled(target) is True
    configure(monkeypatch, prefix, "SOLVER_OS_INPUT_BACKEND", "disabled")
    assert CaptchaOSInputMixin()._native_os_input_enabled() is False
    assert CaptchaOSInputMixin()._uinput_os_input_enabled() is False
    configure(monkeypatch, prefix, "SOLVER_ENABLE_HEADED_PLAYWRIGHT", "yes")
    assert CaptchaPreflightMixin()._headed_playwright_enabled() is True
    configure(monkeypatch, prefix, "SOLVER_NC_RETRY_REPLAYS", "3")
    assert CaptchaNCRetryMixin()._nc_retry_replay_limit() == 3
    configure(monkeypatch, prefix, "CDP_RECONNECT_ATTEMPTS", "4")
    assert transport._cdp_reconnect_attempts() == 4
    configure(monkeypatch, prefix, "CDP_WEBSOCKET_CACHE_PATH", "")
    configure(monkeypatch, prefix, "COOKIE_SNAPSHOT", str(tmp_path / "cookies.json"))
    assert (
        transport._cdp_websocket_cache_path() == tmp_path / "cdp-websocket-cache.json"
    )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "key",
    ["BROWSER_USER_AGENT", "BROWSER_IDENTITY_FULL_VERSION", "SOLVER_DISABLE_STEALTH"],
)
def test_connection_conflicts_fail_before_any_socket_action(monkeypatch, key):
    for setting in (
        "BROWSER_USER_AGENT",
        "BROWSER_IDENTITY_FULL_VERSION",
        "SOLVER_DISABLE_STEALTH",
    ):
        configure(monkeypatch, "CROW", setting, "configured")
    monkeypatch.setenv("FAPAI_" + key, "private-conflict-value")
    sock = Mock()
    connect = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(captcha_cdp.websocket, "create_connection", connect)
    with pytest.raises(EnvironmentAliasConflict) as error:
        captcha_cdp.CaptchaCDPMixin._connect_to_target(
            SimpleNamespace(ws=sock), "ws://example.invalid", "test"
        )
    assert "private-conflict-value" not in str(error.value)
    sock.close.assert_not_called()
    connect.assert_not_called()


def test_cookie_alias_conflict_does_not_fall_back_to_another_transport(monkeypatch):
    configure(monkeypatch, "CROW", "CDP_RECONNECT_ATTEMPTS", "1")
    configure(monkeypatch, "CROW", "CDP_RECONNECT_BACKOFF_SECONDS", "0")
    configure(monkeypatch, "CROW", "CDP_WEBSOCKET_CACHE_PATH", "new-path")
    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", "old-path")
    fallback = Mock()
    with pytest.raises(EnvironmentAliasConflict):
        transport.export_cdp_cookies(
            "http://example.invalid",
            websocket_export=lambda *_: transport._cdp_websocket_cache_path(),
            playwright_export=fallback,
        )
    fallback.assert_not_called()


def test_cache_conflict_is_not_swallowed_by_endpoint_discovery(monkeypatch):
    configure(monkeypatch, "CROW", "CDP_WEBSOCKET_CACHE_PATH", "new-private-path")
    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", "old-private-path")
    session = Mock()
    session.get.return_value.json.return_value = {
        "webSocketDebuggerUrl": "ws://example.invalid/devtools/browser/test"
    }
    with pytest.raises(EnvironmentAliasConflict):
        transport._resolve_cdp_websocket_for_cookie_export(
            session, "http://example.invalid"
        )
    assert session.get.call_count == 1
