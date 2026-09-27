"""Polling cadence is local to each solver-loop invocation."""

import pytest

from tools import pc2_local_solver as loop
from tools import pc2_solver_state_store as store
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def _idle_loop(monkeypatch, stop_after, probes):
    ticks = []
    patch_loop_dependency(monkeypatch, "log_event", lambda _event: None)
    patch_loop_dependency(
        monkeypatch, "write_solver_heartbeat", lambda *_args, **_kwargs: None
    )
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "process_pending_control_actions",
        lambda **kwargs: {
            "handled": False,
            "last_probe_target": kwargs["last_probe_target"],
            "last_auth_confirmed_at": kwargs["last_auth_confirmed_at"],
        },
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": False,
            "running": False,
            "manual_required": False,
        },
    )
    patch_loop_dependency(
        monkeypatch, "compact_active_challenge_pages", lambda *_args: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "reset_forced_solver_scopes",
        lambda _api, _cdp, status, _node: status,
    )
    patch_loop_dependency(
        monkeypatch, "_load_fallback_state", store._default_fallback_state
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda *_args, **_kwargs: probes.append(len(ticks) + 1),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda *_args, **_kwargs: None,
    )

    def sleep(_seconds):
        ticks.append(1)
        if len(ticks) >= stop_after:
            raise SystemExit

    monkeypatch.setattr(loop.time, "sleep", sleep)
    with pytest.raises(SystemExit):
        loop.local_solver_loop(poll_seconds=10)


def test_periodic_probe_rearms_for_each_thirty_second_interval(monkeypatch):
    monkeypatch.delattr(loop.local_solver_loop, "_probe_counter", raising=False)
    probes = []
    _idle_loop(monkeypatch, 6, probes)
    assert probes == [3, 6]


def test_new_loop_invocation_does_not_inherit_previous_probe_count(monkeypatch):
    monkeypatch.delattr(loop.local_solver_loop, "_probe_counter", raising=False)
    first, second = [], []
    _idle_loop(monkeypatch, 2, first)
    _idle_loop(monkeypatch, 2, second)
    assert first == second == []
