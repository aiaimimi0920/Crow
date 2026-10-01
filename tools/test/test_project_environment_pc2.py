"""PC2 configuration compatibility without starting services or contacting hosts."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.project_environment import EnvironmentAliasConflict
from tools import pc2_linux_healthcheck as health
from tools import pc2_solver_auth as auth
from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_transport as transport
from tools import pc2_solver_watchdog as watchdog


def configure(monkeypatch, prefix, **settings):
    for key, value in settings.items():
        for spelling in ("CROW", "FAPAI"):
            monkeypatch.delenv(spelling + "_" + key, raising=False)
            if prefix in (spelling, "BOTH"):
                monkeypatch.setenv(spelling + "_" + key, value)


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_import_time_defaults_accept_both_names_without_live_initialization(
    tmp_path, prefix
):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CROW_", "FAPAI_"))
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    settings = {
        "API_BASE_URL": "https://example.invalid/api",
        "LOCAL_SOLVER_POLL_SECONDS": "9",
        "LOCAL_SOLVER_HEARTBEAT_PATH": str(tmp_path / "heartbeat.json"),
        "SOLVER_COOLDOWN_SECONDS": "17",
        "NAS_AUTH_RECOVERY_TOKEN_FILE": str(tmp_path / "token"),
    }
    for spelling in ["CROW", "FAPAI"] if prefix == "BOTH" else [prefix]:
        env.update({spelling + "_" + key: value for key, value in settings.items()})
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from tools import pc2_solver_config as c; from tools import pc2_solver_retry_state as r; print(json.dumps([c.DEFAULT_API_BASE_URL,c.DEFAULT_POLL_SECONDS,str(c.SOLVER_HEARTBEAT_PATH),r.SOLVER_COOLDOWN_SECONDS,str(c.AUTH_RECOVERY_TOKEN_PATH)])); assert 'src.captcha_solver' not in sys.modules",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        settings["API_BASE_URL"],
        9,
        settings["LOCAL_SOLVER_HEARTBEAT_PATH"],
        17,
        settings["NAS_AUTH_RECOVERY_TOKEN_FILE"],
    ]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_auth_payload_and_dynamic_flags_preserve_legacy_protocol(monkeypatch, prefix):
    configure(
        monkeypatch,
        prefix,
        NODE_ID="fixture-node",
        REPORT_CDP_ENDPOINT="http://example.invalid:9223",
        REAL_TAOBAO_AUTO_SOLVER_ENABLED="0",
        NAS_AUTH_RECOVERY_CLIENT_ENABLED="",
    )
    assert transport.real_taobao_auto_solver_enabled() is False
    assert (
        transport.nas_auth_recovery_client_enabled() is True
    )  # Existing empty-string semantics.
    post = Mock(return_value={"ok": True, "paused": False})
    monkeypatch.setattr(auth, "post_json", post)
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 1)
    auth.notify_auth_complete("https://example.invalid/api")
    assert post.call_args.args[1]["node_id"] == "fixture-node"
    assert post.call_args.args[1]["cdp_endpoint"] == "http://example.invalid:9223"
    assert pending._new_auth_completion_id().startswith("fixture-node-")
    configure(monkeypatch, prefix, REAL_TAOBAO_AUTO_SOLVER_ENABLED="yes")
    assert transport.real_taobao_auto_solver_enabled() is True


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_watchdog_cli_and_healthcheck_use_the_same_heartbeat(
    monkeypatch, tmp_path, prefix
):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"updated_at_epoch": 990}), encoding="utf-8")
    configure(
        monkeypatch,
        prefix,
        LOCAL_SOLVER_HEARTBEAT_PATH=str(heartbeat),
        LOCAL_SOLVER_WATCHDOG_STALE_SECONDS="20",
    )
    health._check_solver_heartbeat(now=1000)
    run = Mock(return_value=0)
    monkeypatch.setattr(watchdog, "run_watchdog", run)
    monkeypatch.setattr(sys, "argv", ["watchdog", "--parent-pid", "424242"])
    assert watchdog.main() == 0
    assert run.call_args.args[0] == heartbeat
    assert run.call_args.kwargs["stale_seconds"] == 20
    assert run.call_args.kwargs["parent_pid"] == 424242


def test_auth_conflict_fails_before_request(monkeypatch):
    monkeypatch.setenv("CROW_NODE_ID", "private-new")
    monkeypatch.setenv("FAPAI_NODE_ID", "private-old")
    post = Mock()
    monkeypatch.setattr(auth, "post_json", post)
    with pytest.raises(EnvironmentAliasConflict) as error:
        auth.notify_auth_complete("https://example.invalid/api")
    assert "private-" not in str(error.value)
    post.assert_not_called()


def test_watchdog_conflict_cannot_start_or_signal_a_process(monkeypatch):
    monkeypatch.setenv("CROW_LOCAL_SOLVER_HEARTBEAT_PATH", "new")
    monkeypatch.setenv("FAPAI_LOCAL_SOLVER_HEARTBEAT_PATH", "old")
    run = Mock()
    monkeypatch.setattr(watchdog, "run_watchdog", run)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    with pytest.raises(EnvironmentAliasConflict):
        watchdog.main()
    run.assert_not_called()


def test_import_conflict_reports_keys_without_values(tmp_path):
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        CROW_API_BASE_URL="https://private-new.invalid",
        FAPAI_API_BASE_URL="https://private-old.invalid",
    )
    result = subprocess.run(
        [sys.executable, "-c", "import tools.pc2_solver_config"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert "EnvironmentAliasConflict" in result.stderr
    assert "CROW_API_BASE_URL" in result.stderr
    assert "private-new" not in result.stderr and "private-old" not in result.stderr


def test_watchdog_script_help_is_available_outside_checkout(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CROW_", "FAPAI_"))
    }
    env.pop("PYTHONPATH", None)
    script = Path(__file__).resolve().parents[1] / "pc2_solver_watchdog.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--heartbeat-path" in result.stdout
    assert not list(tmp_path.iterdir())
