"""Request merging and solver construction honor their explicit owners."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src import server, server_context, solver_request_runtime
from src.runtime_state import RuntimeState


@pytest.fixture(params=["native", "server", "context"])
def refresh(request, monkeypatch):
    monkeypatch.delenv("FAPAI_CDP_ENDPOINT", raising=False)
    runtime = RuntimeState()
    if request.param == "native":

        def apply(payload):
            return solver_request_runtime.refresh_solver_last_request(
                payload, runtime=runtime
            )
    else:
        monkeypatch.setattr(server, "RUNTIME", runtime)
        owner = server if request.param == "server" else server_context
        apply = owner._refresh_solver_last_request
    return runtime, apply


def test_reading_or_mutating_a_request_copy_does_not_change_recovery(refresh):
    runtime, apply = refresh
    runtime.recovery.set_request({"node_id": "first"})
    before = runtime.recovery.snapshot()
    copy = apply(None)
    copy["node_id"] = "outside"
    assert runtime.recovery.snapshot() == before
    copy = apply({"scope": "item"})
    copy.clear()
    assert runtime.recovery.snapshot().last_request == {
        "node_id": "first",
        "scope": "detail",
    }


def test_concurrent_partial_updates_preserve_all_fields(refresh):
    runtime, apply = refresh
    requests = [
        {"node_id": "node-2"},
        {"scope": "detail"},
        {"target_url": "https://example.test/item"},
        {"cookie_snapshot_path": "snapshots/node.json"},
    ]
    ready = Barrier(len(requests))

    def update(payload):
        ready.wait(timeout=5)
        return apply(payload)

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        list(executor.map(update, requests))
    assert runtime.recovery.snapshot().last_request == {
        key: value for payload in requests for key, value in payload.items()
    }
    assert runtime.recovery.snapshot().generation == len(requests)


@pytest.mark.parametrize("payload", [None, [], "request", {}, {"scope": "detail"}])
def test_empty_target_reuses_the_injected_solver(payload):
    fallback = object()

    def unexpected_factory(**kwargs):
        pytest.fail(f"Unexpected solver construction: {kwargs}")

    assert (
        solver_request_runtime.build_solver_for_request(
            payload, default_solver=fallback, factory=unexpected_factory
        )
        is fallback
    )


def test_solver_construction_uses_the_supplied_factory_and_current_config(monkeypatch):
    calls = []
    created = object()

    def factory(**kwargs):
        calls.append(kwargs)
        return created

    payload = {
        "target_url": "https://example.test/item",
        "challenge_target_url": "https://example.test/challenge",
        "cdp_endpoint": "http://localhost:9222",
    }
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "https://browser.example:9444")
    assert (
        solver_request_runtime.build_solver_for_request(
            payload, default_solver=object(), factory=factory
        )
        is created
    )
    assert calls == [
        {
            "cdp_endpoint": "https://browser.example:9222",
            "target_url": "https://example.test/challenge",
        }
    ]
    assert payload["cdp_endpoint"] == "http://localhost:9222"


def test_solver_request_runtime_import_does_not_initialize_server_or_browser():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src import solver_request_runtime; import sys; "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules; "
                "assert 'src.captcha_solver' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
