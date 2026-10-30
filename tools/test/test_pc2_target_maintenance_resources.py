"""Maintenance retains pages but always relinquishes its own CDP socket."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_deferral import TargetNavigationUnconfirmed
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"


@pytest.mark.parametrize(
    "operation", ["rotate_failed_challenge_target", "rebuild_missing_challenge_target"]
)
@pytest.mark.parametrize("outcome", ["opened", "none", "deferred", "stopped", "error"])
def test_maintenance_closes_socket_without_closing_or_replaying_target(
    monkeypatch, operation, outcome
):
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: [])
    owners = []
    close_page = Mock(side_effect=AssertionError("opened target must be retained"))
    monkeypatch.setattr(CaptchaSolver, "_close_cdp_target", close_page)
    errors = {
        "deferred": TargetNavigationUnconfirmed,
        "stopped": SolveStopped,
        "error": OSError,
    }

    def open_target(solver):
        solver.ws = Mock()
        solver._opened_target_ids.add("fresh")
        owners.append((solver, solver.ws))
        if outcome in errors:
            raise errors[outcome]()
        return (
            {"id": "fresh", "url": solver.target_url} if outcome == "opened" else None
        )

    monkeypatch.setattr(CaptchaSolver, "_open_target_tab", open_target)
    if outcome in {"stopped", "error"}:
        with pytest.raises(errors[outcome]):
            getattr(execution, operation)("http://127.0.0.1:9223", TARGET)
    else:
        result = getattr(execution, operation)("http://127.0.0.1:9223", TARGET)
        assert result["opened"] is (outcome == "opened")
        if outcome == "opened":
            assert result["probe_target"]["_target_id"] == "fresh"
        if outcome == "deferred":
            assert result["reason"] == "target_navigation_unconfirmed"
            assert result["probe_target"] is None  # No remembered ID to claim.

    assert len(owners) == 1
    solver, socket = owners[0]
    socket.close.assert_called_once_with()
    assert solver.ws is None
    assert solver._opened_target_ids == {"fresh"}
    close_page.assert_not_called()
