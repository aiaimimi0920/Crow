"""Native PC2 status and heartbeat boundaries without starting a solver."""

import json
import subprocess
import sys

import pytest

from tools import pc2_solver_transport as transport


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.pc2_solver_config",
        "tools.pc2_solver_transport",
        "tools.pc2_solver_manual_handoff",
        "tools.pc2_solver_auth",
        "tools.pc2_solver_scope_policy",
        "tools.pc2_solver_scope",
        "tools.pc2_solver_state_store",
        "tools.pc2_solver_retry_state",
        "tools.pc2_solver_fallback",
        "tools.pc2_solver_auth_pending",
        "tools.pc2_solver_cdp",
        "tools.pc2_solver_execution",
        "tools.pc2_solver_loop_control",
        "tools.pc2_solver_loop_probe",
        "tools.pc2_solver_loop_failure",
        "tools.pc2_solver_loop",
    ],
)
def test_transport_import_does_not_initialize_solver(module_name, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                f"importlib.import_module({module_name!r}); "
                "forbidden = {'tools.pc2_solver_context', 'tools.pc2_local_solver', "
                "'src.captcha_solver', 'src.server_context', 'src.storage'}; "
                f"forbidden |= {{'requests', 'tools.internal_api_http'}} if {module_name!r} not in "
                "{'tools.pc2_solver_scope', 'tools.pc2_solver_auth', "
                "'tools.pc2_solver_fallback', 'tools.pc2_solver_auth_pending', "
                "'tools.pc2_solver_cdp', 'tools.pc2_solver_execution', "
                "'tools.pc2_solver_loop_control', 'tools.pc2_solver_loop_probe', "
                "'tools.pc2_solver_loop_failure', 'tools.pc2_solver_loop'} else set(); "
                "loaded = forbidden.intersection(sys.modules); "
                "assert not loaded, loaded"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_solver_heartbeat_is_written_atomically(monkeypatch, tmp_path):
    from tools import pc2_local_solver

    heartbeat_path = tmp_path / "solver-heartbeat.json"
    monkeypatch.setattr(transport, "SOLVER_HEARTBEAT_PATH", heartbeat_path)
    monkeypatch.setattr(transport.time, "time", lambda: 1234.5)

    assert pc2_local_solver.write_solver_heartbeat(
        "solver_attempt", challenge_id="captcha-1", attempt=3
    )
    assert json.loads(heartbeat_path.read_text(encoding="utf-8")) == {
        "pid": transport.os.getpid(),
        "updated_at_epoch": 1234.5,
        "phase": "solver_attempt",
        "challenge_id": "captcha-1",
        "attempt": 3,
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_heartbeat_publication_keeps_previous_watchdog_receipt(
    monkeypatch, tmp_path
):
    path = tmp_path / "solver-heartbeat.json"
    monkeypatch.setattr(transport, "SOLVER_HEARTBEAT_PATH", path)
    assert transport.write_solver_heartbeat("polling")
    previous = path.read_bytes()
    events = []

    def reject_publication(*_args):
        raise OSError("publication failed")

    monkeypatch.setattr(transport.os, "replace", reject_publication)
    monkeypatch.setattr(transport, "log_event", events.append)

    assert not transport.write_solver_heartbeat("solver_attempt")
    assert path.read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []
    assert events[0]["kind"] == "local_solver_heartbeat_write_error"


@pytest.mark.parametrize("payload", [{"captcha_solver": {"running": True}}, []])
def test_status_entrypoint_uses_native_transport_without_starting_solver(
    monkeypatch, payload
):
    from tools import pc2_local_solver

    requests = []

    def fetch(url, *, timeout):
        requests.append((url, timeout))
        return payload

    from tools import internal_api_http

    monkeypatch.setattr(internal_api_http, "fetch_json", fetch)
    result = pc2_local_solver.read_solver_status("https://crow.example/api/")

    assert requests == [("https://crow.example/api/status", 10)]
    assert result == (
        {"running": True}
        if isinstance(payload, dict)
        else {"error": "non_dict_status_response"}
    )
