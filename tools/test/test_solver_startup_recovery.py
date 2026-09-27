"""The startup owner must operate without server bootstrap or shared globals."""

import json
import subprocess
import sys

import pytest

from src.collection_control_state import new_scope_state
from src.runtime_state import RuntimeState
from src.solver_startup_recovery import (
    restore_legacy_challenge,
    restore_scoped_challenges,
)


@pytest.mark.parametrize(
    "module",
    [
        "solver_startup_recovery",
        "solver_challenge_receipts",
        "solver_challenge_creation",
        "solver_manual_pause",
        "solver_manual_retry",
        "server_solver_dispatch",
        "solver_dispatch_binding",
        "server_solver_state",
        "solver_state_binding",
        "server_auth_recovery",
        "solver_auth_history",
        "solver_status_reader",
        "auth_recovery_binding",
        "solver_retry_monitor",
        "solver_retry_monitor_binding",
        "server_auth_cookie",
        "auth_cookie_paths",
        "solver_captcha_reports",
        "auth_cookie_binding",
    ],
)
def test_native_import_does_not_bootstrap_server(module):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; import src.{module}; "
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


def test_native_restore_keeps_injected_runtimes_and_legacy_ownership_separate(tmp_path):
    first, second = RuntimeState(), RuntimeState()
    request = {"node_id": "legacy-node"}
    flag = tmp_path / "manual.flag"
    flag.write_text(
        json.dumps(
            {
                "manual_required": True,
                "manual_only": True,
                "created_at_epoch": 123.0,
                "last_request": request,
            }
        ),
        encoding="utf-8",
    )
    state = {
        **new_scope_state(),
        "challenge_id": "scoped-id",
        "last_request": {"scope": "detail"},
        "paused": True,
    }
    assert restore_legacy_challenge(
        runtime=first,
        read_legacy=lambda: {"challenge_id": "legacy-id", "last_request": request},
        manual_flag_path=lambda: str(flag),
        set_pause=lambda paused, reason=None, **_: first.control.set_pause(
            paused, reason
        ),
    )
    for runtime in (first, second):
        assert restore_scoped_challenges(
            runtime=runtime,
            read_scope=lambda scope: state if scope == "detail" else new_scope_state(),
            set_pause=lambda paused, reason=None, **_: None,
        )
    assert first.recovery.snapshot().challenge_id == "legacy-id"
    assert first.recovery.snapshot().manual_only is True
    assert first.recovery.snapshot().required_epoch == 123.0
    assert second.recovery.snapshot().challenge_id == "scoped-id"
    assert second.recovery.snapshot().last_request == {"scope": "detail"}
    assert second.recovery.snapshot().manual_only is False
    assert second.recovery.snapshot().required_epoch == 0
    first.control.set_scope("detail", new_scope_state())
    assert second.control.scope_snapshot("detail")["challenge_id"] == "scoped-id"
