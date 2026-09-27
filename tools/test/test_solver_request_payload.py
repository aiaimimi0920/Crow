"""Solver request normalization works without server-global function rebinding."""

import subprocess
import sys
from pathlib import Path

import pytest

from src import server, server_context, solver_request_payload
from src.runtime_state import RuntimeState


@pytest.fixture(params=[solver_request_payload, server], ids=["native", "facade"])
def requests(request, monkeypatch):
    monkeypatch.delenv("FAPAI_CDP_ENDPOINT", raising=False)
    monkeypatch.delenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", raising=False)
    return request.param


def test_request_preserves_collection_identity_and_filters_payload_fields(requests):
    payload = {
        "target_url": (
            "https://sf.taobao.com//list/123.htm/_____tmd_____/punish"
            "?page=4&x5secdata=stale&location_code=310120&st_param=4"
            "&auction_start_seg=-1"
        ),
        "url": "https://example.test/unused",
        "challenge_target_url": (
            "https://sf-item.taobao.com//sf_item/456.htm/_____tmd_____/punish"
            "?x5secdata=stale#challenge"
        ),
        "node_id": " node-2 ",
        "cookie_snapshot_path": " snapshots/node.json ",
        "scope": " Listing ",
        "unknown_field": "ignored",
    }
    original = dict(payload)
    assert requests._build_solver_request(payload) == {
        "target_url": (
            "https://sf.taobao.com/list/123.htm?location_code=310120&st_param=4"
            "&auction_start_seg=-1&page=4&__captcha_solver_bg=1"
        ),
        "challenge_target_url": "https://sf-item.taobao.com/sf_item/456.htm",
        "node_id": "node-2",
        "cookie_snapshot_path": "snapshots/node.json",
        "scope": "seed",
    }
    assert payload == original


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("", "https://browser.example:9444"),
        ("http://127.0.0.1:9222", "https://browser.example:9222"),
        ("http://localhost", "https://browser.example:9444"),
        ("http://remote.example:9222/path", "http://remote.example:9222/path"),
    ],
)
def test_cdp_endpoint_uses_current_runtime_configuration(
    requests, monkeypatch, endpoint, expected
):
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", " https://browser.example:9444/ ")
    assert requests._build_solver_request({"cdp_endpoint": endpoint}) == {
        "cdp_endpoint": expected
    }
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://replacement.example:9223")
    assert requests._normalize_solver_cdp_endpoint("") == (
        "http://replacement.example:9223"
    )


def test_cdp_endpoint_without_configuration_preserves_explicit_value(requests):
    assert requests._normalize_solver_cdp_endpoint(" http://localhost:9222/ ") == (
        "http://localhost:9222/"
    )
    assert requests._normalize_solver_cdp_endpoint(None) == ""


def test_scope_aliases_remain_available_through_request_builder(requests):
    for value in ("list", "seed", "search", " LISTING "):
        assert requests._build_solver_request({"scope": value}) == {"scope": "seed"}
    for value in ("detail", "details", " ITEM "):
        assert requests._build_solver_request({"scope": value}) == {"scope": "detail"}
    assert requests._build_solver_request({"scope": "other"}) == {}


def test_empty_and_non_mapping_requests_do_not_create_fields(requests):
    for payload in (None, [], "request", {}, {"unknown_field": "ignored"}):
        assert requests._build_solver_request(payload) == {}
    assert requests._build_solver_request({"url": "https://example.test/item"}) == {
        "target_url": "https://example.test/item"
    }


def test_manual_policy_defaults_and_opt_in_are_read_on_each_call(requests, monkeypatch):
    payload = {"target_url": "https://sf-item.taobao.com/sf_item/456.htm"}
    assert requests._solver_target_requires_manual_only(payload) is True
    for enabled in ("1", "true", "YES", "on"):
        monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", enabled)
        assert requests._solver_target_requires_manual_only(payload) is False
    for disabled in ("0", "false", " NO ", "off"):
        monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", disabled)
        assert requests._solver_target_requires_manual_only(payload) is True
    for target in (
        "https://example.test",
        "https://taobao.com.example.test",
        "https://[bad",
    ):
        assert requests._solver_target_requires_manual_only({"url": target}) is False


def test_url_cleanup_keeps_non_target_and_invalid_urls_unchanged(requests):
    for target in (
        "https://example.test//list/123.htm?x5secdata=retain#part",
        "https://sf.taobao.com/other/path?x5secdata=retain",
        "https://[bad",
    ):
        assert requests._normalize_solver_target_url(f" {target} ") == target
    assert requests._normalize_solver_target_url(None) == ""


def test_legacy_exports_are_native_request_helpers():
    for name in (
        "_build_solver_request",
        "_normalize_solver_target_url",
        "_normalize_solver_cdp_endpoint",
        "_normalize_challenge_scope",
        "_solver_target_requires_manual_only",
        "_runtime_env_flag",
        "_real_taobao_auto_solver_enabled",
    ):
        native = getattr(solver_request_payload, name)
        assert getattr(server_context, name) is native
        assert getattr(server, name) is native


def test_refresh_request_merges_into_current_runtime_without_mutating_input(
    monkeypatch,
):
    monkeypatch.delenv("FAPAI_CDP_ENDPOINT", raising=False)
    previous = server.RUNTIME
    before = previous.recovery.snapshot()
    replacement = RuntimeState()
    replacement.recovery.set_request({"target_url": "https://example.test/item"})
    monkeypatch.setattr(server, "RUNTIME", replacement)
    payload = {"scope": "item", "node_id": " node-2 "}

    actual = server._refresh_solver_last_request(payload)

    assert actual == {
        "target_url": "https://example.test/item",
        "scope": "detail",
        "node_id": "node-2",
    }
    assert replacement.recovery.snapshot().last_request == actual
    assert server._refresh_solver_last_request(None) == actual
    assert previous.recovery.snapshot() == before
    assert payload == {"scope": "item", "node_id": " node-2 "}


def test_solver_factory_keeps_default_and_challenge_target_precedence(monkeypatch):
    fallback = object()
    created = object()
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return created

    monkeypatch.setattr(server, "solver", fallback)
    monkeypatch.setattr(server, "CaptchaSolver", factory)
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://browser.example:9223")
    assert server._build_solver_for_request({}) is fallback
    assert (
        server._build_solver_for_request(
            {
                "target_url": "https://example.test/fallback",
                "challenge_target_url": "https://example.test/challenge",
                "cdp_endpoint": "http://localhost:9222",
            }
        )
        is created
    )
    assert calls == [
        {
            "cdp_endpoint": "http://browser.example:9222",
            "target_url": "https://example.test/challenge",
        }
    ]


@pytest.mark.parametrize(
    "module_name",
    ["src.solver_request_payload", "src.collection.adapters.taobao_solver_target"],
)
def test_request_modules_import_without_server_initialization(module_name):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                f"module = importlib.import_module({module_name!r}); "
                "assert module._normalize_solver_target_url('https://example.test/') "
                "== 'https://example.test/'; "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
