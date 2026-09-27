"""Cookie health uses native adapters and isolates failures by sample."""

import subprocess
import sys

import pytest

from src import auth_cookie_health
from src.collection.adapters import taobao_health, taobao_list_probe


@pytest.mark.parametrize(
    "module",
    [
        "auth_cookie_health",
        "collection.adapters.taobao_health",
        "collection.adapters.taobao_list_probe",
    ],
)
def test_health_owner_import_does_not_load_tools_or_server(module):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; import src.{module}; "
                "assert not any(n == 'tools' or n.startswith('tools.') for n in sys.modules); "
                "assert 'src.server' not in sys.modules; "
                "assert 'src.server_context' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_sample_does_not_prevent_another_healthy_sample(monkeypatch):
    first = "https://sf.taobao.com/list/first"
    second = "https://sf.taobao.com/list/second"
    observed = []
    session = object()
    monkeypatch.setattr(
        auth_cookie_health, "build_session_from_playwright_cookies", lambda _: session
    )
    monkeypatch.setattr(
        auth_cookie_health, "resolve_cdp_user_agent", lambda _: "test-UA"
    )

    def probe(url, **kwargs):
        assert kwargs["session"] is session
        assert kwargs["user_agent"] == "test-UA"
        assert kwargs["timeout"] == 15
        observed.append(url)
        if url == first:
            raise OSError("synthetic sample failure")
        return taobao_list_probe.summarize_list_page(
            '<script id="sf-item-list-data">{"data":[{"id":"test"}]}</script>',
            final_url=url,
        )

    monkeypatch.setattr(auth_cookie_health, "probe_seed_page", probe)
    result = auth_cookie_health.probe_cookie_snapshot_health([], [first, second])
    assert observed == [first, second]
    assert result["healthy"] is True
    assert result["healthy_samples"] == 1
    assert result["sample_count"] == 2
    assert result["sample_results"][0] == {
        "check_url": first,
        "status": "probe_error",
        "healthy": False,
        "error": "OSError('synthetic sample failure')",
    }
    assert result["sample_results"][1]["status"] == "healthy_list_payload"


def test_tool_health_exports_are_native_functions():
    from tools import browserless_seed_probe, taobao_login_health

    for name in (
        "build_navigation_headers",
        "build_session_from_playwright_cookies",
        "extract_list_payload",
        "summarize_list_page",
        "probe_seed_page",
    ):
        assert getattr(browserless_seed_probe, name) is getattr(taobao_list_probe, name)
    for name in (
        "classify_taobao_health",
        "redact_taobao_sensitive_text",
        "redact_taobao_sensitive_url",
        "redact_taobao_health_output",
    ):
        assert getattr(taobao_login_health, name) is getattr(taobao_health, name)
