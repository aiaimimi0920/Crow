"""Control acknowledgements explicitly reset caller state without a loop back-reference."""

import pytest

from tools import pc2_solver_loop_control as control


@pytest.mark.parametrize("kind", ["auth", "resume"])
def test_confirmation_returns_probe_reset_and_preserves_cleanup_order(
    monkeypatch, kind
):
    events = []
    target = {"_target_id": "old-target"}
    monkeypatch.setattr(control, "nas_auth_recovery_client_enabled", lambda: False)
    monkeypatch.setattr(
        control,
        "_retry_pending_auth_confirmation",
        lambda _api: {"confirmed": kind == "auth"},
    )
    monkeypatch.setattr(
        control, "_retry_pending_collection_resume", lambda _api: {"confirmed": True}
    )
    monkeypatch.setattr(
        control,
        "resolve_stale_challenge_probe_target_after_resume",
        lambda *_args: events.append("resolve") or target,
    )
    monkeypatch.setattr(
        control,
        "close_stale_challenge_probe_target",
        lambda _endpoint, value: events.append(("close", value)) or {},
    )
    monkeypatch.setattr(control, "log_event", lambda _event: None)
    monkeypatch.setattr(control.time, "time", lambda: 123.0)
    monkeypatch.setattr(
        control.time, "sleep", lambda delay: events.append(("sleep", delay))
    )
    result = control.process_pending_control_actions(
        api_base_url="https://nas/api",
        cdp_endpoint="http://cdp",
        expected_node_id="pc2",
        poll_seconds=10,
        last_probe_target=target,
        last_auth_confirmed_at=0,
    )
    assert result["handled"] and result["reset_probe_counter"]
    assert result["last_auth_confirmed_at"] == 123.0
    assert result["last_probe_target"] == (target if kind == "auth" else None)
    assert events == (
        [("sleep", 0)]
        if kind == "auth"
        else ["resolve", ("close", target), ("sleep", 0)]
    )


def test_force_reset_preserves_foreign_node_scope(monkeypatch):
    status = {
        "scopes": {
            "seed": {
                "force_reset_required": True,
                "challenge_id": "foreign",
                "last_request": {"node_id": "pc3", "cdp_endpoint": "http://pc3:9223"},
            }
        }
    }
    monkeypatch.setattr(
        control,
        "close_challenge_pages_for_scope",
        lambda *_args: pytest.fail("foreign tabs must remain intact"),
    )
    monkeypatch.setattr(
        control,
        "notify_force_reset",
        lambda *_args: pytest.fail("foreign challenge must remain intact"),
    )
    assert (
        control.reset_forced_solver_scopes(
            "https://nas/api", "http://pc2:9223", status, "pc2"
        )
        is status
    )
