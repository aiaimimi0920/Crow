"""Exercise real log producers without browser, network or runtime-state access."""

import json

import pytest

from tools import pc2_solver_auth_pending as auth
from tools import pc2_solver_loop as loop
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store
from tools.solver_observation_evidence import project_line, summarize
from tools.test.test_solver_observation import event, payload, success


@pytest.mark.parametrize("delayed", [False, True])
def test_real_confirmation_logs_keep_request_after_state_reset(monkeypatch, delayed):
    target = "https://sf-item.taobao.com/item?secret=private"
    logs = []
    monkeypatch.setattr(auth, "log_event", logs.append)
    monkeypatch.setattr(auth, "read_solver_status", lambda _: {})
    monkeypatch.setattr(auth, "_new_auth_completion_id", lambda: "private-completion")
    confirmed = payload(
        ok=True,
        paused=False,
        scope_paused=False,
        scope_manual_required=False,
        captcha_solver={
            "paused": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
        },
    )
    monkeypatch.setattr(
        auth,
        "notify_auth_complete",
        lambda *_a, **_kw: {"error": "offline"} if delayed else confirmed,
    )
    auth.confirm_local_solver_success(
        "api.test", {"challenge_id": "challenge-a"}, target, "cdp.test", "pc2"
    )
    if delayed:
        monkeypatch.setattr(auth, "notify_auth_complete", lambda *_a, **_kw: confirmed)
        state = store._load_fallback_state()
        result = auth._retry_pending_auth_confirmation(
            "api.test", state=state, now=state["auth_complete_next_retry_at"]
        )
        assert result["confirmed"]
        logs.append({"kind": "auth_complete_confirmed", "result": result["result"]})
    assert store._load_fallback_state()["challenge_id"] is None
    rows = success()[:4]
    for i, log in enumerate(logs):
        projected = project_line(
            f"2026-10-06T12:00:{i + 4:02d}Z " + json.dumps(log), "container-a"
        )
        if projected:
            rows.append(projected)
    counts = summarize(rows)["counts"]
    assert counts["auth_confirmed"] == 1
    assert counts["unlinked_auth_confirmations"] == 0
    assert "private" not in json.dumps(rows)


@pytest.mark.parametrize(
    "profile", ["slow_exact_v4", "slow_settle_v4", "slow_dense_v4"]
)
def test_current_linux_profiles_are_preserved(profile):
    row = event("local_solver_diagnostic", phase="os_drag", profile=profile)
    assert row["profile"] == profile


@pytest.mark.parametrize(
    "field,value",
    [
        ("completion_id", "wrong"),
        ("challenge_id", "wrong"),
        ("target_url", "https://sf-item.taobao.com/other"),
        ("scope", "seed"),
    ],
)
def test_request_binding_does_not_relax_auth_proof(field, value):
    request = {
        "completion_id": "private-completion",
        "challenge_id": "challenge-a",
        "target_url": "https://sf-item.taobao.com/item?secret=private",
        "scope": "detail",
    }
    request[field] = value
    rows = success() + [
        event(
            "auth_complete_result",
            4,
            request=request,
            result={"confirmed": True, "state": {}, "result": payload()},
        )
    ]
    assert summarize(rows)["counts"]["auth_confirmed"] == 0


def test_confirmation_cannot_cross_container_boundary():
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": False, "result": payload()}
        )
    ]
    confirmation = event("auth_complete_confirmed", 5, result=payload())
    confirmation["container_id"] = "other-container"
    assert summarize(rows + [confirmation])["counts"]["auth_confirmed"] == 0


def test_observer_keeps_numeric_cooldown_but_not_unknown_profile():
    row = event(
        "solver_cooldown_started",
        until=1360,
        seconds=360,
        cycles=2,
        consecutive_failures=1,
        token="private",
    )
    assert row["seconds"] == 360 and row["cycles"] == 2
    assert "private" not in json.dumps(row)
    assert (
        event("local_solver_diagnostic", phase="os_drag", profile="private")["profile"]
        == "other"
    )


@pytest.mark.parametrize("path", ["failure", "loop"])
def test_cooldown_log_reports_actual_exponential_duration(monkeypatch, path):
    state = store._default_fallback_state()
    state.update(challenge_id="a", scope="seed", solver_cooldown_cycles=1)
    logs = []
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(loop.time, "time", lambda: 1000.0)
    monkeypatch.setattr(failure, "log_event", logs.append)
    if path == "failure":
        store._save_fallback_state(state)
        monkeypatch.setattr(
            failure, "rotate_failed_challenge_target", lambda *_a, **_k: {}
        )
        monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
        monkeypatch.setattr(failure, "log_event", logs.append)
        failure.record_failed_attempt("api.test", "cdp.test", "target.test", None)
    else:
        state["consecutive_failures"] = 1
        store._save_fallback_state(state)
        replacements = {
            "hold_manual_window": lambda _: False,
            "prepare_solver_browser": lambda *_a: None,
            "IdlePointer": lambda _: None,
            "write_solver_heartbeat": lambda *_a: None,
            "process_pending_control_actions": lambda **_k: {
                "handled": False,
                "last_probe_target": None,
                "last_auth_confirmed_at": 0,
            },
            "read_solver_status": lambda _: {"challenge_id": "a", "scope": "seed"},
            "compact_active_challenge_pages": lambda *_a: {},
            "reset_forced_solver_scopes": lambda _a, _b, value, _d: value,
            "retry_terminal_manual_report": lambda *_a: False,
            "retry_blocked_report": lambda *_a: None,
            "log_event": logs.append,
        }
        for name, replacement in replacements.items():
            monkeypatch.setattr(loop, name, replacement)
        monkeypatch.setattr(
            loop.time, "sleep", lambda _: (_ for _ in ()).throw(SystemExit())
        )
        with pytest.raises(SystemExit):
            loop.local_solver_loop("api.test", "cdp.test", poll_seconds=1)
    cooldown = next(e for e in logs if e["kind"] == "solver_cooldown_started")
    assert cooldown["seconds"] == cooldown["until"] - 1000.0 == 360.0
    assert cooldown["cycles"] == 2
