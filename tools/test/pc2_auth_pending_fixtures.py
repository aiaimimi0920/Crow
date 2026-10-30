"""Synthetic terminal detail receipts; no browser or production data."""

from copy import deepcopy

import pytest

from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_state_store as store

NOW = 1000.0
TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
CDP = "http://browser.test:9224"
BUDGET = {
    "consecutive_failures": 4,
    "slider_attempts": 4,
    "window_started_at": 100.0,
    "slider_next_attempt_at": 1050.0,
    "solver_cooldown_until": 1100.0,
    "solver_cooldown_reason": "repeated_solver_failures",
    "solver_cooldown_cycles": 2,
    "node_solver_blocked_report_attempts": 2,
    "node_solver_blocked_report_next_retry_at": 1100.0,
}


def receipt():
    state = store._default_fallback_state()
    state.update(
        BUDGET,
        scope="detail",
        challenge_id="owned-challenge",
        last_success_at=800.0,
        auth_complete_pending=True,
        auth_completion_id="owned-receipt",
        auth_complete_target_url=TARGET,
        auth_complete_attempts=24,
        auth_complete_next_retry_at=1100.0,
    )
    return state


def terminal_status():
    return {
        "running": False,
        "global_manual_pause_active": False,
        "scopes": {
            "detail": {
                "scope": "detail",
                "challenge_id": "owned-challenge",
                "paused": True,
                "manual_required": False,
                "manual_only": False,
                "node_solver_blocked": False,
                "force_reset_required": True,
                "last_request": {
                    "scope": "detail",
                    "target_url": TARGET,
                    "node_id": "pc2",
                    "cdp_endpoint": CDP,
                },
            }
        },
        "cookie_snapshot_refresh": {
            "scope": "detail",
            "completion_id": "owned-receipt",
            "expected_challenge_id": "owned-challenge",
            "status": "failed",
            "auth_finalize_requested": True,
            "refreshed": False,
            "retry_queued": False,
            "next_retry_at_epoch": None,
            "attempts": 3,
            "max_attempts": 3,
            "result": {
                "refreshed": False,
                "reason": "cookie_snapshot_candidate_unhealthy",
            },
        },
    }


@pytest.fixture
def pending_case(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setattr(pending, "AUTH_COMPLETE_PENDING_MAX_SECONDS", 120.0)
    state, latest = receipt(), terminal_status()
    events = []
    monkeypatch.setattr(pending, "log_event", events.append)
    monkeypatch.setattr(pending, "read_solver_status", lambda _api: deepcopy(latest))
    monkeypatch.setattr(
        pending,
        "notify_auth_complete",
        lambda *_a, **_kw: pytest.fail("terminal proof must not restart refresh"),
    )

    def retry(**identity):
        store._save_fallback_state(state)
        return pending._retry_pending_auth_confirmation(
            "https://nas.test/api",
            now=NOW,
            cdp_endpoint=identity.get("cdp_endpoint", CDP),
            expected_node_id=identity.get("expected_node_id", "pc2"),
        )

    return state, latest, events, retry
