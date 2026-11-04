"""A cooled-down rejected request is rebuilt on demand, never preloaded."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.captcha_solver import CaptchaSolver
from src.collection.adapters.taobao_auth_target import same_auth_target
from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop_control as control
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store

CDP = "http://127.0.0.1:9223"


@pytest.mark.parametrize(
    "scope,target",
    [
        ("detail", "https://sf-item.taobao.com/sf_item/123.htm"),
        ("seed", "https://sf.taobao.com/list/1.htm?location_code=120113&page=5"),
    ],
)
def test_failed_target_cleanup_then_owned_request_recovery(monkeypatch, scope, target):
    state = store._default_fallback_state()
    state.update(challenge_id="old", scope=scope)
    store._save_fallback_state(state)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 1)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180)
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
    browse = Mock()
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    path, _, query = target.partition("?")
    pages = [
        {"id": "blank", "type": "page", "url": "about:blank"},
        {
            "id": "rejected",
            "type": "page",
            "title": "安全验证",
            "url": path + "/_____tmd_____/punish?" + query + "&x5secdata=private",
        },
    ]
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: list(pages))

    def close(_solver, target_id):
        pages[:] = [page for page in pages if page["id"] != target_id]
        return True

    def open_target(solver):
        page = {"id": "fresh", "type": "page", "url": solver.target_url}
        pages.append(page)
        return page

    opened = Mock(side_effect=open_target)
    monkeypatch.setattr(CaptchaSolver, "_close_cdp_target", close)
    monkeypatch.setattr(
        CaptchaSolver, "_open_target_tab", lambda solver: opened(solver)
    )
    assert (
        failure.record_failed_attempt(
            "offline", CDP, target, None, failure_reason="challenge_retry_exhausted"
        )
        is None
    )
    cooled = store._load_fallback_state()
    assert retry._solver_cooldown_active(cooled, now=1001)
    assert [page["id"] for page in pages] == ["blank"]
    opened.assert_not_called()
    browse.assert_not_called()

    # After the cooldown and resume ACK, a fresh owned API request can recover
    # without relying on a preloaded page or an in-memory old probe identity.
    assert not retry._solver_cooldown_active(cooled, now=1181)
    status = {
        "scope": scope,
        "challenge_id": "fresh-request",
        "last_request": {"node_id": "pc2", "target_url": target},
    }
    monkeypatch.setattr(control, "log_event", lambda _: None)
    monkeypatch.setattr(control, "_recent_healthy_auth_snapshot", lambda _: False)
    monkeypatch.setattr(
        control, "check_cdp_browser_for_authenticated_target", lambda *_a: None
    )
    result = control.recover_stale_pause("offline", CDP, status, [target], "pc2", 0)
    opened.assert_called_once()
    assert result["last_probe_target"]["_target_id"] == "fresh"
    assert same_auth_target(scope, result["last_probe_target"]["_target_url"], target)
    assert result["reset_probe_counter"] is True
    assert store._load_fallback_state() == cooled
